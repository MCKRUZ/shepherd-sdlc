# Requirements
<!-- Phase 1 — Requirements | Required artifact -->

## Overview

**Project:** Sample Order Portal
**Version:** 1.0
**Date:** 2026-10-01
**Status:** Draft

Requirements are testable statements of what the system must do.

---

## Summary Table

| Domain | P0 | P1 | P2 | Total |
|--------|----|----|----|-------|
| Order Intake | 2 | 1 | 0 | 3 |
| Pricing Rules | 1 | 1 | 0 | 2 |
| Shipment Tracking | 0 | 1 | 1 | 2 |
| **Total** | 3 | 3 | 1 | 7 |

---

## Functional Requirements

<!-- fixture: FR-099 sits under no `### <Domain>` heading on purpose; it is the case the loaders refuse. -->

### FR-099: Keep an audit trail of every change

**Priority:** P1
**Source:** Operations persona
**Rationale:** A change nobody can trace cannot be explained later.

**Requirement:**
> The system SHALL record who changed an order and when.

**Acceptance criteria:**
- [ ] Given an order edit, when it is saved, then the audit trail gains one entry

---

### Order Intake

### FR-001: Reject duplicate orders

**Priority:** P0 (Must Have)
**Source:** Order desk persona
**Rationale:** Duplicate orders cause double shipments.

**Requirement:**
> The system SHALL reject an order whose order_id matches an existing order.

**Acceptance criteria:**
- [ ] Given an existing order_id, when it is submitted again, then the API returns 409
- [ ] Given a new order_id, when it is submitted, then the API returns 201

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

### FR-003: Confirm receipt to the customer

**Priority:** P1
**Source:** Order desk persona
**Rationale:** Customers resubmit when they hear nothing.

**Requirement:**
> The system SHALL send a confirmation within one minute of an accepted order.

**Acceptance criteria:**
- [ ] Given an accepted order, when one minute passes, then a confirmation has been sent

---

### Pricing Rules

### FR-004: Apply the active price band

**Priority:** P0 / P1 / P2
**Source:** Pricing owner
**Rationale:** Orders must be priced by one rule.

**Requirement:**
> The system SHALL price each order line from the active price band.

**Acceptance criteria:**
- [ ] Given an active band, when an order is priced, then every line uses that band

---

### FR-005: Review price band changes

**Priority:** P1
**Source:** Pricing owner
**Rationale:** A band change moves margin.

**Requirement:**
> The system SHALL hold a price band change until a reviewer approves it.

**Acceptance criteria:**
- [ ] Given a proposed band change, when no reviewer has approved it, then it is not active

---

### Shipment Tracking

### FR-006: Show shipment status

**Priority:** P1
**Source:** Order desk persona
**Rationale:** Desks answer "where is my order" all day.

**Requirement:**
> The system SHALL show the latest carrier status for each shipment.

**Acceptance criteria:**
- [ ] Given a shipped order, when the desk opens it, then the latest carrier status shows

---

### FR-007: Archive delivered shipments

**Source:** Operations persona
**Rationale:** Old shipments slow the screen down.

**Requirement:**
> The system SHALL archive a shipment 90 days after delivery.

**Acceptance criteria:**
- [ ] Given a shipment delivered 90 days ago, when the nightly job runs, then it is archived

---

## Requirement Traceability

| Req ID | Description | Priority | Source Persona | User Story | Status |
|--------|-------------|----------|---------------|------------|--------|
| FR-001 | Reject duplicate orders | P0 | Order desk | US-001 | Draft |
| FR-002 | Persist the first order | P0 | Order desk | US-001 | Draft |
| FR-003 | Confirm receipt | P1 | Order desk | US-002 | Draft |
| FR-004 | Apply the active price band | P0 | Pricing owner | US-003 | Draft |
| FR-005 | Review price band changes | P1 | Pricing owner | US-003 | Draft |
| FR-006 | Show shipment status | P1 | Order desk | US-004 | Draft |
| FR-007 | Archive delivered shipments | P2 | Operations | US-005 | Draft |
| FR-099 | Audit trail | P1 | Operations | US-006 | Draft |
