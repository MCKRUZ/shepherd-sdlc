# Channel Model — the customer surface a capability is delivered through

A **channel** is the customer surface a capability is delivered through — a web AG-UI console, a
voice line, a chat thread. It is the *front door*, not the *brains*. The same business logic behind a
different door is a different product, because each surface carries its own **acceptance dimensions**:
a price *shown* in a web app with a click-to-approve is not the same deliverable as a price *spoken*
over a phone with no screen. Voice needs barge-in, latency, and readback; web needs a confidence
display, an approval affordance, and accessibility; chat needs threading and quoted-content safety.
None of those have anything to do with the core logic — they belong to the channel.

This is the conceptual reference for the `channels/` library. The library itself (schema, template,
starters, and how to add one) is documented in `channels/README.md`; this document explains what a
channel *is*, when it enters the lifecycle, how it binds to a spec, and the **recommended
`evaluation_criteria`** a team can adopt into its own profile.

---

## Where channels come from

A channel is **sensed in Discovery** and **formalized in Requirements during featuring**.

- **Sensed in Discovery (Phase 0).** The persona and current-state work reveals the surfaces a
  capability will be delivered through — a phone line, a dashboard, an in-app chat. At this stage a
  channel is an observation, not yet a descriptor-bound thing.
- **Formalized in featuring (Phase 1).** Featuring — the epic → **feature** → spec decomposition run by
  `/sprd-feature` — is where you decide *how* the feature is delivered, so it is where a sensed surface
  becomes a descriptor-bound **channel**. The feature brief's decomposition table carries a **channel**
  column, and each channel names a `channels/<id>.yaml` descriptor.

The rigor a channel adds does not appear as a new phase or a new gate. It rides the existing spec: the
descriptor's acceptance dimensions become ordinary lines in the spec's `## Acceptance Checks`, which the
existing grader already walks. Everything is additive — no protected-core script reads `channels/`.

---

## One channel per spec

**A spec has at most one channel.** A feature delivered on N surfaces decomposes into per-surface specs
plus **channel-agnostic** shared-logic specs (the "brains" the surfaces build on). This preserves the
Build-loop invariant *one spec = one branch = one PR*, and it naturally yields a **risk-tier mix**:
the channel-agnostic brains tend to land HIGH (they hold the consequential logic), while an in-pattern,
read-only surface can be MEDIUM.

Channel-agnostic specs are **first-class**. A spec with no channel (`channel:` blank, or an explicit
`—`) is the shared brain — it is not an omission to be flagged. `check_channel.py` only advises on specs
that *declare* a channel.

---

## Persona lives in the experience layer

**Persona is not a spec field.** Personas are first-class in the *experience layer* — journeys,
surface layouts, and channel descriptors are all (channel × persona)-aware, and the feature brief's
decomposition table carries a **persona** column alongside the channel column. But the only channel
fact that lands on a spec is the `channel:` line. The persona rides in the experience notes the spec
references (via `source:`), never as spec frontmatter. Channel binds; persona is carried.

---

## The descriptor schema (at a glance)

Each `channels/<id>.yaml` is validated against `channels/_schema.yaml` by `validate_channel.py`. The
fields:

| Field | Required | What it is |
|-------|:--:|------------|
| `id` | yes | Kebab-case identifier; matches the filename (`channels/<id>.yaml`). |
| `name` | yes | Human-readable channel name. |
| `surface` | yes | What the customer touches (e.g. "PSTN/CCaaS voice", "browser SPA via AG-UI events"). |
| `llm_powered` | yes | True when the deliverable on this channel is model-driven. When true, `eval_hooks` is required and the risk floor is HIGH. |
| `acceptance_dimensions` | yes | The dimensions a channel-bound spec must satisfy — each an `{id, intent, example_check}`. These are the load-bearing part: `/sprd-channel` injects them into the spec's `## Acceptance Checks`. |
| `status` | no | `stable` or `experimental` (defaults to experimental). |
| `risk_floor` | no | Advisory minimum risk tier (`HIGH`/`MEDIUM`/`LOW`). May only **raise**, never lower, the tier `risk_model.py` assigns. |
| `harness_context_seed` | no | A canonical existing-pattern phrase a first-of-its-kind channel spec can cite to satisfy the spec DoR's `harness_context` requirement. |
| `interaction_contract` | no | Prose — the turn / round-trip model and where a named human decides (HITL). |
| `discipline_touchpoints` | no | Who owns what on the channel (design / data / bizreq / engineering). |
| `observability_signals` | no | Channel-specific **outcome** signals for monitoring — never vanity metrics. |
| `eval_hooks` | when `llm_powered` | Which dimensions become golden-set cases; points at `harness/skills/eval-builder` + the golden-set template. Required (non-empty) when `llm_powered: true`. |

---

## The spec binding + the advisory check

- **`channel:`** — one optional frontmatter line on `templates/phases/build/spec.md`. It is
  backward-compatible: `parse_frontmatter` ignores unknown keys, so existing channel-less specs are
  unaffected. Blank (or `—`) means channel-agnostic.
- **`check_channel.py`** — a *separate* advisory script (exit 0 always, SHOULD-only). When a spec sets
  `channel: X`, it flags any of channel X's acceptance dimensions not covered in `## Acceptance Checks`.
  It runs *beside* `check_spec.py`, never inside it; `check_spec.py` is byte-for-byte unmodified and the
  channel check can never change a ready / not-ready verdict.

