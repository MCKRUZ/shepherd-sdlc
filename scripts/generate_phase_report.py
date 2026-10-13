"""
generate_phase_report.py — Render SDLC phase artifacts as a self-contained HTML report.

Usage:
    uv run generate_phase_report.py --state .sdlc/state.yaml --phase 0
    uv run generate_phase_report.py --state .sdlc/state.yaml --phase build --output .sdlc/reports/build-report.html
    uv run generate_phase_report.py --state .sdlc/state.yaml --all
"""

import argparse
import html
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
import phase_model as pm


# ── Phase metadata ────────────────────────────────────────────────────────────
#
# Phase identity, ordering, slugs, names, displays, and descriptions are owned by
# phase_model (phases/phase-registry.yaml). This module derives presentation from
# the registry and only hardcodes the artifact label map below (filename -> human
# label) plus the purely presentational colour/icon scheme.

# Human-friendly labels for known artifact filenames. Falls back to a derived
# title for anything not listed.
ARTIFACT_LABELS = {
    "constitution.md": "Project Constitution",
    "problem-statement.md": "Problem Statement",
    "success-criteria.md": "Success Criteria",
    "constraints.md": "Constraints",
    "requirements.md": "Requirements",
    "non-functional-requirements.md": "Non-Functional Requirements",
    "epics.md": "Epics",
    "design-doc.md": "Design Document",
    "api-contracts.md": "API Contracts",
    "adrs/": "Architecture Decision Records",
    "adr-registry.md": "ADR Registry",
    "foundation-report.md": "Foundation Report",
    "risk-tier-map.md": "Risk Tier Map",
    "cadence-plan.md": "Cadence Plan",
    "build-handoff.md": "Build Loop Handoff",
    "README.md": "README",
    "api-docs.md": "API Documentation",
    "RUNBOOK.md": "Runbook",
    "release-notes.md": "Release Notes",
    "deployment-checklist.md": "Deployment Checklist",
    "smoke-test-results.md": "Smoke Test Results",
    "monitoring-config.md": "Monitoring Configuration",
    "alert-definitions.md": "Alert Definitions",
    "incident-response.md": "Incident Response",
    "project-retrospective.md": "Project Retrospective",
    "final-handoff-report.md": "Final Handoff Report",
    "harness-audit.md": "Harness Audit",
    "close-gate-evidence.md": "Close Gate Evidence",
    "access-revocation-checklist.md": "Access Revocation Checklist",
}


def _artifact_label(filename: str) -> str:
    """Human label for an artifact filename, deriving a title when not mapped."""
    if filename in ARTIFACT_LABELS:
        return ARTIFACT_LABELS[filename]
    stem = filename.rstrip("/").rsplit(".", 1)[0]
    return stem.replace("-", " ").replace("_", " ").title()


def phase_artifacts(phase_id) -> list[tuple[str, str]]:
    """(filename, label) pairs for a phase's required artifacts, registry-driven.

    Handoff artifacts and report HTML are exit-gate required entries in the
    registry; the report HTML is excluded since it is this script's own output.
    """
    meta = pm.get_phase(phase_id)
    if meta is None:
        return []
    # The registry declares an entry as a bare filename or as a mapping (`path`, `root`,
    # `required_for`); phase_model reads both. No project type is known here, so a type-specific
    # entry is listed rather than silently dropped — the same fail-closed rule the gates use.
    return [
        (a.name, _artifact_label(a.name))
        for a in pm.required_artifacts(meta)
        if not a.name.endswith("-report.html")
    ]


def phase_exit_criteria(phase_id) -> list[str]:
    """The phase's exit conditions that no machine can settle, registry-driven.

    `exit_gate.conditions[]` carries two shapes, and only the second belongs here:

      - {"artifact": "design-doc.md", "check": "exists_and_complete"}  -> a file check
      - {"check": "Scope boundaries are unambiguous"}                  -> a human's judgement

    `check_gates.py` already surfaces these in the terminal as G7 REVIEW items. This
    report is what the approver actually reads before signing, so it has to carry them
    too — a page that shows only which files exist is the exact failure 1.0.0 set out
    to fix, reproduced one layer up.
    """
    meta = pm.get_phase(phase_id)
    if meta is None:
        return []
    conditions = (meta.get("exit_gate") or {}).get("conditions") or []
    return [
        c["check"]
        for c in conditions
        if isinstance(c, dict) and "artifact" not in c and c.get("check")
    ]


# Presentational scheme keyed by canonical string phase id. Purely cosmetic
# (icon + accent colour); identity/ordering never read from here.
PHASE_PRESENTATION = {
    "0": {"icon": "🔍", "color": "#3F6B35"},
    "1": {"icon": "📋", "color": "#5B7FA6"},
    "2": {"icon": "📐", "color": "#8A6A48"},
    "3": {"icon": "🏗", "color": "#7A8B3C"},
    "build": {"icon": "🔁", "color": "#2F8A86"},
    "7": {"icon": "📚", "color": "#B5651D"},
    "8": {"icon": "🚀", "color": "#B8503C"},
    "9": {"icon": "📊", "color": "#8A6A00"},
    "close": {"icon": "🏁", "color": "#7D5A7A"},
}


def phase_title(phase_id) -> str:
    """Capitalised human name for headings (registry name is lowercase)."""
    name = pm.phase_name(phase_id) or pm.normalize_id(phase_id) or ""
    return name.title()


# ── Markdown → HTML (minimal, safe) ──────────────────────────────────────────

