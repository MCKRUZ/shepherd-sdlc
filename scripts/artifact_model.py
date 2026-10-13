"""artifact_model.py — Single source of truth for the artifact change-ledger entry shape and the
staleness disposition state machine (with honest counting).

The artifact-update-audit layer records every change to a pre-Build artifact (a requirement, an
epic, a design doc) as an append-only ledger entry, and — when an *upstream* artifact changes after
a *downstream* one last did — surfaces the downstream as *potentially stale*. This module owns two
things and does NO I/O (pure functions, so it is trivially testable and safe to import anywhere):

  1. The ledger entry vocabulary. Two entry kinds share one JSONL, told apart by `event`:
       - a CHANGE entry (event ∈ {created, revised, refreshed, snapshot}) records that an artifact's
         content changed: {artifact, target, phase, hash, prev_hash, actor, reason, decision_ref}.
       - a DISPOSITION entry (event == "disposition") records a human's judgement about one staleness
         candidate: {downstream, upstream, upstream_hash, disposition, owner, reason, actor}.

  2. The staleness disposition state machine — the review-closure discipline made mechanical so a
     stale candidate can't be waved away by relabelling it (mirrors findings_model.py's anti-
     relabelling rule):

       - OPEN         — untouched. Counts as debt.
       - REFRESHED    — the downstream was updated *after* the upstream changed. Does NOT count. This
                        is DERIVED from the ledger (a later change hash), never a word someone types,
                        so it is trustworthy by construction.
       - ACKNOWLEDGED — a human accepts the debt for now. Off the books ONLY with an `owner`;
                        otherwise it counts exactly like OPEN.
       - NOT_AFFECTED — a human judges the change doesn't ripple to this downstream. Off the books
                        ONLY with a `reason`; otherwise it counts.

This layer is advisory: nothing here gates. It only lets a human see, and honestly count, what a
change put at risk. Timestamps are always supplied by the caller (never minted here) so the model
stays pure and deterministic under test.
"""

# --- Ledger event vocabulary ------------------------------------------------------------------

# A change entry records that an artifact's *content* moved.
#   created   — first time this artifact is seen by the ledger (baseline / new file)
#   revised   — an explicit, human-driven change (the /sprd-revise write)
#   refreshed — a downstream updated in response to an upstream change (closes a staleness item)
#   snapshot  — drift picked up by a hash-scan (a direct edit the ledger had not yet seen)
CHANGE_EVENTS = ("created", "revised", "refreshed", "snapshot")
DISPOSITION_EVENT = "disposition"
EVENTS = CHANGE_EVENTS + (DISPOSITION_EVENT,)

DISPOSITIONS = {
    "OPEN": "untouched — counts as debt",
    "REFRESHED": "downstream updated after the upstream change — DERIVED from the ledger only",
    "ACKNOWLEDGED": "human accepts the debt — off the books only with an owner",
    "NOT_AFFECTED": "human judges no ripple — off the books only with a reason",
}

# The dispositions a human may RECORD. REFRESHED is deliberately excluded: it is derived from the
# ledger (a downstream that changed after its upstream simply stops being a stale candidate — see
# the timestamp filter in audit_artifacts.compute_staleness), never a word someone types. A typed
# REFRESHED is exactly the relabelling this state machine exists to reject.
SETTABLE_DISPOSITIONS = ("OPEN", "ACKNOWLEDGED", "NOT_AFFECTED")

# Fields a disposition must carry to be "off the books". OPEN can never be off the books; a recorded
# REFRESHED is not trusted (see validate_disposition).
_REQUIRED_FIELDS = {
    "ACKNOWLEDGED": ("owner",),
    "NOT_AFFECTED": ("reason",),
}


# --- Normalization ----------------------------------------------------------------------------

def normalize_event(event) -> str | None:
    """Canonical lower-case event, or None if not one of EVENTS."""
    if event is None:
        return None
    e = str(event).strip().lower()
    return e if e in EVENTS else None


def normalize_disposition(disp) -> str | None:
    """Canonical upper-case disposition, or None if not one of DISPOSITIONS."""
    if disp is None:
        return None
    s = str(disp).strip().upper()
    return s if s in DISPOSITIONS else None


def is_change_entry(entry) -> bool:
    return isinstance(entry, dict) and normalize_event(entry.get("event")) in CHANGE_EVENTS


def is_disposition_entry(entry) -> bool:
    return isinstance(entry, dict) and normalize_event(entry.get("event")) == DISPOSITION_EVENT


# --- Identity ---------------------------------------------------------------------------------

