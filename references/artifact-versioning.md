# Artifact Versioning & Auto-Refresh — content history and back-propagation

The [artifact-lifecycle layer](artifact-lifecycle.md) records change **metadata** (that an artifact
moved, when, by whom, why) and detects **forward** staleness. This layer closes the two gaps that
left behind:

1. **No content history / no safety net.** You could see *that* `FR-012` changed, never *what it said
   before* — you could not diff or roll back, and there was no reversibility to make an automated edit
   safe.
2. **Traceability only flowed forward.** Requirement → spec was declared; nothing flowed a built
   spec's **shipped reality back up** into `requirements.md` / `epics.md` / `feature-brief.md` /
   `business-rules.md`, so those pre-Build artifacts silently drifted from what shipped.

Two additions close them as **one package**: content-snapshot **versioning** (diff/rollback) and
draft+confirm **auto-refresh** (reverse propagation). Versioning is built first because it is the
**safety net** that makes an automated refresh reversible.

The commands are `/sprd-version` (content history: list/show/diff/rollback) and `/sprd-refresh`
(detect → draft → apply/reject → status). The engine folds into `scripts/audit_artifacts.py`; the
derivation math lives in one **pure** module, `scripts/version_model.py`. Everything here is
**advisory — `audit_artifacts.py` exits 0 on every path.**

---

## The store is the ledger rehydrated to bytes

The trust anchor of versioning is that it introduces **no second index**. Every version's identity is
the SHA-256 hash the change-ledger already carries (`track_artifacts.compute_checksum` output:
`sha256:` + 16 hex). The content-addressed object store is just those hashes rehydrated to bytes:

```
.sdlc/versions/objects/<xx>/<16hex>     content blobs, sharded on the first 2 hex, global dedup
```

`version_model.object_relpath(hash)` computes that path; the filename **is** the ledger's 16-hex, so
the join between "what the ledger says changed" and "the bytes of that version" is the hash itself —
there is nothing to drift. `versions_for(ledger, artifact)` walks
`artifact_model.changes_for(ledger, artifact)` **in ledger order** and counts *occurrences*, so a
version's ordinal `vN` is the primary key. A rollback that re-introduces an earlier hash is its own
ordinal (never a skipped one) and is rendered **"restored from vX"** — the ordinal the content first
appeared as.

`resolve_version(ref)` accepts `vN | latest | prev | <hashprefix>`; the ordinal is the key and a hash
prefix is only a disambiguated hint (an ambiguous prefix resolves to the **highest** matching ordinal
and lists the alternatives — never a silent guess).

## What a version is (and isn't)

A version is a **scan-time snapshot**, not keystroke history. There are **no write-path hooks**: the
content store only gains a blob at the layer's capture points, so a version is captured when —

- `/sprd-revise` records a change (it captures the pre- **and** post-edit image);
- `/sprd-next` runs its advance-time `record --scan`;
- `/sprd-audit-artifacts` runs its step-2 `record --scan`;
- `refresh apply` lands a `refreshed` change (pre-image captured, post-image materialized);
- `version rollback` lands a `revised` change (same canonical mutate order).

Between two capture points the file is invisible to the layer: **five edits collapse into the one
version** the next capture records. That is by design (the ledger, not a file-watcher, is the source
of truth) — but it means the history is as coarse as your scans, never a per-save timeline. Scan
often (or revise through `/sprd-revise`) if you want finer granularity.

## Reverse propagation, divergence-aware

Detection surfaces the pre-Build upstreams a `status: merged` spec traces to — from its `source:`
frontmatter **and** any in-vocabulary id (`FR|EP|US|BR|SCEN|FE|NFR|ADR`) in its body — via
`artifact_lineage.upstream_of`. The default is **review-first**: a faithful spec that correctly
realizes its upstream lists that upstream as *trace-only (no drift detected)* and drafts **nothing**.
A `.proposed` is only auto-drafted when a drift signal is present (the spec's acceptance/scope text
references a delta absent upstream) **or** the human passes `--draft`. This keeps the layer from
becoming a rubber-stamp mill while still making the candidates *surface automatically* the moment a
spec merges — zero human memory required.

