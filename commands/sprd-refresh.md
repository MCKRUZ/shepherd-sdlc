# /sdlc-refresh — Back-Propagate a Built Spec into Its Upstream Artifacts

Traceability normally flows forward (requirement → spec → code). This command runs it **backward**:
when a spec merges, it surfaces the pre-Build artifacts that spec implies an edit to —
`requirements.md`, `epics.md`, `feature-brief.md`, `business-rules.md` — so they stop silently
drifting from what actually shipped. It reads as `/sdlc-revise` **inverted**: instead of you changing
one artifact and rippling forward, a merged spec proposes the upstream edits and a **named human**
confirms them.

```
/sdlc-refresh detect --spec specs/0001-duplicate-claim-409.md
/sdlc-refresh draft  --spec specs/0001-duplicate-claim-409.md --draft
/sdlc-refresh apply  --spec specs/0001-duplicate-claim-409.md requirements --actor me
/sdlc-refresh status --spec specs/0001-duplicate-claim-409.md
```

The **One Rule** holds throughout: the discipline agent **drafts** the change into a `.proposed`
copy; a **named human decides** whether to apply it. No agent ever edits the real artifact.

## Instructions

1. **Resolve mode and repo root:**
   - **Workflow mode** (default): look for `.sdlc/state.yaml`; pass `--state .sdlc/state.yaml`. If not
     found, tell the user to run `/sdlc-setup` first.
   - **Standalone mode** (`--repo <path>`, or no `.sdlc/`): operate on the given repo.

2. **Detect — review first, draft only on a signal (the divergence-aware default).** List the
   pre-Build upstreams the merged spec traces to (from its `source:` frontmatter and any in-vocabulary
   id in its body). A faithful spec that correctly realizes its upstream lists the upstreams as
   *trace-only (no drift detected)* and drafts **nothing** — the layer never becomes a rubber-stamp:
   ```bash
   uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/audit_artifacts.py refresh detect --spec <spec-path> --state .sdlc/state.yaml
   ```
   - Each row is tagged **declared** (a written-down link) or **coarse** (a phase-order guess).
     Coarse guesses are listed for context and **never** auto-drafted.
   - **Zero-candidate honesty:** a `source: —`, or a non-vocabulary / nonexistent id (`REQ-042`,
     `FR-999`), yields zero candidates and the nudge *"no traceable upstream — add an FR/EP/US/BR id
     to `source:`"* — never a fabricated guess, never a crash.
   - Upstreams that already changed **after** the spec merged are suppressed as already-fresher.
   - Pass `--draft` to mark all declared upstreams draft-eligible even without a drift signal;
     `--transitive` / `--include-coarse` widen the set (coarse still never drafts).

   To see this across **all** merged specs at once (this is what backs the `/sdlc-status` drift
   nudge), use `refresh scan` instead of `detect --spec`.

3. **Draft — spawn the owning discipline agent to edit the `.proposed` (never the real file).**
   `draft` copies each eligible upstream to a `.proposed` beside a `candidates.json` that pins the
   upstream's hash at draft time:
   ```bash
   uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/audit_artifacts.py refresh draft --spec <spec-path> [<stem>] [--draft] --state .sdlc/state.yaml
   ```
   Then, for each drafted stem, spawn the mapped discipline agent with an explicit contract:
   **"Edit ONLY this `.proposed` file to reflect what spec NNNN shipped; the real artifact stays
   untouched. Return the edited `.proposed`."**

   | Drafted stem | Owning discipline agent |
   |--------------|-------------------------|
   | `requirements` | `requirements-analyst` |
   | `epics` | `feature-architect` |
   | `feature-brief` | `feature-architect` |
   | `business-rules` | `bizreq-analyst` |

   (This is the same `DISCIPLINE_BY_STEM` map the script emits per candidate — keep this table in
   sync with the script, which is the single source.) A re-`draft` overwrites an existing `.proposed`
   and warns.

