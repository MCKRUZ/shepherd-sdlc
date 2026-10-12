# /sdlc-rules — Author Business Rules and Golden Scenarios

Give Bizreq a first-class drafting seat: the **business rules** (a `BR-NN` decision table) and the
**golden scenarios** (`SCEN-NN`) that pin down what "correct" means before anyone builds. Each `BR-NN`
becomes an Acceptance Check on the spec (advisory / soft traceability); each `SCEN-NN` seeds the golden
set at `/sdlc-evals`. Interview-driven like `/sdlc-coach`: the `bizreq-analyst` agent assesses what's
there, asks focused questions, and drafts as answers arrive. It **proposes**; a named human
**decides** (the One Rule). Works inside an SDLC project or standalone.

## Instructions

1. **Resolve context:**
   - **Workflow mode** (default): `.sdlc/state.yaml` exists. Read the requirements, feature-brief, and
     any intake corpus (`DOC-NNN` summaries) for the policy source; outputs land in
     `.sdlc/artifacts/01-requirements/`.
   - **Standalone mode** (`--repo <path>`, or no `.sdlc/` found): operate on the given repo with
     provisional context; write to `--output` (default alongside the repo) and note the missing context
     in the artifact headers.

2. **Assess what exists:** Read the requirements and any policy documents. Identify the decision points
   the feature must get right and the scenarios that would prove it — and where the policy is silent or
   contradictory (a contradiction is a candidate decision-log item, not a guessed rule).

3. **Run the interview:** Spawn the `bizreq-analyst` agent (Bizreq discipline). It runs the coach-style
   dialogue — the conditions, outcomes, and **approver** for each rule; the source policy each rule
   cites; and the representative scenarios (including the tricky/ambiguous ones). It drafts **two**
   files from the templates in `templates/phases/01-requirements/`:
   - `business-rules.md` — the `BR-NN` decision table (condition → outcome → source → approver).
   - `golden-scenarios.md` — the `SCEN-NN` table (input → expected behavior).

4. **Confirm the rules and route open questions with the human:**

> **HITL GATE:** Present the decision table and scenarios using the `AskUserQuestion` tool. Ask:
> (1) Confirm each `BR-NN` outcome and its **approver** — the analyst proposes; a named human signs.
> (2) Any rule whose outcome is **not yet decided** (policy silent/ambiguous) becomes a **decision-log**
>     item (owner + 2-business-day clock), and the rule carries a *pending* marker until it closes —
>     the analyst never guesses the outcome.
> (3) Confirm the `SCEN-NN` set is representative enough to seed the golden set (add missing edge cases).
> Bizreq proposes; a named human signs the rules at the phase gate (captured in state).

5. **Open decision-log items:** For each pending rule the human named, append an entry to the
   decision-log (`templates/phases/01-requirements/decision-log.md` shape) with owner + clock — workflow
   writes `.sdlc/decision-log.md`, standalone writes `<repo>/decision-log.md`. When the decision closes
   it hardens the `BR-NN` and drops its pending marker.

6. **Report:**
   ```
   Business Rules & Golden Scenarios Authored
   ==========================================
   Rules:     N BR-NN (X pending on the decision-log; owners: …)
   Scenarios: M SCEN-NN ready to seed the golden set
   Next: BR-NN → Acceptance Checks at /sdlc-spec (soft traceability); SCEN-NN → /sdlc-evals golden set.
   ```

## Arguments

- No arguments: workflow mode — author against the current project's requirements.
- `--repo <path>`: standalone mode — author in any repo with no `.sdlc/` present.
- `--feature <id>` / `--spec <path>`: scope the rules to a feature or spec (otherwise inferred/asked).
- `--output <path>`: override the output location (standalone).

## Important

- **The analyst proposes; a named human decides.** The `bizreq-analyst` never invents a rule outcome
  where the policy is silent — that becomes a decision-log item with an owner and a clock.
- **`BR-NN` → Acceptance Check is soft traceability** (advisory): a rule *should* map to a check on the
  spec, surfaced by the review lens, never a hard gate.
- **`SCEN-NN` is the golden-set seed.** The scenarios authored here become the cases `/sdlc-evals` builds
  into the versioned golden set for `llm_powered` channels.
- Both files are **optional** for gate purposes; an unfilled/pending rule is an advisory flag. Bizreq
  proposes; a named human signs at the phase gate. The command changes no protected core.
