# Success Criteria
<!-- Phase 0 — Discovery | Required artifact -->

## Measurable Success Dimensions

For each dimension: define what Pass, Partial, and Fail look like with specific, measurable thresholds.

---

### Dimension 1: Turnaround time

**What we're measuring:** How long an order takes from submission to confirmation.

| Outcome | Threshold | How We'll Measure |
|---------|-----------|------------------|
| Pass (exceeds expectations) | Median under 2 minutes | Timestamp difference in the order log |
| Partial (acceptable, improvement required) | Median 2 to 5 minutes | Timestamp difference in the order log |
| Fail (not acceptable for release) | Median over 5 minutes | Timestamp difference in the order log |

**Data collection:** Weekly export of the order log.

---

### Dimension 2: Margin consistency

**What we're measuring:** Whether the same product is priced by the same rule on every order.

| Outcome | Threshold | How We'll Measure |
|---------|-----------|------------------|
| Pass | 100% of orders priced by the active band | Monthly audit of 200 sampled orders |
| Partial | 95% to 99% of orders priced by the active band | Monthly audit of 200 sampled orders |
| Fail | Under 95% of orders priced by the active band | Monthly audit of 200 sampled orders |

**Data collection:** Monthly sample drawn by the pricing owner.

---

### Dimension 3: Adoption

**What we're measuring:** The share of order desks using the portal.

| Outcome | Threshold | How We'll Measure |
|---------|-----------|------------------|
| Pass | 80% of desks active weekly | Sign-in count against the desk list |
| Partial | 50% to 79% of desks active weekly | Sign-in count against the desk list |
| Fail | Under 50% of desks active weekly | Sign-in count against the desk list |

**Data collection:** Sign-in report, first working day of each month.

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

---

## Success Owner

| Dimension | Who owns measuring it | Who reviews results |
|-----------|----------------------|---------------------|
| Turnaround time | Operations lead | Product owner |
| Margin consistency | Pricing owner | Finance reviewer |
| Adoption | Rollout lead | Product owner |