4. **Apply — the named human confirms one stem at a time (preview → confirm).** `apply` previews the
   diff until the human echoes the diffhash they saw:

   a. **Preview** (writes nothing to the artifact) — prints the diff of `.proposed` vs the real
      upstream and a `diffhash`:
      ```bash
      uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/audit_artifacts.py refresh apply --spec <spec-path> <stem> --state .sdlc/state.yaml
      ```

   b. **Confirm** — the human reviews the diff, then re-runs with `--actor <name> --reviewed
      <diffhash>` (presence of `--reviewed` is the confirm signal). `--actor` must be a real person,
      never a discipline agent:
      ```bash
      uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/audit_artifacts.py \
        refresh apply --spec <spec-path> <stem> --actor "<name>" --reviewed <diffhash> \
        --reason "<what shipped, back-propagated>" --decision-ref DL-NN --state .sdlc/state.yaml
      ```
      - **Staleness guard:** if the upstream moved since the draft (its current hash ≠ the pinned
        `candidates.json` hash), apply refuses — *"upstream moved since draft; re-run detect/draft"* —
        no write, exit 0.
      - **Sign-off gate:** a signed-off / completed-phase upstream refuses without `--ack-signoff`
        (exit 0, no write); `--repo` with no sign-off data stays conservative and still asks for it.
      - On confirm it records a `refreshed` change (attributed to this spec) and captures a snapshot,
        so the refresh is **rollback-able** via `/sdlc-version rollback`. That snapshot is a local,
        gitignored safety net — on another machine it may read *"content not captured"* (honest, not a
        bug); see *"Working across machines"* in `references/artifact-versioning.md`.

5. **Reject — record that a listed upstream is NOT affected.** If the spec doesn't ripple to an
   upstream, take it off the books honestly:
   ```bash
   uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/audit_artifacts.py \
     refresh reject --spec <spec-path> <stem> --reason "<why unaffected>" --owner "<name>" --state .sdlc/state.yaml
   ```
   - `--reason` is **required** — a rejection without a reason still counts as debt (honest counting).

6. **Open a linked decision-log item and re-gate** after an apply (a refresh *is* a change):
   - Allocate the next `DL-NN` in `.sdlc/decision-log.md` (create from
     `${CLAUDE_PLUGIN_ROOT}/templates/phases/01-requirements/decision-log.md` if missing), owner =
     the actor, 2-business-day clock, id matching `--decision-ref`.
   - Run `/sdlc-gate` for the refreshed artifact's phase and report PASS/FAIL. Re-gating is a real,
     human-visible gate run — this command writes **nothing** to `state.yaml`.

7. **Status & report.** Show the per-spec disposition of each upstream (honest counting; reads "no
   data" when empty):
   ```bash
   uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/audit_artifacts.py refresh status --spec <spec-path> --state .sdlc/state.yaml
   ```
   ```
   Refresh <spec>: <N> upstreams — <k> refreshed, <m> not-affected, <j> open
   Applied: <stem> in <path>  (actor: <name>, DL-NN)  → rollback via /sdlc-version
   Re-gate: PASS | FAIL (<blockers>)
   ```

## Arguments

- `detect|scan|draft|apply|reject|status` — the verb.
- `--spec <spec-path>`: the merged spec (required for every verb except `scan`; optional on `status`
  where it defaults to a rollup across all merged specs).
- `<stem>`: `requirements | epics | feature-brief | business-rules` — which upstream (positional on
  `draft`/`apply`/`reject`).
- detect/draft: `--draft` (draft without a drift signal), `--transitive`, `--include-coarse`.
- apply: `--actor <name> --reviewed <diffhash>` to confirm; `--ack-signoff`; `--reason`;
  `--decision-ref DL-NN`.
- reject: `--reason` (required), `--owner`, `--actor`.
- `--repo <path>`: standalone mode. `--json` on detect/scan/draft/status for machine output.

## Important

- The user runs `/sdlc-refresh` — never `audit_artifacts.py` by hand. The command owns mode
  resolution, agent routing, the preview→confirm handshake, and the decision-log + re-gate
  follow-through.
- **Agent drafts, human decides.** The discipline agent edits only the `.proposed`; a named human
  echoes the diffhash and owns the decision-log item. Same One Rule as `/sdlc-revise` and
  `/sdlc-spec`'s risk tier.
- **Review-first, never a rubber stamp.** Detection lists trace-only candidates and drafts only on a
  drift signal or explicit `--draft`. A faithful spec produces a review, not an edit.
- **Additive and advisory.** `refresh` writes only to the change-ledger, the object store, and the
  transient `.sdlc/refresh/` drafts. It never touches `state.yaml`, and `audit_artifacts.py` exits 0
  on every path — including every refuse/abort. See `references/artifact-versioning.md`.
- When a refresh lands, the artifact now matches what shipped — and the next `/sdlc-status` scan will
  flag any frozen layer downstream of it, closing the loop forward again.
