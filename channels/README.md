# Channels — the customer-surface library

The authoritative library of **channel descriptors** for the plugin. A **channel** is the customer
surface a capability is delivered through — a web AG-UI console, a voice line, a chat thread — *not*
the logic behind it. The same business logic on a different channel is a different product, because
each surface carries its own **acceptance dimensions** (voice needs barge-in + readback; web needs
confidence display + approval; chat needs threading + quoted-content safety).

Descriptors are **inert data**: read only by `scripts/validate_channel.py`, `scripts/check_channel.py`,
and the discipline commands/agents. No gate or spec-core script reads `channels/` — adding or editing
a descriptor changes no protected code path.

## How to Read This Directory

| File | What it is |
|------|------------|
| `_schema.yaml` | The descriptor schema (validated by `validate_channel.py`). |
| `_template.yaml` | A commented blank descriptor — copy it to add a channel. |
| `ag-ui.yaml` | Agentic web UI (AG-UI protocol) — generic starter. |
| `voice.yaml` | Voice / spoken conversational (transport-agnostic) — generic starter. |
| `chat.yaml` | Text conversational — generic starter. |

Underscore-prefixed files (`_schema`, `_template`) are skipped by the validator and loader.

## A descriptor in one glance

Each `channels/<id>.yaml` declares: `id`, `name`, `surface`, `llm_powered`, an advisory `risk_floor`
(may only *raise* a spec's tier, never lower it), a `harness_context_seed`, an `interaction_contract`,
a list of `acceptance_dimensions` (each with an `id`, an `intent`, and a concrete `example_check`),
`discipline_touchpoints`, `observability_signals`, and — for `llm_powered` channels — `eval_hooks`.

The **`acceptance_dimensions`** are load-bearing: `/sprd-channel` injects them into a spec's existing
`## Acceptance Checks`, and `check_channel.py` advises (never blocks) when a channel-bound spec is
missing one.

## Adding or renaming a channel

1. `cp channels/_template.yaml channels/<id>.yaml` and fill it in (keep it general — no product names).
2. `uv run --project scripts scripts/validate_channel.py channels/<id>.yaml` until it reports `PASS`.
3. Reference it from a spec via the optional `channel:` frontmatter field.

The library is **owned by the team** — at engagement close the client owns and can safely extend it,
because the schema + validator guard every descriptor.
