# Smart Repair Reference

The smart repair system attempts to fix simple gate failures before escalating to the human. It's invoked by the `gate-repair` agent when gate checks find structural issues.

## Repair Categories

### Repairable (Auto-Fix)

| Category | Trigger | Repair Action |
|----------|---------|---------------|
| Template scaffolding | G1: Required artifact missing | Copy from `templates/` directory, fill state/profile fields |
| Section completion | G2: Markdown missing required H2 | Add section header with TODO prompt |
| Frontmatter repair | G2: YAML frontmatter incomplete | Infer values from state.yaml/profile.yaml |
| Placeholder cleanup | G2: `${VARIABLE}` tokens found | Replace with values from state/profile where unambiguous |
| Empty file fill | G1/G2: File exists but empty | Scaffold from corresponding template |

### Not Repairable (Escalate to Human)

| Category | Why |
|----------|-----|
| Missing requirements | Requires domain knowledge and stakeholder input |
| Design decisions | Architectural choices need human judgment |
| Acceptance criteria | Must reflect actual project goals |
| Code quality failures | Tests must pass on real code, not scaffolds |
| Security findings | Security issues require expert review |
| Compliance gaps | Regulatory requirements need verified accuracy |
| Coverage shortfalls | Can't fabricate test coverage |
| Any metric failure | Metrics reflect real state, not fixable by repair |

## Invocation

### Via `/sprd-gate`

The gate command offers repair when failures are found:

```
Gate Check Results — Phase 1
========================================
  [FAIL] [MUST] G1-integrity: Missing: 'requirements.md'
  [FAIL] [MUST] G2-completeness: File 'epics.md' contains placeholder content: ['TODO']
  [PASS] [MUST] G1-integrity: File 'non-functional-requirements.md' exists

Would you like me to attempt auto-repair on the fixable issues?
```

If the user agrees, the `gate-repair` agent:
1. Scaffolds `requirements.md` from the template
2. Cannot fix the TODO in `epics.md` (substantive content needed) — escalates
3. Re-runs gate check on repaired artifacts
4. Reports: "Repaired 1 of 2 failures. 1 requires human attention."

### Via `/sprd-next`

When MUST gates fail during phase advancement, the command offers: "Would you like me to attempt auto-repair on the fixable issues?" Same flow as above.

## Design Principles

1. **Structure over content** — scaffolds and headers, never generated prose masquerading as real content
2. **Human approval required** — repair runs, human reviews, then gates re-run
3. **Conservative classification** — when uncertain whether something is repairable, classify as not-repairable
4. **Idempotent** — running repair multiple times produces the same result
5. **Transparent** — every change is reported with before/after context
