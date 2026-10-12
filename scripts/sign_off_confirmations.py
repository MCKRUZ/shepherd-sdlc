"""Who confirmed which sign-off question, and when — an append-only ledger.

Every phase's exit gate carries plain-language questions for the person who signs it ("Scope
boundaries are unambiguous"). The plugin's own sign-off records one name for the whole phase.
This is the finer record: each question ticked by a named person at a known time, so "was this
actually looked at" has an answer, and `/sprd-next` can refuse to ask for sign-off while one is
still unconfirmed.

The ledger is its own file, `.sdlc/metrics/confirmation-log.jsonl` — append-only like the
plugin's other ledgers, so two people ticking on two machines never overwrite each other. The
current state of a question is its latest entry. It is deliberately NOT written into
`state.yaml`: `advance_phase.py` owns that file and this adds nothing to it.

A confirmation belongs to the question as it was worded when it was ticked. The registry gives
its questions no ids, so the id is a hash of the phase and the wording; if a question is ever
reworded it gets a new id and its old confirmations stop counting — a tick is never carried onto
a question nobody has read.

Usage:
  sign_off_confirmations.py confirm  --phase 0 --question-id q-... --actor "Name" [--repo P | --state P]
  sign_off_confirmations.py withdraw --phase 0 --question-id q-... --actor "Name" [--repo P | --state P]
  sign_off_confirmations.py status   [--phase 0] [--repo P | --state P] [--json]

`status` is read-only and always exits 0. `confirm` / `withdraw` exit 1 on a refusal (no named
person, a question that is not this phase's). Nothing here confirms on anyone's behalf: it
records what a named person says.
"""

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import phase_model as pm  # noqa: E402
import yaml  # noqa: E402

LEDGER_NAME = "confirmation-log.jsonl"


def judgement_questions(phase_def: dict) -> list[str]:
    """The exit-gate conditions that are questions for a person rather than file checks — the
    registry deliberately carries both, and these are the ones a person is asked before signing."""
    conditions = ((phase_def.get("exit_gate") or {}).get("conditions")) or []
    out = []
    for c in conditions:
        if isinstance(c, str):
            out.append(c)
        elif isinstance(c, dict) and c.get("check") and not c.get("artifact"):
            out.append(str(c["check"]))
    return out


def question_id(phase_id: str, text: str) -> str:
    """Stable for a question's phase and wording, different the moment either changes."""
    wording = " ".join(text.split())
    digest = hashlib.sha256(f"{phase_id}\n{wording}".encode("utf-8")).hexdigest()
    return "q-" + digest[:10]


def _phase(phase_id) -> tuple[str, dict]:
    normalized = pm.normalize_id(phase_id)
    phase_def = pm.get_phase(normalized) if normalized is not None else None
    if normalized is None or phase_def is None:
        raise ValueError(f"unknown phase {phase_id!r}")
    return normalized, phase_def


def questions(phase_id) -> list[tuple[str, str]]:
    """(id, text) for each of the phase's questions, in the order the registry lists them."""
    normalized, phase_def = _phase(phase_id)
    return [(question_id(normalized, t), t) for t in judgement_questions(phase_def)]


def _ledger(repo_root: Path) -> Path:
    return Path(repo_root) / ".sdlc" / "metrics" / LEDGER_NAME


def _load(repo_root: Path) -> list[dict]:
    path = _ledger(repo_root)
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # a torn line never takes the record down
    return entries


