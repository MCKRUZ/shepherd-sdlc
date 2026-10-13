# Context Tiers Reference

The SDLC plugin uses a 3-tier context architecture to manage token budget across phases. Each tier has a different loading strategy and token budget.

## Architecture

| Tier | Name | When Loaded | Token Budget | Source |
|------|------|-------------|-------------|--------|
| 1 | Foundation | Always (session start) | ~500 tokens | state.yaml + profile.yaml + constitution.md |
| 1.5 | Intake Index | Session start (when available) | ~5K tokens (configurable) | `.sdlc/context/intake/index.md` |
| 2 | Phase Layers (living summaries) | Session start (recent 3) | ~2K per layer | `.sdlc/context/layers/` |
| 3 | Reference | On-demand | Unbounded | `references/` directory in plugin |

## Tier 1: Foundation (Always Loaded)

Loaded automatically by the session-start hook. Contains:

- **Project identity:** name, profile ID, current phase
- **Phase status:** artifact count, completion state
- **Constitution extract:** first ~375 words of `.sdlc/constitution.md` (mission, principles, constraints)

The foundation provides enough context for Claude to orient itself in the project without loading any phase-specific detail.

**Source files:**
- `.sdlc/state.yaml`
- `.sdlc/profile.yaml`
- `.sdlc/constitution.md`

## Tier 1.5: Intake Index (Opt-In)

Loaded automatically by the session-start hook when `.sdlc/context/intake/index.md` exists. Contains a condensed document corpus index generated during Phase 0 Document Intake.

- **Document ID table:** DOC-NNN | filename | 1-line description
- **Topic clusters:** Grouped keywords for quick relevance assessment
- **Budget:** Configured via `documentation.index_budget_tokens` in profile (default 5000 tokens)

This tier exists only when document intake was performed during Phase 0. Projects without external documentation never see this tier.

**Per-document summaries** are NOT loaded at session start. They live in `.sdlc/context/intake/DOC-NNN-*.md` and are read on-demand when Claude needs detail about a specific source document.

**Source files:**
- `.sdlc/context/intake/index.md` (auto-loaded)
- `.sdlc/context/intake/catalog.json` (metadata, not loaded)
- `.sdlc/context/intake/DOC-NNN-*.md` (on-demand)

## Tier 2: Phase Layers (Per-Phase, living — regenerated when their sources change)

Loaded automatically by the session-start hook for the **most recent 3 completed phases**. Contains condensed phase summaries with locked metrics, constraints, and key decisions.

**Why only 3?** With 9 phases and ~2K tokens per layer, loading all completed layers could consume ~18K tokens. Capping at 3 keeps Tier 2 under ~6K tokens while providing the most relevant context.

**"Most recent" means by lifecycle order, not lexical filename sort.** Layer files are named `phase{id}-{name}.md` where `{id}` is the phase id, which may be non-numeric (`phasebuild-build.md`, `phaseclose-close.md`). Recency is resolved against the registry `order` (`0 → 1 → 2 → 3 → build → 7 → 8 → 9 → close`), so a lexical sort of filenames would order them wrong.

**Loading order:** Most recent 3 completed phases by lifecycle order, loaded oldest-first.

**To access older layers:** Read them on-demand from `.sdlc/context/layers/` — they exist on disk, just aren't auto-loaded.

**Source files:**
- `.sdlc/context/layers/phase{id}-{name}.md`

## Tier 3: Reference (On-Demand)

Not loaded at session start. Claude reads reference docs from the plugin's `references/` directory when specific guidance is needed (e.g., validation rules, compliance frameworks, agent roster).

This is the existing behavior — no change needed. The tier designation formalizes what was already implicit.

**Source files:**
- `references/*.md` in the plugin directory

## Loading Precedence

```
Session Start:
  1.  Foundation (always)           → ~500 tokens
  1.5 Intake Index (if available)   → ~5K tokens (configurable)
  2.  Frozen Layers (recent 3)      → ~6K tokens max
                                      ─────────────
                                      ~11.5K total auto-loaded (max with intake)
                                      ~6.5K total auto-loaded (without intake)

During Work:
  3. References (on-demand)         → loaded as needed
```

## Hook Implementation

The session-start hook (`hooks/shepherd-session-start.ps1`) implements Tier 1+2 loading. Output is tagged:

- `[SHEPHERD-CONTEXT:FOUNDATION]` — Tier 1 content
- `[SHEPHERD-CONTEXT:LAYERS]` — Tier 2 summary
- `[SHEPHERD-CONTEXT:LAYER:{name}]` — Individual layer content

These tags allow Claude to identify the source tier of any context in its prompt.
