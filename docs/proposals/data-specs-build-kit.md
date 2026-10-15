# Data specs — the build kit (for Claude Sonnet subagents)

Companion to `docs/proposals/data-specs.md` (the design, written by DS-P6). This is the *executable* half: pinned interfaces, package cards with exhaustive file ownership, test-first acceptance, mechanical gates, and a guardrail table for a weaker model — the same shape as `docs/proposals/ado-boards-mirror-build-kit.md`. Where this kit and the design disagree, **the kit wins for the build**.

**Baseline:** `origin/master` at `c53c232` (Shepherd 2.0.0, 2026-10-15). Branch `spec/0039-data-specs`. Spec id 0039 is hand-assigned: 0034–0038 exist only on the `ado-boards-mirror` branch, which is itself the cross-branch collision this feature fixes (D6).

**Status:** Built, 2026-10-15: every package DS-P0 through DS-P7 has landed on `spec/0039-data-specs`; nothing is pushed and no pull request is open. Gates run at DS-P7 against `c53c232`: G1 protected files present, exit 0; G2 protected files byte-identical, exit 0; G3 exactly one existing test edited, `scripts/tests/test_activities_model.py` (the sanctioned carve-out in §10); G5 goldens, 65 passed; G6 registries agree, 428 passed; G7 `--help` leaves an empty directory empty; G8 and G9 both `0`; G10 spec 0039 reads `READY — this spec clears the Definition of Ready.`; G11 `0` hits in the five new or edited documents (`CHANGELOG.md` holds 45 `/sdlc-` hits, the same 45 as at `c53c232`, all in the 2.0.0 entry and earlier ones, none in the new `## Unreleased` section). The full suite (`uv run --project scripts python -m pytest scripts/tests/ -q`) reports 4029 passed, 19 skipped. The §7 smoke run is not part of DS-P7 and is not recorded here. Counts are measured when a package lands, never estimated.

## Context
A teammate's two pastes describe one feature: a **data spec** — a spec the data team owns, linked to the build spec it serves, worked through `/sprd-data`, done when real data reaches what the build spec calls. The drafts still say `/sdlc-data` and version 1.7.0; the plugin is now Shepherd 2.0.0 with `/sprd-*` commands.

**Executive table**

| # | Piece | In one sentence | Build now? |
|---|---|---|---|
| 1 | Data spec + link | A "data homework" card stapled to the build card it serves | Yes |
| 2 | Context section | The card lists every rule, decision and document it must respect | Yes |
| 3 | New docs (dictionary, decision memo, handoff) | What each field means, why we chose X, how to use it | Yes |
| 4 | `--live` mode | The data agent may look at the real database, read-only | **Design only** (gives an agent a shell — a security decision) |
| 5 | Platform packs (Databricks) | A cheat-sheet per data platform | **Design only** |
| 6 | Branch-safe ids | Two branches can't both name a decision "DL-07" (or a spec "0034") | Yes |
| 7 | "Done = data really flows" | The card isn't done until the pipe returns real rows | Yes — pre-seeded acceptance checks + an advisory `check`, no gate |

