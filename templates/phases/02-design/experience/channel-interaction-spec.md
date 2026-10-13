# Channel Interaction Spec
<!-- Phase 2 — Design | Optional artifact -->

> The contract that turns a channel's **acceptance dimensions** into the spec's **acceptance checks**.
> The traceability chain is **`<channel>` descriptor dimension → interaction-spec contract → acceptance
> check on the spec**: each `acceptance_dimension` in `channels/<channel>.yaml` drives one contract row,
> and `/sprd-channel` injects that row into the spec's existing `## Acceptance Checks` (graded by the
> unchanged core). For an `ag-ui` channel, this table **is** the AG-UI event contract — Design
> co-authors it with Engineering. Owned by Design.

## Spec identity

**Channel:** `<channel>`  <!-- ag-ui / voice / chat -->
**Descriptor:** `channels/<channel>.yaml`
**Persona:** [who uses this surface]
**Traces to:** [FE-NN feature-brief row · spec name]

---

## The contract

One row per acceptance dimension in the channel descriptor. The contract states the concrete behavior;
the acceptance check is the line that lands in the spec (and that the grader walks one at a time).

| `<channel>` descriptor dimension | Interaction-spec contract | → Acceptance check on the spec |
|----------------------------------|---------------------------|-------------------------------|
| [dimension id, e.g. turn-taking] | [the concrete behavior for this surface] | ["<the graded check>" · NFR-NN if measurable] |
| [...] | [...] | [...] |
| [...] | [...] | [...] |

*Cover every `acceptance_dimension` in the descriptor. `check_channel.py` advises (never blocks) if one
is uncovered.*

---

## AG-UI event contract (`ag-ui` channels only)

*Delete this section unless the channel is `ag-ui`. Here the interaction spec is the Design↔Engineering
event contract — the descriptor made concrete.*

| AG-UI aspect | Contract |
|--------------|----------|
| Events consumed | [e.g. `RUN_STARTED`, streamed `TEXT`, `STATE_DELTA`, `RUN_FINISHED`] |
| Confidence | [how each result's confidence is shown / gated] |
| PII | [what is masked in the view] |
| States | [loading / empty / error rendering] |
| Accessibility | [keyboard path, contrast, ARIA — cite the a11y NFR] |
| HITL | [the approval round-trip, or `none` for a read-only surface] |

---

## Notes

- Each contract row becomes an ordinary **Acceptance Check** once `/sprd-channel` injects it — nothing
  downstream knows it came from a channel.
- Write each check to pass the existing **vague-line** lint (concrete, observable, testable).
- Measurable dimensions (latency, load) cite the matching **NFR** in `non-functional-requirements.md`.
