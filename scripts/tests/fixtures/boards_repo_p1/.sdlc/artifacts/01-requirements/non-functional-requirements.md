# Non-Functional Requirements
<!-- Phase 1 — Requirements | Required artifact
     fixture: NFR-OI01 sits under a domain heading with a category heading below it, NFR-PR01 directly under a domain
     heading, and the rest under category headings that are not domains. NFR-P02 still holds template placeholders,
     NFR-P03 has no requirement text and NFR-C01 is the template's stand-in row. The Acceptance Test Plan repeats
     NFR ids as references; those rows define nothing. Generic names; every address is @example.com. -->

## Overview

Non-functional requirements define *how* the system must behave, not what it does.

---

## Order Intake

### Performance

| NFR ID | Requirement | Threshold | Measurement Method | Priority |
|--------|-------------|-----------|-------------------|----------|
| NFR-OI01 | Duplicate check latency | < 100ms at p95 | APM trace | P0 |

---

## Pricing Rules

| NFR ID | Requirement | Threshold | Measurement Method | Priority |
|--------|-------------|-----------|-------------------|----------|
| NFR-PR01 | Price band lookup | < 50ms at p95 | APM trace | P1 |

---

## Performance
<!-- REQUIRED: At least NFR-P01 and NFR-P02 filled in with specific numeric thresholds and a measurement method -->

| NFR ID | Requirement | Threshold | Measurement Method | Priority | Measurement Basis |
|--------|-------------|-----------|-------------------|---------|------------------|
| NFR-P01 | Response time (p95) | < 300ms | Load test | P0 | Measured: profiling |
| NFR-P02 | Throughput | [X] req/sec sustained | [How measured] | P1 | [source] |
| NFR-P03 |  | < 5ms | Load test | P2 | Industry standard |

---

## Security

| NFR ID | Requirement | Standard / Reference | Priority |
|--------|-------------|---------------------|---------|
| NFR-SEC01 | Authentication | OAuth2 with short-lived tokens | P0 |

---

## Compliance

| NFR ID | Regulation / Standard | Specific Requirement | Verification |
|--------|-----------------------|---------------------|-------------|
| NFR-C01 | [GDPR / SOC 2 / HIPAA / etc.] | [Specific control] | [Audit / test / review] |

---

## NFR Acceptance Test Plan

For each P0 NFR, describe how it will be verified before release:

| NFR ID | Test Method | Pass Condition | Owner |
|--------|-------------|---------------|-------|
| NFR-P01 | k6 load test for 10 minutes | p95 < 300ms with 0 errors | pat.example@example.com |
| NFR-OI01 | Replay of recorded duplicates | p95 < 100ms | @priya-n |
