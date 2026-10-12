# 7-Gate Validation System

Comprehensive reference for the gate validation system used by the Shepherd plugin. Every phase transition in the 9-phase SDLC lifecycle is guarded by seven sequential validation gates. Six check artifact quality, completeness, consistency, and compliance before work advances. The seventh renders the phase's own prose exit criteria for the human who signs.

---

## Table of Contents

1. [Gate System Overview](#1-gate-system-overview)
2. [Gate 1: Artifact Integrity](#2-gate-1-artifact-integrity)
3. [Gate 2: Completeness](#3-gate-2-completeness)
4. [Gate 3: Metrics](#4-gate-3-metrics)
5. [Gate 4: Compliance](#5-gate-4-compliance)
6. [Gate 5: Cross-Phase Consistency](#6-gate-5-cross-phase-consistency)
7. [Gate 6: Quality](#7-gate-6-quality)
8. [Gate 7: Exit Criteria](#8-gate-7-exit-criteria)
9. [Severity Levels Deep Dive](#9-severity-levels-deep-dive)
10. [Gate Results Format](#10-gate-results-format)
11. [Override Protocol](#11-override-protocol)
12. [Compliance Gate Extensions](#12-compliance-gate-extensions)
13. [Gate Auditing](#13-gate-auditing)
14. [Cross-References](#14-cross-references)

---

## 1. Gate System Overview

When a user invokes `/sprd-gate` or `/sprd-next`, the system runs every artifact produced during the current phase through six ordered validation gates. The gates are evaluated by `scripts/check_gates.py`, which reads the phase definition from `phases/phase-registry.yaml`, loads the active profile, and iterates through each gate in sequence.

Phase ids are strings (`0`–`9`, plus `build` and `close`), and phases are ordered but non-sequential — the system resolves "next phase" by the registry `order` field, never by incrementing the id. Advancement is always manual; no phase auto-advances.

**Core rules:**

- A phase transition is **blocked** if any gate with severity `MUST` fails.
- Gates with severity `SHOULD` produce warnings but do not block.
- Gates with severity `MAY` are purely informational.
- Gate definitions live in `phase-registry.yaml` under each phase's `exit_gate.conditions` list.
- Compliance-enabled profiles inject additional gates from `profiles/{profile_id}/compliance/{framework}-gates.yaml`.

**Execution flow:**

```
/sprd-gate (or /sprd-next)
  |
  v
check_gates.py --state .sdlc/state.yaml [--phase ID]
  |
  +-- Load phase-registry.yaml (find phase definition)
  +-- Load .sdlc/profile.yaml (quality thresholds, compliance config)
  +-- Resolve artifacts_dir: .sdlc/artifacts/{slug}/  (slug from registry, e.g. 03-foundation, build, close)
  |
  +-- Gate 1: Artifact Integrity      (file existence, non-empty)
  +-- Gate 2: Completeness            (no placeholder text, sections present)
  +-- Gate 3: Metrics                 (coverage, file sizes — checked per-change in the Build Loop)
  +-- Gate 4: Compliance              (compliance gates from profile)
  +-- Gate 5: Cross-Phase Consistency (locked-metric drift across phase transitions)
  +-- Gate 6: Quality                 (holistic review assessment)
  |
  v
Results: PASS / FAIL / MANUAL per check
  |
  v
Exit code 0 (all clear) or 1 (any MUST gate failed)
```

**Gate application varies by phase.** Not every gate applies at every phase with the same severity. The rows below are the nine registry phases (ordered by `order`, not by id):

| Phase | G1: Integrity | G2: Completeness | G3: Metrics | G4: Compliance | G5: Consistency | G6: Quality | G7: Exit criteria |
|-------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| 0 Discovery | MUST | MUST | -- | -- | -- | SHOULD | -- |
| 1 Requirements | MUST | MUST | -- | MUST | SHOULD | SHOULD | -- |
| 2 Design | MUST | MUST | -- | MUST | SHOULD | MUST | -- |
| 3 Foundation | MUST | MUST | -- | -- | SHOULD | SHOULD | REVIEW (3) |
| build (Build Loop) | MUST | MUST | SHOULD | SHOULD | SHOULD | SHOULD | REVIEW (1) |
| 7 Documentation | MUST | MUST | -- | -- | SHOULD | MUST | REVIEW (2) |
| 8 Deployment | MUST | MUST | SHOULD | -- | SHOULD | SHOULD | REVIEW (3) |
| 9 Monitoring | MUST | SHOULD | -- | -- | SHOULD | SHOULD | REVIEW (2) |
| close (Close & Transfer) | MUST | MUST | -- | -- | SHOULD | MUST | REVIEW (3) |

A dash (--) means the gate is not evaluated for that phase. For the **Build Loop**, the metrics, compliance, consistency, and quality gates are checked **per change** (each spec'd change is proven against its spec before merge) — there is no batch exit gate.

---

## 2. Gate 1: Artifact Integrity

**Purpose:** Verify that every required artifact for the phase exists on disk and is well-formed.

**Implementation in `check_gates.py`:**

The `check_artifact_exists()` function handles two cases:

1. **File artifacts** (e.g., `constitution.md`): The file must exist at `.sdlc/artifacts/NN-phasename/{artifact}`.
2. **Directory artifacts** (e.g., `adrs/`, `section-plans/`): The directory must exist *and* contain at least one child item. An empty directory fails the gate.

```python
def check_artifact_exists(artifacts_dir: Path, artifact: str) -> tuple[bool, str]:
    path = artifacts_dir / artifact
    if path.exists():
        if path.is_dir():
            children = list(path.iterdir())
            if children:
                return True, f"Directory '{artifact}' exists with {len(children)} item(s)"
            return False, f"Directory '{artifact}' exists but is empty"
        return True, f"File '{artifact}' exists"
    return False, f"Missing: '{artifact}'"
```

**What "well-formed" means:**

- The file is present and non-zero bytes (`check_artifact_not_empty()` reads the file and verifies `content.strip()` is truthy).
- For markdown files: the file can be read as UTF-8 text without corruption.
- For YAML files: the file parses without errors.
- For directories: at least one child file exists.

**Example -- Phase 0 (Discovery):** The following artifacts are all checked for existence:

| Artifact | Type | Description |
|----------|------|-------------|
| `constitution.md` | File | Project constitution and guiding principles |
| `problem-statement.md` | File | Problem definition and quantified impact |
| `success-criteria.md` | File | Measurable success metrics |
| `constraints.md` | File | Technical, business, and regulatory constraints |
| `phase1-handoff.md` | File | Handoff package for Phase 1 |

**Example -- Phase 2 (Design):** Includes a directory artifact:

| Artifact | Type | Description |
|----------|------|-------------|
| `design-doc.md` | File | Software architecture document |
| `api-contracts.md` | File | API endpoint specifications |
| `adrs/` | Directory | Must contain at least one ADR file |
| `adr-registry.md` | File | Index of all ADRs |
| `phase3-handoff.md` | File | Handoff package for Phase 3 |

**Severity:** Always `MUST`. A missing required artifact is an immediate blocker.

---

## 3. Gate 2: Completeness

**Purpose:** Verify that artifacts contain all required sections and that no placeholder content remains.

**Implementation in `check_gates.py`:**

The `check_artifact_complete()` function first delegates to `check_artifact_not_empty()` (the file must exist and have content), then scans the file's text for placeholder patterns:

```python
def check_artifact_complete(artifacts_dir: Path, artifact: str) -> tuple[bool, str]:
    exists, msg = check_artifact_not_empty(artifacts_dir, artifact)
    if not exists:
        return False, msg

    path = artifacts_dir / artifact
    if path.is_dir():
        return True, msg

    content = path.read_text(encoding="utf-8", errors="replace")
    placeholders = ["TODO", "TBD", "${", "PLACEHOLDER", "[INSERT", "<!-- REQUIRED:"]
    found = [p for p in placeholders if p in content]
    if found:
        return False, f"File '{artifact}' contains placeholder content: {found}"
    return True, f"File '{artifact}' is complete"
```

**Detected placeholder patterns:**

| Pattern | Meaning | Common Source |
|---------|---------|---------------|
| `TODO` | Work not yet done | Developer notes |
| `TBD` | Decision not yet made | Template stubs |
| `${...}` | Unresolved variable | Template interpolation |
| `PLACEHOLDER` | Filler content | Template boilerplate |
| `[INSERT` | Content insertion point | Template instructions (e.g., `[INSERT diagram here]`) |
| `<!-- REQUIRED:` | Marks a section that must be written — **delete the comment once it is**, or the artifact never passes | Template enforcement markers |

Note what is absent: ordinary bracket prose (`[Describe the situation]`) is **not** a marker.
Templates legitimately use `- [ ]` checkboxes and `[text](links)`, so a general bracket rule would
fail nearly every artifact. Gate 2 catches an untouched template, not a carelessly filled one.

**Build Loop spec-backlog summary:**

Within the Build Loop, the spec is the unit of work (one spec = one branch = one PR) and the durable source of truth. The gate system does not track sections; instead it reports a backlog summary derived directly from the spec files' own frontmatter. The gate runs `track_specs.py`, which scans `<repo>/specs/*.md`, reads each spec's `status` (draft → ready → in-flight → merged, or deferred) and `risk` (HIGH/MEDIUM/LOW), and prints an `INFO`-level breakdown:

1. **Status breakdown:** counts by status (merged / in-flight / ready / draft). `check_gates.py` is protected core, so this line is unchanged — a deferred spec is still counted in the total but not broken out here; `track_specs.py`'s own report does break it out, on its own line, once any spec uses it.
2. **Risk breakdown:** counts by risk tier.
3. **In-flight list:** the specs currently on a branch awaiting merge (a deferred spec is never in it).

This is informational, not a blocking consistency check — progress is read from reality (the spec frontmatter) rather than from a separately maintained tracker that can drift. The per-change checkpoint protocol (each spec committed and proven against its spec in the Discern beat before the next begins) is enforced by the Build loop itself, not by a section-count gate.

**Severity:** `MUST` for all phases except Monitoring (9), where completeness is `SHOULD`.

---

## 4. Gate 3: Metrics

**Purpose:** Verify that quantitative thresholds defined in the project profile are met.

**When it applies:** These metrics are enforced **per change inside the Build Loop**, where each spec'd change produces measurable outputs that must be proven against the spec before merge. There is no batch quality/testing phase — coverage, line counts, issue counts, and E2E results are checked continuously as changes flow through the loop. Deployment (8) also tracks metrics at `SHOULD` severity.

**Checks performed:**

| Metric | Source | Threshold | Phase |
|--------|--------|-----------|-------|
| Code coverage | Test runner output | `>= quality.coverage_minimum` (default 80%) | Build Loop (per change) |
| Critical path coverage | Test runner output | `>= quality.coverage_critical` | Build Loop (per change) |
| File line count | Static analysis | `<= quality.max_file_lines` | Build Loop (per change) |
| Function line count | Static analysis | `<= quality.max_function_lines` | Build Loop (per change) |
| CRITICAL/HIGH issues | Review reports | Must be zero | Build Loop (per change) |
| E2E test pass rate | E2E runner output | 100% pass | Build Loop (per change) |

**Implementation in `check_gates.py`:**

The metrics gate reads thresholds from the loaded `profile.yaml`. Because phase ids are strings, the gate keys off the build phase id rather than a numeric range:

```python
if phase_id == "build":
    quality = profile.get("quality", {})
    results.append({
        "gate": "G3-metrics",
        "check": "coverage_minimum",
        "passed": None,  # Requires external tool execution
        "message": f"Coverage must be >= {quality.get('coverage_minimum', 80)}% (requires test execution)",
        "severity": "SHOULD",
    })
```

Note the `passed: None` value. Metrics gates often require external tool execution (running the test suite, collecting coverage data) that cannot be performed by the gate checker alone. A `None` result means **manual verification is required** -- the gate system flags the check but a human or CI pipeline must confirm the result. In the Build Loop the real gating key is the `build` phase id, and the checks run per change rather than at a single batch transition.

**How external tools feed metrics:**

1. The test runner writes results (test results and coverage reports) under the Build Loop artifact directory `.sdlc/artifacts/build/`.
2. Static analysis tools write findings under `.sdlc/artifacts/build/` alongside each change's spec.
3. The gate system verifies these artifact files exist (Gate 1) and are complete (Gate 2), while flagging the numeric thresholds for manual/CI confirmation (Gate 3).

**Severity:** `SHOULD`, applied per change in the Build Loop. Deployment (8) tracks metrics at `SHOULD` as well.

---

## 5. Gate 4: Compliance

**Purpose:** Verify that artifacts are correctly categorized, labeled, and mapped to compliance requirements.

**Base classification checks:**

| Check | Description | Applicable Phases |
|-------|-------------|-------------------|
| Requirement priorities | All requirements labeled P0-P3 | 1, Build Loop |
| ADR statuses | Each ADR has status: proposed/accepted/deprecated/superseded | 2, Build Loop |
| Test-to-requirement mapping | Traceability matrix links tests to requirements | Build Loop |
| Security threat coverage | Security review covers all identified threat vectors | Build Loop |
| Compliance control mapping | Controls mapped to framework requirements | 1, 2, Build Loop |

**Compliance gate extensions:**

For profiles with `compliance.frameworks` configured, Gate 4 loads additional checks from `profiles/{profile_id}/compliance/{framework}-gates.yaml`. The `get_compliance_gates()` function iterates over each framework and extends the gate list:

```python
def get_compliance_gates(profile: dict) -> list[dict]:
    gates = []
    frameworks = profile.get("compliance", {}).get("frameworks", [])
    profile_id = profile["company"]["profile_id"]
    profile_dir = PLUGIN_ROOT / "profiles" / profile_id / "compliance"

    for fw in frameworks:
        gate_file = profile_dir / f"{fw}-gates.yaml"
        if gate_file.exists():
            data = load_yaml(gate_file)
            gates.extend(data.get("gates", []))
    return gates
```

Each compliance gate specifies a `check_type` that determines how it is evaluated:

| `check_type` | Behavior |
|--------------|----------|
| `artifact_exists` | Calls `check_artifact_exists()` -- file/directory must be present |
| `artifact_content` | Calls `check_artifact_complete()` and optionally checks for `required_content` keywords (case-insensitive match) |
| `manual` | Returns `passed: None` with a description -- requires human verification |
| `metric` | Returns `passed: None` -- requires external measurement |

**Content keyword checking:** When a compliance gate has `check_type: artifact_content` and includes a `required_content` list, the system reads the artifact file and checks that every keyword appears in the content (case-insensitive). Missing keywords cause a failure listing what was not found.

**Severity:** `MUST` for compliance-enabled profiles. `SHOULD` for profiles without compliance frameworks configured.

---

## 6. Gate 5: Cross-Phase Consistency

**Purpose:** Detect drift in locked metrics across phase transitions.

**Checks performed:**

- Read frozen layers from all prior completed phases.
- Identify "Locked Metrics" and "Constraints Carried Forward" sections.
- Flag for manual review: Claude compares locked values against current phase artifacts.
- Verify a decision log exists if any locked metrics have changed.

**Locked Metrics:** Budget, timeline, scope boundaries, stakeholder roster, quality thresholds, compliance requirements. See `references/cross-phase-consistency.md` for the full list and change protocol.

**Severity:** `SHOULD`. Consistency warnings surface drift for human review but do **not** block phase transitions. Legitimate scope changes are documented via decision log entries rather than suppressed.

---

## 7. Gate 6: Quality

**Purpose:** Holistic assessment of clarity, accuracy, consistency, and traceability across all phase outputs.

**Quality dimensions evaluated:**

| Dimension | What Is Checked |
|-----------|----------------|
| **Writing quality** | Clear, unambiguous language; appropriate use of RFC 2119 keywords (MUST/SHOULD/MAY) |
| **Technical accuracy** | Architecture decisions are sound; patterns appropriate for the target stack |
| **Consistency** | Naming conventions match profile; coding style aligns with project conventions |
| **Completeness of thought** | Edge cases considered; error handling defined; rollback plans present |
| **Review status** | Code review findings addressed (Build Loop); security review clean (Build Loop) |
| **Traceability** | Requirements trace to design decisions, design traces to tests, tests trace to code |

**Phase-dependent quality criteria:**

| Phase | Primary Quality Focus |
|-------|----------------------|
| 0 Discovery | Problem statement is specific and measurable; success criteria are quantifiable |
| 1 Requirements | Acceptance criteria are testable; no vague language |
| 2 Design | Architecture decisions justified via ADRs; API contracts complete |
| 3 Foundation | Harness installed, rails proven, walking skeleton deployed; section plans have verification criteria and evaluator contracts |
| build (Build Loop) | Every change spec'd, built from an approved plan, and proven against spec by a non-author before merge; no batch checking |
| 7 Documentation | All docs current; no stale references to pre-implementation design; verified by cold use |
| 8 Deployment | Rollback plan tested; smoke tests comprehensive |
| 9 Monitoring | Alert thresholds justified; incident response playbook actionable |
| close (Close & Transfer) | Client ran one real spec end-to-end unassisted; harness audited; access revoked |

**Severity:** `MUST` for Phase 2 (Design), Phase 7 (Documentation), and Close & Transfer (where quality failures have cascading downstream effects). `SHOULD` for all other phases, including the Build Loop where quality is assessed per change. Quality gate failures can be overridden with documented justification.

---

## 8. Gate 7: Exit Criteria

**Purpose:** Surface each phase's declared exit conditions that cannot be machine-checked, so a human sees the actual checklist before approving advancement. The registry has always declared these conditions under `exit_gate.conditions[]`, but until this gate existed no code ever read the prose ones. The human was stopped at the gate, shown a list of files that exist and contain no placeholders, and asked to approve — without ever seeing the checklist they were approving against. Gates report; humans decide.

**Checks performed:**

`check_gates.py` reads each phase's `exit_gate.conditions[]` from `phases/phase-registry.yaml`. Every condition is a dict:

- Conditions carrying an `artifact:` key are **skipped** — Gate 1 (existence) and Gate 2 (completeness) already check those.
- Conditions that are **prose** (a `check:` key and no `artifact:` key) are surfaced as human-review items. Each becomes a result with gate name `G7-exit-criteria`, `severity: "MUST"`, `passed: None`, and message `Human verification required: {check}`.

```python
for cond in phase.get("exit_gate", {}).get("conditions", []):
    if "artifact" in cond:
        continue  # G1/G2 already cover artifact conditions
    results.append({
        "gate": "G7-exit-criteria",
        "check": cond["check"],
        "passed": None,
        "message": f"Human verification required: {cond['check']}",
        "severity": "MUST",
    })
```

**Why it never blocks:** Severity is `MUST`, but `passed` is always `None` (never `False`), so it renders as `[MANUAL]` / `REVIEW`, never `[FAIL]`. `check_gates.py` exits non-zero only on MUST *failures* (`passed is False`), so G7 results never block the run. Instead, `advance_phase.py` treats `passed is None` as a manual gate: it prints `REVIEW REQUIRED`, lists every G7 item, and refuses to advance without `--confirmed`. The gate does not decide — it makes the human decide against the real checklist.

**Deliberately not machine-checkable:** These conditions encode judgment that no script can make. Examples from the registry:

- **Phase 3 (Foundation):** "The rails are proven, not just present (Stop hook blocks, gates fire, deploy rolls back)." A file existing does not prove the rail fires.
- **build (Build Loop):** "Build backlog is feature-complete (human declaration — no batch artifact gate)." Completeness of the backlog is a human call, not a countable artifact.

**Silence is expected for early phases:** Phases 0–2 declare no prose conditions today, so G7 emits nothing there. That is by design, not a gap. Adding conditions later is a **data-only change** to `phase-registry.yaml` — no code change is needed; the gate reads whatever the registry declares.

**Severity:** `MUST` in name, but always rendered as `REVIEW` because `passed` is `None`. It never blocks the run and never appears as a failure.

---

## 9. Severity Levels Deep Dive

The gate system uses three severity levels drawn from RFC 2119 terminology.

### MUST (Blocker)

An absolute requirement. If any gate check at `MUST` severity fails, the phase transition is blocked. The system exits with code 1 and prints `BLOCKED -- fix failures before advancing to next phase`.

**Examples:**
- A required artifact file does not exist (Gate 1)
- A required artifact contains `TODO` placeholder text (Gate 2)
- Code coverage is below the profile's `coverage_minimum` (Gate 3, Build Loop per change)
- A compliance framework requires an artifact that is missing (Gate 4)

**Aggregation rule:** ALL `MUST` gates must pass. Even a single `MUST` failure blocks the transition.

```python
# From check_gates.py main()
must_failures = [r for r in results if r["passed"] is False and r.get("severity") == "MUST"]
sys.exit(1 if must_failures else 0)
```

### SHOULD (Warning)

A strong recommendation. The transition proceeds, but the issue is flagged in the gate report. Teams are expected to address `SHOULD` warnings before the project completes.

**Examples:**
- Placeholder text found in an optional section of a required artifact
- Metrics thresholds not fully verified in the Build Loop or Deployment (8)
- Cross-phase consistency check flags drift in a locked metric (Gate 5)
- Quality assessment identifies minor inconsistencies

### MAY (Informational)

An optional observation. No impact on the transition. Used for suggestions and optional artifacts.

**Examples:**
- An optional artifact (e.g., `stakeholder-notes.md`) is not present
- A non-critical quality suggestion is noted
- An informational metric is reported but has no threshold

---

## 10. Gate Results Format

The `check_phase_gates()` function in `check_gates.py` returns a list of result dictionaries. Each result represents one check within one gate.

### Result Schema

```python
{
    "gate": str,        # Gate identifier (e.g., "G1-integrity", "G2-completeness",
                        #   "G3-metrics", "G4-compliance-{id}", "G5-consistency",
                        #   "G6-quality")
    "artifact": str,    # Artifact being checked (when applicable)
    "name": str,        # Human-readable check name (compliance gates)
    "check": str,       # Metric name (metrics gates, e.g., "coverage_minimum")
    "passed": bool|None,# True = passed, False = failed, None = requires manual check
    "message": str,     # Human-readable explanation
    "severity": str,    # "MUST", "SHOULD", or "MAY"
}
```

Not all fields are present on every result. The `gate` and `passed` fields are always present. Other fields appear depending on which gate produced the result.

### Formatted Output

The `format_results()` function renders the results for display:

```
Gate Check Results -- Phase 0
========================================
  [PASS] [MUST] G1-integrity: File 'constitution.md' exists
  [PASS] [MUST] G1-integrity: File 'problem-statement.md' exists
  [PASS] [MUST] G1-integrity: File 'success-criteria.md' exists
  [PASS] [MUST] G1-integrity: File 'constraints.md' exists
  [PASS] [MUST] G1-integrity: File 'phase1-handoff.md' exists
  [PASS] [MUST] G2-completeness: File 'constitution.md' is complete
  [PASS] [MUST] G2-completeness: File 'problem-statement.md' is complete
  [FAIL] [MUST] G2-completeness: File 'success-criteria.md' contains placeholder content: ['TODO']
  [PASS] [MUST] G2-completeness: File 'constraints.md' is complete
  [PASS] [MUST] G2-completeness: File 'phase1-handoff.md' is complete

Summary: 9 passed, 1 failed, 0 manual -- 10 total
BLOCKED -- fix failures before advancing to next phase
```

### Three-State Pass Logic

The `passed` field uses a three-state value:

| Value | Display | Meaning |
|-------|---------|---------|
| `True` | `[PASS]` | Check succeeded |
| `False` | `[FAIL]` | Check failed -- severity determines impact |
| `None` | `[MANUAL]` | Requires human or CI verification (e.g., running tests, reviewing code) |

The final summary line reports all three categories and provides a clear verdict:

- `ALL GATES PASSED -- ready to advance` when all checks are `True`
- `REVIEW -- manual checks require human verification` when no failures but some `None` values
- `BLOCKED -- fix failures before advancing to next phase` when any `MUST` check is `False`

---

## 11. Override Protocol

When a gate fails but the team decides to proceed anyway, the override must be formally recorded.

### Override Recording

Overrides are stored in `.sdlc/state.yaml` under the phase's history. Each override entry must contain:

```yaml
phases:
  "0":
    status: completed
    gate_results:
      - gate: G2-completeness
        artifact: success-criteria.md
        passed: false
        message: "File contains placeholder content: ['TODO']"
        severity: MUST
        override: true
        justification: "Metric definition deferred to Phase 1 by stakeholder agreement"
        approved_by: "Tech Lead"
```

### Override Restrictions by Gate

| Gate | Override Allowed? | Notes |
|------|:-----------------:|-------|
| Gate 1: Integrity | SHOULD NOT | Missing artifacts indicate objective failures |
| Gate 2: Completeness | SHOULD NOT | Incomplete artifacts cause downstream issues |
| Gate 3: Metrics | SHOULD NOT | Quantitative thresholds are objective |
| Gate 4: Compliance | **NO** (compliance profiles) | Compliance-enabled profiles MUST NOT override classification failures |
| Gate 4: Compliance | SHOULD NOT (other profiles) | Still represents an objective categorization failure |
| Gate 5: Consistency | SHOULD review, MAY proceed | Drift surfaces for review; intentional changes documented via decision log |
| Gate 6: Quality | MAY | Quality is subjective; override with documented justification |

### Override Tracking

The `audit_gates.py` script tracks override frequency across all completed phases. Override patterns are surfaced in the audit report under the "Override History" section, including which gate was overridden, in which phase, and the justification provided. High override frequency on a particular gate may indicate the gate threshold needs calibration.

---

## 12. Compliance Gate Extensions

Compliance frameworks add extra checks to the base 7-gate system. These are loaded dynamically from profile-specific YAML files.

### Supported Frameworks

| Framework | Gate File | Typical Checks |
|-----------|-----------|----------------|
| SOC 2 | `soc2-gates.yaml` | Access control documentation, audit logging, change management records |
| HIPAA | `hipaa-gates.yaml` | PHI handling procedures, encryption verification, access audit trails |
| GDPR | `gdpr-gates.yaml` | Data processing records, consent mechanisms, right-to-erasure procedures |
| PCI-DSS | `pci-dss-gates.yaml` | Cardholder data handling, network segmentation, vulnerability scanning |
| ISO 27001 | `iso27001-gates.yaml` | Information security policies, risk assessment, control statements |

### Gate File Structure

Compliance gate YAML files follow this structure:

```yaml
# profiles/microsoft-enterprise/compliance/soc2-gates.yaml
gates:
  - id: "soc2-access-control"
    name: "SOC 2 Access Control Documentation"
    phase: 2
    check_type: artifact_content
    artifact: "design-doc.md"
    required_content: ["access control", "authentication", "authorization"]
    severity: MUST

  - id: "soc2-audit-logging"
    name: "SOC 2 Audit Logging"
    phase: build
    check_type: artifact_exists
    artifact: "audit-logging-spec.md"
    severity: MUST

  - id: "soc2-change-management"
    name: "SOC 2 Change Management Review"
    phase: build
    check_type: manual
    description: "Verify change management procedures followed for all code changes"
    severity: MUST
```

### Check Type Behaviors

**`artifact_exists`:** Delegates to the same `check_artifact_exists()` function used by Gate 1. The artifact must be present on disk (and non-empty for directories).

**`artifact_content`:** First runs `check_artifact_complete()` (existence + no placeholders), then performs keyword matching. Each entry in the `required_content` list must appear somewhere in the artifact text (case-insensitive). For example, a SOC 2 gate checking `design-doc.md` for `["access control", "authentication", "authorization"]` will fail if any of those phrases are absent.

**`manual`:** Returns `passed: None` with a descriptive message. The check requires a human reviewer to confirm compliance. Manual checks appear as `[MANUAL]` in the gate report and trigger the `REVIEW` verdict.

**`metric`:** Returns `passed: None` and describes the metric to be measured. Like manual checks, these require external verification.

### Integration with Base Gates

Compliance gates are injected into Gate 4 (Compliance) results. They are filtered by phase number so only relevant compliance checks run for each phase:

```python
compliance_gates = get_compliance_gates(profile)
phase_compliance = [g for g in compliance_gates if g["phase"] == phase_id]
```

Compliance gate results appear in the output with gate identifiers prefixed by `G4-compliance-`:

```
  [PASS] [MUST] G4-compliance-soc2-access-control: File 'design-doc.md' is complete
  [MANUAL] [MUST] G4-compliance-soc2-change-management: Manual check required: SOC 2 Change Management Review
```

---

## 13. Gate Auditing

The `scripts/audit_gates.py` script analyzes gate effectiveness across completed phases to identify process calibration issues.

### Running an Audit

```bash
# Single project audit
uv run scripts/audit_gates.py --state /path/to/project/.sdlc/state.yaml

# Cross-project comparison
uv run scripts/audit_gates.py --state /path/to/project-a/.sdlc/state.yaml \
                               --compare /path/to/project-b/.sdlc/state.yaml
```

### How It Works

1. **Extract gate history:** The `extract_gate_history()` function walks through all phases in `state.yaml` and collects every gate result recorded during the project lifecycle. It handles both list and dict formats for `gate_results`.

2. **Compute statistics:** The `analyze_gates()` function aggregates per-gate metrics: total runs, pass count, fail count, manual count, phases where the gate was evaluated, and any overrides.

3. **Generate report:** The `format_report()` function produces a markdown-formatted audit with four sections.

### Audit Report Sections

**Gate Summary Table:**

```
| Gate | Runs | Passed | Failed | Manual | Fail Rate |
|------|------|--------|--------|--------|-----------|
| G1-integrity | 24 | 24 | 0 | 0 | 0% |
| G2-completeness | 24 | 20 | 4 | 0 | 17% |
| G3-metrics | 4 | 2 | 0 | 2 | 0% |
```

**Always-Pass Gates:** Gates that have never failed across all evaluated phases. These are candidates for tightening (raising the bar) or removal (if they add no value). A gate that passes 100% of the time may indicate the threshold is too lenient.

**High-Fail Gates:** Gates with a failure rate exceeding 50%. These may indicate that the threshold is unrealistic, the process needs better guidance, or teams need training on what the gate expects.

**Override History:** A table of every override recorded, showing the gate, phase, and justification. Frequent overrides on the same gate suggest the gate needs recalibration.

### Recommendations

The audit automatically generates recommendations based on the findings:

- If always-pass gates are found: suggests reviewing whether they add value or can be tightened.
- If high-fail gates are found: suggests reviewing whether thresholds are realistic.
- If overrides are found: suggests reviewing whether overridden gates should be relaxed or better enforced.
- If none of the above: reports that gate configuration appears well-calibrated.

### Minimum Data Warning

If fewer than 3 phases have been completed, the audit prints a warning that results may not be representative. Gate effectiveness analysis becomes meaningful only after several phase transitions have been evaluated.

---

## 14. Cross-References

| Topic | Document | Description |
|-------|----------|-------------|
| Profile configuration | `docs/profiles.md` | How compliance frameworks and quality thresholds are configured in profile YAML |
| `/sprd-gate` command | `commands/sprd-gate.md` | Slash command that triggers gate evaluation |
| `/sprd-next` command | `commands/sprd-next.md` | Slash command that runs gates and advances if all pass |
| `check_gates.py` | `scripts/check_gates.py` | Gate evaluation implementation |
| `audit_gates.py` | `scripts/audit_gates.py` | Gate effectiveness analysis implementation |
| Phase registry | `phases/phase-registry.yaml` | Phase definitions including required/optional artifacts and exit gate conditions |
| Validation rules | `references/validation-rules.md` | Concise reference for the 7-gate system and override protocol |
| Cross-phase consistency | `references/cross-phase-consistency.md` | Locked-metric list and change protocol for Gate 5 |
| State machine | `docs/state-machine.md` | How gate results are stored in `.sdlc/state.yaml` and drive phase transitions |
| Phase definitions | `phases/00-discovery.md`, `01-requirements.md`, `02-design.md`, `03-foundation.md`, `build-loop.md`, `07-documentation.md`, `08-deployment.md`, `09-monitoring.md`, `close.md` | Individual phase requirements and artifact specifications |
