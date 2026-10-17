# Success Criteria
<!-- Phase 0 — Discovery | Required artifact
     fixture: Dimension 1 has three filled threshold rows; Dimension 2 has a row whose threshold is still a template
     placeholder and a row with no Outcome cell (not a measurement); Dimension 3 has no threshold table at all.
     Generic names; every address is @example.com. -->

## Measurable Success Dimensions

For each dimension: define what Pass, Partial, and Fail look like with specific, measurable thresholds.

---

### Dimension 1: Turnaround time

**What we're measuring:** How long an order takes from submission to confirmation.

| Outcome | Threshold | How We'll Measure |
|---------|-----------|------------------|
| Pass (exceeds expectations) | Median under 2 minutes | Timestamp difference in the order log |
| Partial | Median 2 to 5 minutes | Timestamp difference in the order log |
| Fail | Median over 5 minutes | Timestamp difference in the order log |

**Data collection:** Weekly export of the order log.

---

### Dimension 2: Adoption

**What we're measuring:** The share of order desks using the portal.

| Outcome | Threshold | How We'll Measure |
|---------|-----------|------------------|
| Pass | 80% of desks active weekly | Sign-in count against the desk list |
| Partial | [Specific number/condition] | Sign-in count against the desk list |
|  | Under 50% of desks active weekly | Sign-in count against the desk list |

**Data collection:** Sign-in report, first working day of each month.

---

### Dimension 3: Data quality

**What we're measuring:** Whether order lines arrive complete. Thresholds are agreed at the workshop.

---

## Non-Negotiable Requirements

- [ ] No order is lost between submission and confirmation
- [ ] No customer sees another customer's order
- [ ] The portal is deployed without downtime

---

## Time to Value

**Target delivery:** First pilot desk live
**Full value realized:** All desks live and one quarter of data
**Review checkpoint:** End of the first quarter after launch