The confirm path is `/sprd-revise` inverted and enforces the same **One Rule**: the mapped discipline
agent edits **only** a `.proposed` copy (the real artifact stays untouched); a **named human** echoes
the diffhash they reviewed and owns the applied change. `DISCIPLINE_BY_STEM` is the single in-code
source for the stem→agent routing (`requirements→requirements-analyst`,
`epics`/`feature-brief`→`feature-architect`, `business-rules→bizreq-analyst`), emitted per candidate
so the prose routing table in the command docs can't silently drift.

## The canonical mutate order (stated once, obeyed by rollback and refresh apply)

The post-image content is **already known** before the real file is touched (it is the target object
for a rollback, or the reviewed `.proposed` for an apply), so both write paths obey one order:

1. **Capture the pre-image** (current bytes → object). Reversibility is a *precondition* (**R6**): if
   capture fails, surface *"capture failed — this change is not reversible"*, **refuse, exit 0, no
   write.**
2. **Materialize the post-image object** from the known new content (idempotent write-if-absent).
3. **Append the ledger change** (`revised` for rollback, `refreshed` for apply; hash = post-image).
4. **`os.replace` the real file LAST** (temp-in-same-dir → atomic rename).

**Recovery** keys off *"ledger ahead of disk"*: on the next run, if an artifact's latest ledger hash
≠ its on-disk hash and the post-image object exists, the `os.replace` is redone (idempotent). Because
every step's object is present before the ledger references it, recovery can always complete.

## Requirements & resolutions (R1–R6)

| # | Requirement | Resolution |
|---|-------------|------------|
| **R1** | Refresh targets only pre-Build phase artifacts. | `PRE_BUILD_STEMS = {requirements, epics, feature-brief, business-rules}`. Frozen layers are structurally *downstream* and never returned by `upstream_of(spec)`; refreshing the phase artifact lets the existing forward-staleness engine flag the dependent layer on the next `/sprd-status`. |
| **R2** | A phantom or missing upstream never fabricates a candidate. | `source: —`, or a non-vocabulary / nonexistent id (`REQ-042`, `FR-999`), yields **zero** candidates + the nudge *"no traceable upstream — add an FR/EP/US/BR id to `source:`"*. Never a guess, never a crash. |
| **R3** | The lineage→candidate adapter can't `IndexError` on an edge with no declared basis. | `basis = bases[0] if bases else "coarse-phase-order"`; `upstream_hash` from `latest_change_per_artifact(ledger)`, falling back to `compute_checksum(current file)` when absent. |
| **R4** | A rejection must not render as forward staleness. | `reject` records `NOT_AFFECTED` as a **reverse** edge (downstream = the upstream artifact, upstream = the spec) — absent from the forward lineage graph, so `compute_staleness` never renders it. `/sprd-audit-artifacts` forward counts are unaffected. |
| **R5** | Changing a signed-off / completed-phase artifact needs explicit acknowledgement. | A shared `--ack-signoff` gate on `rollback --confirm` and `refresh apply`; without it, WARN and refuse (exit 0, no write). `--repo` with no sign-off data stays conservative and still asks for the flag. |
| **R6** | An automated mutate must be reversible by construction. | Pre-image capture is step 1 of the canonical order and a hard precondition; `track_artifacts.compute_checksum` is the single hashing path shared by ledger identity and object filename, so content↔hash stays lockstep at one `capture()` call-site. |

Two supporting blockers: **B2** — an artifact with no ledger entry (a pre-existing Phase-1 file)
yields a single **`v1` baseline** synthesized from the current file's hash (`present=False`), never
`[]` and never a `KeyError`. **B3** — the `version`/`refresh` subcommands write **nothing** to
`state.yaml`; re-gating stays the command layer's job (`/sprd-version` and `/sprd-refresh` instruct a
real `/sprd-gate` run afterward, exactly as `/sprd-revise` does), so "no `gate_results` phantom rows"
and "this layer writes no `state.yaml`" are both literally true. The apply/rollback impact preview is
a read-only `compute_staleness` render.

## `gc` — cross-ledger refcounted, sign-off-protected

`version gc --keep N` (preview by default; `--apply` to delete) prunes old snapshots. Because the
store is globally deduplicated, an object is evicted **only** if: no retained version across **all**
artifacts references its hash, it is not the latest for any artifact, and it is not
sign-off-protected. There is no direct sign-off→hash map, so for a signed-off artifact the substitute
protects `latest_change_per_artifact` plus every ledger-referenced hash; an **unknown or unparseable
sign-off ⇒ the object is PROTECTED** (a hard invariant — gc never deletes what it can't prove is
safe). Pruned versions render *"content not captured"*; the ledger is unchanged.

