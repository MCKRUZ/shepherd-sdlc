# Golden Scenarios
<!-- Phase 1 — Requirements | Optional artifact -->

Owned collaboratively — **Bizreq owns the scenarios, Data owns the data**. Each `SCEN-NN` is a concrete
input paired with the behavior a correct implementation must produce. These become the **golden set**
at Build: `/sprd-evals` turns them into a versioned `golden-set.yaml` next to the spec (required for
`llm_powered` channels), so the same scenarios that framed intent gate the behavior.

Write each expected behavior so a grader can judge it — observable, not vague. Cover the happy path,
the negative path, and the ambiguous / missing-input path (where the system must **ask, not guess**).

---

| Scenario | Input                              | Expected behavior                                      |
|----------|------------------------------------|--------------------------------------------------------|
| SCEN-01  | [a representative happy-path input] | [the correct, observable outcome]                     |
| SCEN-02  | [a negative / out-of-scope input]   | [declines / handles gracefully — the observable outcome] |
| SCEN-03  | [an ambiguous / missing-input case] | [asks for what's missing; does **not** guess]         |

*Add one row per scenario. Each row should map to at least one business rule (`BR-NN`) or acceptance
check, so the golden set stays traceable to intent.*