def md_to_html(text: str) -> str:
    """Convert a subset of GitHub-flavored markdown to HTML."""
    lines = text.split("\n")
    output: list[str] = []
    in_code = False
    code_lang = ""
    code_buf: list[str] = []
    in_table = False
    list_stack: list[str] = []  # stack of "ul" or "ol" tags

    def flush_code():
        nonlocal in_code, code_buf, code_lang
        body_raw = "\n".join(code_buf)
        if code_lang == "mermaid":
            output.append(f'<pre class="mermaid">{html.escape(body_raw)}</pre>')
        else:
            lang_class = f' class="language-{html.escape(code_lang)}"' if code_lang else ""
            output.append(f'<pre><code{lang_class}>{html.escape(body_raw)}</code></pre>')
        in_code = False
        code_buf = []
        code_lang = ""

    def flush_list():
        while list_stack:
            tag = list_stack.pop()
            output.append(f"</{tag}>")

    def flush_table():
        nonlocal in_table
        if in_table:
            output.append("</tbody></table>")
            in_table = False

    def inline(s: str) -> str:
        # bold
        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        # italic
        s = re.sub(r"\*(.+?)\*", r"<em>\1</em>", s)
        # inline code
        s = re.sub(r"`([^`]+)`", lambda m: f"<code>{html.escape(m.group(1))}</code>", s)
        # links
        s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', s)
        return s

    for line in lines:
        # Code fence
        if line.startswith("```"):
            if in_code:
                flush_code()
            else:
                flush_list()
                flush_table()
                in_code = True
                code_lang = line[3:].strip()
            continue

        if in_code:
            code_buf.append(line)
            continue

        # Table row
        if re.match(r"^\s*\|", line):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if re.match(r"^[\s|:-]+$", line):
                # separator row — already have thead, skip
                continue
            if not in_table:
                flush_list()
                output.append('<table><thead><tr>')
                output.append("".join(f"<th>{inline(c)}</th>" for c in cells))
                output.append("</tr></thead><tbody>")
                in_table = True
            else:
                output.append("<tr>")
                output.append("".join(f"<td>{inline(c)}</td>" for c in cells))
                output.append("</tr>")
            continue
        else:
            flush_table()

        # Headings
        m = re.match(r"^(#{1,6})\s+(.*)", line)
        if m:
            flush_list()
            level = len(m.group(1))
            output.append(f"<h{level}>{inline(html.escape(m.group(2)))}</h{level}>")
            continue

        # Horizontal rule
        if re.match(r"^[-*_]{3,}\s*$", line):
            flush_list()
            output.append("<hr>")
            continue

        # Bullet list
        m = re.match(r"^(\s*)[-*+]\s+(.*)", line)
        if m:
            flush_table()
            indent = len(m.group(1))
            depth = indent // 2 + 1
            while len(list_stack) > depth:
                output.append(f"</{list_stack.pop()}>")
            if len(list_stack) < depth:
                output.append("<ul>")
                list_stack.append("ul")
            elif list_stack and list_stack[-1] != "ul":
                output.append(f"</{list_stack.pop()}>")
                output.append("<ul>")
                list_stack.append("ul")
            output.append(f"<li>{inline(m.group(2))}</li>")
            continue

        # Numbered list
        m = re.match(r"^(\s*)\d+\.\s+(.*)", line)
        if m:
            flush_table()
            indent = len(m.group(1))
            depth = indent // 2 + 1
            while len(list_stack) > depth:
                output.append(f"</{list_stack.pop()}>")
            if len(list_stack) < depth:
                output.append("<ol>")
                list_stack.append("ol")
            elif list_stack and list_stack[-1] != "ol":
                output.append(f"</{list_stack.pop()}>")
                output.append("<ol>")
                list_stack.append("ol")
            output.append(f"<li>{inline(m.group(2))}</li>")
            continue

        # Blank line
        if line.strip() == "":
            flush_list()
            flush_table()
            output.append("")
            continue

        # Paragraph
        flush_list()
        flush_table()
        output.append(f"<p>{inline(html.escape(line))}</p>")

    if in_code:
        flush_code()
    flush_list()
    flush_table()

    return "\n".join(output)


# ── HTML template ─────────────────────────────────────────────────────────────

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
/* Reset & base */
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
/* Shepherd palette — parchment by default, bark when the system prefers dark */
:root {{
  --bg: #F5EFE4;
  --surface: #FBF7EF;
  --surface2: #ECE4D4;
  --border: #D8CDB8;
  --accent: #3F6B35;
  --accent2: #5E452A;
  --on-accent: #F5EFE4;
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
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --bg: #14120F;
    --surface: #1C1915;
    --surface2: #262219;
    --border: #39322A;
    --accent: #9DC58E;
    --accent2: #D9C7A3;
    --on-accent: #14120F;
    --green: #7FBF8A;
    --yellow: #E0B84A;
    --red: #E07B6A;
    --orange: #E0945A;
    --text: #EFEAE1;
    --muted: #A89F8F;
    --code-bg: #0F0D0B;
    --row-alt: rgba(239,234,225,.03);
  }}
}}
html {{ scroll-behavior: smooth; }}
body {{
  background: var(--bg);
  color: var(--text);
  font-family: var(--font);
  font-size: 15px;
  line-height: 1.65;
  display: flex;
  min-height: 100vh;
}}

