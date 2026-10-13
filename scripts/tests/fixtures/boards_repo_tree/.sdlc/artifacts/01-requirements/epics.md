# Epics
<!-- Phase 1 — Requirements | Required artifact -->

## Overview

Epics are large user-facing capabilities.

---

## P0 Epics — Must Ship

### EP-001: Orders are accepted once

**Priority:** P0
**Estimate:** 3
**Linked requirement:** FR-001

**Acceptance criteria:**
- [ ] **Given** a duplicate order, **when** it is submitted, **then** it is refused

---

### EP-002: Customers hear back and pay the right price

**Priority:** P0
**Estimate:** 5
**Linked requirement:** FR-003

**Acceptance criteria:**
- [ ] **Given** an accepted order, **when** it is priced, **then** a confirmation shows the price

---

## P1 Epics — Should Ship

### EP-003: Desks follow a shipment

**Priority:** P1
**Estimate:** 2

**Acceptance criteria:**
- [ ] **Given** a shipped order, **when** the desk opens it, **then** the carrier status shows

---

## Epic Summary

| Epic ID | Title | Persona | Priority | Estimate | FR Link |
|---------|-------|---------|---------|---------|---------|
| EP-001 | Orders are accepted once | Order desk | P0 | 3 | FR-001..002 |
| EP-002 | Customers hear back and pay the right price | Order desk | P0 | 5 | FR-003, FR-005 |
| EP-003 | Desks follow a shipment | Order desk | P1 | 2 | |

**Total P0 epics:** 2
**Total P1 epics:** 1
**Total P2 epics:** 0
**Total estimate:** 10 points
