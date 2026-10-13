"""findings_model.py — Single source of truth for review-finding severity, disposition, identity.

A review (/sprd-review — the grader) surfaces findings. Per the delivery-standard the grader
*advises, never blocks* (the-rails.md §4): so this module does NOT gate. What it does is give a
finding a stable identity, a disposition with honest counting rules, and one arithmetic for
"how much open HIGH+ debt is on the table" — the number the human Checker weighs at the merge bar.

The disposition state machine is the standard's review-closure discipline made mechanical, so a
finding can't be waved away by relabelling it (build-loop.md §Discern; ported from the reference
harness's review-closure gate):

  - OPEN           — untouched. Counts as debt.
  - FIXED          — verified fixed. Does NOT count. ("Verified" is factual — a claim that a file
                     changed when it didn't is caught by the FIXED-claim check in record_findings.)
  - SPLIT          — deferred to a tracked unit. Off the books only when it names BOTH a task/spec
                     id AND an owner; otherwise it counts.
  - ACCEPTED_RISK  — a human signed off on carrying the risk. Off the books only with all four of
                     approver / date / reason / review_condition, AND a *human* approver — an AI may
                     not absolve its own work ("agent proposes, gate disposes", the-rails.md).
  - POSTPONED      — deferred without a home. STILL COUNTS. Debt is not resolution.

Severity is the review's own scale (CRITICAL/HIGH/MEDIUM/LOW). to_gate_severity() maps it onto the
mechanical MUST/SHOULD/INFO scale so the two vocabularies reconcile; open *debt* is HIGH+.
"""

import re

SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW")

# Review severity -> mechanical gate severity (check_gates.py / check_spec.py vocabulary).
_GATE_SEVERITY = {"CRITICAL": "MUST", "HIGH": "MUST", "MEDIUM": "SHOULD", "LOW": "INFO"}

# Severities that count as "debt" the Checker must weigh (the open-HIGH+ signal).
DEBT_SEVERITIES = ("CRITICAL", "HIGH")

DISPOSITIONS = {
    "OPEN": "untouched — counts as debt",
    "FIXED": "verified fixed — does not count (a bare claim is checked against the file)",
    "SPLIT": "deferred to a tracked unit — off the books only with task/spec id AND owner",
    "ACCEPTED_RISK": "a human signed off — off the books only with approver/date/reason/review_condition",
    "POSTPONED": "deferred without a home — STILL COUNTS (debt, not resolution)",
}

# Fields each disposition must carry to be "off the books".
_REQUIRED_FIELDS = {
    "SPLIT": ("split_to", "owner"),
    "ACCEPTED_RISK": ("approver", "date", "reason", "review_condition"),
}

# Actor tokens that may not sign an ACCEPTED_RISK — an AI may not absolve its own work.
_AI_ACTOR_RE = re.compile(r"\b(ai|agent|claude|gpt|codex|llm|bot|automated|assistant|copilot)\b", re.IGNORECASE)


def normalize_severity(sev) -> str | None:
    """Canonical upper-case severity, or None if not one of SEVERITIES."""
    if sev is None:
        return None
    s = str(sev).strip().upper()
    return s if s in SEVERITIES else None


def normalize_disposition(disp) -> str | None:
    """Canonical upper-case disposition, or None if not one of DISPOSITIONS."""
    if disp is None:
        return None
    s = str(disp).strip().upper()
    return s if s in DISPOSITIONS else None


def to_gate_severity(sev) -> str:
    """Map a review severity onto the mechanical MUST/SHOULD/INFO scale (INFO if unknown)."""
    return _GATE_SEVERITY.get(normalize_severity(sev), "INFO")


def is_ai_actor(name) -> bool:
    """True if a signer name reads as an AI/automation rather than a person."""
    return bool(_AI_ACTOR_RE.search(str(name or "")))


def validate_disposition(finding: dict) -> tuple[bool, str]:
    """Is this finding 'off the books' (does not count toward debt), and why / why not.

    Returns (off_books, reason). A mislabeled disposition — missing its required fields, or an AI
    trying to sign an ACCEPTED_RISK — is NOT off the books; it counts exactly like OPEN. This is the
    anti-relabelling rule: you cannot clear debt by typing a word.
    """
    disp = normalize_disposition(finding.get("disposition"))
    if disp is None:
        return False, f"unknown disposition {finding.get('disposition')!r}"
    if disp == "OPEN":
        return False, "open"
    if disp == "POSTPONED":
        return False, "postponed — debt, not resolution"
    if disp == "FIXED":
        return True, "fixed"
    missing = [f for f in _REQUIRED_FIELDS.get(disp, ()) if not str(finding.get(f, "")).strip()]
    if missing:
        return False, f"{disp} missing required field(s): {', '.join(missing)}"
    if disp == "ACCEPTED_RISK" and is_ai_actor(finding.get("approver", "")):
        return False, "ACCEPTED_RISK approver must be a human, not an AI"
    return True, disp.lower()


def counts_as_debt(finding: dict) -> bool:
    """A finding is open debt if it's HIGH+ severity and not legitimately off the books."""
    if normalize_severity(finding.get("severity")) not in DEBT_SEVERITIES:
        return False
    off_books, _ = validate_disposition(finding)
    return not off_books


def open_debt(findings: list[dict]) -> list[dict]:
    """The subset of findings that count as open HIGH+ debt."""
    return [f for f in findings if counts_as_debt(f)]


def debt_exceeds_bar(findings: list[dict], threshold: int = 2) -> bool:
    """Advisory signal (NOT a hard gate): >= threshold findings are open HIGH+ debt.

    The standard's grader advises; the human Checker owns the merge-bar call. This only surfaces
    the number so that call is informed — nothing here refuses to advance.
    """
    return len(open_debt(findings)) >= threshold


def fingerprint(finding: dict) -> str:
    """A stable identity for a *class* of finding, for recurrence and FIXED-claim pairing.

    category slug (+ ':' + the file portion of the target). Deliberately not a hash of the natural-
    language title — recurrence keys on the low-cardinality category the reviewer assigns plus the
    place, and we accept false negatives over falsely minting a permanent rule (proposal R1).
    """
    cat = re.sub(r"[^a-z0-9]+", "-", str(finding.get("category", "")).strip().lower()).strip("-") or "uncategorized"
    target = str(finding.get("target", "")).strip()
    if target:
        file_part = target.split(":", 1)[0].strip()
        if file_part:
            return f"{cat}:{file_part}"
    return cat
