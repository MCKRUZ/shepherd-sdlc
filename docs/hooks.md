# Hook System

The SDLC plugin ships **one hook**: a session-start script that injects the project's SDLC
context (phase, artifacts, active sprint) into Claude's context at the start of every
session. It reads project state and never modifies it.

> An earlier revision of the plugin also shipped a per-edit `sdlc-phase-inject.ps1` hook
> (phase reminders on every Edit/Write). It was retired; phase guidance now lives in the
> commands and the appended CLAUDE.md SDLC section. If you find references to it elsewhere,
> they are stale.

---

## Table of Contents

1. [Hook System Overview](#1-hook-system-overview)
2. [shepherd-session-start — Session Initialization Hook](#2-shepherd-session-start--session-initialization-hook)
3. [Hook Registration in hooks/hooks.json](#3-hook-registration-in-hookshooksjson)
4. [Hook Design Principles](#4-hook-design-principles)
5. [Cross-References](#5-cross-references)

---

## 1. Hook System Overview

Hooks are scripts Claude Code executes at lifecycle events, with their stdout injected into
Claude's context as system-level reminders — visible to the model, not shown in the user's
chat. The plugin's hook fires on the `SessionStart` event.

Key properties:

- **Read-only.** The hook inspects `.sdlc/state.yaml` and related files but never writes.
- **Stdout-driven.** Every output line becomes a context reminder.
- **Gracefully degrading.** If `.sdlc/state.yaml` does not exist (SDLC not initialized),
  the hook exits silently with code 0.
- **Two implementations, one contract.** `shepherd-session-start.ps1` (PowerShell) and
  `shepherd-session-start.sh` (bash) produce the same output; registration tries `pwsh` first
  and falls back to `bash`, so hosts with either runtime work out of the box.

---

## 2. shepherd-session-start — Session Initialization Hook

**Source:** `hooks/shepherd-session-start.ps1` and `hooks/shepherd-session-start.sh` (twins).

### Trigger

Fires once when a new Claude Code session begins. The hook checks for `.sdlc/state.yaml`
in the current working directory. If the file is absent, the hook exits 0 immediately —
no output, no error.

### What It Reads

| File | Purpose |
|------|---------|
| `.sdlc/state.yaml` | Extracts `current_phase`, `phase_name`, `profile_id`, `project_name` via regex |
| `.sdlc/artifacts/<slug>/` | Counts all files recursively to report artifact progress (dir is the phase slug; `build` and `close` are non-numeric) |
| `.sdlc/profile.yaml` | Convention reminders (`immutability`, `no_console_log`) and the opt-in `session_health_check` |
| `.sdlc/constitution.md`, `.sdlc/context/layers/`, `.sdlc/context/intake/index.md` | The 3-tier context: Foundation, the three most recent frozen layers, the document-intake index |
| `.sdlc/sprints/*.md` | Sprint Team Layer — one `[SHEPHERD-SPRINT]` line per sprint record whose `state:` is not `closed` (any phase; silent when the directory is absent) |
| `.sdlc/ado/local/hook-status.txt` | Azure Boards mirror — one `[SHEPHERD-ADO]` line echoing the file's first line (CR and NUL stripped), e.g. `3 rows pending · 1 drifted · as of 2026-10-12T09:02Z`. Written by `/sprd-ado plan` and `pull`; silent when the file is absent or its first line is empty; never calls `az`, never touches the network |

### State Parsing

The hook does not use a full YAML parser. It extracts values with four targeted regexes:

- `current_phase:\s*"?([^"\r\n]+)"?` — phase id (0,1,2,3,build,7,8,9,close; may be non-numeric)
- `phase_name:\s*"?([^"\r\n]+)"?` — human-readable phase name
- `profile_id:\s*"?([^"\r\n]+)"?` — active profile identifier
- `project_name:\s*"?([^"\r\n]+)"?` — project display name

A built-in lookup table maps phase ids to canonical display names (Discovery, Requirements,
Design, Foundation, Build Loop, Documentation, Deployment, Monitoring, Close & Transfer).
The regex-extracted `phase_name` is used only as a fallback when the id is not in the table.

### Artifact Counting

The hook constructs the path from the phase's slug (e.g. `00-discovery`, `03-foundation`,
`build`, `close`) — not by zero-padding an int, since `build` and `close` are non-numeric —
and recursively counts all files. This count appears in the context banner so Claude knows
how much work product exists for the current phase.

### Output Format

The hook emits two mandatory lines for every initialized project, then one phase reminder:

```
[SHEPHERD] Project: My API Service | Profile: microsoft-enterprise | Phase build: Build Loop | Artifacts: 12
[SHEPHERD] Commands: /sprd (guidance) | /sprd-status (dashboard) | /sprd-gate (check) | /sprd-next (advance) | /sprd-coach (coaching)
[SHEPHERD-PHASE] One spec at a time: Intent -> Delegate -> Discern. Check per change, never in a batch. The author never approves their own work. Refinement for the next sprint runs alongside — /sprd-refine; the board is /sprd-sprint.
```

The first line gives Claude situational awareness. The second reminds it which slash
commands are available. The third is the phase's behavioural reminder; the Build Loop's
carries the sprint clause so the reminder is no longer wrong when a session is spent
refining the *next* sprint's specs rather than building the current one.

### Active Sprint Line (Sprint Team Layer)

Directly after the `[SHEPHERD-PHASE]` reminder, the hook lists every sprint record under
`.sdlc/sprints/*.md` (the `templates/phases/build/sprint.md` shape written by `/sprd-sprint`)
whose `state:` is not `closed`. It emits **one additional line per active sprint**, in
filename order:

```
[SHEPHERD-SPRINT] S07 (ready) — "Ship the duplicate-claim rail" — 2026-09-28 → 2026-10-09
```

The fields are the record's `sprint`, `state`, `goal`, `start` and `end` frontmatter values,
read with grep/sed (bash) and `Select-String`-style regexes (PowerShell) only — no date
arithmetic, no JSON, no `uv`, no Python. The parsing rule is deliberately small and
identical in both twins:

- the first `key:` line in the file wins;
- a double-quoted value is taken verbatim; an unquoted value is cut at a trailing `# comment`
  and trimmed (so `state: ready   # planning | ready | closed` reads `ready`);
- `\r` is stripped, so a record authored on Windows renders the same;
- a file with no `state:` line, or an empty one, is not a sprint record the hook understands
  and is skipped; a `closed` record is skipped;
- a missing `sprint:` falls back to the file's basename.

This is the line that lets everyone open a session knowing the sprint and its end date. It is
not phase-gated: refinement for the next sprint runs in any phase where specs exist, so the
sprint shows wherever the record does. Everything the line summarises is computed
authoritatively by `sprint.py status` — the hook only echoes the record.

**Never throws.** The PowerShell twin wraps the whole block in `try/catch` and reads with
`-ErrorAction SilentlyContinue`; the bash twin uses `grep -a` and never exits non-zero on a
bad file. That matters because registration runs `pwsh … || bash …`: a thrown error in the
first twin would fall through to the second and double-print the whole banner. A malformed
sprint file therefore produces no line, no warning and no error.

### Retired: the section-plan handoff summary

Earlier revisions of the Build Loop hook parsed `.sdlc/artifacts/build/session-handoff.json`
and printed a `[SHEPHERD] Session Handoff: 3/8 sections complete …` summary (plus `Context`,
`Next action` and `active blocker(s)` lines). That block has been **removed from both twins**.
The SECTION model it summarised was retired from the Build loop when specs became the Build
unit (`track_specs.py` derives backlog progress from spec frontmatter); left in place, the
old summary would have sat next to `[SHEPHERD-SPRINT]` as a competing progress model. A legacy
`session-handoff.json` may still exist in older projects — the hook ignores it. The bash
twin no longer needs `jq` or Python; both twins are plain regex/grep tooling end to end.

---

## 3. Hook Registration in hooks/hooks.json

Registration lives in `hooks/hooks.json` (NOT in `plugin.json` — Claude Code discovers this
file by convention):

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "pwsh -NoProfile -ExecutionPolicy Bypass -File \"${CLAUDE_PLUGIN_ROOT}/hooks/shepherd-session-start.ps1\" || bash \"${CLAUDE_PLUGIN_ROOT}/hooks/shepherd-session-start.sh\"",
            "timeout": 10000
          }
        ]
      }
    ]
  }
}
```

**Path resolution:** `${CLAUDE_PLUGIN_ROOT}` is the environment variable Claude Code sets
to the plugin's install directory.

**Runtime requirements:** PowerShell 7 (`pwsh`) *or* bash — the single-string command runs
through a shell, so if `pwsh` is missing the `||` fallback runs the bash twin. A host with
neither (rare) gets a hook error that Claude Code logs and continues past.

**Exit codes:**

- `0` — Normal operation. Stdout (if any) is injected into Claude's context.
- Non-zero — Hook failure. Claude Code may log a warning but continues operation. The
  hook prefers silent exit 0 when there is nothing to report.

---

## 4. Hook Design Principles

### Read-Only

The hook MUST NOT modify `.sdlc/state.yaml`, artifact files, or any project files. It is
an observer, not an actor. State transitions happen exclusively through the `/sprd-next`
and `/sprd-gate` commands via the Python scripts.

### Lightweight

The hook must execute in sub-second time. It uses regex-based YAML extraction instead of a
full YAML parser to minimize overhead. Heavy operations (network calls, large file scans)
are prohibited.

### Graceful Degradation

If `.sdlc/state.yaml` does not exist, the hook exits 0 silently. If a sprint record under
`.sdlc/sprints/` is malformed, both twins skip it silently — no line, no warning, no thrown
error (a thrown error would make the `pwsh … || bash …` registration double-print). No hook
failure should block the user's workflow.

### Context Injection Model

Hook output goes into Claude's system context, not into the conversation. This means:

- The user does not see hook output directly in their chat.
- Claude sees it as background instructions, similar to `CLAUDE.md` content.
- Output should be terse and actionable — every line costs context window tokens.

### Idempotent

Running the hook multiple times with the same state produces the same output. There are no
side effects, no counters incremented, no files touched.

---

## 5. Cross-References

- **[Architecture](architecture.md)** — How the hook fits into the plugin anatomy alongside commands, agents, and scripts.
- **[Profiles](profiles.md)** — The profile the session banner reports.
- **[Gate System](gate-system.md)** — The gate checks that control phase transitions (the hook reports state, gates enforce it).
- **[Commands](commands.md)** — The slash commands (`/sprd`, `/sprd-gate`, `/sprd-next`) referenced in the session-start banner.
