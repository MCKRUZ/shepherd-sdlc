# Section [N]: [Section Name]
<!-- Converged template: SDLC structured fields + /deep-plan implementation prose -->

**Owner:** [Name/role responsible for implementation]
**Sprint window:** [SNN] (set at /sprd-sprint slate; blank until slated)
**Estimated effort:** [S / M / L / XL — S=1-2 days, M=3-5 days, L=1-2 weeks, XL=2+ weeks]
**Status:** Not Started | In Progress | Complete

---

## Goal

[One sentence — what capability does the system have when this section is complete that it didn't have before?]

## Epics / Stories Covered

| Epic/Story ID | Title | P-Level |
|--------------|-------|---------|
| [EP-NNN] | [Title] | P0 / P1 |

## Entry Criteria

- [ ] [Dependency or prerequisite]
- [ ] [Dependency or prerequisite]

## Exit Criteria

- [ ] [Specific verifiable condition]
- [ ] All unit tests passing for components in this section
- [ ] Code reviewed and approved

## Dependencies

| Depends On | Type | Notes |
|-----------|------|-------|
| [Section N / External system] | [Blocking / Data / Interface] | [What specifically is needed] |

## Implementation Guidance
<!-- This section carries the full /deep-plan prose content. It should be self-contained
     enough that a developer can read only this section and start implementing. -->

[/deep-plan section content goes here — architecture decisions, code patterns,
directory structure, function signatures, configuration, and step-by-step
implementation instructions]

## Interfaces

What this section exposes to other sections:

| Interface | Type | Contract |
|-----------|------|---------|
| [Function/API/Event] | [Internal / External] | [What callers can expect] |

## Test Strategy
<!-- Combines SDLC coverage targets with /deep-plan TDD stubs -->

| Test Type | What to Test | Coverage Target |
|-----------|-------------|----------------|
| Unit | [Key functions/components] | [X]% |
| Integration | [Integration points] | All happy + error paths |

### TDD Test Stubs
<!-- From /deep-plan's claude-plan-tdd.md, scoped to this section -->

[Prose test descriptions — what to test first, expected behaviors,
edge cases to cover. Not full test implementations.]

## Risk

| Risk | Mitigation |
|------|-----------|
| [Section-specific risk] | [How to handle it] |

## Verification Criteria
<!-- How each exit criterion will be verified. Every criterion must be testable by an agent or human. -->

| Criterion | Verification Method | Pass Condition |
|-----------|-------------------|----------------|
| [Exit criterion from above] | [Unit test / Integration test / Manual inspection / Static analysis] | [Specific measurable condition] |

## Evaluator Contract
<!-- Defines what the section evaluator agent checks after implementation completes.
     This contract is the grading rubric — the evaluator reads it and grades against it. -->

**Evaluation scope:** [What files/modules/APIs are in scope for this section]

**Grading rubric:**
1. **Functional completeness** — All exit criteria pass conditions met
2. **Test quality** — Coverage target met, edge cases from Test Strategy covered
3. **Interface compliance** — Exposed interfaces match the Interfaces table above
4. **Code quality** — Functions within profile size limits, no deep nesting, immutability patterns followed
5. **Deviation accountability** — Any deviation from Implementation Guidance is documented with rationale

**Fail conditions (blocking):**
- Any exit criterion pass condition not met
- Test coverage below section target
- Interface contract broken without documented ADR

**Warn conditions (non-blocking):**
- Code style deviations from profile conventions
- Missing edge case tests (when not in critical path)
