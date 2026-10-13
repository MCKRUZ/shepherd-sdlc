# Review Report — Phase 2: Design
<!-- Written by the multi-reviewer agent (/sprd-review) to .sdlc/artifacts/{NN}-{phase}/review-report.md -->

**Mode:** council
**Date:** 2026-09-30T14:05:00Z
**Artifacts reviewed:** design-doc.md, api-contracts.md, threat-model.md

## Gate Results

<!-- findings: critical=0 high=2 medium=1 low=0 | open=3 fixed=0 accepted_risk=0 split=0 postponed=0 -->

| id | category | severity | target | disposition | detail |
|----|----------|----------|--------|-------------|--------|
| F1 | missing-rollback | HIGH | design-doc.md:88 | OPEN | no rollback strategy for the schema migration |
| F2 | auth-gap | HIGH | api-contracts.md:120 | OPEN | token refresh behaviour is unspecified when the client is offline |
| F3 | untestable-criterion | MEDIUM | design-doc.md:42 | OPEN | the latency target has no measurable threshold |

## Summary

Two HIGH findings block a clean sign-off: the migration has no rollback and the offline token refresh is undefined. The remaining finding is a wording fix.

## Detail

### F1: No rollback for the schema migration
The migration in section 4 is forward-only. If it fails halfway the claims table is left in a mixed state.

**Recommendation:** add an expand/contract plan with a tested rollback step.

### F2: Offline token refresh unspecified
The contract says tokens refresh silently but does not say what the client does with no network.

**Recommendation:** specify the offline behaviour and add a contract test for it.

### F3: Latency target not measurable
"Fast enough" appears as the target in section 2.

**Recommendation:** state a p95 threshold and the load it is measured at.
