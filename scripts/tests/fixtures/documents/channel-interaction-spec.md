# Channel Interaction Spec
<!-- Phase 2 — Design | Optional artifact -->

> The contract that turns a channel's **acceptance dimensions** into the spec's **acceptance checks**.
> The traceability chain is **`<channel>` descriptor dimension → interaction-spec contract → acceptance
> check on the spec**: each `acceptance_dimension` in `channels/<channel>.yaml` drives one contract row,
> and `/sprd-channel` injects that row into the spec's existing `## Acceptance Checks` (graded by the
> unchanged core). For an `ag-ui` channel, this table **is** the AG-UI event contract — Design
> co-authors it with Engineering. Owned by Design.

## Spec identity

**Channel:** `ag-ui`
**Descriptor:** `channels/ag-ui.yaml`
**Persona:** Claimant checking on an open auto claim
**Traces to:** FE-03 · Claim status lookup

---

## The contract

One row per acceptance dimension in the channel descriptor. The contract states the concrete behavior;
the acceptance check is the line that lands in the spec (and that the grader walks one at a time).

| `ag-ui` descriptor dimension | Interaction-spec contract | → Acceptance check on the spec |
|------------------------------|---------------------------|-------------------------------|
| streaming-feedback | Status text streams in as it arrives; a spinner shows until the first token | "A spinner is visible within 200 ms and is replaced by status text within 3 s" · NFR-04 |
| confidence-display | Results below 0.80 confidence show a "needs review" chip | "A result at confidence 0.79 renders the 'needs review' chip; at 0.80 it does not" |
| accessibility | Every control reachable by keyboard in reading order | "Tab order visits sign-in, claim list and status detail in that order, with no keyboard trap" · NFR-07 |

*Cover every `acceptance_dimension` in the descriptor. `check_channel.py` advises (never blocks) if one
is uncovered.*

---

## AG-UI event contract (`ag-ui` channels only)

*Delete this section unless the channel is `ag-ui`. Here the interaction spec is the Design↔Engineering
event contract — the descriptor made concrete.*

| AG-UI aspect | Contract |
|--------------|----------|
| Events consumed | `RUN_STARTED`, streamed `TEXT`, `STATE_DELTA`, `RUN_FINISHED` |
| Confidence | Shown as a chip beside each result; results below 0.80 are gated behind a review click |
| PII | Claimant name masked to first initial and surname; policy number to last four digits |
| States | Skeleton while loading, "No open claims" when empty, retry control on error |
| Accessibility | Full keyboard path, 4.5:1 contrast, ARIA live region for status changes (NFR-07) |
| HITL | none, the status lookup is read-only |

---

## Notes

- Each contract row becomes an ordinary **Acceptance Check** once `/sprd-channel` injects it — nothing
  downstream knows it came from a channel.
- Write each check to pass the existing **vague-line** lint (concrete, observable, testable).
- Measurable dimensions (latency, load) cite the matching **NFR** in `non-functional-requirements.md`.
