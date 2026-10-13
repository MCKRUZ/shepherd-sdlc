"""generate_sprint_report.py — Render a sprint's planning page (or review page) as self-contained HTML.

The sprint-planning page is the artifact the team runs the sprint-planning meeting from
(proposal "Sprint Team Layer" §4): the commitment (the slate with DoR / Eng / Data verdicts and
next owner), the mix actual vs target and the WIP cap, the advisory build order and the
recommended next spec, the dependency picture, one card per slated spec built from the spec
body, the open decisions on their 2-business-day clock, and what was carried in from the
previous sprint. The review page (written at `sprint.py close`) adds this sprint's kept /
carried / dropped outcomes with their recorded reasons.

Everything on the page is derived: the view comes from `sprint.build_view` (the exact JSON of
`sprint.py status --json`), spec cards from the spec bodies via `check_spec.extract_section`,
and markdown snippets go through `generate_phase_report.md_to_html` so the page shares the phase
reports' visual language. The page is honest by design — every empty section reads "no data",
never a fabricated zero — and the footer restates the standard's guardrail: velocity, story
points, PR count and lines of code are never tracked. No per-person aggregation exists here.

Writes: <repo>/.sdlc/reports/sprint-SNN-planning.html (or -review.html), and — only if
<repo>/.sdlc/reports/index.html already exists — an idempotent block between
`<!-- sprints:start -->` / `<!-- sprints:end -->` listing the sprint pages. Nothing else is written.

Standalone or Workflow (CLAUDE.md design rule):
  - Standalone: --repo <path> --sprint S07            (no state.yaml needed; header notes it)
  - Workflow:   --state .sdlc/state.yaml --sprint S07  (repo root = parent of .sdlc/)
Workflow mode is detected by the presence of state.yaml, never by a bare .sdlc/ directory.

Exit codes: 0 rendered; 1 the sprint does not exist (or the id / kind is invalid).
"""

import argparse
import html
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sprint_model as sm  # noqa: E402
from check_spec import extract_section, list_items, parse_frontmatter  # noqa: E402
from generate_phase_report import md_to_html  # noqa: E402



def resolve_build_view():
    """sprint.build_view, imported lazily.

    sprint.py owns the view and imports this module from inside its ready/plan/close functions;
    resolving the function at call time (not import time) keeps that pairing free of a circular
    import, and lets a test install a fake `sprint` module or monkeypatch this function.
    """
    try:
        import sprint  # noqa: PLC0415 — deliberate lazy import (see docstring)
    except ImportError as exc:  # pragma: no cover — scripts/sprint.py absent
        raise RuntimeError("sprint.build_view is unavailable (scripts/sprint.py not importable)") from exc
    return sprint.build_view


KINDS = ("planning", "review")
NO_DATA = "no data"
GUARDRAIL = "Never tracked: velocity, story points, PR count, lines of code."

SPRINTS_START = "<!-- sprints:start -->"
SPRINTS_END = "<!-- sprints:end -->"

# Section ids in page order (planning). The review page appends "outcomes" after the header.
PLANNING_SECTIONS = (
    ("commitment", "Commitment"),
    ("mix", "Mix and capacity"),
    ("order", "Build order and next up"),
    ("dependencies", "Dependencies"),
    ("cards", "Spec cards"),
    ("decisions", "Open decisions"),
    ("carried", "Carried in"),
)


class SprintNotFound(ValueError):
    """Raised when the requested sprint has no record under <repo>/.sdlc/sprints/."""


# --- Small helpers ------------------------------------------------------------------------------

def _esc(value) -> str:
    """HTML-escape any value; None / '' become an em dash so tables never show a blank cell."""
    s = "" if value is None else str(value)
    return html.escape(s) if s.strip() else "&mdash;"


def _num(value) -> str:
    """Render a count honestly: None reads "no data", never 0."""
    return NO_DATA if value is None else html.escape(str(value))


def _no_data(note: str = "") -> str:
    extra = f" &mdash; {html.escape(note)}" if note else ""
    return f'<p class="no-data">{NO_DATA}{extra}</p>'


def _table(headers: list[str], rows: list[list[str]], cls: str = "") -> str:
    """A table from pre-escaped cell HTML. Empty rows -> the no-data paragraph."""
    if not rows:
        return _no_data()
    cls_attr = f' class="{cls}"' if cls else ""
    head = "".join(f"<th>{html.escape(h)}</th>" for h in headers)
    body = "\n".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table{cls_attr}><thead><tr>{head}</tr></thead><tbody>\n{body}\n</tbody></table>"


def _badge(text, kind: str) -> str:
    return f'<span class="badge badge-{kind}">{_esc(text)}</span>'


def _dor_badge(dor) -> str:
    d = str(dor or "unknown")
    kind = "ok" if d.upper() == "READY" else ("bad" if d.upper() == "NOT READY" else "muted")
    return _badge(d, kind)


