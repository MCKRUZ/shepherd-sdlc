# Section [N]: [Section Name]
<!-- REQUIRED: Replace N with section number and give it a clear, outcome-focused name -->

**Owner:** [Name/role responsible for implementation]
**Sprint window:** [SNN] (set at /sprd-sprint slate; blank until slated)
**Estimated effort:** [S / M / L / XL — S=1-2 days, M=3-5 days, L=1-2 weeks, XL=2+ weeks]
**Status:** Not Started | In Progress | Complete

---

## Goal
<!-- REQUIRED: One sentence — what capability does the system have when this section is complete that it didn't have before? -->

[What this section delivers, framed as a user-visible or system capability]

## Epics / Stories Covered

| Epic/Story ID | Title | P-Level |
|--------------|-------|---------|
| [EP-NNN] | [Title] | P0 / P1 |

## Entry Criteria
<!-- REQUIRED: What must be true before work on this section can begin? -->

- [ ] [Dependency or prerequisite]
- [ ] [Dependency or prerequisite]

## Exit Criteria
<!-- REQUIRED: Specific, verifiable conditions that mark this section complete — not "done when it works" -->

- [ ] [Specific verifiable condition]
- [ ] All unit tests passing for components in this section
- [ ] Code reviewed and approved

## Dependencies

| Depends On | Type | Notes |
|-----------|------|-------|
| [Section N / External system] | [Blocking / Data / Interface] | [What specifically is needed] |

## Implementation Guidance
<!-- REQUIRED: Key design decisions, patterns to follow, pitfalls to avoid — enough for the implementer to start without ambiguity -->

[Specific guidance extracted from the design document for this section]

## Interfaces

What this section exposes to other sections:

| Interface | Type | Contract |
|-----------|------|---------|
| [Function/API/Event] | [Internal / External] | [What callers can expect] |

## Test Strategy

| Test Type | What to Test | Coverage Target |
|-----------|-------------|----------------|
| Unit | [Key functions/components] | [X]% |
| Integration | [Integration points] | All happy + error paths |

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
