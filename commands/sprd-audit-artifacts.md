# /sdlc-audit-artifacts — Artifact Freshness, Impact & History

Audit the **content** of your pre-Build artifacts: which ones have gone stale relative to the things
they depend on, what a change would put at risk, and the full change trail of any one artifact.

This is a **sibling** to `/sdlc-audit`, not a replacement. `/sdlc-audit` audits *gate effectiveness*
(are the gates well-calibrated). This command audits *artifact staleness and change history*. They
answer different questions and never overlap.

Everything here is **advisory** — it surfaces candidates a human dispositions; it never blocks a
gate, changes a verdict, or edits your artifacts, specs, or `state.yaml`.

## Instructions

1. **Resolve mode and repo root:**
   - **Workflow mode** (default): look for `.sdlc/state.yaml`. Pass `--state .sdlc/state.yaml` to the
     script. If not found, tell the user to run `/sdlc-setup` first.
   - **Standalone mode** (`--repo <path>`, or no `.sdlc/` found): run against any repo containing a
     `.sdlc/` directory. History and staleness are only as deep as the ledger in that repo.

2. **Freshen the change-ledger** (so staleness reflects what is actually on disk):
   ```bash
   uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/audit_artifacts.py record --scan --state .sdlc/state.yaml
   ```
   This appends **only** to the change-ledger (`.sdlc/metrics/artifact-log.jsonl`) — it hashes the
   artifact tree and records any new or drifted files. It never touches your artifacts, specs, or
   `state.yaml`. On the very first run it seeds a baseline ("history starts now") — it does not
   invent a past. In standalone mode pass `--repo <path>` instead of `--state`.

3. **Pick the lens** from the user's request:

   - **Freshness dashboard (default)** — per artifact: when it last changed and by whom (from the
     ledger), its sign-off status (from `state.yaml`), and **FRESH** or **STALE** vs. its declared
     sources. Scope with `--phase <id>`, `--artifact <id|path>`, or `--since <YYYY-MM-DD>`:
     ```bash
     uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/audit_artifacts.py report --state .sdlc/state.yaml
     ```

   - **`--impact <id|file>`** (forward) — *"I'm about to change FR-012 — what depends on it?"* Walks
     the lineage graph and lists every downstream artifact and the path, **before** you commit:
     ```bash
     uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/audit_artifacts.py impact FR-012 --state .sdlc/state.yaml
     ```

   - **`--history <id|file>`** (backward) — the full change trail of one artifact from the ledger:
     every revision, when, who, why, and any linked `DL-NN`:
     ```bash
     uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/audit_artifacts.py report --history FR-012 --state .sdlc/state.yaml
     ```
     `--history` shows the change **metadata** (when/who/why). To see what the artifact actually
     **said** at each version — or to diff two versions — point the user at the read-only
     `/sdlc-version list|show|diff <id|file>` command (the content complement). Rolling one back lives
     there too, behind its own named-human confirm; this command never mutates.

4. **Display results** with the honest confidence labels intact:
   - Every downstream edge is tagged **declared** (a written-down link: a frozen layer's
     `source_artifacts`, a spec's `source`, an `FR-012`/`BR-04` id reference, an explicit markdown
     path) or **coarse** (a phase-order *guess*, used only where nothing was declared). Never present
     a coarse inference as a declared link.
   - A STALE artifact is a **candidate**, never "broken" — it may already account for the change.
   - Report the honest counts: `N stale · X open · Y dispositioned`. "no data" reads as no data,
     never a fabricated zero.

5. **Offer to disposition open staleness** (optional). For each OPEN candidate the human wants to
   resolve, record their judgement (this is the only write, and only to the ledger):
   ```bash
   uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/audit_artifacts.py \
     record --disposition ACKNOWLEDGED --downstream <file> --upstream <file> --owner "<name>" --state .sdlc/state.yaml
   ```
   - `REFRESHED` is **derived** — update the downstream artifact and the next scan clears it
     automatically; you don't record it by hand.
   - `ACKNOWLEDGED` needs an **owner** or it still counts as debt. `NOT_AFFECTED` needs a **reason**.
     You cannot clear debt by typing a word — honest counting enforces this.

## Arguments

- No arguments: freshness dashboard for the whole project (workflow mode).
- `--repo <path>`: standalone mode — audit any repo with a `.sdlc/` present.
- `--impact <id|file>`: forward lineage — what a change here could make stale.
- `--history <id|file>`: backward change trail for one artifact.
- `--phase <id>` / `--artifact <id|path>` / `--since <YYYY-MM-DD>`: scope the dashboard.

## Important

- The user runs `/sdlc-audit-artifacts` — never `audit_artifacts.py` by hand. The command owns the
  scan, the lens selection, and the disposition recording.
- **Read-only with respect to your project.** The only authoritative thing this command writes is the
  change-ledger (`.sdlc/metrics/artifact-log.jsonl`) — the audit trail itself; the `record --scan` in
  step 2 also best-effort captures each changed artifact's content into the gitignored, non-
  authoritative version store (`.sdlc/versions/`), which a store fault silently skips without changing
  this command's output. It never edits an artifact, a spec, or `state.yaml`. To *change* an artifact,
  use `/sdlc-revise`; to *roll one back*, `/sdlc-version`.
- **Advisory by construction** — `audit_artifacts.py` exits 0 always. Staleness is never a gate; a
  candidate is a prompt for a human's judgement, not a verdict.