/* Sidebar */
#sidebar {{
  position: fixed;
  top: 0; left: 0;
  width: 260px;
  height: 100vh;
  background: var(--surface);
  border-right: 1px solid var(--border);
  overflow-y: auto;
  padding: 24px 0;
  z-index: 100;
}}
.sidebar-header {{
  padding: 0 20px 20px;
  border-bottom: 1px solid var(--border);
  margin-bottom: 16px;
}}
.sidebar-header .phase-badge {{
  display: inline-block;
  background: var(--accent);
  color: var(--on-accent);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: .08em;
  text-transform: uppercase;
  padding: 3px 10px;
  border-radius: 20px;
  margin-bottom: 8px;
}}
.sidebar-header h2 {{
  font-size: 17px;
  font-weight: 700;
  color: var(--text);
}}
.sidebar-header .project-name {{
  font-size: 12px;
  color: var(--muted);
  margin-top: 4px;
}}
.sidebar-nav a {{
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 20px;
  color: var(--muted);
  text-decoration: none;
  font-size: 13.5px;
  transition: all .15s;
  border-left: 3px solid transparent;
}}
.sidebar-nav a:hover, .sidebar-nav a.active {{
  color: var(--text);
  background: var(--surface2);
  border-left-color: var(--accent);
}}
.sidebar-nav .nav-status {{
  width: 8px; height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}}
.nav-status.found {{ background: var(--green); }}
.nav-status.missing {{ background: var(--red); }}

.gate-summary {{
  margin: 16px 20px 0;
  padding: 12px;
  background: var(--surface2);
  border-radius: var(--radius);
  border: 1px solid var(--border);
}}
.gate-summary h4 {{
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: .08em;
  color: var(--muted);
  margin-bottom: 8px;
}}
.gate-item {{
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--muted);
  padding: 3px 0;
}}
.gate-item .gate-icon {{ font-size: 13px; }}
.gate-item.pass {{ color: var(--green); }}
.gate-item.fail {{ color: var(--red); }}
.gate-item.warn {{ color: var(--yellow); }}
.gate-item.warn a {{ color: inherit; text-decoration: none; }}
.gate-item.warn a:hover {{ text-decoration: underline; }}

/* Exit criteria — the questions only a human can close */
.judgement {{
  margin-bottom: 40px;
  padding: 24px 28px;
  background: var(--surface2);
  border: 1px solid var(--border);
  border-left: 3px solid var(--yellow);
  border-radius: var(--radius);
}}
.judgement-header {{
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}}
.judgement-header h2 {{
  font-size: 19px;
  font-weight: 700;
}}
.judgement-count {{
  font-size: 12px;
  color: var(--yellow);
  text-transform: uppercase;
  letter-spacing: .06em;
  white-space: nowrap;
}}
.judgement-lead {{
  color: var(--muted);
  font-size: 14px;
  margin-bottom: 18px;
  max-width: 68ch;
}}
.judgement-list {{
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 12px;
}}
.judgement-list li {{
  display: flex;
  align-items: flex-start;
  gap: 12px;
  font-size: 14px;
  line-height: 1.55;
}}
.judgement-box {{
  flex: none;
  width: 15px; height: 15px;
  margin-top: 3px;
  border: 1.5px solid var(--yellow);
  border-radius: 3px;
}}
.judgement-text {{ max-width: 76ch; }}

/* Main content */
#main {{
  margin-left: 260px;
  flex: 1;
  padding: 40px 48px;
  max-width: 1100px;
}}

/* Page header */
.page-header {{
  margin-bottom: 40px;
  padding-bottom: 24px;
  border-bottom: 1px solid var(--border);
}}
.page-header .meta {{
  font-size: 12px;
  color: var(--muted);
  margin-bottom: 12px;
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
}}
.page-header h1 {{
  font-size: 28px;
  font-weight: 800;
  background: linear-gradient(135deg, var(--accent), var(--accent2));
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  margin-bottom: 8px;
}}
.page-header .subtitle {{
  color: var(--muted);
  font-size: 15px;
}}
.artifact-count {{
  display: flex;
  gap: 20px;
  margin-top: 20px;
}}
.count-chip {{
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--muted);
}}
.count-chip .dot {{
  width: 8px; height: 8px;
  border-radius: 50%;
}}

/* Artifact sections */
.artifact-section {{
  margin-bottom: 56px;
  scroll-margin-top: 20px;
}}
.artifact-header {{
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 20px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--border);
}}
.artifact-icon {{
  width: 36px; height: 36px;
  border-radius: var(--radius);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  flex-shrink: 0;
}}
.artifact-icon.found {{ background: rgba(95,160,110,.12); }}
.artifact-icon.missing {{ background: rgba(200,100,85,.12); }}
.artifact-title h3 {{
  font-size: 18px;
  font-weight: 700;
}}
.artifact-title .filename {{
  font-size: 12px;
  color: var(--muted);
  font-family: var(--mono);
  margin-top: 2px;
}}
.artifact-badge {{
  margin-left: auto;
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .06em;
  padding: 4px 12px;
  border-radius: 20px;
}}
.artifact-badge.found {{ background: rgba(95,160,110,.15); color: var(--green); }}
.artifact-badge.missing {{ background: rgba(200,100,85,.15); color: var(--red); }}

.artifact-body {{
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 28px 32px;
}}
.artifact-body.missing-body {{
  border-style: dashed;
  border-color: var(--red);
  background: rgba(200,100,85,.04);
  text-align: center;
  padding: 40px;
  color: var(--muted);
}}
.artifact-body.missing-body .missing-icon {{
  font-size: 32px;
  margin-bottom: 12px;
}}
.artifact-body.missing-body h4 {{
  color: var(--red);
  margin-bottom: 8px;
}}

