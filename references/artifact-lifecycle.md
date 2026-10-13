# Artifact Lifecycle — changing an artifact after the fact, and auditing the trail

The plugin is strong at *creating* artifacts and *gating* them. This layer is about what happens
**after** an artifact exists and someone needs to change it — a requirement turns out wrong, an SLA
moves, a business rule is refined in design. Left implicit, that change is invisible: nothing flags
the frozen layer or the downstream design doc as out of date, and there is no record of what changed,
when, by whom, or why.

This is the conceptual reference for the artifact-update-audit layer. The commands are
`/sprd-revise` (change one thing) and `/sprd-audit-artifacts` (audit freshness, impact, history);
the engine is `scripts/audit_artifacts.py` over two models (`artifact_model.py`,
`artifact_lineage.py`). Everything here is **advisory** — it tells a human something worth knowing;
it never decides.

---

## The core insight

The tool already knows the two facts needed to detect staleness — it just never connected them:

- **When each artifact last changed** — every artifact is hashed (SHA-256). The change-ledger
  records each new/changed hash with a timestamp, an actor, and a reason.
- **What depends on what** — traceability is *already declared* across the corpus: a frozen layer's
  `source_artifacts:`, a spec's `source:`, the feature-brief "Traces to" column, and the
  `FR-NN` / `EP-NN` / `US-NN` / `BR-NN` / `SCEN-NN` id vocabulary.

Connect "what changed" with "what depends on it" and staleness falls out: if an **upstream** artifact
changed *after* a **downstream** one last did, the downstream is a **stale candidate**.

## The change-ledger

An append-only JSONL at `.sdlc/metrics/artifact-log.jsonl` — the artifact **history** the tool
otherwise lacks. It lives in its own file, never inside `state.yaml`'s `gate_results` (which is
gate-audit territory), so `/sprd-audit` is byte-for-byte identical with or without this layer.

Two entry kinds share the file, told apart by `event`:

- a **change** entry (`created` / `revised` / `refreshed` / `snapshot`) records that an artifact's
  content moved: `{artifact, target, phase, hash, prev_hash, actor, reason, decision_ref}`.
- a **disposition** entry records a human's judgement about one staleness candidate.

Changes reach the ledger three ways, all command-driven (never a hook into `advance_phase.py`):

1. **`/sprd-revise`** appends an explicit `revised` entry for the thing you changed.
2. **`record --scan`** hash-walks the artifact tree and records any new (`created`) or drifted
   (`snapshot`) file. It runs at the top of `/sprd-audit-artifacts` and at advance time in
   `/sprd-next`, so direct edits (made outside `/sprd-revise`) are captured too.
3. The **first-ever scan** seeds a baseline — "history starts now". Nothing about the past is
   fabricated; missing data reads as no data.

## Lineage — declared, with a labeled coarse fallback

`artifact_lineage.py` harvests `upstream → downstream` edges, each tagged with a **confidence**:

- **declared** (high confidence) — the link is written down: a frozen layer's `source_artifacts`, an
  id reference (the file that *declares* `FR-012` is upstream of any file that *references* it), or an
  explicit markdown path pointing from a later-phase file to an earlier-phase one.
- **coarse** (a guess) — where an artifact declares *nothing*, phase order supplies a fallback edge
  (an artifact in the prior phase is assumed upstream). Always labeled, so a coarse inference is never
  mistaken for a declared link.

Traversal is cycle-safe (a visited set), so a mutual reference can never loop forever.

## The staleness disposition state machine

A stale candidate is `(downstream, upstream@hash)` — pinned to the upstream's content hash so a
*later* upstream change re-opens the item rather than silently inheriting an old disposition. Its
disposition follows the same honest-counting discipline as review findings — you cannot clear debt by
typing a word:

| Disposition | Counts as debt? | Rule |
|-------------|-----------------|------|
| `OPEN` | **yes** | untouched. |
| `REFRESHED` | no | the downstream changed *after* the upstream — **derived** from a later ledger hash, not claimed. A re-scan clears it automatically. |
| `ACKNOWLEDGED` | no **only** with an owner | a human accepts the debt for now; without an `owner` it still counts. |
| `NOT_AFFECTED` | no **only** with a reason | a human judges no ripple; without a `reason` it still counts. |

A mislabeled disposition (ACKNOWLEDGED with no owner) counts exactly like OPEN.

## How it stays additive

- **Advisory, never blocks.** `audit_artifacts.py` exits 0 always. Staleness is a REVIEW aid a human
  dispositions — the tool flags **candidates**, it never asserts breakage or changes a gate verdict.
- **Protected core untouched.** `check_spec.py`, `check_gates.py`, `section-evaluator`, `harness/**`,
  `phase_model.py`, `phase-registry.yaml`, `/sprd-coach`, `/sprd-spec`, and `advance_phase.py` are all
  byte-for-byte unchanged. The new modules *read* `check_spec` helpers; they never modify them.
- **No phantom rows.** The ledger is a standalone JSONL; nothing is written into `gate_results`.
- **Dual-mode + graceful degradation.** Every script runs standalone (`--repo`) or in-workflow
  (`--state`). With no ledger yet, the first run snapshots a baseline and reports "no history yet".

*If this whole layer were deleted, the plugin would gate, freeze, and sign off exactly as it does
today. The artifact-update-audit surface only ever tells a human something worth knowing.*