def _review_badge(value) -> str:
    v = sm.normalize_review(value)
    if v == "accepted":
        return _badge(v, "ok")
    if v == "returned":
        return _badge(v, "bad")
    if v == "n-a":
        return _badge(v, "muted")
    return _badge(v or "not recorded", "warn")


def _risk_badge(risk) -> str:
    r = str(risk or "?").upper()
    return _badge(r, {"HIGH": "bad", "MEDIUM": "warn", "LOW": "ok"}.get(r, "muted"))


def _section(sid: str, title: str, inner: str, lead: str = "") -> str:
    lead_html = f'<p class="lead">{html.escape(lead)}</p>' if lead else ""
    return (f'<section class="block" id="{sid}">\n<h2>{html.escape(title)}</h2>\n'
            f"{lead_html}\n{inner}\n</section>")


def _md(snippet: str | None) -> str:
    """Markdown -> HTML for a spec-body snippet; comments stripped; empty -> no data."""
    if snippet is None:
        return _no_data("section absent")
    clean = re.sub(r"<!--.*?-->", "", snippet, flags=re.DOTALL).strip()
    if not clean:
        return _no_data()
    return md_to_html(clean)


# --- Repo-side readers (I/O kept here, rendering below is pure over dicts) -----------------------

def sprint_file(repo_root: Path, sprint_id: str) -> Path:
    return repo_root / ".sdlc" / "sprints" / f"{sprint_id}.md"


def default_output(repo_root: Path, sprint_id: str, kind: str) -> Path:
    return repo_root / ".sdlc" / "reports" / f"sprint-{sprint_id}-{kind}.html"


def is_workflow(repo_root: Path) -> bool:
    """Workflow mode iff state.yaml exists — a bare .sdlc/ directory does not count."""
    return (repo_root / ".sdlc" / "state.yaml").is_file()


def project_name(repo_root: Path) -> str:
    """project_name from state.yaml in workflow mode, else the repo directory name."""
    state_path = repo_root / ".sdlc" / "state.yaml"
    if state_path.is_file():
        try:
            state = yaml.safe_load(state_path.read_text(encoding="utf-8")) or {}
            name = state.get("project_name") if isinstance(state, dict) else None
            if name:
                return str(name)
        except (yaml.YAMLError, OSError):
            pass
    return repo_root.name or str(repo_root)


def read_ledger(repo_root: Path) -> list[dict]:
    """Every parseable line of .sdlc/metrics/sprint-log.jsonl (malformed lines skipped)."""
    path = repo_root / ".sdlc" / "metrics" / "sprint-log.jsonl"
    if not path.is_file():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict):
            out.append(entry)
    return out