/* Markdown content styling */
.artifact-body h1 {{ font-size: 22px; margin: 24px 0 12px; color: var(--accent); }}
.artifact-body h2 {{ font-size: 18px; margin: 20px 0 10px; color: var(--text); border-bottom: 1px solid var(--border); padding-bottom: 6px; }}
.artifact-body h3 {{ font-size: 15px; margin: 16px 0 8px; color: var(--text); }}
.artifact-body h4 {{ font-size: 13px; margin: 12px 0 6px; color: var(--muted); text-transform: uppercase; letter-spacing: .06em; }}
.artifact-body p {{ margin: 10px 0; color: var(--text); }}
.artifact-body ul, .artifact-body ol {{ margin: 8px 0 8px 24px; }}
.artifact-body li {{ margin: 4px 0; }}
.artifact-body strong {{ color: var(--text); font-weight: 700; }}
.artifact-body em {{ color: var(--accent2); font-style: italic; }}
.artifact-body code {{
  font-family: var(--mono);
  font-size: 13px;
  background: var(--code-bg);
  padding: 2px 6px;
  border-radius: 4px;
  color: var(--accent2);
}}
.artifact-body pre {{
  background: var(--code-bg);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 16px 20px;
  overflow-x: auto;
  margin: 12px 0;
}}
.artifact-body pre code {{
  background: none;
  padding: 0;
  font-size: 13px;
  color: var(--text);
}}
.artifact-body table {{
  width: 100%;
  border-collapse: collapse;
  margin: 12px 0;
  font-size: 13.5px;
}}
.artifact-body th {{
  background: var(--surface2);
  color: var(--accent);
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: .07em;
  padding: 10px 14px;
  text-align: left;
  border: 1px solid var(--border);
}}
.artifact-body td {{
  padding: 9px 14px;
  border: 1px solid var(--border);
  color: var(--text);
  vertical-align: top;
}}
.artifact-body tr:nth-child(even) td {{ background: var(--row-alt); }}
.artifact-body hr {{ border: none; border-top: 1px solid var(--border); margin: 20px 0; }}
.artifact-body a {{ color: var(--accent); text-decoration: none; }}
.artifact-body a:hover {{ text-decoration: underline; }}

/* Footer */
.report-footer {{
  margin-top: 60px;
  padding-top: 24px;
  border-top: 1px solid var(--border);
  color: var(--muted);
  font-size: 12px;
  display: flex;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
}}
</style>
</head>
<body>

<nav id="sidebar">
  <div class="sidebar-header">
    <div class="phase-badge">{phase_badge}</div>
    <h2>{phase_name}</h2>
    <div class="project-name">{project_name}</div>
  </div>
  <div class="sidebar-nav">
    {nav_items}
  </div>
  <div class="gate-summary">
    <h4>Exit Gate Status</h4>
    {gate_items}
  </div>
</nav>

<main id="main">
  <div class="page-header">
    <div class="meta">
      <span>🗓 Generated: {generated_at}</span>
      <span>📁 Profile: {profile_id}</span>
      <span>📍 {phase_badge} of {phase_count}</span>
    </div>
    <h1>{phase_heading}</h1>
    <p class="subtitle">{phase_purpose}</p>
    <div class="artifact-count">
      <div class="count-chip">
        <div class="dot" style="background:var(--green)"></div>
        {found_count} artifact{found_plural} present
      </div>
      <div class="count-chip">
        <div class="dot" style="background:var(--red)"></div>
        {missing_count} artifact{missing_plural} missing
      </div>
    </div>
  </div>

  {judgement_section}

  {artifact_sections}

  <div class="report-footer">
    <span>Shepherd — {phase_badge} Report</span>
    <span>{generated_at}</span>
  </div>
</main>

<script>
// Highlight active nav item on scroll
const sections = document.querySelectorAll('.artifact-section');
const navLinks = document.querySelectorAll('.sidebar-nav a');
const observer = new IntersectionObserver(entries => {{
  entries.forEach(e => {{
    if (e.isIntersecting) {{
      navLinks.forEach(l => l.classList.toggle('active', l.getAttribute('href') === '#' + e.target.id));
    }}
  }});
}}, {{ threshold: 0.3 }});
sections.forEach(s => observer.observe(s));
</script>
<script type="module">
import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs';
// Shepherd palette, following the page's own light/dark choice.
const shepherdDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
mermaid.initialize({{ startOnLoad: true, theme: 'base', themeVariables: shepherdDark
  ? {{ darkMode: true, primaryColor: '#9DC58E', primaryTextColor: '#14120F', primaryBorderColor: '#3F6B35', lineColor: '#A89F8F', secondaryColor: '#1C1915', tertiaryColor: '#14120F', textColor: '#EFEAE1' }}
  : {{ darkMode: false, primaryColor: '#3F6B35', primaryTextColor: '#F5EFE4', primaryBorderColor: '#2E5027', lineColor: '#5E452A', secondaryColor: '#ECE4D4', tertiaryColor: '#F5EFE4', textColor: '#1C1915' }} }});
