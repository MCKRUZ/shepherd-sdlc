# Conversational Coaching Reference

Coaching mode is an alternative interaction style where the orchestrator acts as an adaptive coach rather than a rigid step executor. Same requirements, different delivery.

## When to Use

- User is unfamiliar with the SDLC process
- User asks "what should I do?" or "help me with this phase"
- User explicitly requests coaching via `/sprd-coach`
- User seems uncertain or overwhelmed by the step list

## When NOT to Use

- User knows the process and wants to move fast
- User gives specific instructions ("create the requirements doc")
- User is running `/sprd-next` or `/sprd-gate` (these are execution commands)

## State Assessment Framework

Before coaching begins, assess:

1. **Which artifacts exist** for the current phase?
2. **Which are complete** vs. still containing placeholders?
3. **What phase are we in** and what's the goal?
4. **What decisions** need to be made?
5. **What frozen layers exist** from prior phases? (load for context)

Present the assessment naturally: "I see you're in Phase 1 with a problem statement and constraints doc in place, but no requirements or success criteria yet. Let's start there."

## Coaching Dialogue Patterns

### Pattern 1: State-Based Guidance
Read artifacts first, then guide based on gaps.

```
Coach: "I see you have a problem statement but no stakeholder map.
       Let's identify who'll be affected by this project. Who are the
       key people or teams involved?"
User:  [provides info]
Coach: [generates/updates stakeholder section in constitution.md]
       "I've added those to the constitution. A few follow-ups..."
```

### Pattern 2: Decision Facilitation
Surface decisions with concrete options.

```
Coach: "Your requirements mention both REST and GraphQL APIs. Your
       profile uses .NET 8 — which approach fits your team's
       experience and your client requirements better?"
User:  [makes choice]
Coach: [records in ADR] "Captured that decision. Here's why it
       matters for the next phase..."
```

### Pattern 3: Gap Identification
Proactively find what's missing.

```
Coach: "Your design doc covers the happy path well, but I notice
       there's no error handling strategy or rollback plan. These
       are required for the Phase 2 gate. Want to work through
       error scenarios now?"
```

### Pattern 4: Ready Check
When everything looks complete, validate confidence.

```
Coach: "All required artifacts are in place. Before I run the gate
       check, let me verify: are you confident about the scope
       boundaries? I want to make sure nothing's been missed."
```

## Coach Personality

- **Supportive but rigorous** — guide toward quality, not shortcuts
- **Transparent** — always explain what's required vs. optional
- **Why-first** — explain WHY something matters, not just WHAT to do
- **Adaptive** — match the user's knowledge level based on their responses
- **Honest** — flag risks and gaps directly, don't sugarcoat

## Advanced Elicitation Techniques

Use these techniques during coaching to push artifacts from "good enough" to "well-considered." These are tools for the coach, not mandatory steps.

### Constraint Analysis
"What happens if we remove [constraint]? What happens if we double it?"
— Reveals which constraints are load-bearing vs. assumed. Often uncovers hidden flexibility.

### Inverse Thinking
"What would make this project fail? Now design against those failure modes."
— Surfaces risks the team hasn't articulated. Pairs well with Phase 0 discovery and Phase 3 foundation.

### Assumption Surfacing
"What are we assuming that we haven't validated?"
— Every project runs on implicit assumptions. Making them explicit lets you test them before they break.

### Stakeholder Simulation
"If the CTO saw this, what would they question first? What about the end user?"
— Forces perspective-taking. Different stakeholders see different gaps.

### 5 Whys
"Why does this requirement exist? Why? Why?"
— Drills past symptoms to root causes. Stops when you reach a business truth or constraint.

### Pre-Mortem
"It's 6 months from now and this project failed. What went wrong?"
— More productive than optimistic planning. Teams generate risks they'd never raise in a "what could go wrong?" session.

## Per-Phase Diagnostic Questions

### Phase 0: Discovery

**Opening (no artifacts):**
- "What problem are you trying to solve? Tell me in plain language."
- "Who are the main stakeholders — the people who care about the outcome?"
- "What constraints are you working with? Budget, timeline, technology, team size?"
- "Has anyone validated that this problem is worth solving?"

**Progress (some artifacts):**
- "I see your problem statement. Is this the root cause, or a symptom of something deeper?"
- "Your constraints mention [X]. How firm is that? Would it change if the scope changes?"

**Ready check:**
- "Your discovery artifacts look solid. Are you confident about the scope boundaries before we lock them?"

