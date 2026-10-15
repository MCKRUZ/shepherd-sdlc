"""What this plugin can do, declared so a newer Studio can tell an older plugin from a current one.

Studio is released separately from the plugin, so it will meet plugins that predate the scripts it
wants to call. Without a signal the only way to find out is to run the script and show a project
manager an argument-parsing error. This is that signal: `generate_status.py --json` reports the
names below, and Studio hides a button it cannot honour and says why.

The list is DECLARED, not probed — probing would run `--help` on a dozen scripts every time the
dashboard loads. A static list is only trustworthy if something proves each entry true, and
`scripts/tests/test_capabilities.py` does: for every entry it runs the script's real `--help` (for
the verb it names) and requires every listed flag to be there. A capability whose script is not in
this plugin is omitted, never reported.
"""

from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent

# name -> the script that provides it, the verb (argv before --help) when it has subcommands, and
# the flags that must appear in that --help for the capability to be real.
CAPABILITIES: dict[str, dict] = {
    "activities": {"script": "stage_readiness.py", "flags": ["--json"]},
    "add-row": {"script": "document_shape_cli.py", "argv": ["add-row"],
                "flags": ["--cells", "--table-index", "--id-column", "--replace-placeholders"]},
    "doctor-json": {"script": "doctor.py", "flags": ["--json"]},
    "gate-audit-json": {"script": "audit_gates.py", "flags": ["--json", "--repo"]},
    "upgrade-report-json": {"script": "upgrade_harness.py", "flags": ["--json"]},
    "check-channel-json": {"script": "check_channel.py", "flags": ["--json"]},
    "interaction-spec-check": {"script": "check_channel.py", "flags": ["--interaction-spec"]},
    "bind-channel": {"script": "bind_channel.py", "flags": ["--spec", "--channel"]},
    "decision-open": {"script": "track_decisions.py", "argv": ["open"], "flags": ["--decision", "--owner"]},
    "decision-decide": {"script": "track_decisions.py", "argv": ["decide"], "flags": ["--id", "--resolution"]},
    "intake-modes": {"script": "intake_documents.py",
                     "flags": ["--repo", "--docs", "--json", "--skip", "--priority", "--lock"]},
    "new-spec-json": {"script": "new_spec.py", "flags": ["--json"]},
    "new-spike-json": {"script": "new_spike.py", "flags": ["--json"]},
    "pipeline-proof": {"script": "pipeline_proof.py", "flags": ["--write", "--json", "--host"]},
    "workshop-brief": {"script": "workshop_brief.py", "argv": ["build"],
                       "flags": ["--contradictions", "--questions", "--logistics-json", "--json"]},
    "rules-check": {"script": "rules_check.py", "flags": ["--repo", "--json"]},
    "data-contract-summary": {"script": "data_contract.py", "argv": ["summary"], "flags": ["--repo", "--json"]},
    "narrative-status": {"script": "narrative_status.py", "flags": ["--all-phases", "--json"]},
    "phase-report-json": {"script": "generate_phase_report.py", "flags": ["--json", "--all"]},
    "intake-registry": {"script": "intake_documents.py", "flags": ["--registry", "--json"]},
    "brief-candidates": {"script": "workshop_brief.py", "argv": ["candidates"], "flags": ["--state", "--repo", "--json"]},
    # The sprint team layer, read-only from Studio (proposal: studio-improvements, Batches 1-2).
    "sprint-status": {"script": "sprint.py", "argv": ["status"], "flags": ["--repo", "--state", "--sprint", "--json"]},
    "sprint-plan": {"script": "sprint.py", "argv": ["plan"], "flags": ["--repo", "--state", "--sprint", "--json"]},
    "sprint-report": {"script": "generate_sprint_report.py",
                      "flags": ["--repo", "--state", "--sprint", "--kind", "--json"]},
    # Code-host providers (GitHub or Azure DevOps, chosen by the repository): which host, why,
    # and whether its CLI is usable — the `host` block Studio reads before enabling PR features.
    "code-host": {"script": "code_host.py", "flags": ["--repo", "--state", "--host", "--json"]},
    "import-outcomes": {"script": "import_outcomes.py", "flags": ["--since", "--repo", "--state", "--host", "--json"]},
    # The SDLC Studio command center (docs/proposals/togo-command-center.md §2.6). Each name disables one
    # control on an older plugin, with the reason "arrives with a newer plugin: lacks <name>".
    # `sprint-write` is true of 1.6.x already — it is what lets an older plugin's omnibar verbs be
    # disabled honestly rather than fail on argv.
    "sprint-list": {"script": "sprint.py", "argv": ["list"], "flags": ["--repo", "--state", "--json"]},
    "sprint-log": {"script": "sprint.py", "argv": ["log"], "flags": ["--since", "--sprint", "--json"]},
    "sprint-carry": {"script": "sprint.py", "argv": ["carry"], "flags": ["--spec", "--to", "--reason", "--by"]},
    "sprint-edit": {"script": "sprint.py", "argv": ["edit"], "flags": ["--sprint", "--goal", "--by"]},
    "sprint-write": {"script": "sprint.py", "argv": ["slate"], "flags": ["--spec", "--by", "--override", "--reason"]},
    "confirm-tier": {"script": "spec_transition.py", "argv": ["confirm-tier"], "flags": ["--by"]},
    "assign-roles": {"script": "spec_transition.py", "argv": ["assign"], "flags": ["--developer", "--checker", "--by"]},
    "handoff-check": {"script": "handoff.py", "flags": ["--check", "--json"]},
    "findings-json": {"script": "record_findings.py", "argv": ["report"], "flags": ["--json", "--spec"]},
    # Its presence also means `--spec --json` carries `ladder{}`: both landed in the same change.
    "readiness-all": {"script": "spec_readiness.py", "flags": ["--all", "--json"]},
    # The Azure Boards mirror's setup verbs (docs/proposals/ado-boards-mirror.md). None of them touches a
    # work item: `config` starts and checks `.sdlc/ado.yaml` (`config init` carries `--force`), `discover`
    # reads the project's process into `.sdlc/ado/schema.json`, `validate` says whether the config fits it.
    "ado-config": {"script": "ado_sync.py", "argv": ["config", "init"],
                   "flags": ["--repo", "--state", "--json", "--force"]},
    "ado-discover": {"script": "ado_sync.py", "argv": ["discover"],
                     "flags": ["--repo", "--state", "--json", "--team", "--refresh"]},
    "ado-validate": {"script": "ado_sync.py", "argv": ["validate"], "flags": ["--repo", "--state", "--json"]},
    # Its read-only mirror (Fold B2): nothing here writes to the board. `plan` shows what an apply would send,
    # `status` counts the ledger (writes nothing), `pull` reads the board back (`--discussion` caches the comments
    # locally), `link` pairs a ref with a work item in the ledger by a named human, `show` prints one item and its
    # cached discussion as observed content (`--for-agent` withholds lines that read as instructions).
    "ado-plan": {"script": "ado_sync.py", "argv": ["plan"],
                 "flags": ["--repo", "--state", "--json", "--kind", "--id", "--sprint", "--all", "--validate",
                           "--no-comments"]},
    "ado-status-json": {"script": "ado_sync.py", "argv": ["status"], "flags": ["--repo", "--state", "--json"]},
    "ado-pull": {"script": "ado_sync.py", "argv": ["pull"], "flags": ["--repo", "--state", "--json", "--id", "--all"]},
    "ado-link": {"script": "ado_sync.py", "argv": ["link"],
                 "flags": ["--repo", "--state", "--json", "--work-item", "--by"]},
    "ado-show": {"script": "ado_sync.py", "argv": ["show"],
                 "flags": ["--repo", "--state", "--json", "--fetch", "--versions", "--expand", "--for-agent"]},
    "ado-pull-discussion": {"script": "ado_sync.py", "argv": ["pull"],
                            "flags": ["--repo", "--state", "--json", "--discussion", "--full"]},
    # The catch-up (Fold B6): `sync` runs pull, drift, (the discussion pull, only on `--discussion`) and plan in one
    # read and ends with the same `Next:` line `plan` and `comment` print where an apply is offered. It sends nothing.
    "ado-sync": {"script": "ado_sync.py", "argv": ["sync"],
                 "flags": ["--repo", "--state", "--json", "--kind", "--id", "--sprint", "--all", "--discussion",
                           "--no-comments"]},
    # Its write verbs (Fold B3). `apply` is the one verb that sends a plan to the board, and only a named person
    # (`--by`) who typed the plan's 12-hex hash (`--confirm`) on a clone whose posture is `assisted`; `--limit` caps a
    # first seed. `comment` only DRAFTS one comment into a plan file, so it is safe on a `plan-only` clone: nothing
    # is sent until `apply --confirm`. Studio hides the control and says why when a plugin lacks the name.
    "ado-apply": {"script": "ado_sync.py", "argv": ["apply"],
                  "flags": ["--repo", "--state", "--json", "--confirm", "--by", "--limit"]},
    "ado-comment": {"script": "ado_sync.py", "argv": ["comment"],
                    "flags": ["--repo", "--state", "--json", "--message", "--by", "--mention", "--event"]},
    # Its disposition verb (Fold B4). `reconcile` settles one drift row `pull` recorded, through the design's
    # disposition machine: `--take ado` starts the verb that owns the field (never edits a spec itself), `--take sdlc`
    # keeps the repository's value, `ack` needs `--owner`, `not-drift` a `--reason`. Writes nothing to the board.
    # The desktop app hides its control and says why when a plugin lacks the name.
    "ado-reconcile": {"script": "ado_sync.py", "argv": ["reconcile"],
                      "flags": ["--repo", "--state", "--json", "--field", "--take", "--by", "--owner", "--reason",
                                "--from-comment"]},
}


def list_capabilities(scripts_dir: Path = SCRIPTS_DIR) -> list[str]:
    """The capabilities this plugin has, sorted: those whose script is present."""
    scripts_dir = Path(scripts_dir)
    return sorted(name for name, spec in CAPABILITIES.items() if (scripts_dir / spec["script"]).is_file())
