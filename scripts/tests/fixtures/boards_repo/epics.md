# Epics
<!-- Phase 1 — Requirements | Required artifact -->

## Overview

Epics are large user-facing capabilities. This is the mini repository the Boards mirror's source
readers are tested against; every name in it is generic.

---

## P0 Epics — Must Ship
<!-- REQUIRED: at-least-one-p0-epic — define at least one P0 epic with a complete Given/When/Then acceptance criterion -->

### EP-001: Claims intake

**As a** claims adjuster,
**I want to** submit a claim once and see it recorded,
**so that** nothing is lost or paid twice.

**Priority:** P0
**Estimate:** 3
**Linked requirement:** FR-001..004

**Acceptance criteria:**
- [ ] **Given** an existing claim id, **when** it is submitted again, **then** the API returns 409

---

## P1 Epics — Should Ship

### EP-002: Claim status

**As a** claims adjuster,
**I want to** see where each claim stands,
**so that** I do not have to ask.

**Priority:** P1
**Estimate:** 5
**Linked requirement:** FR-010

**Acceptance criteria:**
- [ ] **Given** a filed claim, **when** I open the dashboard, **then** its status is shown

---

## P2 Epics — Nice to Have

### EP-003: Claims export

**As a** claims adjuster,
**I want to** export my claims,
**so that** I can analyse them offline.

**Priority:** P2
**Estimate:** 2

**Acceptance criteria:**
- [ ] Export produces one row per claim

---

## Epic Summary

| Epic ID | Title | Persona | Priority | Estimate | FR Link |
|---------|-------|---------|---------|---------|---------|
| EP-001 | Claims intake | Claims adjuster | P0 | 3 | FR-001..004 |
| EP-002 | Claim status | Claims adjuster | P1 | 5 | FR-010 |

**Total P0 epics:** 1
**Total P1 epics:** 1
**Total P2 epics:** 1
**Total estimate:** 10 points
