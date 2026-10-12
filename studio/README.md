# Shepherd

Shepherd is the desktop shell for the [Shepherd](../) plugin,
which is the repository this folder lives in — so the plugin Shepherd drives is always the one
beside it. Shepherd is an **optional add-on** — the plugin is fully usable on its own; Shepherd just
gives it a visual front end for people who want one. Shepherd never reimplements plugin logic:
every piece of project state it shows, and every change it makes, goes through the plugin's
own scripts, run the same way a person would run them from the command line.

The folder is still `studio/` and the npm package `sdlc-studio`; the product, window title and
packaged app are Shepherd — see `docs/brand/shepherd/brandbook.html`.

Scaffolded from [electron-vite-react](https://github.com/electron-vite/electron-vite-react)
(Electron + Vite + React + TypeScript + Tailwind).

## Quick Start

Shepherd is a Node project inside a Python plugin repository, so everything below runs from
this folder, not the repository root.

```sh
cd studio
npm install
npm run dev
```

The integration tests additionally need the plugin's Python environment — `uv run --project
scripts pytest scripts/tests -q` from the repository root builds it. Without it those tests
fail loudly rather than skipping, on purpose; run only the rest with
`STUDIO_SKIP_PLUGIN_TESTS=1`.

## Available Scripts

- `npm run dev`: start the Vite dev server with the Electron shell.
- `npm run build`: build the renderer and package the app with electron-builder.
- `npm run preview`: preview the production web build locally.
- `npm test`: run Vitest unit tests (runs `pretest`, a `vite build --mode=test`, first so the
  bundle-budget test has something to measure).
- `npm run test:e2e`: build the test-mode bundle and run Playwright end-to-end tests.
- `npm run typecheck`: run the TypeScript type checker.

## The smoke suite: Shepherd as a user sees it

`test/e2e/smoke.spec.ts` walks the real window the way a person would: a first-time user (Welcome, New project,
the setup wizard) and a team a few days in (every stage and tab, the Build screens, a document and its history,
a spec and its hand-off form, Settings, the Console), at 1280, 1024 and 640 px wide. It clicks every read-only
control, and lists the ones it deliberately did not (anything that changes something or starts a model run).

```
npm run pretest
STUDIO_SKIP_LIVE_MODEL=1 npx playwright test test/e2e/smoke.spec.ts
```

It takes about 3.5 minutes, needs the plugin checkout and its Python environment, and Shepherd must not already
be open. It uses **no live model**: the chat and draft entry points are replaced for the run, because opening a
stage with an unstarted document otherwise makes the chat greet with a real model call by itself.

What it writes, to `test/screenshots/smoke/` (ignored by git): a screenshot of every screen at every size (plus
one scrolled to the bottom where the panel scrolls), `observations.json`, and `report.md`. Read the pictures as
well as the report; the rules in `test/smoke/findings.ts` catch leaked internals, unnamed controls, sideways
scrolling and unexpected errors, but not a layout that is valid and still confusing.

The run fails only on a **new** bug. Problems already found are listed in `test/smoke/knownIssues.ts`, each with
what fixing it looks like, and shown under "Known, not yet fixed" in the report; fix one, delete its entry. The
first review is `docs/studio-smoke-review-2026-10-05.md` in the plugin repo.

## Project Structure

```tree
├── build/            Packaging assets
├── dist-electron/    Compiled Electron output
├── electron/         Main-process and preload source
│   ├── main/
│   └── preload/
├── public/           Static assets
├── src/              Renderer source code (React)
│   ├── theme/        Design tokens, light/dark remap, density
│   ├── ui/           The UI kit (typed contracts in contract.ts)
│   ├── motion/       The one motion rule and the GSAP choreographies
│   ├── palette/      Command palette
│   ├── shortcuts/    Keyboard map (shortcutMap.ts) and listener
│   ├── scenes/       3D scenes: core shell, spine (+ the SVG strip), constellation, ambient
│   └── components/   Screens, composed from the kit
│       ├── lanes/    The sprint home's four lanes, the baton, the verdict dialog, `j k ↵ h v`
│       ├── today/    The Today column and the "How it is going" panel
│       ├── planning/ Sprint planning: backlog · slate · what the plugin says · Commit
│       ├── SpecCard/ The spec card: DoR, the checking ladder, the findings ledger, Hand off
│       └── brand/    The mark, the wordmark and the command center's figures (`figures/`)
├── shared/           Types and pure models both processes use (`nav.ts`, `sprintVerbArgv.ts`, `reasons.ts`, `identity.ts`, `ladderJoin.ts`)
└── test/             Unit and end-to-end tests
    └── e2e/          Playwright, incl. `cc/` for the command center
```

Files under `electron/` are compiled into `dist-electron/`. The main process's command-center
bridge is `electron/main/{commandCenter,commandCenterReaders,sprintWrites,decisions,specCard,actor}.ts`.

## Command center

`docs/proposals/togo-command-center.md` (2026-10-06) reorganised the app around the Build loop.
The sidebar is gone. Every project screen sits under one shell: the **top band** (the mark and
project name as one button that leans out to the lifecycle home · the **omnibar** trigger, a
button that reads "⌘K · a spec id, a verb, or a place" and is never an `<input>` at rest · the
**needs-you** chip, the length of the list the main process addressed to you by exact handle ·
the sync chip · Console · Appearance · Settings · a `…` menu with Chat, Shortcuts, Steering mode,
New project and Open folder) and the **lifecycle strip** — nine SVG stations on a lit rail from
`spineModel`, the Build station reading "Build Loop · S08 · 8th sprint" from `sprint.py list`,
expanding on click to Build's views: Home · Planning · Board · How it is going · Closing ·
Documents. Exactly one entry carries `aria-current="page"`; the viewed station carries
`data-viewing`. The strip is the first `<aside>` and the chat the second, so the a11y pins hold.

**Two homes, one pure choice.** `homeFor(status, sprintProbe, capabilities)` (`shared/nav.ts`) lands a
project in the Build loop on the **sprint home** when the plugin declares `sprint-status`, and every
other project on the **lifecycle home** (today's stage home with a Today column). Chosen once per
open, never on a timer; `g s` / `g l` switch, the strip and the palette too.

**The sprint home** (`SprintHome.tsx`) draws one read, `getCommandCenter`: the header with the
business-day bar; four lanes — Ready, Building, Checking, Merged — a *partition* of the plugin's
`status`, `dor`, `verdicts_pending` and the pull request's `waiting_on` (anything else is listed
as "slated, not in a lane"); the hand-off **baton** on the Building→Checking edge (`↵` acks); the
Today column ("needs you" with one action each, "Team is waiting on", "since yesterday" from
`sprint.py log`, Shepherd's own record of Claude's work, Standup notes disabled with its reason);
**In the room** (roster people with lane dots — presence, never digits; hover lights their cards);
**Refining** for the next sprint with the checker's own DoR gaps; **How it is going** from the
scorecard. The slate constellation keeps its Graph surface below, with the slate table as its twin.

**The omnibar** (`palette/intents.ts`, `VerbDialog.tsx`). ⌘K takes plain words — `pull 0005`,
`verdict 0002 accepted`, `hand 0006 to Sam`, `ack 0006`, `defer 0003 because …`, `defer 0003 to S08
because …`, `unslate 0004 because …`, `decide DL-02 …`, `decision …`, `confirm tier 0007`, `ready
S08`, `close S07`, `new sprint` — and resolves ids and names only against the board's rows and the
roster. A match is the first palette row ("Run: sprint.py verdict --spec 0002 --lane eng --verdict
accepted --by @arjun"); `↵` opens the dialog, never runs. The dialog shows the exact argv, the
actor and where that identity came from, what the plugin will check, and one Confirm; the answer
is stdout/stderr verbatim under **Done** / **Not done** / **Refused by the plugin** (exit 0 / 1 /
2). A name the roster does not know is a visible gap — the Confirm is present and disabled with the
reason, a roster picker beside it — never a guess.

**Planning** (`planning/`, `g p`): the refined backlog READY-first ("Add to slate" is enabled for
drafts — the plugin, not the UI, lists the gaps at `ready`), the slate in the plugin's build order
with Builder / Checker pickers (`assign`) and the Security signer slot disabled with its reason,
what the plugin says, its deterministic proposal ("Apply proposal" previews in the dialog), and
**Commit the sprint**: a dialog that lists the lines it will run, then `slate → ready → plan →
open report → decisions`, stopping at the first non-zero exit with each step's answer.

**The spec card** (`SpecCard/`), opened in place from a lane card or a Refining row (the home stays
mounted beneath, inert and out of flow, so Back / Esc hand focus back to the opener): the
Definition of Ready verbatim, scope and `harness_context` from the document, the channel's
dimensions when one is bound, the **checking ladder** (`ladder.rungs[]` joined by a fixed table to
the host's fields; a rung is coloured only by the host's conclusion; correctness is always "no
data"), the **findings ledger** with the plugin's dispositions and "off the books", and a **Hand
off** foot disabled with `handoff.py --check`'s own refusal.

**Close and steering** (`SprintClose.tsx`, `SteeringMode.tsx`): the close screen above the
unchanged *Declaring Build finished* — outcomes, kept, open specs each Carry or Drop with a
required reason and a per-row Carry-to picker (one `--carry-to`; "create S09 first →" opens
`new`) — then one `close` dialog whose exit-1 text names an undecided spec by id. Steering mode
(`g t`, the `…` menu) is the committee's read-only room: tiles at 56 px, every number naming its
field, no chat, no console, zero `button[data-write]`, `Esc` returns to the screen it was entered
from.

**The truth rule.** The renderer never spawns, never joins across sources and never derives a
status. The main process assembles one `CommandCenter` document with per-block provenance
(`source`, `fetchedAt`, `ok`, `data`, `error` — `data: null` reads "no data", never 0) and runs
every write through `shared/sprintVerbArgv.ts`, a closed argv table with the signed-in person as
`--by` (`electron/main/actor.ts`; no actor → every write refuses before spawning). After an exit 0
the screens re-read — never before. "Refresh this screen" drops main's cache and re-reads. A count
of zero recorded events reads "none recorded in this window" (the plugin's own wording for a
ledger with nothing in it); no velocity, points, PR counts, lines or hours appear anywhere; a
disabled control always carries its reason, as a tooltip and as its accessible description
(`aria-describedby`), and every such sentence is in `shared/reasons.ts` or is the plugin's own.

### The kit

Every screen is composed from `src/ui/` (typed contracts in `contract.ts`, exports in `index.ts`).
Round 2 (`docs/proposals/studio-upgrade-2.md`) added the pieces every screen now shares:

- `PageHeader` — area eyebrow ("BUILD · BOARD"), the `h2[data-page-heading]` with the heading
  text byte-identical to before, a lede as the h2's next sibling, right-aligned actions;
  `sticky` uses the one sticky recipe (`components/useStuck.ts`: transparent at rest, `surface-0`
  and a hairline only once scrolled — the ghost-strip fix).
- `Disclosure` — a `<details>` with a chevron summary and no `::marker`; closed by default.
- `EmptyState figure=…` — six small figures in the product's own vocabulary (`emptyFigures.tsx`).
- `Dialog scrollBody` — a scrolling body with the footer pinned; rows stagger in (cap 8).
- Toasts anchor over `<main>` (never over the chat composer), dedupe a same-title update within
  2 s in place, and their rail is a clock that pauses while hovered.
- Text: `text-accent-text` / `hover:text-accent-text-hover` for every link-coloured word (readable
  in dark too); `Eyebrow` / `EYEBROW_TYPE_CLASS` for the label voice — `ink-4` is decoration only,
  never a word, and a bare `text-eyebrow` class is the colour utility alone.
- `shared/format.ts` — `plural`, `formatDate`, `formatRelative`, `formatHours`, `NO_DATA`: the one
  place a plugin value becomes words. It formats what the plugin reported and derives nothing;
  a value the plugin did not give reads "no data" / "no date recorded", never 0 or today.
- **Radix under the kit** (command-center round 3; the only dependency added since round 2):
  `@radix-ui/react-dialog` sits under `Dialog` (focus scope, dismissable layer, `aria-hidden`
  outside, labelled-by / described-by from Title and Description), `react-tooltip` under
  `Tooltip`, `react-hover-card` under `HoverCard`, `react-tabs` under `Tabs`, `react-dropdown-menu`
  under the band's `…` (`OverflowMenu`), and `cmdk` under the palette's list. The kit keeps what
  Radix does not do: the portal goes to `#overlays` (never inside `<main>` or an `<aside>`),
  `role="dialog" aria-modal` stays literal, focus returns to the opener as soon as the panel is
  gone, the catalogue's motion rows are unchanged and a disabled control still carries its reason.
  `shortcuts/escOwners.ts` is the one list of what owns Escape above the screen (`[role=dialog]`,
  `[role=alertdialog]`, `[role=tooltip]`, `[role=menu]`, `[data-hover-card]`) so the screen's own
  Esc chain steps aside while any of them is up. `Dialog placement="top"` is the palette's seat.

### Cockpit QA

The sprint home's first screen is the **cockpit** (`components/lanes/cockpitLayout.ts`): from
1240 px of home width the four lane wells sit in one row with Today as a 300 px rail, and the home
grid's row is `100dvh − --cockpit-chrome` (floor 280) so wells and rail fill it and end on one line
24 px above the fold; `useCockpitChrome.ts` measures the chrome live from the grid's own top at
rest and writes the custom property (the classes carry the first-paint defaults, 396 rail / 572
strip). Under 1240 Today is a 120 px strip above the lanes with a bottom fade. The chat starts
collapsed to a 40 px rail on the sprint home and planning (`stores/chatStore.ts`, per area,
remembered per machine; the band's Chat toggle, the `…` row and ⌘\ reopen it; it stays mounted).
`main#main { position: relative }` in `theme/base.css` keeps the root from ever scrolling. What
holds it: unit `cockpitGeometry.test` (the class literals against the arithmetic),
`useCockpitChrome.test`, `rootNeverScrolls.test`, `frameChat.test` / `chatStore.test`,
`escOwners.test`; e2e `test/e2e/cc/overlap.spec.ts` (`measureLandmarks`: at 1280×800 and 1440×900,
light and dark, on four screens every landmark sits inside the viewport, no two intersect
unintentionally, the root never scrolls; `cockpitRules` checks lane bottoms == rail bottom ==
fold − 24; `captionRules` checks a chip never crosses its caption's text), `cockpit.spec.ts` (the
walk against the real plugin: land → card → hand off → verdict → omnibar → spec card → planning →
close → steering) and `steering.spec.ts` (the room pages; no tile straddles the fold). The capture
script has the same probe: `SHOT_OVERLAP=1 SHOT_WIDTHS="1280x800,1440x900,1680x1000"` measures
every shot and exits 3 on a violation; `SHOT_PROBE=ghost` measures the band above the header at
1.2 / 1.6 / 2.0 / 2.5 s; a GPU console line fails the run. The series the guide ships on is
`observatory-v30` (the Shepherd re-capture; `docs/guide/build-user-guide.mjs` defaults to it).

## Releases — the .dmg and the .exe

Installers are never committed: `studio/release/` is gitignored and the artifacts live on GitHub
Releases. `.github/workflows/release.yml` builds them on a version tag — the `.dmg` (and `.zip`)
on a macOS runner, the `.exe` installer on a Windows runner, both from `electron-builder.json`
with the Shepherd icon and bundle id `com.mckruz.shepherd` — and attaches them to one Release with
install notes. The tag must match `.claude-plugin/plugin.json`'s version:

```bash
git tag v2.0.0 && git push origin v2.0.0
```

Locally, `npm run build` produces the same files under `release/<version>/`. Signing is switched
on by secrets alone (macOS: `CSC_LINK`, `CSC_KEY_PASSWORD`, `APPLE_ID`,
`APPLE_APP_SPECIFIC_PASSWORD`, `APPLE_TEAM_ID`; Windows: `WIN_CSC_LINK`, `WIN_CSC_KEY_PASSWORD`);
without them the builds are unsigned and the first launch needs right-click → Open on macOS or
SmartScreen's "run anyway" on Windows. There is no auto-update channel: people install the new
release. A packaged Shepherd finds the plugin in Claude Code's marketplace cache
(`/plugin install shepherd@mckruz`), or at the path set in Settings.

## Window

The window opens sized to the display: the person's last size and place when it still lands on
a connected display (`electron/main/windowBounds.ts`, remembered in `window-bounds.json` under
the user-data folder), else the largest window up to 1680×1050 that fits the work area with a
margin, never under 1180×720. The rendering scale follows the window's width (`zoomFor`: 1.0 at
or under 1440 px, rising to 1.3 at 2560 — the layout is drawn for ~1440 and read small on a wide
display); `TOGO_AUTO_ZOOM=0` turns that off, which the tests and the capture do. The capture can take
the guide's screenshots at `SHOT_SCALE=2` (Chromium's force-device-scale-factor, appended by
main from `TOGO_DEVICE_SCALE`) — honoured on the Linux and Windows runners; macOS fixes the
scale to the display, so a Mac capture stays at 1× and the guide embeds the 1440-px PNGs as
high-quality JPEGs instead. `SHOT_WINDOW=1` resizes the real window rather than emulating the
viewport, which is how the rendering scale is probed.