</script>
</body>
</html>
"""

def phase_purpose(phase_id) -> str:
    """Phase purpose/subtitle text, sourced from the registry description."""
    meta = pm.get_phase(phase_id)
    return meta.get("description", "") if meta else ""


ARTIFACT_ICONS = {
    "handoff": "🤝",
    "default": "📄",
    "review": "🔍",
    "security": "🔒",
    "test": "🧪",
    "deploy": "🚀",
    "monitor": "📊",
    "retro": "🔄",
}

def get_icon(filename: str) -> str:
    if "handoff" in filename:
        return ARTIFACT_ICONS["handoff"]
    if "security" in filename:
        return ARTIFACT_ICONS["security"]
    if "review" in filename or "report" in filename:
        return ARTIFACT_ICONS["review"]
    if "test" in filename or "coverage" in filename or "smoke" in filename:
        return ARTIFACT_ICONS["test"]
    if "deploy" in filename or "release" in filename:
        return ARTIFACT_ICONS["deploy"]
    if "monitor" in filename or "alert" in filename or "incident" in filename:
        return ARTIFACT_ICONS["monitor"]
    if "retrospective" in filename:
        return ARTIFACT_ICONS["retro"]
    return ARTIFACT_ICONS["default"]


# ── Core functions ─────────────────────────────────────────────────────────────

def load_state(state_path: Path) -> dict:
    with open(state_path) as f:
        return yaml.safe_load(f)


def find_artifact(project_root: Path, phase_id, filename: str) -> Path | None:
    """Search for an artifact in .sdlc/artifacts/<slug>/ or project root."""
    artifacts_dir = project_root / ".sdlc" / "artifacts"
    slug = pm.artifact_dirname(phase_id)
    candidates = []
    if slug:
        candidates.append(artifacts_dir / slug / filename)
    candidates.extend([
        project_root / filename,
        project_root / "docs" / filename,
    ])
    for p in candidates:
        if p.exists():
            return p
    return None


def build_nav_items(artifacts: list[tuple[str, str]], found_set: set[str]) -> str:
    items = []
    for filename, label in artifacts:
        found = filename in found_set
        status_class = "found" if found else "missing"
        anchor = filename.replace(".", "-").replace("/", "-")
        items.append(
            f'<a href="#{anchor}">'
            f'<span class="nav-status {status_class}"></span>'
            f'{label}</a>'
        )
    return "\n    ".join(items)


def build_gate_items(
    artifacts: list[tuple[str, str]],
    found_set: set[str],
    criteria: list[str] | None = None,
) -> str:
    items = []
    for filename, label in artifacts:
        found = filename in found_set
        cls = "pass" if found else "fail"
        icon = "✓" if found else "✗"
        items.append(
            f'<div class="gate-item {cls}">'
            f'<span class="gate-icon">{icon}</span>'
            f'{label}</div>'
        )
    # The file checks above can all be green while the phase is nowhere near done.
    # Carry the human decisions into the same summary so the sidebar never reads as
    # "everything passed" when four questions are still unanswered.
    if criteria:
        plural = "s" if len(criteria) != 1 else ""
        items.append(
            f'<div class="gate-item warn">'
            f'<span class="gate-icon">?</span>'
            f'<a href="#exit-criteria">{len(criteria)} decision{plural} for a human</a>'
            f'</div>'
        )
    return "\n    ".join(items)


def build_judgement_section(criteria: list[str]) -> str:
    """The exit conditions a human has to answer, rendered for the person signing.

    Deliberately placed above the artifacts: the approver meets the questions before
    the evidence, not after scrolling past ten documents. Rendered unticked because
    nothing in this pipeline can know the answers — only the signer can.
    """
    if not criteria:
        return ""
    rows = "\n    ".join(
        f'<li><span class="judgement-box"></span>'
        f'<span class="judgement-text">{html.escape(c)}</span></li>'
        for c in criteria
    )
    plural = "s" if len(criteria) != 1 else ""
    return f"""\
<section class="judgement" id="exit-criteria">
  <div class="judgement-header">
    <h2>Before you sign</h2>
    <span class="judgement-count">{len(criteria)} judgement call{plural}</span>
  </div>
  <p class="judgement-lead">
    The checks below cannot be automated, and nothing above answers them. The gate
    reports; you decide. Each one needs a person's answer before this phase closes.
  </p>
  <ul class="judgement-list">
    {rows}
  </ul>
</section>"""


def build_artifact_section(
    filename: str,
    label: str,
    content_path: Path | None,
) -> str:
    anchor = filename.replace(".", "-").replace("/", "-")
    icon = get_icon(filename)
    found = content_path is not None
    status_class = "found" if found else "missing"
    badge_label = "Present" if found else "Missing"

    header = f"""\
<div class="artifact-header">
  <div class="artifact-icon {status_class}">{icon}</div>
  <div class="artifact-title">
    <h3>{html.escape(label)}</h3>
    <div class="filename">{html.escape(filename)}</div>
  </div>
  <span class="artifact-badge {status_class}">{badge_label}</span>
</div>"""

    if found:
        if content_path.is_dir():
            children = sorted(content_path.iterdir())
            items_html = "".join(
                f'<li><code>{html.escape(c.name)}</code></li>'
                for c in children if not c.name.startswith(".")
            )
            body_html = f"<p><em>Directory — {len(children)} file(s)</em></p><ul>{items_html}</ul>"
        else:
            raw = content_path.read_text(encoding="utf-8", errors="replace")
            body_html = md_to_html(raw)
        body = f'<div class="artifact-body">{body_html}</div>'
    else:
        body = f"""\
<div class="artifact-body missing-body">
  <div class="missing-icon">📭</div>
  <h4>Artifact Not Found</h4>
  <p><code>{html.escape(filename)}</code> has not been created yet.</p>
  <p>Complete this artifact to satisfy the phase exit gate.</p>
</div>"""

    return f"""\
<div class="artifact-section" id="{anchor}">
  {header}
  {body}