Where the rigor lands: channel dimensions become ordinary lines in `## Acceptance Checks` (graded by
the existing grader), plus the documented `evaluation_criteria` below (advisory G6 REVIEW items, emitted
`passed=None`). For `llm_powered` channels the descriptor's `eval_hooks` route to the existing golden-set
+ `eval-regression.yml` rail — **evals are required, not optional**, for LLM-powered channels.

---

## Recommended `evaluation_criteria`

The plugin ships **no profile edits**. Instead, this is a documented general set of qualitative
`evaluation_criteria` a team can **append to its own profile** (`profiles/<id>/profile.yaml`, under
`quality.evaluation_criteria`). These items are read by the existing gate/section-evaluation machinery
(`check_gates.py`, `section-evaluator`) and validated by `profiles/_schema.yaml` — each is an object with
`name`, `description`, an optional `severity` (`fail` = blocking, `warn` = advisory; default `warn`), and
an optional `phases` array keyed by phase id (`0, 1, 2, 3, build, 7, 8, 9, close`; omitted defaults to
`[build]`).

**All shipped defaults are `warn` (advisory).** This is deliberate and faithful to the IDD One Rule:
these are pure judgment items — the machine reports, a named human decides, so they surface as advisory
G6 REVIEW items (`passed=None`) rather than blocking a gate. The hard requirement for `llm_powered`
channels (that evals exist and pass) is enforced mechanically on the **eval-regression rail**, not by a
profile criterion. A team **MAY** promote a specific criterion to `severity: fail` in its own profile if
it wants that criterion to block; the natural candidates are called out below.

Append this block under `quality.evaluation_criteria` (match your profile's existing indentation):

```yaml
  evaluation_criteria:
    # --- Channel layer (append to your own profile; all advisory by default) ---
    - name: "Channel binding present"
      phases: ["build"]
      description: "A spec that names a customer surface declares channel: <id> matching a channels/<id>.yaml descriptor, and its ## Acceptance Checks cover that channel's acceptance dimensions. A surface spec left channel-agnostic (blank / —) when it clearly targets one surface is a miss; a shared-logic brain spec is correctly channel-agnostic."
      severity: warn
    - name: "Interaction contract per touchpoint"
      phases: [2]
      description: "Each channel touchpoint has a channel-interaction-spec row mapping a descriptor acceptance dimension to a concrete interaction contract to an acceptance check (dimension to contract to check). A touchpoint described only as 'handles the conversation' with no per-turn / per-event contract fails."
      severity: warn
    - name: "Channel fallback and accessibility"
      phases: [2, "build"]
      description: "Conversational channels specify a human-fallback path reachable at every turn; visual channels specify accessibility (keyboard path, contrast, ARIA / WCAG). A voice or chat spec with no escalation path, or a web surface with no a11y acceptance check, fails."
      severity: warn
    - name: "Agentic spec carries evals"                # candidate to raise to fail
      phases: ["build"]
      description: "A spec on an llm_powered channel references a versioned golden set (eval-datasets/specs/<feature>/golden-set.yaml) and points its Checking Plan at the eval-regression rail. An LLM-powered surface spec with no golden set fails — evals ARE its acceptance criteria."
      severity: warn
    - name: "Data contract for data-bearing specs"
      phases: [1, 2]
      description: "A spec that reads or writes customer data traces to a data-contract.md with each field typed, sourced, and PII-classified; PII presence is reflected in the risk tier. A data-bearing spec with an unclassified field, or PII that did not drive the tier, fails."
      severity: warn
    - name: "Model output treated as untrusted"        # candidate to raise to fail
      phases: [2, "build"]
      description: "On llm_powered channels, model output and upstream/quoted content are treated as untrusted input: agent-emitted UI is rendered as data (never executed), and injected instructions cannot drive a consequential action. Covered by an explicit acceptance check and an eval golden-set case. A generative surface that executes model-emitted markup, or has no injection-resistance case, fails."
      severity: warn
```

These six are drawn from the channel model (interaction contract, fallback/accessibility, untrusted
output) and the discipline seats (channel binding, evals, data contract). They are the qualitative
overlay; the mechanical rigor still lands on the spec's `## Acceptance Checks` and the eval rail.

---

## Golden-set path convention

For `llm_powered` channels the acceptance criteria are a **versioned golden set** authored by the
existing harness eval-builder (wrapped by `/sprd-evals` — the plugin adds no new eval script). The path
convention is:

```
eval-datasets/specs/<feature>/golden-set.yaml
```

- **One golden set per feature/spec**, versioned in-repo next to the spec it grades.
- `<feature>` is the spec's slug (e.g. `voice-call-handling`), so the set sits with the change it covers.
- The spec's **Checking Plan** references this path for any `llm_powered`-channel spec; the
  `eval-regression.yml` rail fires on any prompt/model change and **blocks** on degradation like a
  failing test.
- **Bizreq owns the scenarios, Data owns the data** — the set is authored collaboratively via
  `/sprd-evals`, and neither discipline touches CI YAML (the harness owns the rail).

The path lives in the eval-builder SKILL, not hardcoded by the channel layer; this document records the
convention so specs and reviews can cite it consistently.