## Appearance

Settings › **Appearance** (also the top band's "Appearance" button) holds four per-person
preferences. Each is stored in `localStorage` and takes effect without a reload.

| Preference | Options | Stored as | Notes |
|---|---|---|---|
| Theme | System / Light / Dark | `studio.theme` | System follows the operating system. The dark theme is a remap of the colour ramps, so every screen flips at once. |
| Density | Comfortable / Compact | `studio.density` | Compact tightens the vertical rhythm; the band, the strip and the chat keep their size. |
| Animations | Auto / On / Off | `studio.motion` | Auto honours the OS reduced-motion setting. **On** is an explicit opt-in that overrides it; Off turns every animation off. Animations are always off under test. The opening flourishes (project assemble, Welcome field, Spine draw) quieten with familiarity — opens 1–3 in full, 4–10 brisk, then not at all; a hashed per-project counter in `studio.opens.<hash>`. **Play the opening again** resets it (disabled outside a project, saying why). |
| Visuals default | Graph / Table | `studio.sprint.surface` | Which surface the Sprint constellation opens on. The Table twin is always one click away, and is what shows when graphics are unavailable. |

## Keyboard shortcuts

The map lives in `src/shortcuts/shortcutMap.ts`; the Shortcuts help (⌘/ or `?`) renders the
same data. `Mod` is ⌘ on macOS and Ctrl elsewhere. Two-key sequences (`g` then `b`) must be
typed within 800 ms. Shortcuts marked † also fire while an input has focus.

| Keys | Where | Does |
|---|---|---|
| `Mod+K` †, `/` | everywhere | Command palette |
| `Mod+/` †, `?` | everywhere | Keyboard shortcuts help |
| `Mod+Shift+D` † | everywhere | Cycle theme: system → light → dark |
| `Mod+Shift+M` † | everywhere | Toggle animations |
| `Mod+Shift+L` † | everywhere | Toggle density |
| `Mod+J` † | in a project | Toggle the console |
| `Mod+Shift+C` † | in a project | Focus the chat composer |
| `Mod+\` † | in a project | Toggle the chat panel |
| `Mod+,` † | in a project | Settings |
| `g` `0`…`g` `9`, `g` `.` | in a project | Go to Phase 0–9, or Close |
| `g` `s` / `g` `l` | in a project | The sprint home / the lifecycle home |
| `g` `p` / `g` `b` / `g` `h` / `g` `c` / `g` `d` | in a project | Planning / Board / How it is going / Closing / Build documents |
| `g` `t` | in a project | Steering mode (`Esc` leaves) |
| `[` / `]` | in a project | Previous / next stage |
| `j` / `k` | in the lanes | Previous / next card (roving focus across the four lanes) |
| `↵` / `h` / `v` / `Esc` | in the lanes | Open the spec card / hand off / record a verdict / clear |
| `1` / `2` / `3` | stage home | Workflow / Documents / Guide tab |
| `Alt+↑` / `Alt+↓` | document view | Previous / next document |
| `Mod+S` † | document view | Save the open field |
| `Home` / `n` | in a graph | Fit the graph / focus the spec the plugin named next up |
| `Shift+←→↑↓` / `+` `−` | in a graph | Orbit / zoom the camera |
| `↑` / `↓` / `Esc` | in a graph | Previous / next spec in build order / clear the hover |

"In a graph" bindings fire only while a Constellation figure (the Sprint or Board graph) has
keyboard focus — the Spine carries no keyboard scope — and
the same two commands — *Fit the graph*, *Focus next up* — sit in the palette while a graph is on
screen. They move a camera and a focus ring; nothing is fetched or written. "In the lanes"
bindings fire only while focus is inside the sprint home's board (`data-shortcut-scope="lanes"`);
`h` and `v` open dialogs — nothing runs without Confirm.

⌘W / ⌘Q / ⌘R / ⌘1–9 and the F-keys are deliberately absent: Electron and the OS own them.
Escape always closes the innermost thing (palette, dialog, hover card) and never discards an
unsaved edit — the field editor, hand-off form and an open AI proposal register as "dirty".

## Scenes

Two 3D scenes and one background, all built on `src/scenes/core/SceneShell.tsx`: a lazily
loaded `<canvas>` with a **Graph / Table** toggle, where the Table twin is the real content, not
a fallback. The Table is what renders when WebGL is unavailable, the window is under 400 px,
the canvas has crashed, or Shepherd is under test. Scenes draw only what the plugin reports —
Shepherd computes no status of its own, and a value the plugin reports as null reads "no data".

- **Lifecycle strip** (`scenes/spine/SpineStrip.tsx`) — the shell's navigation: the same nine
  stations as the Spine, as plain SVG (no canvas) from `spineModel` — a 2 px lit rail for the
  signed-off count (`role="progressbar"`), shape-coded station rings, the viewed station ringed
  `strip-viewing`, the current one pulsing three times on a full-tier open. It draws at the
  `"spine"` label of the frame assemble (`stripDraw`, `full` tier only).
- **Lifecycle Spine** (`scenes/spine/`) — the stage order and each stage's sign-off state, as a
  band above a stage's home (the lifecycle home) and on the Closing screen. Station plates carry short names
  (`STAGE_SHORT_LABEL`; the full name on hover and on the current station); a thin accent
  reticle marks the stage whose home is open ("The accent ring marks the stage you are
  viewing" — `data-viewing` on the Table twin, never `aria-current`); on Closing every plate
  carries its ledger line word for word from the plugin's row ("signed off · name · date",
  "completed · no name recorded", "not started"). Sign-off plays a short ceremony along the
  rail; the end state equals a cold reload.
- **Dependency Constellation** (`scenes/constellation/`) — specs as nodes, `depends_on` as
  edges, below the lanes on the sprint home, on planning (Slate / Proposal surfaces — a proposed
  set draws every body at `buildOrderIndex: null` with the caption "order arrives when the slate
  is committed") and on the Board (Graph in the filter bar). A node's size comes from
  its risk tier alone; a dependency on an id with no spec is a ghost node drawn from the id; a
  dependency outside the slate on an unmerged spec is warn-toned. The Sprint's Table twin is the
  slate itself; the Board's is the list. The Board host spreads bodies into a band and fits the
  camera to the host's aspect (bodies fill ≥ 60 % of the figure); y carries no meaning. A spec
  page draws its own dependency neighbourhood as plain SVG (`SpecNeighbourhood`), no canvas.
- **Materials and light** (`scenes/core/`) — bodies carry a fresnel rim in their own status colour
  and a soft specular dot; rings and the rail are shaded so the token colour is the brightest
  pixel; a three-point rig, a contact pool under every body (scale from radius only) and a
  theme-aware grid. Nothing takes geometry, brightness or size from time, people or activity.
- **Ambient field** (`scenes/ambient/`) — a slow particle background behind the entry screens
  only (Welcome, New project, Setup), gated by `AMBIENT_ENABLED && motion.enabled() &&
  canUseWebGL()`; never on a project screen and never under test.

## Bundle

Re-measured on the production `vite build` of the v14 capture, after the cockpit round and Radix
(2026-10-06; Vite reports 1000-based kB): main chunk `dist/assets/index-*.js` **773.3 kB**
(755.2 KiB; gzip 234.2 kB; budget ≤ 800, enforced by `test/bundleSize.test.ts` — the `--mode=test`
build measures 772.7 kB / 754.6 KiB), `scene-core-*.js` **966.9 kB** (gzip 259.6 kB; three, R3F,
d3-force-3d — loaded on the first Canvas mount only), the command center's lazy chunks `Planning`
32.4 kB, `SpecCard` 21.8 kB, `SprintClose` 14.4 kB and `SteeringMode` 7.7 kB, per-scene chunks
ConstellationScene 26.3 kB and SpineScene 18.0 kB, `DependencyConstellation` 8.4 kB, `gsap`
69.6 kB, CSS 93.0 kB (gzip 20.2 kB). The history: round 2 641.8 → the command center (v11) 715.7 →
Radix + `cmdk` (round 3) 768.8 → the cockpit round 772.7 in test mode. The main chunk carries the
shell (band, strip, omnibar grammar and dialog), the sprint home (lanes, Today, the room,
Refining) and the brand figures — the sprint home is the default screen in Build and stays eager;
everything behind a click is a chunk. Fonts (Inter Variable, JetBrains Mono Variable) are bundled
woff2; nothing is fetched over the network, and the Content-Security-Policy in `index.html` is
unchanged.

## Security

- The renderer never gets `nodeIntegration` — the main process talks to `claude`/`uv`/the
  filesystem, and exposes only a narrow, explicit API to the renderer via the preload script's
  `contextBridge`.
- `index.html` carries a restrictive Content-Security-Policy (`script-src 'self'`).
- `test/noNewIpcInRenderer.test.ts` fails if any file under `src/{ui,motion,palette,scenes,
  theme,shortcuts,stores}` reaches for `window.studio`.

## Code host

A project opens without `gh` or `az`. The code host is chosen **by the repository** — the
`origin` remote says GitHub or Azure DevOps (a per-clone `.sdlc/code-host.yaml`, written from
Settings › *Repository* through the plugin's `set_setting.py code-host`, can pin it) — and only
the matching CLI matters: the GitHub CLI (`gh`) for GitHub, the Azure CLI with its `azure-devops`
extension for Azure DevOps. The tooling screen lists both under *Code-host CLIs* as optional.
Features that read or write pull requests (live spec status, the hand-off's draft PR, branch
policies, pipeline evidence, gate credentials) say exactly what they need when the CLI is missing
or signed out, in one sentence from `shared/codeHostModel.ts`, and stay disabled with that
reason; everything else keeps working from the spec files. Who you are comes from the signed-in
CLI mapped through the roster (`@handle`, or `people[].email` for an Azure DevOps sign-in); when
the host cannot say, Settings and the hand-off dialog offer a typed name, and anything saved
that way is marked as typed. The renderer never spawns a CLI — the main process resolves the
host once per project (`electron/main/codeHost.ts`) and the Console narrates `gh` and `az`
calls in plain words. Design: `../docs/proposals/code-host-providers.md`.

## Status

Shepherd drives the plugin **beside it**. Unpackaged, tool detection prefers `<studio>/../scripts`
when it carries `capabilities.py`, then the newest marketplace-cached plugin that does, then a
path set in Shepherd — and Settings › *Tooling on this machine* says which one is in use and the
version it declares. Every `claude` call uses the flags listed in `shared/claudeContract.ts`,
checked once against the installed CLI's `--help`: an older Claude Code is reported ("Claude Code
<version> lacks <flags> — update with `claude update`") and the model controls stay off until it is
updated, while the project itself stays readable.

The specs in the repository's `specs/` directory (0008 onward) record Shepherd's build order;
`docs/proposals/studio-improvements.md` is the plan (Batches 1–2 built; its D4/D5 became the
code-host providers plan, built through Wave 7), `docs/proposals/studio-observatory.md` the visual
overhaul (spec 0033, built), `docs/proposals/studio-upgrade-2.md` the second round (built;
its status line records what P7 verified), `docs/proposals/togo-command-center.md` the command
center (built as P0–P8; its status line and §8 record what P8 verified and which pins moved, with
evidence), and `docs/brand/shepherd/` the identity — the mark is a chamfered frame holding the S
(Mark A, the gate-S); its Depth gradient lives at hero size only (Welcome, the opening card, the
app icon, the steering lockup), regenerated by `docs/brand/shepherd/build-assets.mjs`.