</div>"""


def _phase_badge(phase_id: str) -> str:
    """Short badge label: 'Phase 0' for numeric ids, registry display otherwise."""
    if phase_id.isdigit():
        return f"Phase {phase_id}"
    return pm.phase_display(phase_id) or phase_title(phase_id)


def generate_report(
    state_path: Path,
    phase_id,
    output_path: Path,
) -> dict:
    state = load_state(state_path)
    project_root = state_path.parent.parent

    phase_id = pm.normalize_id(phase_id)
    phase_name = phase_title(phase_id)
    phase_heading = pm.phase_display(phase_id) or f"{_phase_badge(phase_id)}: {phase_name}"
    artifacts = phase_artifacts(phase_id)

    found_set: set[str] = set()
    artifact_paths: dict[str, Path | None] = {}
    for filename, _ in artifacts:
        p = find_artifact(project_root, phase_id, filename)
        artifact_paths[filename] = p
        if p:
            found_set.add(filename)

    found_count = len(found_set)
    missing_count = len(artifacts) - found_count

    exit_criteria = phase_exit_criteria(phase_id)

    nav_items = build_nav_items(artifacts, found_set)
    gate_items = build_gate_items(artifacts, found_set, exit_criteria)
    judgement_section = build_judgement_section(exit_criteria)

    sections: list[str] = []
    for filename, label in artifacts:
        sections.append(
            build_artifact_section(filename, label, artifact_paths[filename])
        )
    artifact_sections = "\n\n".join(sections)

    project_name = state.get("project_name", project_root.name)
    profile_id = state.get("profile_id", "unknown")
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    title = f"{phase_heading} — {project_name}"

    report_html = HTML_TEMPLATE.format(
        title=title,
        phase_badge=html.escape(_phase_badge(phase_id)),
        phase_heading=html.escape(phase_heading),
        phase_count=pm.phase_count(),
        phase_name=html.escape(phase_name),
        project_name=html.escape(project_name),
        profile_id=html.escape(profile_id),
        generated_at=generated_at,
        phase_purpose=html.escape(phase_purpose(phase_id)),
        found_count=found_count,
        missing_count=missing_count,
        found_plural="s" if found_count != 1 else "",
        missing_plural="s" if missing_count != 1 else "",
        nav_items=nav_items,
        gate_items=gate_items,
        judgement_section=judgement_section,
        artifact_sections=artifact_sections,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report_html, encoding="utf-8")

    return {
        "phase": phase_id,
        "phase_name": phase_name,
        "output": str(output_path),
        "found": found_count,
        "missing": missing_count,
        "total": len(artifacts),
        "exit_criteria": len(exit_criteria),
        "artifacts": {
            filename: (artifact_paths[filename] is not None)
            for filename, _ in artifacts
        },
    }


# ── Index generator ───────────────────────────────────────────────────────────

INDEX_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
/* Shepherd palette — parchment by default, bark when the system prefers dark */
:root {{
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
  --row-alt: rgba(28,25,21,.03);
  --radius: 8px;
  --font: system-ui, -apple-system, 'Segoe UI', sans-serif;
  --mono: 'JetBrains Mono', 'Fira Code', Consolas, monospace;
}}
@media (prefers-color-scheme: dark) {{
  :root {{
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
    --row-alt: rgba(239,234,225,.03);
  }}
}}
html {{ scroll-behavior: smooth; }}
body {{
  background: var(--bg);
  color: var(--text);
  font-family: var(--font);
  font-size: 15px;
  line-height: 1.65;
  padding: 40px 48px;
  max-width: 1100px;
  margin: 0 auto;
}}

/* Header */
.page-header {{
  margin-bottom: 40px;
  padding-bottom: 24px;
  border-bottom: 1px solid var(--border);
}}
.page-header .meta {{
  font-size: 12px;
  color: var(--muted);
  margin-bottom: 12px;
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
}}
.page-header h1 {{
  font-size: 28px;
  font-weight: 800;
  background: linear-gradient(135deg, var(--accent), var(--accent2));
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  margin-bottom: 8px;
}}
.page-header .subtitle {{
  color: var(--muted);
  font-size: 15px;
}}

/* Progress bar */
.progress-section {{
  margin-bottom: 40px;
}}
.progress-section h2 {{
  font-size: 13px;
  text-transform: uppercase;
  letter-spacing: .08em;
  color: var(--muted);
  margin-bottom: 12px;
}}
.progress-bar-wrap {{
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 20px;
  height: 18px;
  overflow: hidden;
  margin-bottom: 8px;
}}
.progress-bar-fill {{
  height: 100%;
  border-radius: 20px;
  background: linear-gradient(90deg, var(--accent), var(--accent2));
  transition: width .4s ease;
}}
.progress-label {{
  font-size: 13px;
  color: var(--muted);
}}

/* Phase timeline */
.timeline-section {{
  margin-bottom: 40px;
}}
.timeline-section h2 {{
  font-size: 13px;
  text-transform: uppercase;
  letter-spacing: .08em;
  color: var(--muted);
  margin-bottom: 16px;
}}
.timeline-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 12px;
}}
.phase-card {{
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 16px;
  text-decoration: none;
  color: var(--text);
  display: block;
  transition: border-color .15s, background .15s;
}}
.phase-card:hover {{
  border-color: var(--accent);
  background: var(--surface2);
}}
.phase-card.status-completed {{ border-left: 3px solid var(--green); }}
.phase-card.status-active {{ border-left: 3px solid var(--yellow); }}
.phase-card.status-pending {{ border-left: 3px solid var(--border); opacity: .7; }}
.phase-card-header {{
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}}
.phase-num {{
  font-size: 11px;
  font-weight: 700;
  color: var(--muted);
  font-family: var(--mono);
}}
.phase-status-dot {{
  width: 8px; height: 8px;
  border-radius: 50%;
  margin-left: auto;
}}
.phase-status-dot.completed {{ background: var(--green); }}
.phase-status-dot.active {{ background: var(--yellow); }}
.phase-status-dot.pending {{ background: var(--border); }}
.phase-card-name {{
  font-size: 14px;
  font-weight: 700;
  margin-bottom: 4px;
}}
.phase-card-meta {{
  font-size: 12px;
  color: var(--muted);
  display: flex;
  flex-direction: column;
  gap: 2px;
}}
.phase-artifacts-count {{
  font-size: 12px;
  font-family: var(--mono);
  color: var(--muted);
}}
.phase-artifacts-count.complete {{ color: var(--green); }}
.phase-artifacts-count.partial {{ color: var(--yellow); }}
.phase-artifacts-count.empty {{ color: var(--muted); }}

/* Transition history */
.history-section {{
  margin-bottom: 40px;
}}
.history-section h2 {{
  font-size: 13px;
  text-transform: uppercase;
  letter-spacing: .08em;
  color: var(--muted);
  margin-bottom: 16px;
}}
.history-table {{
  width: 100%;
  border-collapse: collapse;
  font-size: 13.5px;
}}
.history-table th {{
  background: var(--surface2);
  color: var(--accent);
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: .07em;
  padding: 10px 14px;
  text-align: left;
  border: 1px solid var(--border);
}}
.history-table td {{
  padding: 9px 14px;
  border: 1px solid var(--border);
  color: var(--text);
  vertical-align: top;
  font-family: var(--mono);
  font-size: 13px;
}}
.history-table tr:nth-child(even) td {{ background: var(--row-alt); }}
.history-empty {{
  color: var(--muted);
  font-size: 13px;
  padding: 16px 0;
}}

/* Quick links */
.links-section {{
  margin-bottom: 40px;
}}
.links-section h2 {{
  font-size: 13px;
  text-transform: uppercase;
  letter-spacing: .08em;
  color: var(--muted);
  margin-bottom: 16px;
}}
.links-grid {{
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}}
.report-link {{
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 8px 14px;
  font-size: 13px;
  color: var(--accent);
  text-decoration: none;
  font-family: var(--mono);
  transition: border-color .15s, background .15s;
}}
.report-link:hover {{
  border-color: var(--accent);
  background: var(--surface2);
}}

/* Footer */
.report-footer {{
  margin-top: 60px;
  padding-top: 24px;
  border-top: 1px solid var(--border);
  color: var(--muted);
  font-size: 12px;
  display: flex;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
}}
</style>
</head>
<body>

<div class="page-header">
  <div class="meta">
    <span>Generated: {generated_at}</span>
    <span>Profile: {profile_id}</span>
    <span>Current Phase: {current_phase}</span>
  </div>
  <h1>{project_name}</h1>
  <p class="subtitle">SDLC Project Overview — All Phases</p>
</div>

<div class="progress-section">
  <h2>Overall Progress</h2>
  <div class="progress-bar-wrap">
    <div class="progress-bar-fill" style="width:{progress_pct}%"></div>
  </div>
  <div class="progress-label">{completed_count} of {phase_count} phases completed ({progress_pct}%)</div>
</div>

<div class="timeline-section">
  <h2>Phase Timeline</h2>
  <div class="timeline-grid">
    {phase_cards}
  </div>
</div>

<div class="history-section">
  <h2>Transition History</h2>
  {history_content}
</div>

<div class="links-section">
  <h2>Quick Links</h2>
  <div class="links-grid">
    {quick_links}
  </div>
</div>

<div class="report-footer">
  <span>Shepherd — Project Index</span>
  <span>{generated_at}</span>
</div>

<script type="module">
import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs';
// Shepherd palette, following the page's own light/dark choice.
const shepherdDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
mermaid.initialize({{ startOnLoad: true, theme: 'base', themeVariables: shepherdDark
  ? {{ darkMode: true, primaryColor: '#9DC58E', primaryTextColor: '#14120F', primaryBorderColor: '#3F6B35', lineColor: '#A89F8F', secondaryColor: '#1C1915', tertiaryColor: '#14120F', textColor: '#EFEAE1' }}
  : {{ darkMode: false, primaryColor: '#3F6B35', primaryTextColor: '#F5EFE4', primaryBorderColor: '#2E5027', lineColor: '#5E452A', secondaryColor: '#ECE4D4', tertiaryColor: '#F5EFE4', textColor: '#1C1915' }} }});
</script>
</body>
</html>
"""