## 0. How to run it (the orchestrator's checklist — a stronger model does this part)
1. `git checkout master && git pull --ff-only origin master` (local master is 3 behind: #106 rebrand, #107, #108). `BASE=$(git rev-parse origin/master)`. Branch `spec/0039-data-specs`. The untracked `docs/proposals/studio-upgrade-3*` files carry over and are never committed here.
2. Write `docs/proposals/data-specs-build-kit.md` = §1–§9 of this file (so every subagent can read the kit from the repo), then build **DS-P0** yourself (contracts; sequential).
3. Each later package = one `Agent` call, `model: "sonnet"`, `isolation: "worktree"`, prompt = the §2 house rules + the §3 interface sheet + that one §4 card + "return `{status, files, tests_run[{cmd,passed,failed,skipped}], failures, notes, sha}`; a file not on your card → `status: blocked`". Levels per §5; packages in one level run in parallel; you merge each level into the branch (`git merge --no-ff refs/pkg/<id>`), then run the §6 gates before starting the next level.
4. After DS-P7: all gates green → commit, then stop and ask before any push or PR. The Workflow tool is NOT used unless the user says "use a workflow"; if they do, copy `.claude/workflows/boards-fold-runner.js` to `data-specs-runner.js`, swap its Boards critic list for §8, pass `fold: "DS"`, `version: "unreleased"`, `present: []`.

## 1. Binding decisions
| # | Decision | Why |
|---|---|---|
| D1 | Marker is **`type: data`** (the existing `type: feature \| bugfix` field) plus a new **`serves: "<parent id>"`** key. No `kind:`. | `kind` already means three other things (`activities.yaml`, `TransitionError.kind`, `generate_sprint_report --kind`). |
| D2 | New **`scripts/data_spec.py`** + pure **`scripts/data_spec_model.py`**. `new_spec.py` is imported (`next_spec_id`, `render_spec`, `slugify`, `SPEC_FILE_RE`), never edited. | `new_spec.py` is pinned byte-for-byte by earlier features; `test_new_spec_spike_json.py:46-50` asserts its JSON is exactly `{path,id,name,risk}`. |
| D3 | Link direction: the **parent's `depends_on` gains the data id**; the data spec's `serves:` points back. Both written by the same call. | `sprint_model.build_order` already orders by `depends_on`, so the data spec is built first with no new logic. |
| D4 | Parent `data_review` → `pending` only from `""`, `n-a` or `returned`. `pending` stays. **`accepted` is kept** and the result carries `data_review_note`. Acceptance is never written by this tool — it stays `sprint.py verdict --lane data --verdict accepted --by <human>`. | A tool must not silently undo a named human's verdict; the existing verb already refuses an AI `--by`. |
| D5 | `track_decisions.py open --all-branches` (edit, additive) reads the log on every **local** ref (`refs/heads`, `refs/remotes`) via `git show`; it never fetches. Help text says "run `git fetch` first". Without the flag: output byte-identical (goldens). | The issue's ask; `track_decisions.py` is not in CLAUDE.md's protected core (spec 0021 added its verbs). |
| D6 | `data_spec.py new --all-branches` applies the same scan to spec ids (`git ls-tree <ref> specs/`). | Spec ids collide too: this very branch takes **0039** because 0034–0038 exist only on `ado-boards-mirror`. |
| D7 | The data-spec template keeps the heading `# Spec NNNN — <title>` and every placeholder literal `spec.md` has, so `new_spec.render_spec` fills it unchanged. | Zero new rendering code. |
| D8 | `## Context` is ONE `section`-anchored shape field; `## Deliverables` is one `table` field. | Same reasoning as `spec.shape.yaml:77-83` (list-marker labels can't be inline fields). |
| D9 | No version bump; `CHANGELOG.md` gets `## Unreleased`. | 2.1.0–2.5.0 are claimed by the unmerged Boards folds; numbering is decided at release. |
| D10 | Rows 4–5 are written up in `docs/proposals/data-specs.md` §Deferred; `agents/data-analyst.md` tools stay `Read, Write, Edit, Grep, Glob`. | Giving the agent Bash against a client data platform is a security decision for the owner, not a package. |
| D11 | Spec 0039's id is **hand-written by DS-P0**, never allocated with `new_spec.py`. Tier **MEDIUM** (no external write, no gated path). | Guardrail 18 of the Boards kit. |

## 2. House rules (every package brief carries these)
1. Dual-mode: every verb takes `--state <state.yaml> | --repo <path>` on a `common` parent parser (copy `track_decisions.py:518-528`), plus `--json`; `--help` touches no filesystem.
2. `--json` prints exactly ONE JSON document and nothing else; refusals go to **stderr**; exit codes unchanged by the flag.
3. Honesty: `has_data: false` / `null` / "not measured" for never-read; an integer `0` only after a read that found none; never velocity/points/hours/LOC.
4. Exit codes: reads **0 always**; writes 0 ok / 1 illegal (missing parent, malformed file, ledger `DRIFT`) / 2 usage or refused (self-reference, parent is data, cycle, conflicting `serves`).
5. Protected core byte-identical to `$BASE` (§6 G2 list). Never edit `new_spec.py`, `check_spec.py`, `sprint.py`, `sprint_model.py`, `spec_transition.py`, `templates/phases/build/spec.md`, `spec.shape.yaml`, `harness/**`, any existing test or fixture.
6. Pure model + thin CLI: `data_spec_model.py` imports no `subprocess`, `argparse` or `branch_scan`; the only new `subprocess` importer is `branch_scan.py` (argv lists, never `shell=True`, never `fetch`).
7. Frontmatter writes are targeted line edits: `depends_on`/`data_review` through `sprint_model.set_frontmatter` (keeps trailing comments, inserts after `status:`); `type`/`serves` through `data_spec_model.set_scalar_line` (same behaviour, pinned by test). Never regenerate a file; CRLF preserved (`newline=""` on read and write).
8. Ledger: `.sdlc/metrics/spec-log.jsonl`, append-only, `"a"` mode, one `json.dumps(e) + "\n"`; written in `--state` mode only; an `OSError` prints `DRIFT: …` and exits 1 (copy `sprint.py` `_append_event`).
9. Tests are new files only; subprocess tests run `[sys.executable, str(SCRIPTS_DIR / script), *args]` with `encoding="utf-8"` (copy `test_new_spec_spike_json.py:29-33`); every git-backed test builds its own repo under `tmp_path` with `git -c user.name=t -c user.email=t@example.com`.
10. Brand: `/sprd-*`, `shepherd:<agent>`, "Shepherd" in prose; `.sdlc/`, `specs/`, `DL-NN`, `SDLC` the noun are kept. Never write `/sdlc-`.
11. A file not named on your card: **stop and return `status: blocked` with `blocked_on`.** Never run `new_spec.py` to allocate an id for this repo's own spec.

## 3. Interface sheet (pinned; packages implement exactly this)

**Existing, reused (do not change):**
- `new_spec.next_spec_id(specs_dir: Path) -> str` (:47), `new_spec.render_spec(template, spec_id, name, risk, source, owner="", team="") -> str` (:69), `new_spec.slugify` (:42), `new_spec.SPEC_FILE_RE` (:27), `new_spec.VALID_RISK`.
- `check_spec.parse_frontmatter(text) -> (dict, body)` (:83), `check_spec.REQUIRED_SECTIONS` (:31), `check_spec.PLACEHOLDER_RE` (:42), `check_spec.check_spec_text(text, roster_path=None) -> list[dict]` (:135).
- `sprint_model.set_frontmatter(text, key, value) -> str` (:448; keys only `sprint,next_owner,eng_review,data_review,depends_on`; refuses `#`, quotes, newlines, placeholders), `sprint_model.parse_depends_on(value) -> list[str]` (:224).
- `check_dependencies.detect_cycles(graph: dict[str, list[str]]) -> list[list[str]]` (:57).
- `track_decisions._highest_used(lines, table, placeholders) -> int` (:336), `_split_lines`, `_find_table`, `_is_placeholder`, `_row_cells`, `LogError`, `parse_decisions(log_path)`.
- `handoff.run_git(args, cwd, env=None, input_text=None) -> str` raising `HandoffError` (:67) — pattern to copy, not import (avoid importing handoff's code-host probes).

**New — `scripts/branch_scan.py`** (thin git I/O; no fetch, ever)
```python
class BranchScanError(Exception): ...
@dataclass
class ScanResult:
    is_git: bool
    refs_scanned: list[str]          # sorted refnames, e.g. "refs/heads/feature", "refs/remotes/origin/master"
    texts: dict[str, str]            # ref -> file text (only refs where the path exists)
    unread: list[dict]               # [{"ref": str, "reason": str}] — a ref that could not be read is named, never dropped
def is_git_repo(repo_root: Path) -> bool                      # `git rev-parse --is-inside-work-tree` == "true"
def list_refs(repo_root: Path) -> list[str]                   # `git for-each-ref --format=%(refname) refs/heads refs/remotes`, minus any ending "/HEAD"
def read_at(repo_root: Path, ref: str, rel_path: str) -> str | None   # `git show <ref>:<rel_path>`; None when git says the path does not exist on that ref; other failures raise BranchScanError
def list_dir_at(repo_root: Path, ref: str, rel_dir: str) -> list[str] | None   # `git ls-tree --name-only <ref> <rel_dir>/` basenames; None when absent
def scan_file(repo_root: Path, rel_path: str) -> ScanResult
def scan_dir(repo_root: Path, rel_dir: str) -> tuple[bool, list[str], dict[str, list[str]], list[dict]]   # (is_git, refs_scanned, ref -> names, unread)
```
`rel_path`/`rel_dir` are forward-slash, repo-relative (git requires it). Not a git repo → `ScanResult(False, [], {}, [])`.

**Edit — `scripts/track_decisions.py`** (additive only; existing lines untouched)
- `open_decision(log_path, decision, owner, opened, other_logs: list[str] = ())` — the new keyword param defaults to empty; for each text in `other_logs` compute `_highest_used` with that text's own table/placeholders (a text where `_find_table` raises `LogError` is skipped by the caller and reported); the id is `max(local, *others) + 1`.
- `open` gains `--all-branches` (store_true). `run_verb`: with the flag, `scan_file(repo_root, <log path relative to repo>)` and pass `list(result.texts.values())`; result gains `"refs_scanned": [...]` and `"unread": [...]` **only when the flag is given**; text output gains one line `  Ids checked on N branch(es)` only with the flag. Not a git repo + flag → proceeds locally, `refs_scanned: []`, text line `  Ids checked on 0 branches (not a git repository)`.

**New — `scripts/data_spec_model.py`** (pure)
```python
DATA_TYPE = "data"; SERVES_KEY = "serves"; CONTEXT_HEADING = "Context"; DELIVERABLES_HEADING = "Deliverables"
LINKED_EVENT = "data_spec_linked"
REF_PATTERNS = {"BR": r"\bBR-\d{2,}\b", "DL": r"\bDL-\d{2,}\b", "ADR": r"\bADR-\d{3,}\b", "DOC": r"\bDOC-\d{3}\b"}
REF_LABELS = {"BR": "Business rules", "DL": "Decisions", "ADR": "Decision records", "DOC": "Intake documents"}
RESOLVE_ROOTS = (".sdlc/artifacts", ".sdlc", "docs", "specs")          # searched in this order, *.md only
REVIEW_TO_PENDING = ("", "n-a", "returned")                           # D4
class DataSpecError(Exception): kind in {"missing_parent","parent_is_data","self_reference","cycle","malformed","bad_value","conflicting_serves","not_data"}
def spec_id_from_name(filename: str) -> str | None                     # SPEC_FILE_RE
def is_data_spec(fm: dict) -> bool                                     # fm.get("type","").strip().lower() == "data"
def set_scalar_line(text, key, value) -> str                           # replace `^key:` line keeping a trailing `# comment`; else insert after `type:` line, else after `status:`, else after opening ---; CRLF kept; refuses newline/`#`/quotes in value (ValueError)
def mark_data(text, parent_id) -> str                                  # type -> `data` (bare), serves -> `"<id>"` (quoted); DataSpecError(conflicting_serves) if serves is set to another id; idempotent
def cited_refs(parent_text) -> dict[str, list[str]]                   # from the parent BODY only (frontmatter excluded), sorted unique per kind, every kind present (possibly [])
def is_definition_line(line, ref) -> bool                              # `^#{1,6} .*\bREF\b` or `^\|\s*REF\s*\|`
def render_context(parent_id, parent_rel_path, parent_checks: list[str], refs, resolved: dict[str, str|None], today: str) -> str   # exact layout below
def replace_section_body(text, heading, body) -> str                   # bytes outside [end of `## heading` line, next `^## ` or EOF) untouched; raises DataSpecError(malformed) if heading absent
def has_section(text, heading) -> bool
def link_parent(parent_text, data_id, parent_id) -> tuple[str, dict]   # D3/D4; returns (new_text, {"depends_on_before","depends_on_after","data_review_before","data_review_after","data_review_note"|None,"changed": bool}); refuses self_reference / parent_is_data
def cycle_after_link(graph: dict[str, list[str]], parent_id, data_id) -> list[list[str]]   # graph = every spec's parse_depends_on; adds parent->data; detect_cycles
def ledger_event(data_id, parent_id, ts) -> dict                       # {"ts","event": LINKED_EVENT,"spec","serves"} — nothing else, no names
def status_row(data_fm, data_status, parent_fm | None) -> dict         # {"id","serves","status","parent_found","parent_depends_on_has_me","parent_data_review","acceptance_due"}; acceptance_due = status=="merged" and parent_data_review != "accepted"
def context_coverage(data_text, parent_text) -> list[str]             # refs the parent cites that the data spec's Context lacks
```
`render_context` layout (exact; `- none` when a list is empty; unresolved → ``- DL-07 — not found in this repository``):
```
**Serves:** spec 0007 — `specs/0007-duplicate-claim-409.md`

**Parent acceptance checks (read-only copy, taken 2026-10-15):**
- [ ] a duplicate submission returns 409 …

**Business rules:**
- BR-03 — `.sdlc/artifacts/01-requirements/business-rules.md`

**Decisions:**
- none

**Decision records:**
- none

**Intake documents:**
- DOC-004 — `.sdlc/context/intake/DOC-004-vendor-api.md`
```

**New — `scripts/data_spec.py`** (CLI; verbs `new target status check`; `VERBS = ("new","target","status","check")`)
| Verb | Args | Does | Exit | `--json` document |
|---|---|---|---|---|
| `new` | `--serves NNNN --name … [--risk MEDIUM] [--source —] [--owner] [--team] [--all-branches]` | id = `next_spec_id(specs/)`, or with the flag `max` over local and every ref's `specs/` names + 1; render `templates/phases/build/data-spec.md` via `new_spec.render_spec`; `set_scalar_line(serves)`; `replace_section_body("Context", render_context(...))` with refs resolved from the parent; `link_parent`; refuse on cycle; ledger in `--state` mode | 0 / 1 / 2 | `{"path","id","name","risk","serves","parent_path","parent":{depends_on_before,depends_on_after,data_review_before,data_review_after,data_review_note},"context_refs":{BR:[],DL:[],ADR:[],DOC:[]},"unresolved_refs":[],"refs_scanned"?:[]}` |
| `target` | `--spec NNNN --serves NNNN` | `mark_data`; add `## Context` (rendered) at the end of the file only if absent; `link_parent`; cycle check; ledger | 0 / 1 / 2 | `{"path","id","serves","changed":{"type":bool,"serves":bool,"context_added":bool},"parent":{…},"context_refs","unresolved_refs"}` |
| `status` | `[--spec NNNN]` | read-only; every `type: data` spec (or the one) | 0 | `{"has_data":bool,"specs":[status_row…]}`; text: one line per spec, `No data specs.` when none |
| `check` | `--spec NNNN` | advisory: `context-coverage` (refs missing from Context), `readiness-gaps-owned` (each `DL-NN` in `.sdlc/artifacts/02-design/data/data-readiness.md`'s Gaps table has an owner in the decision log via `track_decisions.parse_decisions`; `not measured` when the file is absent), `handoff-present` (`data-handoff.md` exists and its `## Smoke tests` holds no `[bracketed]` placeholder) | 0 | `{"spec","findings":[{"name","passed":bool|null,"detail"}]}` |
Parent lookup: the one `specs/NNNN-*.md` matching `^\d{4}-`; two matches → exit 1 naming both. Text output of `new` mirrors `new_spec.py`'s four lines plus `  Serves: spec 0007 (parent depends_on: 0009; data_review: pending)`.

**New templates** (DS-P0 + DS-P3; every one has `<name>.shape.yaml` with `template: <name>`, `version: "1.0"`, a `description:`; and a filled fixture `scripts/tests/fixtures/documents/<name>.md` exercising EVERY declared field — `test_shaped_templates_roundtrip.py` requires it)
- `templates/phases/build/data-spec.md` — frontmatter = `spec.md:1-22` + `serves: "NNNN"           # the build spec this data spec serves (its depends_on names this spec)` inserted after `type:`; `type: data               # a data spec — see references/data-specs.md`. Sections in order: Goal, Why, **Context**, Scope (In/Out), Acceptance Checks (pre-seeded, below), **Deliverables**, Risk Tier, Delegation Plan, Checking Plan, Decision List. Shape = `spec.shape.yaml` + `Context` (section/longtext/required) + `Deliverables` (section/table/required).
  Pre-seeded Acceptance Checks (each passes `check_spec.CONCRETE_RE` and uses no `VAGUE_WORDS`):
  ```
  - [ ] The pipeline runs end to end on the target environment named in `data-handoff.md` and exits 0.
  - [ ] The serving object named in `data-handoff.md` returns >= 1 row for a real record the parent spec's acceptance checks use.
  - [ ] `data-dictionary.md` has a row for every input the parent spec names, with null %, distinct count and min/max from a live profile query cited in that row.
  - [ ] `lineage-audit.md` shows a source -> transform -> serve path for every serving object.
  - [ ] The smoke tests in the integration example pass and their output is linked from `data-handoff.md`.
  - [ ] Every gap in `data-readiness.md` has a `DL-NN` with an owner in `decision-log.md`.
  ```
  Deliverables table columns `Deliverable | Where | Status`, rows: data-contract.md, data-dictionary.md, lineage-audit.md, data-readiness.md, decision-memo.md, transformation code, serving code, integration example + smoke tests, data-handoff.md.
- `templates/phases/02-design/data/data-dictionary.md` — `## Dictionary identity` (inline: Feature / spec [req], Serves, Profiled on, Profile source), `## Inputs` (table [req]: Input | Source object | Derivation | Null % | Distinct | Min–max | Median | Profile query), `## Serving objects` (table: Object | Kind | Grain | Keys | Refresh), `## Notes` (longtext). A cell nobody measured reads `not measured`, never `0`.
- `templates/phases/02-design/data/decision-memo.md` — `## Memo identity` (inline: Feature / spec [req], Owner, Date, Decision-log ref), `## Constraints` (checklist [req]), `## Options` (table [req]: Option | Evidence | Cost | Risk | Reversible?), `## Scorecard` (table), `## Decision` (inline Chosen [req]; labeled_block Why [req]; inline Decided by [req]).
- `templates/phases/02-design/data/data-handoff.md` — `## Handoff identity` (inline: Feature / spec [req], Serves, Owner), `## What is live` (table [req]: Object | Environment | Since | Owner), `## How to call it` (longtext [req]), `## Degraded results` (table [req]: Result | Meaning | What the caller does), `## Smoke tests` (longtext [req]: command + output link), `## What is left` (checklist), `## Owners` (table).
Line endings: match `git ls-files --eol templates/phases/02-design/data/data-contract.md` for the data templates and `templates/phases/build/spec.md` for the data spec.

## 4. Package cards
Conventions: one Sonnet session each (≤ ~600 lines incl. tests); **Owns** is exhaustive; tests first; `(edit)` marks an existing file.

| Pkg | Owns (creates unless `(edit)`) | Imports | Acceptance (exact) |
|---|---|---|---|
| **DS-P0 Contracts** (orchestrator, first) | `docs/proposals/data-specs-build-kit.md`; `specs/0039-data-specs.md`; `templates/phases/build/data-spec.md`; `templates/phases/build/data-spec.shape.yaml`; `scripts/tests/fixtures/documents/data-spec.md`; `scripts/tests/test_data_spec_template.py` | `new_spec.render_spec`, `check_spec.check_spec_text` | `uv run --project scripts pytest scripts/tests/test_data_spec_template.py scripts/tests/test_shapes_cover_templates.py scripts/tests/test_shaped_templates_roundtrip.py -q` green; pins: the template rendered by `render_spec("0002","x","MEDIUM","—")` then `serves` filled and the body filled by the test → `check_spec_text` has **no failing MUST** and **no failing `vague-line`** finding; the unfilled template has every `check_spec.REQUIRED_SECTIONS` heading plus `Context` and `Deliverables`; `## Context` appears before `## Scope`; spec 0039 → `check_spec.py` prints `READY — this spec clears the Definition of Ready.` (owner `@MCKRUZ`, team `core`, `**Ladder depth:** MEDIUM`) |
| **DS-P1 Branch scan + DL ids** | `scripts/branch_scan.py`; `scripts/track_decisions.py` `(edit, additive: new kwarg, new flag, new result keys under the flag only)`; `scripts/tests/test_branch_scan.py`; `scripts/tests/test_track_decisions_all_branches.py` | `subprocess` (branch_scan only) | `uv run --project scripts pytest scripts/tests/test_branch_scan.py scripts/tests/test_track_decisions_all_branches.py scripts/tests/test_track_decisions_verbs.py -q` green; pins: `list_refs` omits `refs/remotes/origin/HEAD`; `read_at` → `None` for an absent path; a monkeypatched `subprocess.run` asserts no argv contains `"fetch"`; non-git dir → `ScanResult(False, [], {}, [])`; temp repo: master log DL-01..03, branch `feature` commits DL-07 → on master `open --all-branches` yields `DL-08`, without the flag `DL-04`; without the flag the `--json` keys are exactly `{"id","opened","due","owner","path"}`; a ref whose log has no table lands in `unread` with a reason and the verb still succeeds; `grep -c '"fetch"' scripts/branch_scan.py` → 0; `git diff $BASE -- scripts/track_decisions.py` shows **added lines only** except the `open_decision` signature line |
| **DS-P2 Model** | `scripts/data_spec_model.py`; `scripts/tests/test_data_spec_model.py` | `check_spec`, `sprint_model`, `check_dependencies`, `new_spec.SPEC_FILE_RE`, `re`, `dataclasses` | `uv run --project scripts pytest scripts/tests/test_data_spec_model.py -q` green; pins: AST of the module imports no `subprocess`/`argparse`/`branch_scan`; `set_scalar_line` keeps a trailing comment, keeps CRLF, inserts `serves` after `type:` when missing, refuses `#`/quotes/newlines; `mark_data` idempotent and `conflicting_serves` on a different id; `cited_refs` ignores frontmatter and sorts; `link_parent` transition table `""→pending`, `n-a→pending`, `returned→pending`, `pending→pending`, `accepted→accepted + data_review_note`; `depends_on` `"0007" + 0009 → "0007,0009"` deduped; `self_reference` and `parent_is_data` raise; `cycle_after_link` finds `0009→0007→0009`; `replace_section_body` leaves every byte outside the span identical (CRLF fixture) and raises when the heading is absent; `render_context` golden string (the §3 layout, `- none` for empties, `not found in this repository` for unresolved) |
| **DS-P3 Three data templates** | `templates/phases/02-design/data/{data-dictionary,decision-memo,data-handoff}.md` + `.shape.yaml`; `scripts/tests/fixtures/documents/{data-dictionary,decision-memo,data-handoff}.md` | — | `uv run --project scripts pytest scripts/tests/test_shapes_cover_templates.py scripts/tests/test_shaped_templates_roundtrip.py -q` green and the run shows the three new ids; `uv run scripts/validate_shape.py <each shape>` exit 0; each template opens with `# <Title>` then `<!-- Phase 2 — Design \| Optional artifact -->` and a `>` purpose line like `data-contract.md:1-8`; `data-dictionary.md` says `not measured` in its guidance, never `0` |
| **DS-P6 Design doc** (parallel with P1–P3) | `docs/proposals/data-specs.md`; `references/data-specs.md` | — | `references/data-specs.md` ≤ 120 lines: the `type: data`/`serves:` contract, the four verbs' table copied from §3, the D4 transition table, the Context layout; `docs/proposals/data-specs.md` has §Problem, §Decisions (D1–D11), §Deferred — `--live` (read-only queries, a cited source per number, human approval for any write, the agent-shell security posture to decide, what `data-dictionary.md` cells read until then) and §Platform packs (`harness/packs/tools/<platform>/pack.yaml` following `harness/packs/tools/gitnexus`, Databricks first, installed by `install_harness._resolve_tools`); both say `/sprd-data`, never `/sdlc-data`; `grep -c '/sdlc-' <both>` → 0 |
| **DS-P4 CLI** (after P0–P2) | `scripts/data_spec.py`; `scripts/tests/test_data_spec_cli.py` | `data_spec_model`, `branch_scan`, `new_spec`, `check_spec`, `track_decisions.parse_decisions`, `sprint_model.parse_depends_on` | `uv run --project scripts pytest scripts/tests/test_data_spec_cli.py scripts/tests/test_new_spec_spike_json.py -q` green; pins: temp repo with parent `0001` (made by `new_spec.py`) → `new --serves 0001 --name "claims profile"` creates `specs/0002-claims-profile.md` with `type: data`, `serves: "0001"`, a filled `## Context`; the parent differs from before in exactly **2 lines** (`depends_on`, `data_review`) and both keep their `# comment`; `--json` doc keys exactly as §3; `target` on a fresh `new_spec.py` spec adds `## Context` once (second run: `context_added: false`, file byte-identical); `new --serves 0002` where 0002 is data → exit 2, nothing written; `target --spec 0001 --serves 0001` → exit 2; a cycle (`0003 depends_on 0001`, then `target --spec 0003 --serves 0001`, which would add the edge 0001 -> 0003) → exit 2 and both files unchanged; missing parent → exit 1; `status --json` on an empty repo → `{"has_data": false, "specs": []}` (no `0` anywhere); `check` exits 0 with `passed: null` + `not measured` when `data-readiness.md` is absent; `--state` mode appends exactly one `data_spec_linked` line to `.sdlc/metrics/spec-log.jsonl`, `--repo` mode appends none; `--help` on each of `VERBS` in an empty temp cwd leaves it empty; with `--all-branches`, a branch holding `specs/0005-x.md` makes the new id `0006` |
| **DS-P5 Command + agent + activities** (after P3, P4) | `commands/sprd-data.md` `(edit)`; `agents/data-analyst.md` `(edit)`; `phases/activities.yaml` `(edit: "2".data.creates += the three new paths; "build" += {id: data-spec, label: "Link a data spec to the build spec it serves", command: sprd-data, kind: run})` | — | `uv run --project scripts pytest scripts/tests/test_command_contracts.py scripts/tests/test_agent_references.py scripts/tests/test_activities_model.py -q` green (plus any `test_activities*.py` present); the command: step 1a "Load the Context bundle" when `--spec` names a `type: data` spec; step 3 lists six artifacts; step 5's fenced block is `uv run scripts/track_decisions.py open --decision "<gap>" --owner "<@handle>" --all-branches --repo <repo>` and a second block `uv run scripts/data_spec.py new --serves <parent id> --name "<name>" --repo <repo>`; Arguments gains `--spec <id>` wording and `--all-branches`; Important gains "The agent has no shell and does not query a platform; live evidence is a deferred design (docs/proposals/data-specs.md)"; the agent: tools list **unchanged**, a "When driven for a data spec" subsection (read `## Context` first; author the three new documents; a number with no cited query reads `not measured`); `grep -c '/sdlc-' commands/sprd-data.md agents/data-analyst.md` → 0 |
| **DS-P7 Integration** (last) | `scripts/capabilities.py` `(edit, +data-spec, data-spec-status, decision-open-all-branches)`; `CHANGELOG.md` `(edit, ## Unreleased)`; `CLAUDE.md` `(edit: one Key Features bullet, Testing lines for data_spec.py new/target/status/check and track_decisions open --all-branches, the Architecture line's command list unchanged)`; `docs/commands.md` `(edit, row 906 text only)`; `docs/proposals/data-specs-build-kit.md` `(edit, Status line)` | — | §6 G1–G10 green; `uv run --project scripts pytest scripts/tests -q` green with the counts reported (passed/failed/skipped) |

Capability entries (exact):
```python
"data-spec": {"script": "data_spec.py", "argv": ["new"], "flags": ["--serves", "--name", "--all-branches", "--json"]},
"data-spec-status": {"script": "data_spec.py", "argv": ["status"], "flags": ["--repo", "--state", "--json"]},
"decision-open-all-branches": {"script": "track_decisions.py", "argv": ["open"], "flags": ["--all-branches"]},
```

## 5. Order (levels; merge + gates between levels)
L0 `[DS-P0]` → L1 `[DS-P1, DS-P2, DS-P3, DS-P6]` → L2 `[DS-P4]` → L3 `[DS-P5]` → L4 `[DS-P7]`.

## 6. Gates (`$BASE` = `git rev-parse origin/master` at run time)
| # | Name | Command (repo root) | Expect |
|---|---|---|---|
| G1 | protected present | `for f in <PROTECTED>; do test -e "$f" \|\| { echo missing $f; exit 1; }; done` | exit 0 |
| G2 | protected byte-identical | `git diff --exit-code "$BASE" -- <PROTECTED>` | exit 0 |
| G3 | no existing test or fixture edited | `git diff --diff-filter=M --name-only "$BASE" -- scripts/tests \| wc -l` | `0` |
| G4 | pytest | `uv run --project scripts python -m pytest scripts/tests/ -q` | exit 0 |
| G5 | goldens | `uv run --project scripts pytest scripts/tests/test_new_spec_spike_json.py scripts/tests/test_track_decisions_verbs.py -q` | exit 0 |
| G6 | registries agree | `uv run --project scripts pytest scripts/tests/test_capabilities.py scripts/tests/test_command_contracts.py scripts/tests/test_agent_references.py scripts/tests/test_shapes_cover_templates.py scripts/tests/test_shaped_templates_roundtrip.py scripts/tests/test_registry_docs_consistency.py -q` | exit 0 |
| G7 | help touches nothing | `d=$(mktemp -d) && cd "$d" && for v in new target status check; do uv run --project "$OLDPWD/scripts" "$OLDPWD/scripts/data_spec.py" $v --help >/dev/null \|\| exit 1; done && uv run --project "$OLDPWD/scripts" "$OLDPWD/scripts/track_decisions.py" open --help >/dev/null && test -z "$(ls -A "$d")"` | exit 0 |
| G8 | subprocess only in branch_scan | `grep -lE '^\s*(import\|from)\s+subprocess\b' scripts/data_spec.py scripts/data_spec_model.py \| wc -l` | `0` |
| G9 | never fetches | `grep -c '"fetch"' scripts/branch_scan.py` | `0` |
| G10 | spec READY | `uv run --project scripts scripts/check_spec.py --spec specs/0039-data-specs.md \| tail -1` | `READY — this spec clears the Definition of Ready.` |
| G11 | no old command name | `git grep -n '/sdlc-' -- commands/sprd-data.md agents/data-analyst.md references/data-specs.md docs/proposals/data-specs.md templates/phases/build/data-spec.md \| wc -l` | `0` |

`<PROTECTED>` = `scripts/new_spec.py scripts/check_spec.py scripts/check_gates.py scripts/advance_phase.py scripts/phase_model.py scripts/sprint.py scripts/sprint_model.py scripts/spec_transition.py scripts/scorecard.py scripts/generate_status.py scripts/handoff.py scripts/spec_status.py scripts/track_specs.py scripts/check_dependencies.py scripts/document_shape.py scripts/data_contract.py phases/phase-registry.yaml templates/state-init.yaml templates/phases/build/spec.md templates/phases/build/spec.shape.yaml agents/section-evaluator.md commands/sprd-coach.md commands/sprd-spec.md harness`.

## 7. Smoke run (after G1–G11)
```
uv run scripts/init_project.py --profile profiles/microsoft-enterprise/profile.yaml --target /tmp/ds
uv run scripts/new_spec.py --repo /tmp/ds --name "duplicate claim 409" --risk HIGH --owner @priya-n
uv run scripts/data_spec.py new --repo /tmp/ds --serves 0001 --name "claims profile" --owner @sam-k --json
uv run scripts/check_spec.py --spec /tmp/ds/specs/0002-claims-profile.md      # NOT READY only for unfilled body prompts, never for frontmatter
uv run scripts/sprint.py status --repo /tmp/ds --json                          # 0001 shows data_review pending; build order puts 0002 first once slated
uv run scripts/data_spec.py status --repo /tmp/ds
uv run scripts/track_decisions.py open --repo /tmp/ds --decision "Fail open or closed?" --owner "@priya-n" --all-branches --json
```

## 8. Guardrails for a weaker model
| # | Likely mistake | Mechanical catch |
|---|---|---|
| 1 | "Just add `--kind` to `new_spec.py`" | G2; `test_new_spec_spike_json.py:46-50` exact-dict assertion; the card does not own the file |
| 2 | Writes `depends_on` with a hand-rolled regex | the 2-line-diff pin in DS-P4; comment-kept pin; only `sprint_model.set_frontmatter` is allowed for those keys |
| 3 | Flips `accepted` → `pending` | the D4 transition-table test |
| 4 | `git fetch` inside `branch_scan` | G9 + the monkeypatched `subprocess.run` test |
| 5 | Changes `track_decisions` output without the flag | G5 goldens; the exact-keys JSON pin |
| 6 | Uses `kind: data` | `is_data_spec` reads `type`; G11-style grep `kind: data` in the template → the template test |
| 7 | Edits `spec.md` to add Context | G2 (`templates/phases/build/spec.md` is protected here) |
| 8 | Renders a `0` for "no data specs" | `status --json` pin `{"has_data": false, "specs": []}` |
| 9 | Seeds a vague acceptance check ("data is clean") | the DS-P0 `vague-line` pin |
| 10 | Forgets the round-trip fixture for a new shape | `test_shaped_templates_roundtrip.py` fails by name |
| 11 | Puts `--all-branches` in the command doc before the flag exists | `test_command_contracts.py` (G6) — DS-P5 is ordered after DS-P1/P4 |
| 12 | Allocates spec 0039 with `new_spec.py` on a branch | D11; P0 writes it by hand |
| 13 | Gives the data agent Bash "for --live" | the agent's tools list is pinned in DS-P5's card; D10 |
| 14 | Writes a person's name into the ledger line | `ledger_event` returns four keys only (model test) |
| 15 | Regenerates a spec file from YAML and loses its comments | comment-kept pins in P2 and P4; CRLF fixture |

## 9. Human steps (no agent performs these)
1. Confirm D1 (`type: data`) and D4 (accepted is kept) — the two choices a user already made in this session; the rest are mine.
2. Review and sign `specs/0039-data-specs.md` (tier MEDIUM).
3. Decide, later, the `--live` security posture (docs/proposals/data-specs.md §Deferred) before any agent gets a shell against a data platform.
4. Push and open the PR against `master` — only after an explicit go-ahead.

## Verification (what "done" looks like)
G1–G11 green; the §7 smoke run behaves as annotated; `git diff --stat $BASE` shows only the files named on the cards; nothing committed or pushed without the user's say-so.

## 10. What the build changed in this kit (recorded as packages landed)
| Pkg | Deviation from the sheet | Why it was accepted |
|---|---|---|
| DS-P1 | `refs_scanned` means "refs read successfully"; a ref that raised, or whose log has no usable table, appears only in `unread`. `read_at` uses `git show <ref>:./<path>` (relative to `repo_root`, so a project inside a larger repo works) and `_run_git` sets `LC_ALL=C` and `GIT_NO_LAZY_FETCH=1`. `import branch_scan` inside `track_decisions.py` is lazy, so `sprint_model`/`sprint.py`/`confirmation_hints` do not pull `subprocess` into their import graph. In text mode, unread refs produce one stderr `Warning:` line. | "Ids checked on N branches" must never count a branch nobody could use; a partial clone must not fetch because a text edit asked for it. |
| DS-P2 | `set_scalar_line` permits exactly one matching quote pair wrapping the whole value (so `serves: "0007"` can be written); any stray quote, `#`, newline or carriage return is refused. `link_parent` restores the CR that `sprint_model.set_frontmatter` drops on a CRLF line. `mark_data` treats a placeholder `serves` (`NNNN`, `TODO`, empty) as unset. `status_row` with no parent reports `acceptance_due: false`. Ids must be 4+ digits (`bad_value`). | The caller decides quoting; the protected writer is not edited, so the CRLF repair lives in the model. |
| DS-P4 | Every error goes to stderr in text mode too. A missing `--state` file is exit 2 on every verb. The cycle refusal fires only for a cycle that passes through both the parent and the data spec (a pre-existing cycle elsewhere does not block every link). `--all-branches` adds a sixth text line `  Ids checked on N branch(es)`. `target` prints `Spec updated|unchanged: <path>`. `handoff-present` also fails on a missing or empty `## Smoke tests`; HTML comments are ignored by both checks. `resolve_ref(repo_root, ref, skip=None)`. The new spec is written LF; parent and target keep their own line endings. | One JSON document on stdout; a tool that refused every link because of an unrelated cycle would be unusable. |
| DS-P6 | The design's open questions include: whether an `accepted` verdict recorded before any data spec existed is still true; whether a data spec may serve more than one parent; where the spec lives when the data code is in a separate repository. | Real questions the kit does not answer; left for the owner. |
| DS-P5 | The build phase's exact-list pin `test_activities_model.py::test_the_build_phase_declares_the_sprint_layer` gained `data-spec` after `sprint` — the ONE sanctioned edit to an existing test in this kit, made by the orchestrator, not the package (the pin exists to notice exactly this kind of deliberate addition). G3 carves out that single path. The agent's Workflow step 4 and Standalone step 2 now hand routed gaps to the command layer (`track_decisions.py open --all-branches`) instead of hand-appending `DL-NN` rows, so the agent and the command agree. The memo's identity header has no `Serves` (its template has none). | A declaration pin must move with the declaration; the hand-append path would have reintroduced the id collision the feature fixes. |
