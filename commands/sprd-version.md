# /sdlc-version — Content History of One Artifact (diff & roll back)

See what a pre-Build artifact **used to say**, diff any two of its versions, and — when a change went
wrong — roll it back. This is the content complement to `/sdlc-audit-artifacts`: that command tracks
*that* an artifact changed (the metadata trail); this one recovers *what it said* at each version and
restores it if needed.

```
/sdlc-version list requirements.md
/sdlc-version diff FR-012 prev latest
/sdlc-version rollback requirements.md prev
```

Versions are derived from the change-ledger's SHA-256 hashes — the object store is just those hashes
rehydrated to bytes, so there is no second index to drift. Snapshots are a **local safety net**
(`.sdlc/versions/objects/` is gitignored by default); a fresh clone or CI degrades to *"content not
captured"* at exit 0, never a crash.

## Instructions

1. **Resolve mode and repo root:**
   - **Workflow mode** (default): look for `.sdlc/state.yaml`; pass `--state .sdlc/state.yaml`. If not
     found, tell the user to run `/sdlc-setup` first.
   - **Standalone mode** (`--repo <path>`, or no `.sdlc/`): operate on the given repo. History is only
     as deep as that repo's ledger and object store.

2. **Pick the verb** from the user's request. Every one accepts an **id** (`FR-012`) or an
   **artifact path** and joins on the repo-relative path, so `FR-012` and its file resolve to the
   same history.

   - **`list <artifact>`** — the version list `v1..vN`: ordinal, event, when, who. A version whose
     bytes were never captured is marked `[content not captured]` (honest — not a lie that it's gone):
     ```bash
     uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/audit_artifacts.py version list <artifact> --state .sdlc/state.yaml
     ```

   - **`show <artifact> [ref]`** — print one version's content. `ref` is `vN | latest | prev |
     <hashprefix>` (default `latest`). Missing blob → *"content not captured for this version"*:
     ```bash
     uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/audit_artifacts.py version show <artifact> v2 --state .sdlc/state.yaml
     ```

   - **`diff <artifact> [a] [b]`** — unified diff between two versions (default `prev` → `latest`):
     ```bash
     uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/audit_artifacts.py version diff <artifact> prev latest --state .sdlc/state.yaml
     ```

3. **Roll back — preview first, then a named human confirms** (the One Rule; identical handshake to
   `/sdlc-revise` and `refresh apply`):

   a. **Preview** (default — writes nothing to the artifact). It prints the diff you'd apply and a
      `diffhash` to echo back:
      ```bash
      uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/audit_artifacts.py version rollback <artifact> prev --state .sdlc/state.yaml
      ```
      - Rolling back to an **uncaptured** version refuses here (*"content not captured — cannot
        restore"*) — it never restores from a missing object.

   b. **Confirm** — the human reviews the diff, then re-runs with `--confirm --actor <their name>
      --reviewed <diffhash>`. Echoing the exact `diffhash` from the preview is how they attest they
      saw *this* change; `--actor` must be a real person, never a discipline agent:
      ```bash
      uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/audit_artifacts.py \
        version rollback <artifact> prev --confirm --actor "<name>" --reviewed <diffhash> \
        --decision-ref DL-NN --state .sdlc/state.yaml
      ```
      - **Sign-off gate:** if the artifact is signed off or in a completed phase, the rollback refuses
        unless the human adds `--ack-signoff` (exit 0, no write). In `--repo` mode with no sign-off
        data it stays conservative and still asks for the flag.
      - The revert is recorded as an **append-only** `revised` version — the rollback is itself
        undoable, and a restored earlier hash renders "restored from vX". Nothing is ever destroyed.

4. **Open a linked decision-log item and re-gate** (a confirmed rollback *is* a change):
   - Read `.sdlc/decision-log.md`, allocate the next `DL-NN`, append one row (id matching the
     `--decision-ref` you passed), owner = the actor, with the 2-business-day clock — exactly as
     `/sdlc-revise` does. If the file is missing, create it from
     `${CLAUDE_PLUGIN_ROOT}/templates/phases/01-requirements/decision-log.md`.
   - Run `/sdlc-gate` for the artifact's phase and report PASS/FAIL. Re-gating stays a real,
     human-visible gate run — this command writes **nothing** to `state.yaml`.

5. **Maintenance — `gc` (optional, preview by default).** Prune old snapshots, keeping the newest N
   per artifact. An object is evicted only if **no** retained version across **all** artifacts
   references its hash, it is not any artifact's latest, and it is not sign-off-protected
   (unknown/unparseable sign-off ⇒ protected). Preview first; `--apply` to delete:
   ```bash
   uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/audit_artifacts.py version gc --keep 10 --state .sdlc/state.yaml
   ```

## Arguments

- `list|show|diff|rollback|gc` — the verb.
- `<artifact>`: an id (`FR-012`) or an artifact path — the two resolve to one history.
- `[ref]` / `[a] [b]`: `vN | latest | prev | <hashprefix>`; ordinal is the primary key, a hash prefix
  is a disambiguated hint (ambiguous prefix → highest ordinal + lists alternatives).
- `--repo <path>`: standalone mode (no `.sdlc/` present).
- rollback: `--confirm --actor <name> --reviewed <diffhash>` to apply; `--ack-signoff` to change a
  signed-off artifact; `--decision-ref DL-NN` to link the decision.
- gc: `--keep N`, `--apply`.
- `--json` on `list` for machine output.

## Important

- The user runs `/sdlc-version` — never `audit_artifacts.py` by hand. The command owns mode
  resolution, the preview→confirm handshake, and the decision-log + re-gate follow-through.
- **Additive and advisory.** `version` writes only to the object store (`.sdlc/versions/`) and, on a
  confirmed rollback, appends one `revised` entry to the change-ledger. It never touches
  `state.yaml`'s gate results or sign-off records, and `audit_artifacts.py` exits 0 on every path.
- **Versions are scan-time snapshots, not keystroke history.** Content is captured only at the
  layer's capture points (`/sdlc-revise`, `/sdlc-next`'s and `/sdlc-audit-artifacts`'s `record --scan`,
  `refresh apply`, `rollback`) — there are no write-path hooks, so several edits between captures
  collapse into one version. See *"What a version is (and isn't)"* in
  `references/artifact-versioning.md`.
- **The store is a local safety net.** `.sdlc/versions/objects/` is gitignored by default, so a
  version's bytes live only on the machine that captured them; a version present in one clone reads
  *"content not captured"* in another (fresh clone/CI, after `gc`, or a store fault) — honest, not a
  bug. Start capturing here with `record --scan`, or flip the documented one-line `.gitignore`
  override to make snapshots portable. See *"Working across machines"* in
  `references/artifact-versioning.md`.
- **Rollback is reversible.** Every confirmed rollback appends a new version rather than overwriting
  history, so you can always roll forward again.
