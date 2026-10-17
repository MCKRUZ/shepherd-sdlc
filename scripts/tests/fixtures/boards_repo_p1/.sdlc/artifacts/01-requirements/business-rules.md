# Business Rules
<!-- Phase 1 — Requirements | Optional artifact
     fixture: BR-01 is named by one feature brief (FE-01), BR-02 by two (FE-01 and FE-02), BR-04 by one (FE-02), BR-05
     by none. BR-02 is pending DL-03 (in the decision log) and BR-06 pending DL-09 (not in it). BR-03 is the template's
     stand-in row. Generic names; every address is @example.com. -->

Owned by **Bizreq**. A decision table of the business rules a feature must honor.

---

| Rule  | Condition                                 | Outcome                                   | Source        | Approver |
|-------|-------------------------------------------|-------------------------------------------|---------------|----------|
| BR-01 | An order repeats an existing order id     | Reject it with a 409                      | policy §3     | @priya-n |
| BR-02 | The order total exceeds the credit limit  | Hold for review *(pending DL-03)*         | —             | @priya-n |
| BR-03 | [ambiguous / edge condition]              | [action] *(pending <DL-NN>)*              | —             | [name/role] |
| BR-04 | A price band expires while an order is open | Use the band active at submission       | policy §7     | pat.example@example.com |
| BR-05 | A shipment weighs zero                    | Flag it for a manual check                | —             | @priya-n |
| BR-06 | A customer is on the hold list            | Refuse the order *(pending DL-09)*        | —             | @priya-n |

*Add one row per rule.*