def staleness_key(downstream: str, upstream: str, upstream_hash: str = "") -> str:
    """Stable identity for one staleness candidate: a downstream artifact vs. a specific upstream
    *change* (pinned by the upstream's content hash so a later upstream change re-opens the item
    rather than silently inheriting the old disposition)."""
    down = str(downstream or "").strip()
    up = str(upstream or "").strip()
    h = str(upstream_hash or "").strip()
    return f"{down}<-{up}@{h}" if h else f"{down}<-{up}"


# --- Honest counting --------------------------------------------------------------------------

def validate_disposition(item: dict) -> tuple[bool, str]:
    """Is this staleness item 'off the books' (does not count toward debt), and why / why not.

    A mislabeled disposition — ACKNOWLEDGED without an owner, NOT_AFFECTED without a reason — is NOT
    off the books; it counts exactly like OPEN. You cannot clear debt by typing a word.
    """
    disp = normalize_disposition(item.get("disposition"))
    if disp is None:
        return False, f"unknown disposition {item.get('disposition')!r}"
    if disp == "OPEN":
        return False, "open"
    if disp == "REFRESHED":
        # REFRESHED is DERIVED, not recordable. A genuinely refreshed downstream never reaches here
        # (it is filtered out of the stale set by its later change timestamp). So a stale item that
        # carries REFRESHED was hand-typed — we do not take the word for it; it still counts as debt.
        return False, "REFRESHED is derived from the ledger, not a recordable disposition — still counts"
    missing = [f for f in _REQUIRED_FIELDS.get(disp, ()) if not str(item.get(f, "")).strip()]
    if missing:
        return False, f"{disp} missing required field(s): {', '.join(missing)}"
    return True, disp.lower()


def counts_as_debt(item: dict) -> bool:
    """A staleness item is open debt unless it is legitimately off the books."""
    off_books, _ = validate_disposition(item)
    return not off_books


def open_debt(items: list[dict]) -> list[dict]:
    """The subset of staleness items that still count as debt."""
    return [i for i in items if counts_as_debt(i)]


# --- Entry builders (the canonical ledger shape) ----------------------------------------------

def change_entry(
    *,
    ts: str,
    artifact: str,
    event: str = "revised",
    target: str = "",
    phase: str = "",
    hash: str | None = None,
    prev_hash: str | None = None,
    actor: str = "",
    reason: str = "",
    decision_ref: str = "",
) -> dict:
    """Build a CHANGE ledger entry. `event` is normalized (falls back to 'revised' if unknown)."""
    entry = {
        "ts": ts,
        "event": normalize_event(event) or "revised",
        "artifact": artifact,
        "target": target,
        "phase": str(phase) if phase != "" and phase is not None else "",
        "hash": hash,
        "prev_hash": prev_hash,
        "actor": actor,
        "reason": reason,
    }
    if decision_ref:
        entry["decision_ref"] = decision_ref
    return entry


def disposition_entry(
    *,
    ts: str,
    downstream: str,
    upstream: str,
    disposition: str,
    upstream_hash: str = "",
    owner: str = "",
    reason: str = "",
    actor: str = "",
) -> dict:
    """Build a DISPOSITION ledger entry for one staleness candidate."""
    return {
        "ts": ts,
        "event": DISPOSITION_EVENT,
        "downstream": downstream,
        "upstream": upstream,
        "upstream_hash": upstream_hash,
        "disposition": normalize_disposition(disposition) or str(disposition or "").strip().upper(),
        "owner": owner,
        "reason": reason,
        "actor": actor,
        "key": staleness_key(downstream, upstream, upstream_hash),
    }


# --- Ledger projections (still pure — operate on an in-memory list) ----------------------------

def latest_change_per_artifact(ledger: list[dict]) -> dict[str, dict]:
    """Latest CHANGE entry per artifact path — the artifact's current state. The ledger is
    append-only in time order, so the last write wins."""
    latest: dict[str, dict] = {}
    for e in ledger:
        if is_change_entry(e):
            art = e.get("artifact")
            if art:
                latest[art] = e
    return latest


def latest_dispositions(ledger: list[dict]) -> dict[str, dict]:
    """Latest DISPOSITION entry per staleness key."""
    latest: dict[str, dict] = {}
    for e in ledger:
        if is_disposition_entry(e):
            key = e.get("key") or staleness_key(
                e.get("downstream", ""), e.get("upstream", ""), e.get("upstream_hash", "")
            )
            latest[key] = e
    return latest


def changes_for(ledger: list[dict], artifact: str) -> list[dict]:
    """Every CHANGE entry for one artifact, in ledger (time) order — its history trail."""
    return [e for e in ledger if is_change_entry(e) and e.get("artifact") == artifact]