def read_spec_body(repo_root: Path, row: dict) -> tuple[dict, str] | None:
    """(frontmatter, body) of a slate row's spec file, or None when unreadable."""
    raw = row.get("path")
    if not raw:
        return None
    p = Path(str(raw))
    if not p.is_absolute():
        p = repo_root / p
    if not p.is_file():
        return None
    try:
        return parse_frontmatter(p.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return None


def read_close_section(repo_root: Path, view: dict, sprint_id: str) -> str | None:
    """The `## Close` section body of the sprint record (None if absent)."""
    sprint = view.get("sprint") or {}
    raw = sprint.get("path")
    path = Path(str(raw)) if raw else sprint_file(repo_root, sprint_id)
    if not path.is_absolute():
        path = repo_root / path
    if not path.is_file():
        return None
    _fm, body = parse_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
    return extract_section(body, "Close")


_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")


def cadence_targets(repo_root: Path) -> dict:
    """{'wip_cap': str|None, 'review_wait': str|None} from cadence-plan.md; bracketed template
    values like **[2]** read as unset (None). Advisory text only — nothing is computed from it."""
    out = {"wip_cap": None, "review_wait": None}
    artifacts = repo_root / ".sdlc" / "artifacts"
    if not artifacts.is_dir():
        return out
    for plan in sorted(artifacts.glob("*/cadence-plan.md")):
        for line in plan.read_text(encoding="utf-8", errors="replace").splitlines():
            low = line.lower()
            key = None
            if "wip cap" in low:
                key = "wip_cap"
            elif "review-turnaround" in low or "review turnaround" in low:
                key = "review_wait"  # the per-lane target, not the review-wait tripwire
            if key is None or out[key] is not None:
                continue
            bolds = [b.strip() for b in _BOLD_RE.findall(line)]
            values = [b for b in bolds
                      if not (b.startswith("[") and b.endswith("]"))
                      and b.lower().rstrip(":") not in ("wip cap", "review-turnaround target")]
            if values:
                out[key] = values[-1]
        break  # first cadence plan wins
    return out


# --- Renderers (pure over the view + pre-read snippets) -----------------------------------------

def latest_event_date(ledger: list[dict], event: str, sprint_id: str) -> str | None:
    """ISO date of the latest ledger `event` for this sprint, or None ("no data")."""
    hits = [e for e in ledger if e.get("event") == event and str(e.get("sprint", "")) == sprint_id]
    if not hits:
        return None
    d = sm.ts_to_date(max(hits, key=lambda e: str(e.get("ts", ""))).get("ts"))
    return d.isoformat() if d else None


def _by_when(name, when: str | None, fallback: str) -> str:
    if not name:
        return fallback
    return f"{_esc(name)} on {_esc(when)}" if when else _esc(name)


def render_header(view: dict, sprint_id: str, kind: str, *, name: str, workflow: bool, generated_at: str,
                  ledger: list[dict] | None = None) -> str:
    sprint = view.get("sprint") or {}
    days = sprint.get("days") or {}
    ledger = ledger or []
    mode_note = ("workflow mode" if workflow
                 else "standalone mode — no state.yaml, so the engagement context (phase, profile, gates) is not shown")
    chips = [
        f"<span>Generated: {html.escape(generated_at)}</span>",
        f"<span>Project: {_esc(name)}</span>",
        f"<span>{html.escape(mode_note)}</span>",
    ]
    facts = [
        ("Goal", _esc(sprint.get("goal"))),
        ("Window", f"{_esc(sprint.get('start'))} &rarr; {_esc(sprint.get('end'))}"),
        ("State", _badge(sprint.get("state") or "unknown", "muted")),
        ("Business days", f"total {_num(days.get('total'))} &middot; elapsed {_num(days.get('elapsed'))} &middot; remaining {_num(days.get('remaining'))}"),
        ("Target", _num(sprint.get("target"))),
        ("Board ref", _esc(sprint.get("board_ref")) if sprint.get("board_ref") else "&mdash; (manual mapping only)"),
        ("Readied by", _by_when(sprint.get("readied_by"), latest_event_date(ledger, "ready", sprint_id), "not yet readied")),
    ]
    if kind == "review":
        facts.append(("Closed by", _by_when(sprint.get("closed_by"), latest_event_date(ledger, "closed", sprint_id), "not yet closed")))
    facts_html = "\n".join(f"<div class=\"fact\"><span class=\"k\">{html.escape(k)}</span><span class=\"v\">{v}</span></div>" for k, v in facts)
    title = f"Sprint {html.escape(sprint_id)} &mdash; {'Planning' if kind == 'planning' else 'Review'}"
    banner = "" if view.get("has_data", True) else '<p class="no-data">no data — nothing has been slated into this sprint yet</p>'
    return (f'<header class="page-header">\n<div class="meta">{"".join(chips)}</div>\n'
            f"<h1>{title}</h1>\n<div class=\"facts\">{facts_html}</div>\n{banner}\n</header>")


def render_commitment(view: dict) -> str:
    slate = view.get("slate") or []
    readiness = view.get("readiness") or {}
    rows = []
    for r in sorted(slate, key=lambda x: str(x.get("id", ""))):
        rows.append([
            f"<code>{_esc(r.get('id'))}</code>", _esc(r.get("name")), _risk_badge(r.get("risk")),
            _esc(r.get("type")), _esc(r.get("channel")), _dor_badge(r.get("dor")),
            _review_badge(r.get("eng_review")), _review_badge(r.get("data_review")),
            _esc(r.get("next_owner")) if r.get("next_owner") else "&mdash;",
        ])
    table = _table(["spec", "name", "risk", "type", "channel", "DoR", "eng", "data", "next owner"], rows)
    if not slate:
        return table
    ready_n, total_n = readiness.get("ready"), readiness.get("total")
    summary = f'<p class="lead">{_num(ready_n)} of {_num(total_n)} slated specs ready</p>'
    gaps = readiness.get("gaps") or []
    if gaps:
        items = []
        for g in gaps:
            sub = "".join(f"<li>{_esc(x)}</li>" for x in (g.get("gaps") or []))
            items.append(f"<li><code>{_esc(g.get('spec'))}</code><ul>{sub}</ul></li>")
        gaps_html = f'<h3>Gaps against the ready rule</h3><ul class="gaps">{"".join(items)}</ul>'
    else:
        gaps_html = '<p class="ok-line">Every slated spec clears the ready rule (DoR READY, status ready, Eng accepted, Data accepted or n-a, no dependency gap).</p>'
    pending = view.get("verdicts_pending") or []
    handoffs = view.get("handoffs_open") or []
    pend_rows = [[f"<code>{_esc(p.get('spec'))}</code>", _esc(p.get("lane")), _num(p.get("since_business_days"))] for p in pending]
    hand_rows = [[f"<code>{_esc(h.get('spec'))}</code>", _esc(h.get("to")), _num(h.get("since_business_days"))] for h in handoffs]
    extras = (f"<h3>Verdicts pending</h3>{_table(['spec', 'lane', 'business days waiting'], pend_rows)}"
              f"<h3>Handoffs awaiting acknowledgement</h3>{_table(['spec', 'to', 'business days waiting'], hand_rows)}")
    return summary + table + gaps_html + extras


def render_mix(view: dict, cadence: dict) -> str:
    sprint = view.get("sprint") or {}
    mix = view.get("mix") or {}
    rows = []
    for tier in ("HIGH", "MEDIUM", "LOW"):
        cell = mix.get(tier)
        if cell is None:
            continue
        rows.append([_risk_badge(tier), _num(cell.get("target")) if cell.get("target") is not None else "no target",
                     _num(cell.get("actual"))])
    for tier, cell in mix.items():
        if tier not in ("HIGH", "MEDIUM", "LOW"):
            rows.append([_risk_badge(tier), _num(cell.get("target")) if cell.get("target") is not None else "no target",
                         _num(cell.get("actual"))])
    parts = [f'<p class="lead">Mix string: <code>{_esc(sprint.get("mix"))}</code> &middot; target {_num(sprint.get("target"))} specs (a count, never a size)</p>',
             _table(["tier", "target", "actual"], rows)]
    warnings = view.get("mix_warnings") or []
    if warnings:
        parts.append("<h3>Mix warnings (advisory)</h3><ul class=\"warn-list\">" + "".join(f"<li>{_esc(w)}</li>" for w in warnings) + "</ul>")
    wip = view.get("wip") or {}
    cap = wip.get("cap")
    cap_text = _num(cap) if cap is not None else (f"{_esc(cadence['wip_cap'])} (cadence plan)" if cadence.get("wip_cap") else "no cap set")
    review_text = _esc(cadence["review_wait"]) if cadence.get("review_wait") else "no target set"
    parts.append(_table(["measure", "value"], [
        ["WIP in flight", _num(wip.get("in_flight"))],
        ["WIP cap", cap_text],
        ["Review-turnaround target", review_text],
    ]))
    return "\n".join(parts)


def _slate_index(view: dict) -> dict[str, dict]:
    return {str(r.get("id", "")): r for r in (view.get("slate") or [])}


def _unblocks(view: dict) -> dict[str, list[str]]:
    rows = _slate_index(view)
    out: dict[str, list[str]] = {sid: [] for sid in rows}
    for sid, row in rows.items():
        for dep in sm.parse_depends_on(row.get("depends_on")):
            if dep in out:
                out[dep].append(sid)
    return {k: sorted(v) for k, v in out.items()}


def render_build_order(view: dict) -> str:
    order = view.get("build_order") or []
    rows = _slate_index(view)
    if not order:
        return _no_data("no slated specs to order")
    unblocks = _unblocks(view)
    items = []
    for i, sid in enumerate(order, start=1):
        row = rows.get(sid, {})
        deps = sm.parse_depends_on(row.get("depends_on"))
        dep_text = (" &larr; depends on " + ", ".join(f"<code>{_esc(d)}</code>" for d in deps)) if deps else ""
        unb = unblocks.get(sid) or []
        unb_text = f" &middot; unblocks {len(unb)}" if unb else ""
        items.append(f"<li><span class=\"pos\">{i}</span> <code>{_esc(sid)}</code> {_esc(row.get('name'))} "
                     f"{_risk_badge(row.get('risk'))} {_dor_badge(row.get('dor'))}{dep_text}{unb_text}</li>")
    arrows = " &rarr; ".join(f"<code>{_esc(s)}</code>" for s in order)
    nxt = view.get("next_up")
    if nxt:
        wip = view.get("wip") or {}
        cap_clause = f", and in-flight work ({_num(wip.get('in_flight'))}) is under the WIP cap ({_num(wip.get('cap'))})" if wip.get("cap") is not None else ""
        next_html = (f'<div class="next-up"><h3>Next up: <code>{_esc(nxt)}</code> {_esc(rows.get(nxt, {}).get("name"))}</h3>'
                     f"<p>First in the build order that is DoR READY with <code>status: ready</code> and every dependency merged{cap_clause}. Advisory &mdash; the human picks.</p></div>")
    else:
        next_html = f'<div class="next-up"><h3>Next up</h3>{_no_data("no slated spec is READY with merged dependencies inside the WIP cap")}</div>'
    lead = ('<p class="lead">Dependencies first (topological), then the spec that unblocks the most others, '
            'then HIGH &rarr; MEDIUM &rarr; LOW (the longest checking ladder starts first), then spec id. Advisory, never enforced.</p>')
    return f"{lead}<p class=\"arrows\">{arrows}</p><ol class=\"order\">{''.join(items)}</ol>{next_html}"


def render_dependencies(view: dict) -> str:
    rows = _slate_index(view)
    if not rows:
        return _no_data()
    unblocks = _unblocks(view)
    table_rows = []
    for sid in sorted(rows):
        deps = sm.parse_depends_on(rows[sid].get("depends_on"))
        dep_cells = []
        for d in deps:
            if d in rows:
                dep_cells.append(f"<code>{_esc(d)}</code>")
            else:
                dep_cells.append(f"<code>{_esc(d)}</code> {_badge('outside the slate', 'warn')}")
        table_rows.append([f"<code>{_esc(sid)}</code>",
                           ", ".join(dep_cells) if dep_cells else "&mdash;",
                           ", ".join(f"<code>{_esc(u)}</code>" for u in unblocks.get(sid, [])) or "&mdash;"])
    out = _table(["spec", "depends on", "unblocks"], table_rows)
    gaps = view.get("dependency_gaps") or []
    if gaps:
        out += "<h3>Dependency gaps</h3><ul class=\"warn-list\">" + "".join(f"<li>{_esc(g)}</li>" for g in gaps) + "</ul>"
    else:
        out += '<p class="ok-line">No dependency gaps: no cycle, nothing pointing outside the slate at an unmerged spec.</p>'
    return out


def render_spec_card(row: dict, parsed: tuple[dict, str] | None) -> str:
    sid = str(row.get("id", ""))
    head = (f"<h3><code>{_esc(sid)}</code> {_esc(row.get('name'))} {_risk_badge(row.get('risk'))} "
            f"{_dor_badge(row.get('dor'))}</h3>")
    if parsed is None:
        return f'<article class="card" id="spec-{html.escape(sid)}">{head}{_no_data("spec body not found")}</article>'
    fm, body = parsed
    acc = extract_section(body, "Acceptance Checks")
    acc_count = len(list_items(acc)) if acc is not None else None
    hc = (fm.get("harness_context") or "").strip()
    source = (fm.get("source") or "").strip()
    facts = _table(["field", "value"], [
        ["Acceptance checks", _num(acc_count)],
        ["Harness context", _esc(hc) if hc else NO_DATA],
        ["Source", _esc(source) if source and source != "—" else NO_DATA],
        ["Status", _esc(row.get("status"))],
        ["Eng / Data", f"{_review_badge(row.get('eng_review'))} {_review_badge(row.get('data_review'))}"],
    ])
    blocking = row.get("dor_blocking") or []
    blocking_html = ("<h4>DoR blocking findings</h4><ul class=\"warn-list\">" + "".join(f"<li>{_esc(b)}</li>" for b in blocking) + "</ul>") if blocking else ""
    parts = [
        head, facts,
        "<h4>Goal</h4>", _md(extract_section(body, "Goal")),
        "<h4>Why</h4>", _md(extract_section(body, "Why")),
        "<h4>Risk tier</h4>", _md(extract_section(body, "Risk Tier")),
        "<h4>Decision list</h4>", _md(extract_section(body, "Decision List")),
        blocking_html,
    ]
    return f'<article class="card" id="spec-{html.escape(sid)}">{"".join(parts)}</article>'


def render_spec_cards(view: dict, bodies: dict[str, tuple[dict, str] | None]) -> str:
    slate = sorted(view.get("slate") or [], key=lambda x: str(x.get("id", "")))
    if not slate:
        return _no_data()
    return "\n".join(render_spec_card(r, bodies.get(str(r.get("id", "")))) for r in slate)


def render_decisions(view: dict) -> str:
    decisions = view.get("decisions")
    if decisions is None:
        return _no_data("no decision-log found")
    slate_ids = set(_slate_index(view))
    overdue = decisions.get("overdue") or []
    rows = []
    for d in overdue:
        text = str(d.get("decision", ""))
        touches = [sid for sid in sorted(slate_ids) if sid and sid in text]
        rows.append([f"<code>{_esc(d.get('id'))}</code>", _esc(text), _esc(d.get("owner")), _esc(d.get("due")),
                     ", ".join(f"<code>{_esc(s)}</code>" for s in touches) or "&mdash;"])
    lead = f'<p class="lead">Open: {_num(decisions.get("open"))} &middot; overdue (2-business-day clock): {len(overdue) if overdue else NO_DATA}</p>'
    return lead + _table(["id", "decision", "owner", "due", "touches slated spec"], rows)


def render_carried_in(view: dict) -> str:
    carried = view.get("carried_in") or []
    rows = [[f"<code>{_esc(c.get('spec'))}</code>", _esc(c.get("from_sprint")), _esc(c.get("reason"))] for c in carried]
    return _table(["spec", "from sprint", "reason"], rows)


def render_outcomes(view: dict, sprint_id: str, close_section: str | None, ledger: list[dict]) -> str:
    """Review page: kept / carried / dropped from the ## Close table plus the ledger's reasons."""
    parts = []
    outcome = sm.outcomes(view.get("slate") or [])
    parts.append(f'<p class="lead">Kept (merged): {len(outcome["kept"]) if view.get("slate") else NO_DATA} &middot; '
                 f'open at close: {len(outcome["open"]) if view.get("slate") else NO_DATA}</p>')
    parts.append("<h3>Close table (sprint record)</h3>")
    parts.append(_md(close_section))
    events = [e for e in ledger if e.get("event") in ("carried", "dropped") and str(e.get("sprint", "")) == sprint_id]
    rows = []
    for e in sorted(events, key=lambda x: str(x.get("ts", ""))):
        to = e.get("to_sprint")
        outcome_text = f"carried &rarr; {_esc(to)}" if e.get("event") == "carried" else "dropped"
        rows.append([f"<code>{_esc(e.get('spec'))}</code>", outcome_text, _esc(e.get("by")), _esc(e.get("reason")), _esc(sm.ts_to_date(e.get("ts")))])
    parts.append("<h3>Carried and dropped (ledger)</h3>")
    parts.append(_table(["spec", "outcome", "by", "reason", "date"], rows))
    carries: dict[str, int] = {}
    for e in ledger:
        if e.get("event") == "carried" and e.get("spec"):
            carries[str(e["spec"])] = carries.get(str(e["spec"]), 0) + 1
    recurrence = [[f"<code>{_esc(s)}</code>", str(n)] for s, n in sorted(carries.items()) if n >= 2]
    parts.append("<h3>Carry-over recurrence (per spec, 2+ sprints)</h3>")
    parts.append(_table(["spec", "times carried"], recurrence))
    return "\n".join(parts)


# --- Page assembly ------------------------------------------------------------------------------

STYLE = """
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
/* Shepherd palette — parchment by default, bark when the system prefers dark */
:root {
  --bg: #F5EFE4;
  --surface: #FBF7EF;
  --surface2: #ECE4D4;
  --border: #D8CDB8;
  --accent: #3F6B35;
  --accent2: #5E452A;
  --green: #2F6B3E;
  --yellow: #7A5C00;
  --red: #A23B2A;
  --orange: #9C5418;
  --text: #1C1915;
  --muted: #6B6358;
  --code-bg: #ECE4D4;
  --row-alt: rgba(28,25,21,.03);
  --radius: 8px;
  --font: system-ui, -apple-system, 'Segoe UI', sans-serif;
  --mono: 'JetBrains Mono', 'Fira Code', Consolas, monospace;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #14120F;
    --surface: #1C1915;
    --surface2: #262219;
    --border: #39322A;
    --accent: #9DC58E;
    --accent2: #D9C7A3;
    --green: #7FBF8A;
    --yellow: #E0B84A;
    --red: #E07B6A;
    --orange: #E0945A;
    --text: #EFEAE1;
    --muted: #A89F8F;
    --code-bg: #0F0D0B;
    --row-alt: rgba(239,234,225,.03);
  }
}
html { scroll-behavior: smooth; }
body { background: var(--bg); color: var(--text); font-family: var(--font); font-size: 15px; line-height: 1.65; }
#main { max-width: 1100px; margin: 0 auto; padding: 40px 48px; }
nav.toc { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 28px; }
nav.toc a { color: var(--muted); text-decoration: none; font-size: 13px; padding: 4px 10px; border: 1px solid var(--border); border-radius: 20px; }
nav.toc a:hover { color: var(--text); border-color: var(--accent); }
.page-header { margin-bottom: 36px; padding-bottom: 24px; border-bottom: 1px solid var(--border); }
.page-header .meta { font-size: 12px; color: var(--muted); margin-bottom: 12px; display: flex; gap: 16px; flex-wrap: wrap; }
.page-header h1 { font-size: 28px; font-weight: 800; background: linear-gradient(135deg, var(--accent), var(--accent2)); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; margin-bottom: 14px; }
.facts { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 10px 24px; }
.fact { display: flex; gap: 10px; font-size: 14px; }
.fact .k { color: var(--muted); min-width: 110px; }
.block { margin-bottom: 44px; scroll-margin-top: 20px; }
.block h2 { font-size: 19px; font-weight: 700; margin-bottom: 12px; padding-bottom: 8px; border-bottom: 1px solid var(--border); }
.block h3 { font-size: 15px; margin: 18px 0 8px; }
.block h4 { font-size: 12px; margin: 14px 0 6px; color: var(--muted); text-transform: uppercase; letter-spacing: .06em; }
.lead { color: var(--muted); font-size: 14px; margin-bottom: 12px; }
.no-data { color: var(--muted); font-style: italic; padding: 10px 14px; border: 1px dashed var(--border); border-radius: var(--radius); }
.ok-line { color: var(--green); font-size: 14px; margin-top: 10px; }
table { width: 100%; border-collapse: collapse; margin: 10px 0; font-size: 13.5px; background: var(--surface); }
th { background: var(--surface2); color: var(--accent); font-size: 11px; text-transform: uppercase; letter-spacing: .07em; padding: 10px 14px; text-align: left; border: 1px solid var(--border); }
td { padding: 9px 14px; border: 1px solid var(--border); vertical-align: top; }
tr:nth-child(even) td { background: var(--row-alt); }
code { font-family: var(--mono); font-size: 13px; background: var(--code-bg); padding: 2px 6px; border-radius: 4px; color: var(--accent2); }
pre { background: var(--code-bg); border: 1px solid var(--border); border-radius: var(--radius); padding: 16px 20px; overflow-x: auto; margin: 12px 0; }
ul, ol { margin: 8px 0 8px 24px; }
li { margin: 4px 0; }
.badge { display: inline-block; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .05em; padding: 2px 9px; border-radius: 20px; }
.badge-ok { background: rgba(95,160,110,.15); color: var(--green); }
.badge-bad { background: rgba(200,100,85,.15); color: var(--red); }
.badge-warn { background: rgba(200,160,60,.15); color: var(--yellow); }
.badge-muted { background: rgba(150,140,125,.15); color: var(--muted); }
.warn-list li { color: var(--yellow); }
.gaps > li { margin-bottom: 8px; }
.arrows { font-size: 14px; margin: 8px 0 12px; }
ol.order { list-style: none; margin-left: 0; }
ol.order li { padding: 8px 12px; border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); margin-bottom: 6px; }
ol.order .pos { display: inline-block; min-width: 24px; color: var(--accent); font-weight: 700; }
.next-up { margin-top: 16px; padding: 16px 20px; background: var(--surface2); border: 1px solid var(--border); border-left: 3px solid var(--green); border-radius: var(--radius); }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 20px 24px; margin-bottom: 16px; }
.card h3 { margin-top: 0; }
.card p { margin: 6px 0; }
.report-footer { margin-top: 56px; padding-top: 20px; border-top: 1px solid var(--border); color: var(--muted); font-size: 12px; display: flex; justify-content: space-between; flex-wrap: wrap; gap: 8px; }
.report-footer .guardrail { color: var(--text); font-weight: 600; }
"""


def render_page(view: dict, sprint_id: str, kind: str, *, name: str, workflow: bool, generated_at: str,
                bodies: dict[str, tuple[dict, str] | None], cadence: dict,
                close_section: str | None = None, ledger: list[dict] | None = None) -> str:
    """Assemble the full self-contained HTML page (pure over already-read inputs)."""
    sections: list[tuple[str, str, str]] = []
    if kind == "review":
        sections.append(("outcomes", "Outcomes: kept, carried, dropped",
                         render_outcomes(view, sprint_id, close_section, ledger or [])))
    sections.append(("commitment", "Commitment", render_commitment(view)))
    sections.append(("mix", "Mix and capacity", render_mix(view, cadence)))
    sections.append(("order", "Build order and next up", render_build_order(view)))
    sections.append(("dependencies", "Dependencies", render_dependencies(view)))
    sections.append(("cards", "Spec cards", render_spec_cards(view, bodies)))
    sections.append(("decisions", "Open decisions", render_decisions(view)))
    sections.append(("carried", "Carried in", render_carried_in(view)))

    toc = '<nav class="toc">' + "".join(f'<a href="#{sid}">{html.escape(title)}</a>' for sid, title, _ in sections) + "</nav>"
    body = "\n".join(_section(sid, title, inner) for sid, title, inner in sections)
    title = f"Sprint {html.escape(sprint_id)} — {kind} page"
    footer = (f'<footer class="report-footer"><span class="guardrail">{html.escape(GUARDRAIL)}</span>'
              f"<span>Shepherd — sprint {html.escape(kind)} page — {html.escape(generated_at)}</span></footer>")
    return (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"UTF-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">\n"
        f"<title>{title}</title>\n<style>{STYLE}</style>\n</head>\n<body>\n<main id=\"main\">\n"
        f"{render_header(view, sprint_id, kind, name=name, workflow=workflow, generated_at=generated_at, ledger=ledger)}\n"
        f"{toc}\n{body}\n{footer}\n</main>\n</body>\n</html>\n"
    )


# --- index.html block ---------------------------------------------------------------------------

_SPRINT_PAGE_RE = re.compile(r"^sprint-(S\d{2,})-(planning|review)\.html$")


def sprint_pages(reports_dir: Path) -> list[tuple[str, str, str]]:
    """[(sprint_id, kind, filename)] for every sprint page in the reports dir, sorted."""
    out = []
    if not reports_dir.is_dir():
        return out
    for p in reports_dir.iterdir():
        m = _SPRINT_PAGE_RE.match(p.name)
        if m:
            out.append((m.group(1), m.group(2), p.name))
    return sorted(out, key=lambda t: (t[0], KINDS.index(t[1])))


def sprints_block(pages: list[tuple[str, str, str]]) -> str:
    links = "".join(
        f'<a class="report-link" href="{html.escape(fn)}">Sprint {html.escape(sid)}: {html.escape(kind)}</a>\n    '
        for sid, kind, fn in pages
    ) or f'<p class="history-empty">{NO_DATA}</p>'
    return (f"{SPRINTS_START}\n<div class=\"links-section\">\n  <h2>Sprint pages</h2>\n"
            f"  <div class=\"links-grid\">\n    {links}</div>\n</div>\n{SPRINTS_END}")


def splice_sprints_block(index_html: str, block: str) -> str:
    """Replace an existing sprints block, else insert before </body> (append if there is none)."""
    start = index_html.find(SPRINTS_START)
    end = index_html.find(SPRINTS_END)
    if start != -1 and end != -1 and end >= start:
        return index_html[:start] + block + index_html[end + len(SPRINTS_END):]
    body_close = index_html.rfind("</body>")
    if body_close == -1:
        sep = "" if index_html.endswith("\n") else "\n"
        return index_html + sep + block + "\n"
    return index_html[:body_close] + block + "\n" + index_html[body_close:]


def update_index(reports_dir: Path) -> bool:
    """Idempotently (re)write the sprints block in reports/index.html. False if there is no index."""
    index_path = reports_dir / "index.html"
    if not index_path.is_file():
        return False
    current = index_path.read_text(encoding="utf-8")
    updated = splice_sprints_block(current, sprints_block(sprint_pages(reports_dir)))
    if updated != current:
        index_path.write_text(updated, encoding="utf-8")
    return True


# --- Entry point --------------------------------------------------------------------------------

def generate(repo_root: Path, sprint_id: str, kind: str = "planning", output: Path | None = None,
             today: date | None = None, view: dict | None = None) -> Path:
    """Render the sprint page and return its path. `view` may be injected (tests); else sprint.build_view.

    Raises SprintNotFound when the sprint has no record, ValueError on a bad kind or id.
    """
    repo_root = Path(repo_root).resolve()
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)} (got '{kind}')")
    if not sm.is_valid_sprint_id(sprint_id):
        raise ValueError(f"'{sprint_id}' is not a sprint id (expected S07, S12, ...)")
    if view is None:
        if not sprint_file(repo_root, sprint_id).is_file():
            raise SprintNotFound(f"no sprint record at {sprint_file(repo_root, sprint_id)}")
        view = resolve_build_view()(repo_root, sprint_id, today=today)
    if not view.get("sprint"):
        raise SprintNotFound(f"sprint {sprint_id} does not exist under {repo_root / '.sdlc' / 'sprints'}")

    bodies = {str(r.get("id", "")): read_spec_body(repo_root, r) for r in (view.get("slate") or [])}
    close_section = read_close_section(repo_root, view, sprint_id) if kind == "review" else None
    ledger = read_ledger(repo_root)  # readied/closed dates on both pages; carried/dropped reasons on review
    page = render_page(
        view, sprint_id, kind,
        name=project_name(repo_root), workflow=is_workflow(repo_root),
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        bodies=bodies, cadence=cadence_targets(repo_root),
        close_section=close_section, ledger=ledger,
    )
    out = Path(output) if output else default_output(repo_root, sprint_id, kind)
    if not out.is_absolute():
        out = repo_root / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    update_index(repo_root / ".sdlc" / "reports")
    return out


