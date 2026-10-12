# Feature Brief — <FE-NN>: [Feature title]   (epic: <EP-NAME>)
<!-- Phase 1 — Requirements | Optional artifact -->

A feature brief decomposes one epic into a coherent slice of user value, the **channels** it is
delivered through, and the **specs** that build it (one channel per spec; shared logic is
channel-agnostic). It sits **below** the epic — it reads `epics.md` and fans an epic into features +
specs. It does not replace the epic or the stories. Authored on every channel-bound feature; optional,
so gates never demand it.

Each `##` section below is **discipline-owned**. An unfilled section is an advisory flag; formal
acceptance happens at the Phase-1 gate, where each discipline signs its section (captured in
`.sdlc/state.yaml`).

---

## Outcome — owner: Bizreq · signs at gate

[The business result this feature moves. Traces to <N-NN>, <FR-NNN>.]

## Feature — owner: Product · signs at gate

[One coherent slice of user value, described end to end. Realizes <FE-NN> under <EP-NAME>
(story <US-NNN>).]

## Channels × personas — owner: Product + Design · signs at gate

[List each (channel × persona) this feature reaches — the narrative kept alongside the Spec
decomposition table below. Shared "brain" logic that no surface owns is channel-agnostic and uses `—`.]

- <channel> × [persona] — [what this surface does for this persona]

## Per-channel experience — owner: Design · signs at gate

[Per channel, the shape of the experience at a glance — the turn or flow, the confirmation, the
fallback. The detailed craft (journeys, layout, interaction spec) is authored in Phase 2 via
`/sprd-experience`.]

- <channel>/[persona]: [entry → … → confirm → fallback, at a glance]

## Data touchpoints — owner: Data · signs at gate

[The records, sources, and reads/writes this feature depends on. Call out any **PII** — it is a
risk-tier driver. Detailed contracts are authored in Phase 2 via `/sprd-data`.]

## Spec decomposition — owner: Product · one channel per spec

The agent **proposes** the decomposition and tiers; a **named human confirms** them — it never assigns
risk. **One channel per spec.** Channel-agnostic rows — the shared "brain" the surfaces build on — are
first-class and use `—` for both channel and persona.

| Spec name          | Channel   | Persona   | Proposed risk         | Traces to |
|--------------------|-----------|-----------|-----------------------|-----------|
| [reasoning-core]   | —         | —         | [HIGH / MEDIUM / LOW] | <FR-NNN>  |
| [surface-name]     | <channel> | [persona] | [HIGH / MEDIUM / LOW] | <US-NNN>  |

*Add one row per spec. Brains tend HIGH; in-pattern read-only surfaces can be MEDIUM. The chain closes
on each spec's existing `source:` field (FR → EP → feature-brief → US → spec).*
