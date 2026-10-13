---
phase: ${PHASE_ID}
phase_name: "${PHASE_NAME}"
created: "${TIMESTAMP}"
gate_decision: "${GATE_DECISION}"
gate_summary:
  passed: ${PASSED}
  failed: ${FAILED}
  manual: ${MANUAL}
source_artifacts: ${SOURCE_ARTIFACTS}
estimated_tokens: ${ESTIMATED_TOKENS}  # word_count × 1.3
---

# Phase ${PHASE_ID}: ${PHASE_NAME} — Phase Layer

<!--
  A living summary of this phase's artifacts as they are NOW — not a lock on them. When a source
  artifact changes later (refinement, /sprd-revise, /sprd-refresh), this layer is regenerated and
  the previous version is kept as phase{N}-{name}.md.superseded-<YYYYMMDD>. The `## Locked Metrics`
  heading is read literally by the G5 gate; "locked" means carried forward and re-checked.
  See references/frozen-layers.md.
-->


## Decision

${GATE_DECISION} — Score: ${SCORE}. ${CONDITIONS_SUMMARY}

## Key Outcomes

- ${OUTCOME_1}
- ${OUTCOME_2}
- ${OUTCOME_3}

## Locked Metrics

> Include ONLY metrics with explicit values established in this phase.
> Omit this entire section if no metrics were established.
> Any change to these values in later phases requires a decision log entry.
> See `references/cross-phase-consistency.md`.
>
> Common metrics: Budget, Timeline, Scope boundaries, Stakeholder roster, Quality thresholds.
> Include only those with concrete values — never use "TBD" or "N/A".

| Metric | Value | Source Artifact |
|--------|-------|-----------------|

## Constraints Carried Forward

${CONSTRAINTS}

## Risks & Mitigations

> Omit this section if no active risks were identified.

| Risk | Severity | Mitigation | Status |
|------|----------|------------|--------|

## Artifact Summary

| Artifact | Summary |
|----------|---------|
| ${ARTIFACT_NAME} | ${ONE_LINE_SUMMARY} |

---

**Traceability** — This frozen layer was derived from:

| Source Artifact | Sections Extracted |
|-----------------|-------------------|
| ${SOURCE_FILE} | ${SECTIONS_USED} |

---

**Condensation Rules:**
- Target: 1500–2000 tokens (hard max: 2500)
- Priority: Locked Metrics > Constraints > Risks > Key Outcomes
- Omit boilerplate, template headers, and placeholder content
- Every value must trace to a source artifact
- Tables are preferred over prose for density
