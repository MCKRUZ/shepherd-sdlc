# SDLC Studio Command Center — visual direction (binding)

Written 2026-10-06 for the master plan (`togo-command-center.md` §3–§4, §7) from the brief's five screens, the current app (`observatory-v10-*` shots), `studio/src/theme/{tokens,dark,type,base}.css`, `studio/src/ui/*`, and the brand (`docs/brand/togo/brandbook.html`, `palette.json`). Every value here is a hex or a px. **P0 adds exactly the tokens in §2–§3 (no more, no fewer); every other package reads them by name and invents no colour, size, or motion of its own.** Where this document and a package's taste disagree, this document wins; where this document and the plugin's facts disagree, the plugin wins and the element shows "no data".

## 1. The look

A precision instrument for a delivery team. Dark-first observatory — a deep blue-black ground (`surface-0` #0b1120), cards lit by a rim rather than a shadow, one teal accent that means "where you are / what is yours" and nothing else — with an equally finished light theme that is the same instrument in daylight (paper #f8fafc, white cards, hairlines). The Depth gradient appears at **exactly two places** in the command center: the steering-mode title lockup and the one-time "What moved where" overlay card (both ≥ 48 px, both heroes, brand §2); everything else is the flat mark. Rhythm is generous: 24 px around every screen (`p-6`, an e2e pin), 12 px between lanes, 8 px between cards, 48 px before a new section. Type is built for scanning: Inter for UI with a display cut (650, −0.02 em) for the sprint title and the lane counts, JetBrains Mono for every id, date and path, and tabular numerals wherever a number sits (already global in `base.css`). Colour is never the only signal and never SDLC Studio's opinion: a chip is tinted only by a plugin field, a wait is amber only when the plugin's number says so, and "no data" is two words in `ink-3`, never a grey zero. Four lanes are four shallow wells on the ground; the cards are the bright things; the Today column is the one place the accent wash is allowed to pool.

## 2. Colour system — the tokens P0 adds

Rules: (a) every row below is a `--color-*` custom property on `:root` in `tokens.css`, restated inside the **first** `[data-theme="dark"] {` block of `dark.css` (`tokenContrast.test` reads only the first block), and mapped once in `@theme inline reference` as `--color-X: var(--color-X);` so `bg-X` / `text-X` / `border-X` / `ring-X` / `fill-X` / `stroke-X` exist; (b) an "alias" row is written as `var(--color-<existing>)` in **both** files so it follows the existing token if that is ever retuned; (c) no token here may be named like a `--text-*` token in §3 (Tailwind resolves `text-<name>` against colours first — the `Eyebrow.tsx` lesson); (d) no new gradient, no new shadow, no `--color-*` for Depth.

| Token (`--color-…`) | Light | Dark | Means / where it may be used |
|---|---|---|---|
| `lane` | `#efeae1` | `#1c1915` | the four lane wells and the planning backlog column ground |
| `lane-header` | `#e9e3d9` | `#25211c` | the sticky lane header band (paints opaque when stuck) |
| `lane-line` | `#d9d1c4` | `#2e2923` | the hairline under a lane header and between lane and ground |
| `card-lit` | `#4f8545` (accent-500) | `#6fa55f` (accent-500) | the 1 px edge a card gains when "In the room" lights a person; also the `data-lit` edge on a Refining row |
| `baton` | `#3f6b35` (accent-600) | `#6fa55f` (accent-500) | the baton glyph body and its slide trail (2 px) |
| `baton-bg` | `#e3eddd` (accent-100) | `#243f20` (accent-100) | the baton's resting slot on the Building→Checking edge |
| `baton-ink` | `#3f6b35` | `#9dc58e` | the "0006 → Sam · 2 business days" text on `baton-bg` |
| `you-ring` | `#3f6b35` | `#9dc58e` | the 2 px ring (after a 2 px `surface-1` gap) on the signed-in person's initials, nowhere else |
| `strip-lit` | `#15803d` (stage-signed-ink) | `#34d399` | the strip's lit rail = signed-off count (same fact as the Spine; light takes the signed INK step — the fill is 2.88:1 on the sand canvas) |
| `strip-unlit` | alias `line-2` | alias | the rail beyond the last signed station |
| `strip-viewing` | alias `stage-current-fill` | alias | the ring on the station carrying `data-viewing`; the current station's pulse |
| `today-act-bg` / `-ink` / `-line` | alias `stage-current-bg/-ink/-line` | alias | "needs you" items (the accent wash) — only an item in `needsYou[]` |
| `today-wait-bg` / `-ink` / `-line` | alias `status-warn-bg/-ink/-line` | alias | a measured wait: `since_business_days > 1` or `over_alarm:true`, never otherwise |
| `today-late-bg` / `-ink` / `-line` | alias `status-error-bg/-ink/-line` | alias | the plugin's `overdue:true` on a decision; a refusal (exit 2) |
| `plan-backlog` | alias `lane` | alias | planning left column ground |
| `plan-slate` | alias `surface-1` | alias | planning middle column — the commitment is the brightest surface |
| `plan-says` | `#f3f7f0` (accent-50) | `#192d17` (accent-50) | planning right column — the plugin's own voice wears the lightest accent wash |
| `plan-says-line` | `#c7e0bc` (accent-200) | `#2f5229` (accent-200) | its hairline |
| `rung-pass` | alias `status-ok-fill` | alias | a rung whose host conclusion is success |
| `rung-fail` | alias `status-error-fill` | alias | a rung whose host conclusion is failure (carries `waiting_on` as its reason) |
| `rung-pending` | `#0369a1` (status-running-ink) | `#38bdf8` (status-running-fill) | pending / queued / in progress from the host (light uses the ink step: the fill is 2.77:1 on white) |
| `rung-none` | alias `ink-4` | alias | a hollow ring beside the words "no data" — the correctness rung is always this |
| `rung-rail` | alias `line-2` | alias | the ladder's vertical rail |
| `ledger-open-bg` / `-ink` | alias `status-warn-bg/-ink` | alias | disposition OPEN (open debt) |
| `ledger-fixed-bg` / `-ink` | alias `status-ok-bg/-ink` | alias | FIXED, verified against a changed file |
| `ledger-split-bg` / `-ink` | alias `stage-current-bg/-ink` | alias | SPLIT (alive elsewhere, with id + owner) |
| `ledger-accepted-bg` / `-ink` | alias `stage-signed-bg/-ink` | alias | ACCEPTED_RISK signed by a person |
| `ledger-postponed-bg` / `-ink` | alias `stage-later-bg/-ink` | alias | POSTPONED |
| `ledger-offbooks` | alias `status-error-fill` | alias | a 1 px outline + the words "off the books" when the plugin says `off_books:true` — the chip keeps its disposition colour |
| `steer-bg` | `#ffffff` | `#0e0c0a` | steering mode's ground (one step beyond `surface-0` so the room goes dark) |
| `steer-tile` | `#f5efe4` | `#1c1915` | a steering tile |
| `steer-tile-line` | alias `line-1` | alias | its hairline |
| `steer-number-ink` | alias `ink-1` | alias | the number |
| `steer-label-ink` | alias `ink-2` | alias | the measure's name — `ink-2`, not `ink-3`, because the screen is read from across a room |
| `steer-nodata-ink` | alias `ink-3` | alias | the words "no data" at 24 px |

Cards keep the existing tokens and gain no new ones: surface `surface-1`, raised/popover `surface-raised`, hover edge `line-2` (`Card interactive`), focus `--ring`. The TopBand and the strip sit on `surface-0` with a `line-1` hairline below. Risk chips keep `CHIP_TONE` (`HIGH` = `error`, `MEDIUM` = `warn`, `LOW` = `neutral`) and status words keep the `spec-*` tones.

**Contrast, measured** — re-measured 2026-10-12 for the Shepherd palette (Furrow); the Tōgō figures live in git history (WCAG 2.x, the `tokenContrast.test` formula; script in the scratchpad `cc-contrast.mjs`; text floor 4.5:1, UI floor 3:1):

| Pair | Light | Dark | Floor |
|---|---|---|---|
| `ink-1` on `lane` | #1c1915/#efeae1 **14.61** | #f5efe4/#1c1915 **15.30** | 4.5 |
| `ink-2` on `lane` | 9.91 | 11.56 | 4.5 |
| `ink-3` on `lane` | #6b625a/#efeae1 **4.98** | #a69d94/#1c1915 **6.56** | 4.5 |
| `ink-3` (eyebrow) on `lane-header` | #6b625a/#e9e3d9 **4.67** | #a69d94/#25211c **6.00** | 4.5 |
| `ink-1` on `lane-header` | 13.72 | 13.98 | 4.5 |
| `accent-text` on `lane` | #3f6b35/#efeae1 **5.21** | #9dc58e/#1c1915 **9.01** | 4.5 |
| `card-lit` on `surface-1` / on `lane` | 4.40 / 3.67 | 6.02 / 6.02 | 3 |
| `baton` on `lane` / on `surface-1` | 5.21 / 6.24 | 6.02 / 6.02 | 3 |
| `baton-ink` on `baton-bg` | #3f6b35/#e3eddd **5.18** | #9dc58e/#243f20 **5.98** | 4.5 |
| `you-ring` on `surface-1` / `lane` / `surface-raised` | 6.24 / 5.21 / 6.24 | 9.01 / 9.01 / 7.42 | 3 |
| `strip-lit` on `surface-0` | #15803d/#f5efe4 **4.38** | #34d399/#14120f **9.73** | 3 |
| `strip-viewing` on `surface-0` | 5.45 | 9.63 | 3 |
| `today-act-ink` on `today-act-bg` | #3f6b35/#f3f7f0 **5.76** | #9dc58e/#243f20 **5.98** | 4.5 |
| `today-wait-ink` on `-bg` · `today-late-ink` on `-bg` | 4.84 · 5.91 | 11.23 · 9.32 | 4.5 |
| `ink-2` / `ink-3` / `accent-text` on `plan-says` | 10.95 / 5.50 / 5.76 | 9.70 / 5.51 / 7.56 | 4.5 |
| `rung-pass` / `rung-fail` / `rung-pending` on `surface-1` | 3.30 / 4.83 / 5.93 | 10.05 / 6.33 / 8.17 | 3 |
| `ledger-postponed-ink` on `-bg` (the tightest chip) | #6b625a/#f5efe4 **5.21** | #a69d94/#1c1915 **6.56** | 4.5 |
| `ledger-fixed/-accepted-ink` on `-bg` | 4.79 | 10.96 | 4.5 |
| `ink-1` / `ink-2` on `steer-bg` | 17.51 / 11.87 | 17.06 / 12.89 | 4.5 |
| `ink-1` / `ink-2` / `ink-3` on `steer-tile` | 15.30 / 10.37 / 5.21 | 15.30 / 11.56 / 6.56 | 4.5 |
| Figure tones `accent-500` on `accent-200` (decoration, `aria-hidden`) | 3.10 — not text | 3.06 | — |
Every text pair ≥ 4.5:1 and every UI pair ≥ 3:1 in both themes. `rung-none` (`ink-4`) is 2.67:1 on purpose: it is decoration beside the words "no data". P0 adds the pairs with a hex in the first column to `PAIRS` in `tokenContrast.test.ts`.

## 3. Type scale additions (`type.css`, inside the existing `@theme`)

| Token | Size / line / tracking / weight | Face | Where |
|---|---|---|---|
| `--text-sprint-title` | 32 px / 36 px / −0.02 em / 650 | Inter | the sprint header: "S08 — Adjusters file without a phone call" (the id's digits tabular) |
| `--text-lane-count` | 20 px / 24 px / −0.01 em / 600 | Inter, tabular | the numeral in a lane header ("3", "2 of 4") and the needs-you chip count |
| `--text-metric` | 26 px / 30 px / −0.015 em / 600 | Inter, tabular | How-it-is-going tiles on the sprint home; the close screen's Outcomes |
| `--text-ident` | 13 px / 16 px / +0.01 em / 500 | JetBrains Mono | spec ids on cards and rows, `DL-NN`, sprint ids in facts lines, dates, paths, branch names |
| `--text-steer-number` | 56 px / 60 px / −0.025 em / 650 | Inter, tabular | the number on a steering tile |
| `--text-steer-label` | 24 px / 32 px / 0 / 500 | Inter | every other word in steering mode (measure name, unit, "no data", provenance) |

Nothing on a steering screen is set below `--text-steer-label` except the provenance line, which may be 20 px / 28 px / 450. Existing tokens keep their roles: `--text-eyebrow` for lane labels and section labels, `--text-code` for `<pre>`, `--text-xl` for a screen's h2, `--text-display` stays the Welcome hero's.

## 4. Spacing and layout

**Grid**: 4 px base; the rhythm 2 · 4 · 8 · 12 · 16 · 24 · 32 · 48. Radii: cards `--radius-2` (10), panels `--radius-3` (14), the omnibar panel and the spec card `--radius-4` (20), chips `--radius-pill`. Shadows: the kit's two only — `--shadow-1` on a hovered card, `--shadow-3` on the omnibar and the spec card panel; dark renders both as rim light.

**Shell** (every screen): TopBand **48 px** (padding-x 16; flat mark 24 + project name 15/20 600 as one button; omnibar trigger h-32, width `clamp(320px, 36vw, 560px)`, `surface-2` field with `line-2` edge and `ink-3` placeholder text; needs-you chip h-24 `today-act-*`; SyncChip; overflow 32×32) · LifecycleStrip **64 px** (padding-x 24; nine stations on `stationU` spacing; station ring Ø 14 at 1.5 px, viewing ring Ø 18 at 2 px; rail 2 px lit / 1 px unlit; short label 11 px eyebrow 6 px below each station; the Build station's label 12/16 500 "Build Loop · S08 · 8th sprint"; hairline `line-1` below) · `<main>` padding **24**.

**Sprint home** (`grid-template-columns: repeat(4, minmax(220px, 1fr)) 320px`, column-gap 12 between lanes and 24 before Today, row-gap 24):
- Header block ≈ 112 px: title in `--text-sprint-title`; facts line 13/18 (`ink-2`; dates and ids in `--text-ident`; chips `size="xs"`); **BusinessDayBar** 6 px tall, one segment per `days.total`, gap 3 px, radius 3: done = `line-3`, today = `strip-viewing`, left = 1 px `line-2` outline, no fill; the bar renders only when all three numbers are numbers, else the sentence "dates unreadable — no bar".
- Lane: ground `lane`, radius 14, padding 8; header 40 px (`lane-header`, eyebrow label left, `--text-lane-count` numeral right, `lane-line` below); lane glyph 18 px before the label; cards `surface-1`, radius 10, padding 12, gap 8; a card is three lines — id (`--text-ident`) with the risk chip right-aligned; name 14/20 500 `ink-1` clamped to two lines; people rings 20 px overlapping by 4 px plus PR facts 12/16 `ink-3`; the "next up" card carries a `today-act-line` 2 px left edge and the words "next up · deps merged · pull →" in `accent-text`. Checking cards show the wait as "2 business days" in `--text-ident`, tinted `today-wait-*` only on the plugin's condition.
- Baton: a 24 px glyph centred on the Building→Checking gap, 12 px below the headers, in a `baton-bg` slot 28 px tall with the open hand-off's text in `baton-ink`; a stack of several hand-offs lists downwards at 8 px gap.
- Today 320 px: groups in order with eyebrows; items min-height 44, padding 12, radius 10, `border-l-2` in the group's `-line` token, ground `-bg` only for "needs you"; one action button per item, right-aligned, `size="sm"`.
- Below the lanes: `grid-template-columns: minmax(280px, 1fr) minmax(320px, 1fr) minmax(320px, 1fr)`, gap 24 — In the room · Refining for S(n+1) · How it is going; two columns under 1280, one under 960. Minimum width for the full lane row = 4×220 + 3×12 + 24 + 320 + 48 = 1308 px; under that, Today drops below the lanes at full width.

**Planning** (`grid-template-columns: minmax(300px, 1fr) minmax(360px, 1.2fr) 320px`, gap 16, from `lg` 1024 px; below, stacked slate-first): backlog on `plan-backlog`, the slate on `plan-slate`, what-the-plugin-says on `plan-says` with a `plan-says-line` edge; each column's header 40 px with an eyebrow; slate rows 56 px with the build-order numeral in `--text-ident` left and the Builder / Checker pickers right; the mix meter is three 6 px bars (actual over target, `accent-600` over `line-2`), never a chart.

**Spec card** (a panel over the lanes, max-width 1200, radius 20, `--shadow-3`, padding 24; `grid-template-columns: minmax(320px, 1fr) 280px minmax(300px, 1fr)`, gap 24, from `lg`; below, stacked header → Intent·DoR → Ladder → Findings → Hand off): header 2 rows (id + name in `--text-xl`; facts chips); ladder rungs 40 px apart on a 2 px `rung-rail`, rung disc Ø 12, the failing rung's reason 12/16 `ink-2` under it; findings rows 44 px with the disposition chip left; the Hand off foot sticks to the panel's bottom, 64 px, `surface-1`, hairline above, the caption "one spec · one branch · one PR" in `ink-3`.

**Steering mode** (`steer-bg` full-bleed; padding 48; title row 64 px with the Depth lockup at 48 px; tiles `repeat(auto-fit, minmax(280px, 1fr))`, gap 32, padding 24, radius 14, `steer-tile` + `steer-tile-line`; number `--text-steer-number`, everything else `--text-steer-label`; no chat, no console, zero `button[data-write]`).

## 5. Iconography — lucide, stroke 1.75 (`ICON_STROKE`), never filled

| Concept | lucide icon | Concept | lucide icon |
|---|---|---|---|
| pull (into Building) | `arrow-right-to-line` | merged | `git-merge` |
| hand-off | `hand` | blocked / refused | `ban` |
| verdict | `gavel` | security pass (rung) | `shield-check` pass · `shield-alert` fail · `shield` pending or no data |
| decision (clock) | `scale` | grader (rung) | `scan-search` |
| refine in place | `pen-line` | correctness (rung) | `check-check` |
| CI (rung) | `workflow` | non-author approval / named sign-off | `user-check` |
| ack | `check` | pull request | `git-pull-request` |
| carry to a later sprint | `forward` | defer (leave Build) | `corner-down-right` |
| needs you | `bell` | in the room | `users` |
| omnibar | `command` | steering mode | `presentation` |
| close the sprint | `flag` | overflow menu | `ellipsis` |

Sizes: **16** inside chips, table rows and before inline text; **18** in lane headers, buttons and Today actions; **20** in omnibar rows, TopBand controls and steering. An icon beside a word is `aria-hidden`; an icon alone carries `label`. Rung state is drawn by the rung disc (`rung-*`) **and** named by the host's word; the icon never changes colour by itself.

## 6. Assets (created in this package; deterministic, inline, CSP-safe)

- `studio/src/components/brand/figures/` — `CcEmptyFigure` (`figure=` `no-sprint` · `nothing-needs-you` · `no-findings` · `no-decisions` · `backlog-empty`; 120×72, `aria-hidden`, two tones only: quiet `fill-accent-200`, lit `fill-accent-500` / `stroke-accent-500`; no `<text>`, no digit, byte-identical on re-render), `BatonGlyph` (24×24, `baton` body with two quiet bands), `LaneGlyph` (`lane=` `ready` dashed ring · `building` half disc · `checking` ring with a seam · `merged` filled disc; 18×18 `currentColor` — the cue is shape, not colour, as the Spine's stations), `SteeringLockup` (Depth mark 48 + wordmark 22 px + the eyebrow "Steering"), `PersonRing` (20 px initials ring; `you` draws the `you-ring` after a `surface-1` gap; `lit` the `card-lit` edge; `dim` opacity .55; never adds a digit). Geometry lives once in `ccFigureGeometry.ts`.
- `studio/public/brand/cc/` — the same twelve shapes as static SVG files in the light values (#A7E6E7 quiet, #1A99A3 lit, `#0E7C86` for `currentColor` glyphs; `steering-lockup-depth.svg` carries the one Depth gradient on the (17, 9) → (47, 56) vector) for documents and the guide; `test/ccBrandAssets.test.ts` holds each file's path data in step with the component.
- Frame for an empty state: the kit's `rounded-xl border border-dashed border-line-2 px-5 py-6`, figure above, the plugin's sentence (or `reasons.ts`) below in 13/18 `ink-2`, the "what would produce data" line in 12/16 `ink-3`. The Scorecard gets no figure.

## 7. Motion — from the existing token scale; end state = cold reload

| Interaction (row) | Full | Reduced motion | Off / test | Tier (`motion.familiarity`) |
|---|---|---|---|---|
| Card arrival on first paint (`listStagger` #4) | y 4→0 + fade, `dur-3` 320 ms `expo.out`, stagger amount 0.18, cap 12 | opacity 120 ms, no transform | end state | `full` only; `quiet`/`settled` paint at once |
| A later Today row (identity `timestamp+event+spec`) | rise y 6→0, 240 ms `power3.out`, alone — never a re-stagger | fade 120 ms | end state | all |
| Baton pass (#30 `batonPass`) — **420 ms** | pop scale .6→1 `back.out(1.4)` 100 ms, then slide along the lane edge 320 ms `expo.out` (= `dur-3`), trail 2 px `baton`; the card Flips via `boardRegroup` from 100 ms; plays only after exit 0 **and** the refreshed read | crossfade at the new position 120 ms | end state | `full`, `quiet`; `settled` = crossfade only |
| Verdict seal (#31 `verdictSeal`) | `SEAM`: 2 px `accent-600` from the card's top-centre, scaleX 0→1, 300 ms `expo.out`; chip crossfade out `dur-1` / in `dur-2` at 150 ms; `returned` draws no seam | chip crossfade 120 ms | end state | `full`, `quiet`; `settled` = crossfade only |
| Lane re-order (`boardRegroup` #6) | Flip `dur-4` 560 ms `power3.inOut`, `scale:false`, `absolute` | none — instant | instant | all |
| Spec card open / back (`sharedElement` #8) | `FLIP_SHARED` 360 ms `power3.inOut`; siblings fade `dur-1`; focus returns to the opener always | instant; focus returns | instant | all |
| Strip lean-in (station → lifecycle home) | viewing ring scale 1→1.12 `dur-1` 120 ms `power2.out`; the home's `screenEnter` rise 240 ms | fade 120 ms | end state | all (navigation, not ceremony) |
| Strip draw (#32 `stripDraw`) | rail `stroke-dashoffset` draw `dur-5` 900 ms `expo.inOut` at `frameAssemble`'s `"spine"` label; stations pop with `stagger-2` 60 ms | none | end state | `full` only |
| Current-station pulse | `attachPulse`: `sine.inOut` 2.4 s yoyo, 3 cycles, held while the pointer is over the strip | none | none | `full` only — the one idle motion |
| Omnibar open / close (`dialog` #15) | panel y 6→0 + fade `dur-2` 200 ms `power2.out`, scrim fade `dur-2`; close `dur-1` 120 ms; no result stagger | fade 120 ms | instant | all |
| Needs-you count, lane counts, waits (`counters` #11 / `useCountUp`) | number→number `dur-3`; `null`↔number is a text crossfade `dur-2`; never 0→n | crossfade 120 ms | end state | all |
| Steering enter / leave | tiles Flip large `FLIP_SHARED` 360 ms; counters as above; Esc fades `dur-2` | fade 120 ms | instant | all |
| Theme change (#25), hover edge, press | unchanged: reveal 420 ms, edge 120 ms, press scale .985 80 ms | unchanged | zeroed by `base.css` | — |

**Calm by day 30**: opens 1–3 `full` (everything above), 4–10 `quiet` (no first-paint stagger, no strip draw, no pulse; pops, the seam and the baton stay — they are evidence of a verb), > 10 `settled` (only verb-triggered crossfades and counters). The DOM after `progress(1)` is identical across tiers (P5's `calm.test`). Under test mode and reduced motion every row applies its end state synchronously. Budget: ≤ 30 concurrent tweens (`MAX_CONCURRENT_TWEENS`); a lane of more than 12 cards paints the rest at once.

## 8. Do not

1. No gradient anywhere except Depth, at the two places in §1, ≥ 48 px, the one construction (`TogoMark variant="depth"`). Not on a lane, a card, a bar, a chip, a rung or behind text.
2. No shadow beyond the kit's two (`--shadow-1` hover, `--shadow-3` overlay); no `--shadow-2` on cards, no blur in dark.
3. No decorative glow, halo, bloom or particle on any 2-D surface; the canvas keeps its two existing radial glows and nothing new.
4. No colour that is not a plugin fact: amber only from `since_business_days > 1` / `over_alarm` / `mix_warnings` / a SHOULD finding; red only from `overdue:true`, exit 2 or a failed host conclusion; green only from a host success or a signed stage; the accent only for "yours / where you are / the plugin's voice".
5. No per-lane hue, no per-person colour, no avatar photos; a person is initials in a ring, and only the signed-in person wears `you-ring`.
6. No number that the plugin did not report; no 0 for "no data"; no velocity, points, PR count, LOC or hours anywhere, including a figure.
7. No idle motion beyond the current-station pulse; no geometry, brightness or size from time, people or activity.
8. No second display face, no letter-spaced caps for the wordmark, no colour text below 4.5:1, no word in `ink-4`.
9. No lucide icon outside §5's set without adding it to §5 first; no icon filled, no icon as the only signal.
10. No `<canvas>` in the strip, the lanes, the Today column, planning's columns, the spec card or steering; one live WebGL canvas, every canvas with a Table twin.

## 9. Per-screen checklist (score each line 0/1; a screen ships at 100 %)

**Every screen**: shell 48 + 64 px, `<main>` padding 24 · every text pair ≥ 4.5:1, every UI edge ≥ 3:1 in both themes (measured, not eyeballed) · every number tabular · every id/date/path in `--text-ident` · every eyebrow in `--text-eyebrow` + `ink-3` · every disabled control carries its reason · every "no data" is words in `ink-3` · every element names its source field in a tooltip or provenance line · no gradient, shadow or glow beyond §8 · motion rows from §7 only, end state = cold reload · dark and light shots both taken.

**Sprint home**: four lane wells on `lane` with 40 px headers and `--text-lane-count` numerals · lane glyphs are shape-coded, monochrome · "next up" card carries the accent left edge and the three words · Checking waits amber only on the plugin's condition · the baton sits on the Building→Checking gap in `baton-bg` · people rings 20 px, one `you-ring` at most, no digit inside `[data-person]` · Today column 320 px, "needs you" washed `today-act-bg`, one action per item · BusinessDayBar 6 px, three states, or the sentence · In the room / Refining / How it is going in the 3-column band · empty states use `CcEmptyFigure` with the plugin's own sentence.

**Planning**: three columns on `plan-backlog` / `plan-slate` / `plan-says` with `plan-says-line` · READY-first order visible from the rows alone · build-order numerals in `--text-ident` · mix meter is three bars, no chart · the HIGH line quoted verbatim from `ladder.rungs` · "Add to slate" enabled on drafts, gaps shown inline · Commit shows each step's exit code.

**Spec card**: panel radius 20 with `--shadow-3`, header `--text-xl` · ladder rungs on a `rung-rail`, discs coloured only by the host's conclusion, correctness always `rung-none` + "no data" · the failing rung carries `waiting_on` under it · findings chips in `ledger-*`, off-books outlined · Hand off foot 64 px sticky with the plugin's refusal verbatim · Esc returns focus to the opener.

**Lifecycle home**: the strip's viewed station ringed `strip-viewing`, lit rail = signed count in `strip-lit` · the Spine canvas has its Table twin · Today column identical in spacing to the sprint home's · decisions list shows `clock_due` / `overdue` with `today-late-*` only on `overdue:true`.

**Close and steering**: Outcomes in `--text-metric`, "no data" never a 0 · every open spec has a Carry-to or Drop with a reason field · steering on `steer-bg`, title lockup Depth at 48 px, tiles ≥ 280 px, numbers 56 px, every other word ≥ 24 px (provenance ≥ 20) · zero `button[data-write]`, no chat, no console, no `<input>` · no forbidden metric word in the DOM.

## 10. Flows in gestures (Q4, this round — append-only)

A gesture is one keypress, one chord, one click or one typed phrase; reading is free. "Before" is v12 as captured in `observatory-v12-*`; "after" counts what this round's mechanics make possible once Q1/Q2 wire the exposed hooks (`usePendingVerb`, `useFocusReturn`, `kbdFor`, `namedEscLayers`, `intentEntries(…, onSuggest)`, `prefetchCommandCenter`). Every count assumes the sprint home is the landing screen (`homeFor` = `sprint`) and the person is signed in. Nothing here is a plugin fact; it is a count of the shell's own gestures.

| Flow | Before (v12) | After | What made it shorter |
|---|---|---|---|
| Open to what needs me | open project → wait for the fan-out → scroll Today to "needs you" → click the item's action: **3** (+ one spawn-set wait on first paint) | open project → `↵` on the first needs-you item, already focused: **1** | `prefetchCommandCenter` on project open (one fan-out shared with the renderer's first read via in-flight dedupe); `returnFocus({kind:'needs-you'})` on landing; the honest `fetchedAt` stamp says "as of" for a cache hit instead of pretending the read is new |
| Pull | click the "next up" card → click "pull →" → confirm in the hand-off dialog → find the card again: **4** | `j` to the card → `↵`… or ⌘K `pull 0002` → Confirm: **3**; focus lands on the card afterwards without a search: **−1 hunt** | the lanes scope (`j k ↵ h v`) and the omnibar grammar were there; `focusPlanFor(request)` → the card that changed takes focus once the refreshed read lands (never before) |
| Hand off | `h` on a card → pick the person → Confirm → read the toast → find the card in Checking: **5** | `h` → pick → Confirm: **3**; the pending line reads "sending to the plugin…" with the argv, then the plugin's first line verbatim, then "re-reading"; focus lands on the baton's card | `pendingStore` + `toastWording` (no optimistic word; sticky until the refreshed read settles it); `focusReturn` |
| Verdict | `v` → choose verdict → Confirm → look for the chip change: **4** | `v` → choose → Confirm: **3**; or ⌘K `verdict 0002 accepted` → ↵ → Confirm: **3**; a typo (`verdcit 0002 accepted`) is offered as the repaired phrase, one `↵` away instead of a retype: **−1** | `nearestIntents` (three nearest templates, filled only with values the text already names; placeholders stay placeholders); the effect sentence ("writes eng_review: accepted … one "verdict" ledger line") shows before Confirm so the preview is the write, not a promise |
| Plan + commit | `g p` → Add to slate ×N → pick builders ×N → Commit → read each step's exit → `g s`: **2N+3** | unchanged in count (**2N+3**) — the slate is a human decision per row by design; what shortens is the wait: each write's pending line is truthful and the post-exit re-read is warmed by `warmCommandCenter`, so "Commit → refreshed slate" is one fan-out, not two | `warmCommandCenter` after exit 0 in `sprintWrites`; in-flight dedupe |
| Read a spec's ladder | click card → scroll the card to the ladder → `Esc` → find the card: **4** | `j`… `↵` → read → `Esc`: **3**, focus returns to the opener by `ESC_LAYERS['spec-card']` | the Esc order is one list (`ESC_LAYERS`, `namedEscLayers`) so the spec card always closes before the lanes clear and focus goes back to the card that opened it |
| Close a sprint | `g c` → Carry/Drop + reason ×open → Close → read exit: **2·open + 2** | unchanged in count; every carry/drop's pending line reads the plugin's words, and the close verb's `focusPlanFor` lands on the sprint header afterwards | `pendingStore` per row target (`{spec}`), `{kind:'sprint'}` focus plan |
| Present steering | `g t` → `Esc` to leave: **2** | **2** (already minimal); `Esc` is now the `steering` layer in `ESC_LAYERS`, listed after the spec card and before lane focus, so an open dialog closes first and the room never loses its screen to a stray Esc | documented layering |

**Shortcut hints on controls (new mechanic, no count change).** `kbdFor(ALL_BINDINGS, type, match)` returns a control's own key from the one map (⌘K on the omnibar trigger, `h` on Hand off, `g` `p` on Planning) so the binding and its label can never disagree; `describeBindings(ALL_BINDINGS)` generates the README's "Keyboard shortcuts" table from the same data.

**Still a gap (reported to Q1/Q2/P3/P4).** (1) `index.ts` must call `prefetchCommandCenter(projectPath, scriptsDir)` in `studio:openProject` after `openProjectPath = projectPath` — the function exists; the one-line call is P3's file. (2) `CommandPalette` must pass `onSuggest` (set the field's text to the phrase, keep the palette open) for incomplete suggestions to appear; without it only complete repairs show. (3) `VerbDialog` / `VerdictDialog` / `HandoffDialog` / `Refining` / `TierChip` / `RolePicker` / `BacklogColumn` / `Planning` should replace their own "Waiting for the plugin to answer." with `toastWording.WAITING_FOR_PLUGIN` and run writes through `trackVerb`, then `settleReread()` when the refreshed `getCommandCenter` lands. (4) `SprintHome` should schedule `focusPlanFor(request)` via `useFocusReturn(root, cc)` after each exit 0 (its current `focusBack` covers the spec card's return only). (5) `Frame` should build `escLayers` with `namedEscLayers({...})`.
