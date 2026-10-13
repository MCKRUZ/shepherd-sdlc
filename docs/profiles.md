# Profile System

Profiles are the configuration backbone of the Shepherd plugin. They define everything from your technology stack and quality thresholds to compliance frameworks and coding conventions. This document is the authoritative reference for the profile system.

---

## Table of Contents

1. [What Profiles Are](#1-what-profiles-are)
2. [Schema Reference](#2-schema-reference)
3. [Built-in Profiles](#3-built-in-profiles)
4. [How Profiles Affect the System](#4-how-profiles-affect-the-system)
5. [Creating Custom Profiles](#5-creating-custom-profiles)
6. [Profile Validation](#6-profile-validation)
7. [Compliance Framework Integration](#7-compliance-framework-integration)
8. [Evaluation Criteria System](#8-evaluation-criteria-system)
9. [Cross-References](#9-cross-references)

---

## 1. What Profiles Are

A profile is a YAML configuration file that customizes the entire SDLC pipeline for a specific company, team, or technology stack. Profiles control:

- **Technology stack** -- backend language/framework, frontend framework, database, cloud provider, and CI/CD platform.
- **Quality thresholds** -- minimum code coverage, maximum file/function sizes, whether TDD is mandatory, and qualitative evaluation criteria.
- **Compliance gates** -- which regulatory frameworks (SOC 2, HIPAA, GDPR, PCI-DSS, ISO 27001) trigger additional gate checks at phase transitions.
- **Coding conventions** -- commit message format, branch naming, immutability enforcement, and console.log prohibition.

### Lifecycle of a Profile

1. Profiles are authored as YAML files inside `profiles/<profile-name>/profile.yaml` in the plugin repository.
2. They are validated against `profiles/_schema.yaml` using `scripts/validate_profile.py`.
3. When a target project is initialized with `/sprd-setup`, the selected profile is copied to the target project's `.sdlc/profile.yaml`.
4. Once copied, the profile is **immutable** within the target project -- it serves as the contract that governs all subsequent SDLC phases.
5. Every phase, gate check, hook, agent, and report reads from `.sdlc/profile.yaml` to determine behavior.

### Directory Structure

```
profiles/
  _schema.yaml                          # Validation schema (all profiles MUST conform)
  starter/
    profile.yaml                        # Minimal profile for any stack
  microsoft-enterprise/
    profile.yaml                        # Full enterprise profile
    compliance/
      soc2-gates.yaml                   # SOC 2 gate definitions per phase
  ado-enterprise/
    profile.yaml                        # microsoft-enterprise's stack on Azure Repos + Azure Pipelines
    compliance/
      soc2-gates.yaml                   # SOC 2 gate definitions per phase
  ado-enterprise-python/
    profile.yaml                        # ado-enterprise's Python sibling (FastAPI + React, same rails)
    compliance/
      soc2-gates.yaml                   # SOC 2 gate definitions per phase
  creative-tooling/
    profile.yaml                        # Claude Code plugin development profile
```

---

## 2. Schema Reference

All profiles are validated against `profiles/_schema.yaml`. The schema uses standard JSON Schema types and enforces RFC 2119 keywords (MUST, SHOULD, MAY) in descriptions.

### Top-Level Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `version` | string | MUST | Schema version in semver `major.minor` format. Pattern: `^\d+\.\d+$`. Current: `"1.0"`. |
| `company` | object | MUST | Organization identity. |
| `stack` | object | MUST | Technology stack configuration. |
| `quality` | object | MUST | Quality thresholds and enforcement rules. |
| `compliance` | object | MAY | Compliance framework configuration. |
| `conventions` | object | MAY | Coding and workflow conventions. |

### `company` (required)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | MUST | Company or organization name. Free-form text. |
| `profile_id` | string | MUST | Unique profile identifier. MUST be kebab-case (lowercase letters, digits, hyphens only). Pattern: `^[a-z0-9-]+$`. This ID is used to locate the profile directory under `profiles/`. |

### `stack` (required)

The `stack` object defines the technology choices for the project. Only `backend` has required sub-fields; all other sub-objects are optional.

#### `stack.backend` (required within stack)

| Field | Type | Required | Constraints | Description |
|-------|------|----------|-------------|-------------|
| `language` | string | MUST | Enum: `csharp`, `typescript`, `python`, `java`, `go`, `rust` | Primary backend language. |
| `framework` | string | MUST | -- | Backend framework identifier (e.g., `dotnet-8`, `node`, `fastapi`). |
| `orm` | string | MAY | -- | ORM or data access layer (e.g., `ef-core`, `prisma`, `sqlalchemy`). |
| `testing` | string | MAY | -- | Testing framework (e.g., `xunit`, `jest`, `pytest`). |

#### `stack.frontend` (optional)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `language` | string | MAY | Frontend language (e.g., `typescript`). |
| `framework` | string | MAY | Frontend framework (e.g., `angular-17`, `react-18`, `vue-3`). |
| `state` | string | MAY | State management library (e.g., `ngrx`, `redux`, `pinia`). |
| `e2e` | string | MAY | End-to-end testing framework (e.g., `playwright`, `cypress`). |

#### `stack.database` (optional)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `engine` | string | MAY | Database engine (e.g., `sql-server`, `postgresql`, `mongodb`). |
| `migrations` | string | MAY | Migration tool (e.g., `ef-core`, `flyway`, `alembic`). |

#### `stack.cloud` (optional)

| Field | Type | Required | Constraints | Description |
|-------|------|----------|-------------|-------------|
| `provider` | string | MAY | Enum: `azure`, `aws`, `gcp`, `self-hosted` | Cloud provider. |
| `services` | array of strings | MAY | -- | List of cloud services used (e.g., `app-service`, `azure-sql`, `key-vault`). |

Note: The `microsoft-enterprise` profile also uses non-schema fields `auth_pattern`, `secrets`, and `monitoring` under `stack.cloud`. The schema does not restrict additional properties, so profiles MAY include extra fields for documentation purposes.

#### `stack.ci_cd` (optional)

| Field | Type | Required | Constraints | Description |
|-------|------|----------|-------------|-------------|
| `platform` | string | MAY | Enum: `github-actions`, `azure-devops`, `gitlab-ci`, `jenkins`, `circleci` | CI/CD platform. |

### `quality` (required)

| Field | Type | Required | Constraints | Description |
|-------|------|----------|-------------|-------------|
| `coverage_minimum` | integer | MUST | 0--100 | Minimum code coverage percentage. Enforced at Gate 3 (Metrics). |
| `coverage_critical` | integer | MAY | 0--100 | Coverage required for critical paths (auth, payments, identity). |
| `max_file_lines` | integer | MAY | >= 100 | Maximum lines per file. Checked during quality reviews. |
| `max_function_lines` | integer | MAY | >= 10 | Maximum lines per function. Checked during quality reviews. |
| `require_tdd` | boolean | MAY | -- | When `true`, the Build Loop MUST use test-driven development per change. |
| `require_code_review` | boolean | MAY | -- | When `true`, every change in the Build Loop MUST pass code review before merge. |
| `require_security_review` | boolean | MAY | -- | When `true`, the Build Loop MUST include a security review on sensitive (HIGH-risk) changes. |
| `evaluation_criteria` | array | MAY | -- | Qualitative evaluation standards for the section-evaluator agent. See [Section 8](#8-evaluation-criteria-system). |

#### `quality.evaluation_criteria[]` items

| Field | Type | Required | Constraints | Description |
|-------|------|----------|-------------|-------------|
| `name` | string | MUST | -- | Short name for the criterion (e.g., `"Result pattern"`, `"API documentation"`). |
| `description` | string | MUST | -- | What the evaluator checks for and what constitutes a pass. |
| `severity` | string | MAY | Enum: `fail`, `warn` | `fail` blocks section completion. `warn` is advisory. Default: `warn`. |

### `compliance` (optional)

| Field | Type | Required | Constraints | Description |
|-------|------|----------|-------------|-------------|
| `frameworks` | array of strings | MAY | Each item enum: `soc2`, `hipaa`, `gdpr`, `pci-dss`, `iso27001`, `none` | Compliance frameworks to enforce. Each adds framework-specific gate checks at phase transitions. |
| `audit_trail` | boolean | MAY | -- | When `true`, MUST maintain an audit trail of all changes and decisions. |
| `change_approval` | string | MAY | Enum: `peer-review`, `manager-approval`, `change-board`, `none` | Required approval level for changes. Affects the Build Loop (per-change review) and Phase 8 (Deployment) workflows. |

### `conventions` (optional)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `commit_format` | string | MAY | Commit message format pattern (e.g., `"type: description"`). |
| `branch_naming` | string | MAY | Branch naming convention pattern (e.g., `"type/ticket-description"`). |
| `immutability` | boolean | MAY | When `true`, prefer immutable data patterns. Hooks remind developers during edits. |
| `no_console_log` | boolean | MAY | When `true`, disallow `console.log` in production code. Hooks flag violations. |

---

## 3. Built-in Profiles

### `microsoft-enterprise`

A full-featured enterprise profile for C#/.NET 10 + Angular 22 projects deployed to Azure with SOC 2 compliance.

**Location:** `profiles/microsoft-enterprise/profile.yaml`

```yaml
version: "1.0"

company:
  name: "Example Corp"
  profile_id: "microsoft-enterprise"

stack:
  backend:
    language: csharp
    framework: dotnet-10
    orm: ef-core
    testing: xunit
  frontend:
    language: typescript
    framework: angular-22
    state: ngrx
    e2e: playwright
  database:
    engine: sql-server
    migrations: ef-core
  cloud:
    provider: azure
    services:
      - app-service
      - azure-sql
      - key-vault
      - app-insights
      - entra-id
    auth_pattern: DefaultAzureCredential
    secrets: azure-key-vault
    monitoring: app-insights
  ci_cd:
    platform: github-actions

quality:
  coverage_minimum: 80
  coverage_critical: 100
  max_file_lines: 800
  max_function_lines: 50
  require_tdd: true
  require_code_review: true
  require_security_review: true
  evaluation_criteria:
    - name: "Result pattern"
      description: "Error-prone operations use Result<T> instead of throwing exceptions. Evaluator checks for try/catch blocks that could use Result<T>."
      severity: warn
    - name: "Immutable state"
      description: "NgRx reducers return new state objects. No Array.push(), Object.assign() mutations, or direct property assignment on state."
      severity: fail
    - name: "API documentation"
      description: "All public API endpoints have XML doc comments on the controller action and a corresponding entry in api-contracts.md."
      severity: warn
    - name: "FluentValidation"
      description: "All DTOs received from external input have a corresponding FluentValidation validator class."
      severity: fail

compliance:
  frameworks:
    - soc2
  audit_trail: true
  change_approval: peer-review

conventions:
  commit_format: "type: description"
  branch_naming: "type/ticket-description"
  immutability: true
  no_console_log: true
```

**Key characteristics:**

- **Stack** -- Full Microsoft stack with C#/.NET 10 backend (Entity Framework Core, xUnit), Angular 22 frontend (NgRx state management, Playwright E2E), SQL Server database, and Azure cloud services including Entra ID for authentication, Key Vault for secrets, and Application Insights for monitoring.
- **Quality** -- 80% minimum coverage across the codebase, 100% coverage on critical paths (auth, payments). TDD is mandatory. Both code review and security review are required. Four evaluation criteria enforce Result pattern usage (warn), immutable NgRx state (fail), API documentation (warn), and FluentValidation on all DTOs (fail).
- **Compliance** -- SOC 2 framework enabled, which loads `compliance/soc2-gates.yaml` containing 10 phase-specific gate checks (CC6.1 access controls, CC6.6 system boundaries, CC7.1 change management, CC7.2 vulnerability management, CC8.1 code review, CC2.1 documentation, CC7.4 deployment). Audit trail is required. Change approval is set to `peer-review`.
- **Conventions** -- Conventional commits (`type: description`), feature branches (`type/ticket-description`), immutability enforcement, and no `console.log` in production code.

### `starter`

A minimal profile for getting started quickly with any stack. No compliance overhead, relaxed quality thresholds.

**Location:** `profiles/starter/profile.yaml`

```yaml
version: "1.0"

company:
  name: "My Project"
  profile_id: "starter"

stack:
  backend:
    language: typescript
    framework: node

quality:
  coverage_minimum: 60
  max_file_lines: 800
  max_function_lines: 50
  require_tdd: false
  require_code_review: false
  require_security_review: false

compliance:
  frameworks:
    - none
  audit_trail: false
  change_approval: none

conventions:
  commit_format: "type: description"
  branch_naming: "type/description"
  immutability: false
  no_console_log: false
```

**Key characteristics:**

- **Stack** -- TypeScript/Node backend only. No frontend, database, cloud, or CI/CD defined. Users are expected to customize these for their project.
- **Quality** -- 60% minimum coverage. No TDD requirement. No code review or security review mandated. No evaluation criteria defined -- the starter profile relies on numeric thresholds only.
- **Compliance** -- Framework set to `none`, no audit trail, no change approval. This means no compliance-specific gates are checked at phase transitions.
- **Conventions** -- Conventional commits only. No immutability or console.log enforcement.

---

## 4. How Profiles Affect the System

Profiles are not just documentation -- they are actively read by scripts, hooks, agents, and commands at every stage of the SDLC. Here is how each component uses the profile.

### Gate Validation (`scripts/check_gates.py`)

The gate checker reads `.sdlc/profile.yaml` at every phase transition and enforces:

- **Gate 3 (Metrics)** -- `quality.coverage_minimum` is checked against actual test coverage. If the project reports coverage below this threshold, the gate fails and blocks advancement to the next phase.
- **Gate 4 (Compliance)** -- For each framework listed in `compliance.frameworks`, the script loads the corresponding gate YAML file from `profiles/<profile_id>/compliance/<framework>-gates.yaml`. Each compliance gate specifies a `phase`, `check_type`, and `severity`. Gates are matched to the current phase and executed. Check types include:
  - `artifact_exists` -- Verifies a file or non-empty directory exists in the artifacts directory.
  - `artifact_content` -- Verifies a file exists, is non-empty, contains no placeholder content (TODO, TBD, PLACEHOLDER), and includes all `required_content` keywords.
  - `metric` -- References a threshold from the profile (e.g., `quality.coverage_minimum`) for comparison against actual metrics.
  - `manual` -- Flags a check that requires human verification. Reported as MANUAL in results.

Gate results are categorized as PASS, FAIL, or MANUAL. Any FAIL on a MUST-severity gate blocks phase advancement.

### Phase Behavior

- **Build Loop** -- When `quality.require_tdd` is `true`, every change MUST follow TDD (red-green-refactor) per spec: write failing tests first, then implement to make them pass, then refactor. The section-evaluator/grader verifies it per change.
- **Build Loop** -- code review (non-author Checker) and, for HIGH-risk changes, security review are enforced at the per-change merge bar. When `quality.require_code_review` is `true`, a code review MUST be completed and documented before merge. When `quality.require_security_review` is `true`, a security review MUST be performed on sensitive code (authentication, authorization, payments, identity).
- **Phase 8 (Deployment)** -- The `compliance.change_approval` setting determines what approval is required before deployment:
  - `peer-review` -- At least one peer must review and approve.
  - `manager-approval` -- A manager or team lead must approve.
  - `change-board` -- A formal change advisory board must approve.
  - `none` -- No approval gate.

### Hook Behavior

The session-start hook (`hooks/shepherd-session-start.ps1`) reads `.sdlc/state.yaml` at the beginning of each Claude Code session and loads the current phase context. Profile conventions are injected into the active session:

- When `conventions.immutability` is `true`, the session context includes reminders to use immutable data patterns (spread operators, `with` expressions, new state objects in reducers).
- When `conventions.no_console_log` is `true`, the session context includes a reminder to use structured logging instead of `console.log`.
- `conventions.commit_format` and `conventions.branch_naming` are surfaced so that Claude Code follows the team's conventions when creating commits and branches.

### Agent Behavior

The **section-evaluator agent** (`agents/section-evaluator.md`) reads `.sdlc/profile.yaml` during the Build Loop (per completed spec/section) to apply profile-defined evaluation criteria. For each completed section:

1. The agent loads the section plan from `.sdlc/artifacts/03-foundation/section-plans/`.
2. It reads the profile's `quality.evaluation_criteria` array.
3. Each criterion is evaluated against the implementation. If a criterion's `severity` is `fail`, a violation blocks section completion. If `warn`, the violation is reported but does not block.
4. Results appear in the evaluation report under a "Profile Evaluation Criteria" table.

### Report Generation

Profile information is included in HTML reports generated by `scripts/generate_phase_report.py`. The report header displays the company name, profile ID, stack summary, and compliance frameworks. Quality thresholds are shown alongside actual metrics for comparison.

---

## 5. Creating Custom Profiles

### Step 1: Copy the Starter Profile

```bash
mkdir profiles/my-company
cp profiles/starter/profile.yaml profiles/my-company/profile.yaml
```

### Step 2: Edit the Profile

Update all sections to match your organization's requirements:

```yaml
version: "1.0"

company:
  name: "My Company"
  profile_id: "my-company"       # MUST match the directory name

stack:
  backend:
    language: python              # Choose: csharp, typescript, python, java, go, rust
    framework: fastapi
    orm: sqlalchemy
    testing: pytest
  frontend:
    language: typescript
    framework: react-18
    state: redux
    e2e: cypress
  database:
    engine: postgresql
    migrations: alembic
  cloud:
    provider: aws
    services:
      - ecs
      - rds
      - secrets-manager
  ci_cd:
    platform: github-actions

quality:
  coverage_minimum: 75
  coverage_critical: 95
  max_file_lines: 600
  max_function_lines: 40
  require_tdd: true
  require_code_review: true
  require_security_review: true
  evaluation_criteria:
    - name: "Type hints"
      description: "All public functions have complete type annotations."
      severity: warn
    - name: "Pydantic models"
      description: "All API request/response schemas use Pydantic models with validators."
      severity: fail

compliance:
  frameworks:
    - gdpr
  audit_trail: true
  change_approval: peer-review

conventions:
  commit_format: "type: description"
  branch_naming: "feature/JIRA-NNN-description"
  immutability: true
  no_console_log: true
```

### Step 3: Validate the Profile

```bash
uv run scripts/validate_profile.py profiles/my-company/profile.yaml
```

Expected output on success:

```
PASS -- profile.yaml is valid
```

On failure, the script reports each validation error with the field path and reason:

```
FAIL -- 2 validation error(s):
  x quality.coverage_minimum: 150 > maximum 100
  x stack.backend.language: 'php' not in allowed values ['csharp', 'typescript', 'python', 'java', 'go', 'rust']
```

### Step 4: Add Compliance Gate Files (Optional)

If your profile uses compliance frameworks other than `none`, create framework-specific gate YAML files:

```
profiles/my-company/
  profile.yaml
  compliance/
    gdpr-gates.yaml
```

Each gate file defines phase-specific checks. Use the SOC 2 gates file as a template:

```yaml
version: "1.0"
framework: gdpr

gates:
  - phase: 1
    id: gdpr-data-mapping
    name: "Data Mapping"
    criteria: "Article 30 -- Records of processing activities"
    check_type: artifact_content
    artifact: "requirements.md"
    required_content:
      - "personal data"
      - "data processing"
    severity: MUST

  - phase: 2
    id: gdpr-privacy-design
    name: "Privacy by Design"
    criteria: "Article 25 -- Data protection by design"
    check_type: artifact_content
    artifact: "design-doc.md"
    required_content:
      - "data minimization"
      - "encryption"
    severity: MUST
```

Supported `check_type` values:

| Check Type | What It Does | Required Fields |
|------------|-------------|-----------------|
| `artifact_exists` | Verifies a file or non-empty directory exists | `artifact` |
| `artifact_content` | Verifies file exists, is non-empty, has no placeholders, and contains required keywords | `artifact`, `required_content` |
| `metric` | Compares a metric against a profile threshold | `metric`, `threshold_key` |
| `manual` | Flags for human verification | `description` |

### Step 5: Done — There Is No Registration Step

Profiles are **auto-discovered**: `/sprd-setup` lists the `profiles/` directory at runtime
(excluding `_schema.yaml`) and presents every profile it finds — including ones not named in
any documentation. The plugin manifest (`.claude-plugin/plugin.json`) is metadata only and has
no profile registry; the plugin ships the whole repository directory
(`.claude-plugin/marketplace.json` declares `"source": "."`), so your new directory ships with
it automatically.

Two things must be true for the profile to work fully, both enforced by
`scripts/tests/test_validate_profile.py::TestOnDiskProfiles` the moment the directory exists:

1. `profile.yaml` passes the schema (Step 3).
2. `company.profile_id` equals the directory name — compliance gates are resolved at
   `profiles/<profile_id>/compliance/`, so a mismatched id silently loses its gates (Step 4).

---

## 6. Profile Validation

### The Validator Script

`scripts/validate_profile.py` performs comprehensive validation against `profiles/_schema.yaml`. It is the single source of truth for profile correctness.

**Usage:**

```bash
uv run scripts/validate_profile.py <path-to-profile.yaml>
```

### What Gets Validated

| Check Category | What Is Checked |
|----------------|-----------------|
| **Required fields** | Top-level `version`, `company`, `stack`, `quality` must exist. Within `company`: `name` and `profile_id`. Within `stack.backend`: `language` and `framework`. Within `quality`: `coverage_minimum`. |
| **Type validation** | Each field is checked against its expected type (string, integer, boolean, array, object). |
| **Enum validation** | `stack.backend.language` must be one of: `csharp`, `typescript`, `python`, `java`, `go`, `rust`. `stack.cloud.provider` must be one of: `azure`, `aws`, `gcp`, `self-hosted`. `stack.ci_cd.platform` must be one of: `github-actions`, `azure-devops`, `gitlab-ci`, `jenkins`, `circleci`. `compliance.frameworks[]` items must be one of: `soc2`, `hipaa`, `gdpr`, `pci-dss`, `iso27001`, `none`. `compliance.change_approval` must be one of: `peer-review`, `manager-approval`, `change-board`, `none`. `evaluation_criteria[].severity` must be one of: `fail`, `warn`. |
| **Pattern validation** | `company.profile_id` must match `^[a-z0-9-]+$` (kebab-case). `version` must match `^\d+\.\d+$` (semver major.minor). |
| **Range validation** | `coverage_minimum` and `coverage_critical` must be 0--100. `max_file_lines` must be >= 100. `max_function_lines` must be >= 10. |
| **Evaluation criteria** | Each item in `evaluation_criteria` must have `name` and `description`. If `severity` is present, it must be `fail` or `warn`. |

### Exit Codes

| Code | Meaning |
|------|---------|
| `0` | All validations passed. |
| `1` | One or more validation errors found. Errors are printed to stdout with field paths. |

### Error Message Format

Errors include the full field path for easy identification:

```
Root: missing required field 'quality'
company.profile_id: must be kebab-case (a-z, 0-9, hyphens)
quality.coverage_minimum: 150 > maximum 100
stack.backend.language: 'php' not in allowed values ['csharp', 'typescript', 'python', 'java', 'go', 'rust']
quality.evaluation_criteria[0]: missing required field 'name'
quality.evaluation_criteria[1].severity: 'error' not in allowed values ['fail', 'warn']
```

---

## 7. Compliance Framework Integration

### How Compliance Frameworks Work

When `compliance.frameworks` includes one or more framework identifiers (anything other than `none`), the gate checker loads framework-specific gate YAML files at every phase transition. These files live in the profile's `compliance/` subdirectory.

**Resolution path:** `profiles/<profile_id>/compliance/<framework>-gates.yaml`

For example, a profile with `frameworks: [soc2, hipaa]` would load:
- `profiles/<profile_id>/compliance/soc2-gates.yaml`
- `profiles/<profile_id>/compliance/hipaa-gates.yaml`

If a gate file does not exist, no gates are loaded for that framework -- there is no error, but no compliance checks run either.

### SOC 2 Gate Definitions

The `microsoft-enterprise` profile ships with a complete SOC 2 gates file (`profiles/microsoft-enterprise/compliance/soc2-gates.yaml`) that maps AICPA Trust Services Criteria to SDLC phase gates:

| Phase | Gate ID | SOC 2 Criteria | Check Type | What Is Verified |
|-------|---------|---------------|------------|-----------------|
| 1 (Requirements) | `soc2-cc6.1-requirements` | CC6.1 -- Access Controls | `artifact_content` | `requirements.md` mentions "authentication" and "authorization" |
| 2 (Design) | `soc2-cc6.6-boundaries` | CC6.6 -- System Boundaries | `artifact_content` | `design-doc.md` mentions "trust boundary" and "security" |
| 2 (Design) | `soc2-cc7.1-change-mgmt` | CC7.1 -- Change Management | `artifact_exists` | `adrs/` directory exists with at least one ADR |
| build (Build Loop) | `soc2-cc6.1-implementation` | CC6.1 -- Access Controls | `manual` | Verify auth/authz code exists with unit tests |
| build (Build Loop) | `soc2-cc7.2-vulnerability` | CC7.2 -- Vulnerability Mgmt | `artifact_exists` | `review-reports/` directory exists |
| build (Build Loop) | `soc2-cc8.1-code-review` | CC8.1 -- Code Review | `artifact_exists` | `review-reports/` directory exists |
| build (Build Loop) | `soc2-cc7.1-testing` | CC7.1 -- Testing | `metric` | Coverage meets `quality.coverage_minimum` |
| 7 (Documentation) | `soc2-cc2.1-documentation` | CC2.1 -- Documentation | `manual` | README and API docs reflect current system |
| 8 (Deployment) | `soc2-cc7.4-deployment` | CC7.4 -- Change Deployment | `artifact_content` | `release-notes.md` mentions "rollback" |
| 9 (Monitoring) | `soc2-cc7.2-monitoring` | CC7.2 -- Monitoring | `manual` | Security monitoring alerts are configured |

All SOC 2 gates have `severity: MUST`, meaning failures block phase advancement.

### HIPAA Integration

A HIPAA gates file would follow the same structure, adding checks for:

- Protected Health Information (PHI) handling verification in requirements and design
- Encryption at rest and in transit validation
- Access logging and audit trail verification
- Minimum necessary access principle in authorization design
- Business Associate Agreement (BAA) documentation

To add HIPAA support, create `profiles/<profile_id>/compliance/hipaa-gates.yaml` following the gate file format described in [Section 5](#step-4-add-compliance-gate-files-optional).

### Other Frameworks

The same pattern applies to GDPR (data protection, consent management, right to erasure), PCI-DSS (cardholder data environment, network segmentation, encryption), and ISO 27001 (information security management controls). Each framework needs a corresponding gate YAML file in the profile's `compliance/` directory.

### How `change_approval` Affects the Pipeline

The `compliance.change_approval` setting controls the approval workflow:

- **`peer-review`** -- Every change in the Build Loop requires a documented non-author review (the Checker). At Phase 8 (Deployment), the release must have a peer-reviewed approval.
- **`manager-approval`** -- Same as peer-review, but the reviewer must have manager-level authority. This is enforced via manual checks.
- **`change-board`** -- A formal Change Advisory Board review is required before deployment. This typically maps to an external approval process and is flagged as a manual gate check.
- **`none`** -- No approval gates are added beyond what the compliance frameworks already require.

### Audit Trail

When `compliance.audit_trail` is `true`, the SDLC system expects all phase transitions, gate results, decisions (ADRs), and review outcomes to be recorded in `.sdlc/` artifacts. The `check_gates.py` script verifies that required audit artifacts exist at each phase transition.

---

## 8. Evaluation Criteria System

### Overview

Evaluation criteria are profile-defined qualitative standards that go beyond numeric thresholds (coverage, line counts). They are applied by the **section-evaluator agent** in the Build Loop, as each spec/section is completed (per change, not batched).

Unlike numeric checks that can be automated, evaluation criteria require semantic analysis of the code -- the agent reads the implementation and judges whether the criterion is satisfied.

### Schema

Each evaluation criterion is an object in the `quality.evaluation_criteria` array:

```yaml
evaluation_criteria:
  - name: "Short name"                    # Required. Identifies the criterion.
    description: "What to check for..."   # Required. Instructions for the evaluator.
    severity: fail                         # Optional. "fail" or "warn". Default: "warn".
```

### Severity Levels

| Severity | Behavior |
|----------|----------|
| `fail` | Violation **blocks** section completion. The section cannot be marked as done until the issue is fixed. |
| `warn` | Violation is **reported** but does not block. Appears in the evaluation report as an advisory finding. |

If `severity` is omitted, the section-evaluator agent treats it as `warn` (non-blocking).

### How the Section-Evaluator Agent Uses Criteria

When the section-evaluator agent is invoked for a completed section:

1. It loads `.sdlc/profile.yaml` and extracts `quality.evaluation_criteria`.
2. For each criterion, it reads the relevant implementation files and applies the `description` as evaluation instructions.
3. Results are recorded in a "Profile Evaluation Criteria" table in the evaluation report:

```
## Profile Evaluation Criteria

| Criterion         | Result | Notes                                       |
|-------------------|--------|---------------------------------------------|
| Result pattern    | PASS   | All service methods use Result<T>            |
| Immutable state   | FAIL   | Array.push() found in user.reducer.ts:42    |
| API documentation | WARN   | POST /api/users missing XML doc comment      |
| FluentValidation  | PASS   | All 3 DTOs have validator classes            |
```

4. If any `fail`-severity criterion results in FAIL, the overall section verdict is FAIL.
5. If only `warn`-severity criteria have findings, the section gets a CONDITIONAL PASS with warnings listed.

### Example: microsoft-enterprise Criteria

The `microsoft-enterprise` profile defines four evaluation criteria:

| Name | What It Checks | Severity | Rationale |
|------|---------------|----------|-----------|
| **Result pattern** | Error-prone operations use `Result<T>` instead of throwing exceptions. The evaluator looks for try/catch blocks that could be replaced with Result types. | `warn` | Encourages the Result pattern but does not block if exceptions are used in some cases. |
| **Immutable state** | NgRx reducers return new state objects. No `Array.push()`, `Object.assign()` mutations, or direct property assignment on state. | `fail` | State mutation in NgRx is a correctness bug that causes subtle issues. This must be caught. |
| **API documentation** | All public API endpoints have XML doc comments on the controller action and a corresponding entry in `api-contracts.md`. | `warn` | Documentation is important but should not block implementation progress. |
| **FluentValidation** | All DTOs received from external input have a corresponding FluentValidation validator class. | `fail` | Input validation is a security boundary concern. Missing validators are a security risk. |

### Designing Good Criteria

When writing evaluation criteria for your custom profile:

- **Be specific** -- The description should tell the evaluator exactly what to look for. Vague criteria produce inconsistent evaluations.
- **Use `fail` sparingly** -- Reserve `fail` severity for correctness and security concerns. Use `warn` for style and documentation.
- **Keep the list focused** -- 3--6 criteria is typical. Too many dilute the evaluator's attention.
- **Match your stack** -- Criteria should reflect patterns specific to your technology choices. A Python project would not check for FluentValidation.

---

## 9. Cross-References

| Topic | Location | Description |
|-------|----------|-------------|
| Gate system | `docs/gate-system.md` | How gates work, gate categories (G1--G6), phase transitions |
| Commands | `docs/commands.md` | `/sprd-setup` (profile selection and initialization) |
| Scripts | `docs/scripts.md` | `validate_profile.py`, `check_gates.py`, `generate_phase_report.py` |
| Agents | `docs/agents.md` | `section-evaluator` agent behavior and evaluation workflow |
| Phase definitions | `phases/00-discovery.md`, `01-requirements.md`, `02-design.md`, `03-foundation.md`, `build-loop.md`, `07-documentation.md`, `08-deployment.md`, `09-monitoring.md`, `close.md` | Per-phase requirements and artifacts |
| Phase registry | `phases/phase-registry.yaml` | Phase metadata and gate definitions |
| Schema file | `profiles/_schema.yaml` | The validation schema itself |
| SOC 2 gates | `profiles/microsoft-enterprise/compliance/soc2-gates.yaml` | SOC 2 gate definitions |
| Plugin manifest | `.claude-plugin/plugin.json` | Plugin metadata only — profiles are auto-discovered from `profiles/`, not registered |
| Validation rules | `references/validation-rules.md` | Additional validation rule documentation |