## Working across machines (`.gitignore` policy — a local safety net)

The committed source of truth is the metadata ledger (`.sdlc/metrics/artifact-log.jsonl`). The object
store and the transient refresh drafts are **local, non-authoritative** and gitignored:

```
.sdlc/refresh/**/*.proposed        # auto-refresh drafts (real artifact untouched)
.sdlc/refresh/**/candidates.json   # working candidate list (pinned upstream_hash)
.sdlc/refresh/_rollback/           # rollback previews awaiting confirm
.sdlc/versions/objects/            # content blobs — LOCKED default: gitignored
```

Because the blobs are gitignored, **a version's bytes live only on the machine that captured them.**
On a second machine (a fresh clone, CI, after a `gc` prune, or after a store fault) that version's
content is simply absent, and `list` / `show` / `diff` / `rollback` all read *"content not
captured"* at exit 0 — never a crash, and **not a bug**. The metadata (that the version exists, its
hash, when, by whom) is intact from the ledger; only the recoverable *bytes* are missing. The CLI
messages say this and point back here.

Two honest ways forward:

- **Start capturing on this machine.** Run the `record --scan` step (via `/sprd-audit-artifacts` or
  `/sprd-next`) here; from that scan on, this machine has the bytes of whatever it snapshots. It
  cannot recover a version captured only elsewhere.
- **Make the store portable.** Flip the one-line documented override in `.gitignore` — comment out
  the `.sdlc/versions/objects/` line and commit the store — so snapshots travel with the repo. History
  stays lean by default; this trades repo size for team-portable diff/rollback.

## How it stays additive

- **Advisory, never blocks.** Exit 0 on every path, including every refuse/abort (missing
  `--ack-signoff`, a moved `upstream_hash`, an agent-name `--actor`, rollback-to-uncaptured,
  capture-failed, R2 zero-candidate, empty / no-specs / first-ever-run).
- **Protected core byte-for-byte unchanged.** `check_spec.py`, `check_gates.py`, `section-evaluator`,
  `harness/**`, `phase_model.py`, `phase-registry.yaml`, `advance_phase.py`, `/sprd-coach`,
  `/sprd-spec`, `plugin.json` — and `artifact_model.py`: the `refreshed` entry reuses
  `change_entry(...)` unchanged, and the `source_spec` attribution is a **rider key** the caller adds
  to the dict, not a change to the model.
- **The ledger stays its own JSONL.** Nothing is written into `gate_results`; `/sprd-audit` is
  byte-identical with or without a version store or refresh run present. `audit_artifacts.py`'s
  existing `record` / `impact` / `report` output is byte-identical too — `capture()` rides the ledger
  append best-effort and prints nothing.

## Deletability caveat (the revert boundary)

Folding the verbs into `audit_artifacts.py` (rather than a standalone script) buys a single
`capture()` call-site that enforces content↔hash lockstep by construction — at the cost of
deletability. Reverting this feature is a **scoped code-revert** of the `version` and `refresh`
subcommand groups plus the `capture()` / `record_change()` wiring (and deleting `version_model.py`,
the two command docs, and this reference), **not** a single file delete. The forward-audit layer
underneath is untouched by such a revert.

## Deferred / accepted for v1

- **`NOT_AFFECTED` rejections are sticky** — a spec that re-merges after a rejection produces no new
  detection signal (reopen-on-spec-change needs a pinned spec-content hash; deferred).
- **The divergence heuristic needs tuning** — the review-only default + `--draft` bound the blast
  radius; a too-tight signal means the feature proposes little until tuned (visible, not silent).
- **`objects/` is a local-only safety net** (gitignored) — a fresh clone/CI degrades to "content not
  captured"; flip the documented override for portability.
- **R1's payoff is latent** — the dependent frozen layer is flagged on the *next* `/sprd-status`; the
  apply impact preview mitigates but doesn't fully resolve.
- **`gc` is a maintenance subcommand** (preview default, no dedicated slash command) — unbounded local
  growth until `gc --apply` is run.

*If this layer were reverted, the plugin would gate, freeze, revise, and audit exactly as it does
today. Versioning and auto-refresh only ever add reversibility and surface drift a human then
decides.*