def _append(repo_root: Path, phase_id, qid: str, actor: str, action: str) -> None:
    normalized, _ = _phase(phase_id)
    text = dict(questions(normalized)).get(qid)
    if text is None:
        raise ValueError(f"{qid!r} is not a question of phase {normalized}")
    if not (actor or "").strip():
        raise ValueError("a confirmation needs a named person")
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "phase": normalized,
        "question_id": qid,
        "question": text,
        "action": action,
        "actor": actor.strip(),
    }
    path = _ledger(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def confirm(repo_root: Path, phase_id, qid: str, actor: str) -> None:
    _append(repo_root, phase_id, qid, actor, "confirm")


def withdraw(repo_root: Path, phase_id, qid: str, actor: str) -> None:
    _append(repo_root, phase_id, qid, actor, "withdraw")


def current_confirmations(repo_root: Path, phase_id) -> dict[str, dict]:
    """{question id: {actor, ts}} for the questions of this phase, as they are worded now, whose
    latest entry is a confirmation."""
    normalized, _ = _phase(phase_id)
    live = {qid for qid, _ in questions(normalized)}
    latest: dict[str, dict] = {}
    for e in _load(repo_root):
        if e.get("phase") == normalized and e.get("question_id") in live:
            latest[e["question_id"]] = e
    return {
        qid: {"actor": e.get("actor", ""), "ts": e.get("ts", "")}
        for qid, e in latest.items()
        if e.get("action") == "confirm"
    }


def all_confirmed(repo_root: Path, phase_id) -> bool:
    return len(current_confirmations(repo_root, phase_id)) == len(questions(phase_id))


def status(repo_root: Path, phase_id) -> dict:
    normalized, phase_def = _phase(phase_id)
    got = current_confirmations(repo_root, normalized)
    items = [{"id": qid, "text": text, "confirmation": got.get(qid)} for qid, text in questions(normalized)]
    return {
        "phase": normalized,
        "display": phase_def.get("display"),
        "total": len(items),
        "confirmed": len(got),
        "all_confirmed": len(got) == len(items),
        "items": items,
    }


def format_status(result: dict) -> str:
    lines = [f"Sign-off questions — {result['display']}", "=" * 50, ""]
    for item in result["items"]:
        c = item["confirmation"]
        box = "[x]" if c else "[ ]"
        lines.append(f"  {box} {item['text']}")
        lines.append(f"      id: {item['id']}" + (f"   confirmed by {c['actor']} at {c['ts']}" if c else ""))
    lines += ["", f"{result['confirmed']} of {result['total']} confirmed."]
    return "\n".join(lines)


def _resolve(args) -> Path:
    if getattr(args, "state", None):
        state_path = Path(args.state)
        if not state_path.exists():
            print(f"Error: State file not found: {state_path}")
            sys.exit(1)
        return state_path.resolve().parent.parent
    return Path(args.repo).resolve()


def _phase_arg(args, repo_root: Path):
    if args.phase is not None:
        return args.phase
    try:
        state = yaml.safe_load((repo_root / ".sdlc" / "state.yaml").read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        state = {}
    return state.get("current_phase", 0)


def cmd_write(args) -> int:
    repo_root = _resolve(args)
    try:
        (confirm if args.command == "confirm" else withdraw)(repo_root, _phase_arg(args, repo_root), args.question_id, args.actor)
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1
    print(f"Recorded: {args.command} {args.question_id} by {args.actor.strip()}.")
    return 0


def cmd_status(args) -> int:
    repo_root = _resolve(args)
    try:
        result = status(repo_root, _phase_arg(args, repo_root))
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}) if args.json else f"Error: {exc}")
        return 0  # advisory — an unknown phase is a report, not a crash
    print(json.dumps(result, indent=2) if args.json else format_status(result))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Record and report who confirmed each sign-off question")
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    src = common.add_mutually_exclusive_group()
    src.add_argument("--state", help="Path to .sdlc/state.yaml (workflow mode)")
    src.add_argument("--repo", default=".", help="Target repo root (standalone mode; default: cwd)")
    common.add_argument("--phase", help="Phase id (default: the project's current phase)")

    for name, help_text in (("confirm", "Confirm one question"), ("withdraw", "Withdraw a confirmation")):
        p = sub.add_parser(name, parents=[common], help=help_text)
        p.add_argument("--question-id", required=True, help="The id `status` prints beside the question")
        p.add_argument("--actor", required=True, help="The named person confirming — never the agent")

    p_status = sub.add_parser("status", parents=[common], help="Which questions are confirmed, and by whom")
    p_status.add_argument("--json", action="store_true")

    args = parser.parse_args()
    return cmd_status(args) if args.command == "status" else cmd_write(args)


if __name__ == "__main__":
    sys.exit(main())