def rel_output(repo_root: Path, out: Path) -> str:
    """The page's repo-relative POSIX path (".sdlc/reports/sprint-S07-planning.html"); the absolute
    path as a string when --output put it outside the repo."""
    try:
        return Path(out).resolve().relative_to(Path(repo_root).resolve()).as_posix()
    except ValueError:
        return str(out)


def page_result(repo_root: Path, sprint_id: str, kind: str, out: Path) -> dict:
    """The one document `--json` prints on success — the same shape `sprint.py plan --json` prints."""
    return {"ok": True, "sprint": sprint_id, "kind": kind, "output": str(out),
            "rel_output": rel_output(repo_root, out)}


def resolve_repo_root(args) -> Path | None:
    """Workflow: parent of .sdlc/ from --state (None if the state file is missing). Standalone: --repo."""
    if args.state:
        state_path = Path(args.state)
        if not state_path.is_file():
            return None
        return state_path.resolve().parent.parent
    return Path(args.repo).resolve()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render a sprint's planning or review page as self-contained HTML (sprint team layer)")
    src = parser.add_mutually_exclusive_group()
    src.add_argument("--state", help="Path to .sdlc/state.yaml (workflow mode)")
    src.add_argument("--repo", default=".", help="Target repo root (standalone mode; default: cwd)")
    parser.add_argument("--sprint", required=True, help="Sprint id, e.g. S07")
    parser.add_argument("--kind", choices=KINDS, default="planning", help="planning (default) or review page")
    parser.add_argument("--output", type=Path, default=None,
                        help="Output path (default: .sdlc/reports/sprint-SNN-<kind>.html)")
    parser.add_argument("--json", action="store_true",
                        help='Emit {"ok", "sprint", "kind", "output", "rel_output"} (or {"ok": false, "error"}) '
                             "on stdout instead of prose; exit codes are unchanged")
    args = parser.parse_args()

    def fail(message: str) -> int:
        if args.json:
            print(json.dumps({"ok": False, "error": message}, indent=2))
        else:
            print(f"Error: {message}", file=sys.stderr)
        return 1

    repo_root = resolve_repo_root(args)
    if repo_root is None:
        return fail(f"state file not found: {args.state}")
    try:
        out = generate(repo_root, args.sprint, kind=args.kind, output=args.output)
    except (SprintNotFound, ValueError) as exc:
        return fail(str(exc))
    if args.json:
        print(json.dumps(page_result(repo_root, args.sprint, args.kind, out), indent=2))
        return 0
    mode = "workflow" if is_workflow(repo_root) else "standalone"
    print(f"Sprint {args.sprint} {args.kind} page written to: {out} ({mode} mode)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