def _phase_entered_date(history: list[dict], phase_id) -> str | None:
    """Return the ISO timestamp when a phase was entered, or None."""
    pid = pm.normalize_id(phase_id)
    for entry in history:
        to = pm.normalize_id(entry.get("to"))
        ph = pm.normalize_id(entry.get("phase"))
        if to == pid or ph == pid:
            return entry.get("at") or entry.get("timestamp") or entry.get("date")
    return None


def _phase_status(phase_id, current_phase) -> str:
    pid = pm.normalize_id(phase_id)
    cur = pm.normalize_id(current_phase)
    if pid == cur:
        return "active"
    if pm.is_before(pid, cur):
        return "completed"
    return "pending"


def _generate_index(
    state_path: Path,
    phase_results: list[dict],
    output_path: Path,
) -> None:
    """Build and write the project-level index.html."""
    state = load_state(state_path)
    project_name = html.escape(state.get("project_name", state_path.parent.parent.name))
    profile_id = html.escape(state.get("profile_id", "unknown"))
    current_phase = pm.normalize_id(state.get("current_phase", "0"))
    history: list[dict] = state.get("history", [])
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    phase_count = pm.phase_count()

    # Completed count: phases strictly before current_phase with full artifacts
    completed_count = sum(
        1 for r in phase_results
        if _phase_status(r["phase"], current_phase) == "completed"
    )
    progress_pct = round(completed_count / phase_count * 100) if phase_count else 0

    # ── Phase cards ─────────────────────────────────────────────────────────────
    cards: list[str] = []
    for result in phase_results:
        pnum = result["phase"]
        pname = html.escape(result["phase_name"])
        status = _phase_status(pnum, current_phase)
        found = result["found"]
        total = result["total"]

        if found == total:
            art_cls = "complete"
        elif found > 0:
            art_cls = "partial"
        else:
            art_cls = "empty"

        entered_raw = _phase_entered_date(history, pnum)
        entered_str = ""
        if entered_raw:
            entered_str = f'<span>Entered: {html.escape(str(entered_raw))}</span>'

        report_filename = f"{pm.artifact_dirname(pnum)}-report.html"
        card_badge = html.escape(_phase_badge(pnum).upper())

        cards.append(f"""\
<a class="phase-card status-{status}" href="{report_filename}">
  <div class="phase-card-header">
    <span class="phase-num">{card_badge}</span>
    <span class="phase-status-dot {status}"></span>
  </div>
  <div class="phase-card-name">{pname}</div>
  <div class="phase-card-meta">
    <span class="phase-artifacts-count {art_cls}">{found}/{total} artifacts</span>
    {entered_str}
  </div>
</a>""")

    # ── Transition history ───────────────────────────────────────────────────────
    if history:
        rows: list[str] = []
        for entry in history:
            from_phase = entry.get("from", entry.get("from_phase", "—"))
            to_phase = entry.get("to", entry.get("to_phase", "—"))
            at = entry.get("at") or entry.get("timestamp") or entry.get("date") or "—"
            note = html.escape(str(entry.get("note", entry.get("reason", ""))))
            rows.append(
                f"<tr>"
                f"<td>{html.escape(str(from_phase))}</td>"
                f"<td>{html.escape(str(to_phase))}</td>"
                f"<td>{html.escape(str(at))}</td>"
                f"<td>{note}</td>"
                f"</tr>"
            )
        history_content = (
            '<table class="history-table">'
            "<thead><tr>"
            "<th>From</th><th>To</th><th>At</th><th>Note</th>"
            "</tr></thead>"
            "<tbody>" + "\n".join(rows) + "</tbody>"
            "</table>"
        )
    else:
        history_content = '<p class="history-empty">No phase transitions recorded yet.</p>'

    # ── Quick links ──────────────────────────────────────────────────────────────
    links: list[str] = []
    for result in phase_results:
        pnum = result["phase"]
        pname = html.escape(result["phase_name"])
        filename = f"{pm.artifact_dirname(pnum)}-report.html"
        badge = html.escape(_phase_badge(pnum))
        links.append(f'<a class="report-link" href="{filename}">{badge}: {pname}</a>')

    index_html = INDEX_TEMPLATE.format(
        title=f"{project_name} — SDLC Project Index",
        project_name=project_name,
        profile_id=profile_id,
        current_phase=html.escape(_phase_badge(current_phase)),
        generated_at=generated_at,
        completed_count=completed_count,
        phase_count=phase_count,
        progress_pct=progress_pct,
        phase_cards="\n    ".join(cards),
        history_content=history_content,
        quick_links="\n    ".join(links),
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(index_html, encoding="utf-8")


# ── CLI ────────────────────────────────────────────────────────────────────────

def _json_result(result: dict) -> dict:
    """The result as JSON prints it: the output path with forward slashes on every platform."""
    return {**result, "output": Path(result["output"]).as_posix()}


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate SDLC phase HTML report")
    parser.add_argument("--state", required=True, type=Path, help="Path to .sdlc/state.yaml")
    parser.add_argument("--phase", type=str, help="Phase id (e.g. 0, 1, build, 7, close). Defaults to current phase.")
    parser.add_argument("--output", type=Path, help="Output HTML file path.")
    parser.add_argument("--all", action="store_true", dest="all_phases", help="Generate reports for all phases and write an index.html summary.")
    parser.add_argument("--json", action="store_true", help="Print the result as one JSON document instead of text")
    args = parser.parse_args()

    if not args.state.exists():
        print(f"ERROR: state file not found: {args.state}", file=sys.stderr)
        return 1

    state = load_state(args.state)

    if args.all_phases:
        results = []
        for phase in pm.all_phases():
            phase_id = pm.normalize_id(phase["id"])
            default_output = args.state.parent / "reports" / f"{pm.artifact_dirname(phase_id)}-report.html"
            result = generate_report(args.state, phase_id, default_output)
            results.append(result)
            if not args.json:
                status = "[ok]" if result["missing"] == 0 else f"[!!] {result['missing']} missing"
                print(f"  {_phase_badge(phase_id)}: {result['phase_name']} - {status} -> {result['output']}")

        # Generate index.html
        index_path = args.state.parent / "reports" / "index.html"
        _generate_index(args.state, results, index_path)
        if args.json:
            print(json.dumps({"reports": [_json_result(r) for r in results], "index": index_path.as_posix()}, indent=2))
            return 0
        print(f"\n{len(results)} reports generated.")
        print(f"\nProject index written to: {index_path}")
        return 0

    # Single phase
    phase_id = pm.normalize_id(args.phase)
    if phase_id is None:
        phase_id = pm.normalize_id(state.get("current_phase", "0"))

    if pm.get_phase(phase_id) is None:
        valid = ", ".join(pm.all_phase_ids())
        print(f"ERROR: invalid phase id {phase_id!r}. Valid ids: {valid}.", file=sys.stderr)
        return 1

    output_path = args.output or (
        args.state.parent / "reports" / f"{pm.artifact_dirname(phase_id)}-report.html"
    )

    result = generate_report(args.state, phase_id, output_path)

    if args.json:
        print(json.dumps(_json_result(result), indent=2))
        return 0

    print(f"\n{_phase_badge(phase_id)}: {result['phase_name']} Report")
    print("-" * 50)
    for filename, found in result["artifacts"].items():
        icon = "[ok]" if found else "[--]"
        print(f"  {icon} {filename}")
    print(f"\n{result['found']}/{result['total']} artifacts present")
    print(f"\nReport written to: {result['output']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
