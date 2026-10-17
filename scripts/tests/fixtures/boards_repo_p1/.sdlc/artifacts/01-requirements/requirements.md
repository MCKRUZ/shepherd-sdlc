# Requirements
<!-- Phase 1 — Requirements | Required artifact -->

## Overview

**Project:** Sample Order Portal
**Version:** 1.0
**Date:** 2026-09-20
**Status:** Draft

Requirements are testable statements of what the system must do. This is the breadth mini repository's copy:
two domains and three requirements, enough for an NFR to sit under a domain heading.

---

## Summary Table

| Domain | P0 | P1 | P2 | Total |
|--------|----|----|----|-------|
| Order Intake | 2 | 0 | 0 | 2 |
| Pricing Rules | 1 | 0 | 0 | 1 |
| **Total** | 3 | 0 | 0 | 3 |

---

## Functional Requirements

### Order Intake

### FR-001: Reject duplicate orders

**Priority:** P0 (Must Have)
**Source:** Order desk persona
**Rationale:** Duplicate orders cause double shipments.

**Requirement:**
> The system SHALL reject an order whose order_id matches an existing order.

**Acceptance criteria:**
- [ ] Given an existing order_id, when it is submitted again, then the API returns 409

---

### FR-002: Persist the first order

**Priority:** P0
**Source:** Order desk persona
**Rationale:** The first order must always be recorded.

**Requirement:**
> The system SHALL persist exactly one row for the first submission of an order_id.

**Acceptance criteria:**
- [ ] Given a new order_id, when it is submitted, then exactly one row exists

---

### Pricing Rules

### FR-003: Apply the active price band

**Priority:** P0
**Source:** Pricing owner
**Rationale:** Orders must be priced by one rule.

**Requirement:**
> The system SHALL price each order line from the active price band.

**Acceptance criteria:**
- [ ] Given an active band, when an order is priced, then every line uses that band

---

## Requirement Traceability

| Req ID | Description | Priority | Source Persona | User Story | Status |
|--------|-------------|----------|---------------|------------|--------|
| FR-001 | Reject duplicate orders | P0 | Order desk | US-001 | Draft |
| FR-002 | Persist the first order | P0 | Order desk | US-001 | Draft |
| FR-003 | Apply the active price band | P0 | Pricing owner | US-002 | Draft |