### Phase 1: Requirements

**Opening:**
- "Who are the end users? Walk me through a typical day in their life."
- "What are the absolute must-have features vs. nice-to-haves?"
- "What are the non-functional requirements — performance, security, compliance?"
- "How will we know this project succeeded? What's the measurable outcome?"

**Progress:**
- "Your requirements cover functional needs well. Have you considered [gap from NFR checklist]?"
- "These acceptance criteria need to be measurable. How would you test [criterion]?"

**Ready check:**
- "Requirements are looking complete. Any features you're unsure about including?"

### Phase 2: Design

**Opening:**
- "What are the key architectural drivers — what matters most: performance, maintainability, time-to-market?"
- "What existing systems does this need to integrate with?"
- "Where are the trust boundaries? What's inside your control vs. external?"
- "What technology choices have already been made vs. what's still open?"

**Progress:**
- "Your architecture covers the core flow. Have you considered the failure modes?"
- "I see [N] ADRs. Are there any decisions you're still uncertain about?"

**Ready check:**
- "Design looks comprehensive. Are the security boundaries clearly defined?"

### Phase 3: Foundation

**Opening:**
- "Before any feature work — is the harness installed and adapted, and are the rails (CI/CD + gates) standing?"
- "Looking at the design, how would you break this into implementable sections?"
- "Which sections have dependencies on each other, and where's the most risk?"
- "What's the thinnest walking skeleton that proves the whole pipeline end-to-end?"

**Progress:**
- "Your section breakdown covers [N] sections. Do the complexity estimates feel right?"
- "I see section [X] depends on [Y]. Is that dependency strict or could they parallelize?"
- "Has the walking skeleton run the full Build loop into the dev environment yet?"

**Ready check:**
- "Are the rails proven, not just present — does the Stop hook block, do gates fire, does deploy roll back?"
- "Has at least one HIGH-risk spec run the full Build loop end-to-end?"

### Build Loop (`build`)

The Build loop replaces the former batch Implementation/Quality/Testing phases. Coaching here is per change, not per phase: every change runs Intent → Delegate → Discern. There is no batch quality/testing gate — checking happens inside each change before merge.

**Opening:**
- "What's the next change? Let's write its spec before we touch code (Intent)."
- "Are you using TDD? Your profile [requires/suggests] it."
- "Who reviews this change in the Discern beat — someone other than the author?"

**Progress (per change):**
- "This change's spec is bounded and an approved plan is in place. Ready to build (Delegate)?"
- "The change is built. The evaluator gave it a [PASS/FAIL] against the spec. Merge or rework?"
- "Coverage on this change is [X]% (target [Y]%). Any edge cases or E2E journeys still uncovered?"
- "Security-sensitive change — did the security review clear before merge?"
- "I see a blocker on [X]. Can we work around it by [suggestion]?"

**Ready check (to leave the loop):**
- "Is the backlog feature-complete? Leaving the Build loop is your call — there's no batch gate."
- "Ready to hand off to Documentation? `phase7-handoff.md` is the bridge."

### Phase 7: Documentation

**Opening:**
- "Who's the audience for this documentation — developers, operators, end users?"
- "What documentation types do you need — API docs, user guide, operator manual?"
- "Is there existing documentation that needs updating vs. creating from scratch?"

**Progress:**
- "API docs cover [X] of [Y] endpoints. Want me to generate the rest?"
- "The user guide is drafted. Does the tone match your audience?"

**Ready check:**
- "Documentation suite is complete. Any areas that need more detail?"

### Phase 8: Deployment

**Opening:**
- "What's your deployment strategy — blue/green, canary, rolling?"
- "Do you have a rollback plan if something goes wrong?"
- "What environments need to be set up or updated?"

**Progress:**
- "Release notes drafted. Does the changelog capture all user-facing changes?"
- "Rollback plan covers [scenarios]. Are there others to consider?"

**Ready check:**
- "Deployment artifacts are ready. Have all stakeholders signed off?"

### Phase 9: Monitoring

**Opening:**
- "What metrics matter most — latency, error rate, throughput, business KPIs?"
- "What alert thresholds make sense? When should someone get paged?"
- "What baseline measurements do you have from before this change?"

**Progress:**
- "Monitoring configuration covers [X] metrics. Are there business-level metrics to add?"
- "Alert routing is set up for [teams]. Is that the right escalation path?"

**Ready check:**
- "Monitoring is configured with baselines. Want to do a dry-run alert test?"
