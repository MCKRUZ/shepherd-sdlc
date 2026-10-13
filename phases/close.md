# Phase C: Close & Transfer

## Purpose
Prove the client can run all of it without the pod — the system, the harness, the loop, and the judgment — by observed, unassisted use; then exit cleanly and feed the standard. The engagement does not end when the code is done; the code was done weeks ago. It ends when the close gate passes: the client team ran one real spec end-to-end — triage, spec, delegate, grade, merge, deploy — without us driving. This phase is terminal. There is no handoff out, only a clean exit and a harvest PR back to the delivery standard.

## Entry Criteria
- Phase 9 exit gate passed and `close-handoff.md` reviewed
- The system live in production, observable, drilled, and retrospected
- The client Setup Owner named **before this phase starts**
- Client engineers available to orchestrate real specs (the training workstream priced into the SOW from Phase 0)

## Workflow

> **CONSTRAINT:** The close-gate spec MUST be a real spec — something the client genuinely needs, with a real risk tier and real consequences. A toy spec (a copy change at LOW tier chosen so it cannot fail) proves nothing and counts for nothing. And the run MUST be unassisted: any answer, hint, or keyboard touch from the pod voids it — the gap the help revealed is the finding; record it, fix it, and re-run on a *different* real spec.

### Step 0: HITL Gate — Confirm the Transfer Is Real Before Testing It

> **HITL GATE:** Read `close-handoff.md` and the Phase 9 retrospective. Before scheduling any close activity, present the following to the human using the `AskUserQuestion` tool — do not use inline markdown for HITL questions: (1) Are client engineers named and available to orchestrate real specs — at least three with pod Checkers, then one solo? If not, the close gate cannot be passed, and that is a steering conversation, not a scheduling one. (2) Is the client Setup Owner named, and have they merged (or are they ready to merge) harness changes themselves? (3) Which real backlog items are candidates for the shadow-flip specs and the close-gate spec — confirm each clears the real-spec bar. (4) What pod access exists to revoke (seats, tokens, repo permissions, environment roles, vault policies)? Do not begin the shadow flip until the human confirms the transfer's readiness.

Phase C answers four questions and nothing else: Can their people run the loop? Is the harness fully theirs? Is the record complete and delivered? Did we leave cleanly — and did the standard learn? New features are out of scope unless they are the *vehicle* — the specs run this phase are real work from the client's own backlog, chosen because the close gate must run on something that matters. A follow-on engagement is a new SOW with its own Phase 0, not a quiet extension of this one.

### Step 1: The Shadow Flip — Their Hands, Our Eyes

Reverse the roles that opened Build. The client's engineers take the Orchestrator seat on real specs from their own backlog — triage with their PO, spec writing, bounds, plan approval, driving the agent — while the pod serves only as **Checkers**. Coaching happens by question ("what does the spec say about that path?"), never by taking the keyboard.

- **At least three real specs** ride the loop this way, at the same bar as any change: the grader runs, a non-author approves, merge deploys. The specs come out of the client's own intent triage like any other work — ordinary backlog items, mixed tiers, each sized to merge within the window. The Pod Lead confirms each is real work, not an exercise built for the occasion.
- The pod Checkers **log every place they had to coach** — every moment they wanted the keyboard — because each one is a transfer gap with a name. Roll those logs into the shadow-flip spec record: per spec, who orchestrated, who checked, the grader and Checker outcomes, and the gaps.

Record this in `close-gate-evidence.md` (the shadow-flip section) — the three-spec threshold is a hard exit condition.

### Step 2: The Harness Audit — Find Anything Only We Understand

Run the harness audit in parallel with the shadow flip. It is a sweep of the repo for anything that would strand the client: skills with pod-specific assumptions, hooks referencing paths or permissions only the pod had, conventions that live in pod memory instead of `CLAUDE.md`. The one question: *could their team operate this if we vanished tonight?*

Use a read-only sweep agent to surface candidates, then have the Setup Owner walk every skill, hook, and convention:

```
Agent(Explore, "Read-only audit of the harness for transfer risk. Sweep CLAUDE.md, .claude/ (skills, agents, hooks, settings), and specs/ for: skills or hooks that assume pod-only paths/permissions/tools, conventions referenced but not documented in CLAUDE.md, and any knowledge that lives in pod memory rather than in the repo. List each finding with its location and why it would strand the client.")
```

Every finding becomes a documented fix the **client Setup Owner** merges — which kills two birds: the gap closes, and the client owner's merge history starts being real. "Ask the pod" must return zero results before the gate. Record findings and their fixes in `harness-audit.md`.

The client Setup Owner also ships at least one harness change **of their own** this phase — their improvement, their PR, their deputy arrangement on their side (the no-role-without-a-deputy rule transfers too: a named client engineer reviews the client Setup Owner's harness changes). Merge history is the test — a Setup Owner named in a deck but who never merged anything is a label, not an owner.

### Step 3: The Close Gate — One Real Spec, Solo, Observed

The phase's defining test. One real spec — something the client genuinely needs, with a real risk tier — runs the loop end to end with **nobody from the pod driving**: their triage, their spec, their bounds, their plan approval, their Checker, their merge, the automatic deploy. The client's triage picks the spec; the Pod Lead confirms it clears the real-spec bar before the run is scheduled.

The pod observes the way the Quality Engineer observed the cold runs in Documentation and Deployment: present, silent, taking notes. The observation record captures each loop step with timestamps and names, every stall, every guardrail event and how the team responded, and the merge and deploy that closed it. **Stalls are data; help voids the run.**

A failed or wobbly run is information, not embarrassment: name the gap, fix it (more reps, a harness clarification, a missing playbook line), and **re-run on a different real spec**. "They got through it with a little help" fails the close gate for the same reason it fails a cold checkout.

Record the close-gate observation in `close-gate-evidence.md` — names, timestamps, the loop steps, the merge that deployed, and the verdict. This is the engagement's last and most important gate.

### Step 4: Hand Over the Record

The complete engagement record, delivered into the client's tooling, not left in the pod's:
- The **final handoff report** (`final-handoff-report.md`) — the engagement record in one place
- Every phase report from 0 through 9
- The **outcomes dashboard**, re-pointed to client ownership with its caveats intact and the quarter-read date (the day the outcome metric gets its first full-period reading) on the client's calendar — record the handover in `outcomes-dashboard-handover.md`
- The debt log with owners and dates

Draft the final handoff report in two passes — deterministic first, judgment second:

1. **Mechanical assembly (the script).** Run `generate_handoff_report.py` to draft
   `final-handoff-report.md` straight from the engagement's records — the phase report index, the
   per-phase gate/sign-off table from `state.yaml`, the metrics history (via `scorecard.py`), and
   the spec backlog (via `track_specs.py`). It fills what is data and marks the rest with
   `[Fill: ...]` slots. It refuses to clobber a human-edited report without `--force`.

   ```
   uv run scripts/generate_handoff_report.py --state .sdlc/state.yaml
   ```

2. **Narrative enrichment (the agent).** Fill the marked slots — the judgment the script cannot
   make: outcomes against the Phase 0 statement, the debt log, open items with owners and dates,
   and who the client calls now.

   ```
   Agent(Explore, "Read-only sweep of the engagement record to fill the [Fill: ...] slots in the drafted final-handoff-report.md. Collect: each Phase 0 outcome and its result with caveats, the debt log with owners and dates, and all open items. Leave the script-filled sections (phase index, engagement record, metrics history, spec backlog) intact; enrich only the narrative slots, organized for the sponsor and the client's incoming team.")
   ```

### Step 5: Revoke Access, Audited

Every pod seat, token, repo permission, environment role, and vault access — removed on a checklist, confirmed against the client's audit trail by their security. The engagement ends with the pod provably unable to touch the system, which is not distrust; it is the last deliverable of the security posture the engagement ran on.

Draft `access-revocation-checklist.md` early (in week one) from everything the engagement was ever granted — the Phase 0/1 access checklist, CI secrets, environment roles, vault policies — so the revocation step is execution, not discovery. Production secrets the pod ever touched get rotated into production-only values the pod cannot read, signed by the client's security. The checklist is done when each item is removed *and* confirmed against the client's audit trail.

### Step 6: The Harvest PR — Feed the Standard

Open the mandatory improvements PR against the firm's own `delivery-standard` repo, carrying what this engagement taught: generalized skills, corrected templates, patterns worth repeating — drawn from the Phase 9 retrospective's list, with client specifics stripped. This is the compounding asset doing its compounding; an engagement that ends without a harvest taught the standard nothing.

```
Agent(Explore, "Read the Phase 9 project-retrospective and the engagement's harness changes. Draft the harvest PR content for the delivery-standard repo: the generalized skills, the corrected templates, and the repeatable patterns this engagement surfaced — with all client-specific names, data, and domain details stripped. List each candidate improvement with the engagement evidence behind it and the standard file it would touch.")
```

The pod reviews it; the standard's deputy merges it. Write the retro file into the standard repo's `retros/`: one file recording what this engagement changed about the standard and why. Record the harvest in `harvest-pr-notes.md`. The harvest is a gate item, not a virtue — leaving without it means the next pod re-discovers this engagement's lessons at a client's expense.

### Step 7: Generate Visual Report

Generate an interactive HTML visual report at `.sdlc/reports/close-visual.html` using the `/visual-explainer` skill (or equivalent HTML generation). This report is the close-steering artifact.

**Required visualizations for Phase C (Close):**
- Transfer scorecard — the three+ shadow-flip specs and the solo close-gate spec, each with orchestrator, Checker, and outcome
- Harness audit findings — each finding, its fix, and the client Setup Owner's merge
- Access revocation tracker — every credential, its removal, and its audit-trail confirmation
- Harvest summary — the patterns sent home to the standard

See the Visual Report Protocol in `SKILL.md` for rendering standards and fallback behavior.

### Step 8: Generate Phase Report

Run `/sprd-gate` to validate exit criteria and automatically generate the phase HTML report at `.sdlc/reports/close-report.html`. Share this report with stakeholders at the close steering. The report includes artifact inventory and gate status. The last billing milestone lands with the close gate's evidence attached.

## Standalone or Workflow

In the workflow, Close reads `.sdlc/state.yaml`, the Phase 9 retrospective, and `close-handoff.md`. It also runs standalone: a transfer audit can be pointed at any repo with a harness installed, with no `.sdlc/` present — run the harness audit and draft the access-revocation checklist against the actual repo and granted access, and draft the handoff report with `generate_handoff_report.py --repo <path>`, noting the missing engagement context in each artifact's header. The close gate itself, however, requires a real client team and real backlog specs — it cannot be simulated standalone, and the artifact will say so explicitly when the engagement context is absent.

## Artifact Specifications

### `final-handoff-report.md` (REQUIRED)
Must contain ALL of:
- **Engagement record** — every phase gate and its named sign-off, in one place
- **Phase reports** — links to all phase reports (0 through 9)
- **Metrics history** — accepted-as-is, review wait, the DORA four, escaped bugs, as trends across the engagement
- **Debt log** — every open item with an owner and a date, in the client's hands
- **Who they call now** — the client's own team, and what a future engagement would look like (a new Phase 0)

### `harness-audit.md` (REQUIRED)
Must contain ALL of:
- **Findings table** — each transfer-risk finding, its location, and why it would strand the client
- **Fixes** — the documented PR that closed each finding, and confirmation the **client Setup Owner** merged it
- **Client Setup Owner ownership** — evidence the client owner merged at least one harness change of their own, plus their named deputy arrangement
- **"Ask the pod" result** — confirmation the audit returned zero undocumented knowledge

### `close-gate-evidence.md` (REQUIRED)
Must contain ALL of:
- **Shadow-flip record** — at least three real specs orchestrated by client engineers with pod Checkers; per spec: who orchestrated, who checked, grader and Checker outcomes, and the coaching gaps logged
- **The close-gate observation** — one real spec, end to end, client-driven, observed and unassisted: the spec, its real risk tier, names, timestamps per loop step, every stall and guardrail event, the merge that deployed, and the verdict
- **Re-run record** (if applicable) — any run voided by help, the gap it revealed, the fix, and the different real spec it was re-run on

### `access-revocation-checklist.md` (REQUIRED)
Must contain ALL of:
- **Credential inventory** — every pod seat, token, repo permission, environment role, and vault access ever granted (sourced from the Phase 0/1 access checklist, CI secrets, environment roles, vault policies)
- **Removal status** — each item marked removed, with date
- **Audit-trail confirmation** — each removal confirmed against the client's audit trail by their security
- **Secret rotation** — production secrets the pod touched, rotated into values the pod cannot read, signed by client security

### Optional Artifacts
- `outcomes-dashboard-handover.md` — the dashboard re-pointed to client ownership, caveats intact, quarter-read date on their calendar
- `harvest-pr-notes.md` — the patterns sent home to the standard, the harvest PR reference, and the retro file
- `close-report.html` — the generated phase report

## Exit Criteria
- [ ] `final-handoff-report.md`, `harness-audit.md`, `close-gate-evidence.md`, and `access-revocation-checklist.md` exist and are complete
- [ ] The harness audit ran and found nothing undocumented — every finding fixed by a PR the client Setup Owner merged
- [ ] The client Setup Owner is named and has merged harness changes themselves — including at least one of their own
- [ ] Client engineers completed at least three real specs as Orchestrators with pod Checkers — the bar unchanged
- [ ] **The close gate: the client team ran one real spec end-to-end — triage, spec, delegate, grade, merge, deploy — without the pod driving.** Observed, unassisted; a run that needed help was re-run on a different real spec
- [ ] Every phase report delivered and the outcomes dashboard handed over, caveats intact, with the quarter-read date on the client's calendar
- [ ] The debt log is in the client's hands with owners and dates
- [ ] Pod access is revoked — every seat, token, and permission — and confirmed against the client's audit trail
- [ ] The harvest PR is opened against the delivery-standard repo, and the retro file is written
- [ ] A named human on each side signed the close (manual gate) — gates report, humans decide, one last time

## HTML Report
The phase report is generated automatically when you run `/sprd-gate` or `/sprd-next`. It is written to `.sdlc/reports/close-report.html` and is fully self-contained — share it with stakeholders at the close steering as the review artifact for the final sign-off.

To regenerate at any time: `/sprd-phase-report`

## Terminal Phase
Close is the final phase of the engagement. There is **no next phase and no handoff out** — only the clean exit (access revoked, audited) and the harvest PR back to the delivery standard. If the client wants ongoing help, that is a new agreement made in daylight, with its own Phase 0 — not a transition-services annex that quietly keeps the pod on retainer.

## Guidance
- **The indispensable pod member** — one person's head still holds how something really works, discovered the week after they leave. The harness audit exists for exactly this; "ask the pod" must return zero results before the gate.
- **The toy close gate** — a copy change at LOW tier with no stakes, chosen so it cannot fail, proves nothing and everyone in the room knows it. Real spec, real tier, real consequences — or the gate did not run.
- **The helpful observer** — someone from the pod answers one little question forty minutes in. The run is void. The gap the question revealed is the finding; record it, fix it, re-run.
- **The Setup Owner in name only** — named in a deck but never merged anything. Merge history is the test: the audit fixes plus at least one change of their own, or the harness has no owner.
- **Access that lingers** — "we'll clean up the seats next sprint." Revocation is a dated checklist item confirmed by their security, not a cleanup intention.
- **Scope dressed as closure** — "before you go, could you just—" burns the calendar the gate needs. New work is a new conversation with a new SOW.
- **The skipped harvest** — the pod rolls off and the PR never opens; the standard learns nothing. The harvest is a gate item.
- **The quiet retainer** — hypercare reflexes outlive their window and the pod keeps answering questions off the record. The close means the close; future help is a future agreement.

## Coaching Prompts

When operating in coaching mode (`/sprd-coach`) for this phase:

### Opening (transfer not yet started)
- "Are client engineers named and ready to orchestrate real specs? If not, the close gate can't pass — that's a steering conversation now."
- "Is the client Setup Owner named, and have they merged a harness change yet? A name in a deck isn't an owner."
- "Which real backlog items are candidates for the shadow-flip and the solo close-gate spec?"

### Progress Check (shadow flip running)
- "How many real specs have client engineers orchestrated with you as Checker? The bar is at least three."
- "Where did you want to grab the keyboard? Every one of those is a transfer gap with a name."

### Ready Check (approaching the close gate)
- "Is the close-gate spec a real one — real need, real tier, real consequences? A toy spec proves nothing."
- "Is the access-revocation checklist drafted and ready to execute, or is it still discovery?"
- "Is the harvest PR drafted? Leaving without it means the next pod re-learns this at a client's expense."
