import { useState } from 'react'
import type { ReactNode } from 'react'
import { Button, DensityToggle, Eyebrow, MotionToggle, Segmented, SURFACE_OPTIONS, ThemeToggle, toast, type SceneSurfaceValue } from '../ui'
import { DEFAULT_SURFACE } from '../scenes/core/sceneDefaults'
import { motion } from '../motion/motion'
import { useProjectKey } from '../motion/projectKey'
import { Section } from './SettingsSections'

/** `localStorage['studio.sprint.surface']` (§2.1): which surface the Sprint constellation opens
 * on. A preference of this machine, not of the project — so it lives beside theme, density and
 * motion rather than in a repository file, and the section says so. */
export const SURFACE_STORAGE_KEY = 'studio.sprint.surface'

function isSurface(value: unknown): value is SceneSurfaceValue {
  return value === 'graph' || value === 'table'
}

export function readSurfaceDefault(): SceneSurfaceValue {
  try {
    const raw = typeof localStorage === 'undefined' ? null : localStorage.getItem(SURFACE_STORAGE_KEY)
    return isSurface(raw) ? raw : DEFAULT_SURFACE
  } catch {
    return DEFAULT_SURFACE
  }
}

export function writeSurfaceDefault(next: SceneSurfaceValue): void {
  try {
    if (typeof localStorage !== 'undefined') localStorage.setItem(SURFACE_STORAGE_KEY, next)
  } catch {
    // Not remembered this time; the choice still applies for this session.
  }
}

/** Settings › Appearance: the four machine-local preferences, each a Segmented of buttons (no
 * `<input>`). The toggles read and write through the Wave 0 preference bridge, so this section,
 * the Sidebar footer and the ⌘⇧D / ⌘⇧L / ⌘⇧M shortcuts always agree. Outside edit mode on
 * purpose, like the gate credential: nothing here is a project file, so there is nothing to
 * stage or save, and a person should not have to turn on editing to pick a theme. */
export function AppearanceSection() {
  const [surface, setSurface] = useState<SceneSurfaceValue>(readSurfaceDefault)
  // M3: the opening flourishes quieten with familiarity; this is the one place to ask for them
  // back. The key is the open project's path (App's `ProjectKeyProvider`); outside a project
  // there is nothing to reset, and the button says so rather than resetting nothing.
  const projectKey = useProjectKey()
  const replayOpening = () => {
    motion.resetFamiliarity(projectKey)
    toast({ tone: 'ok', title: 'The next open plays the full opening again' })
  }

  return (
    <Section id="appearance" title="Appearance" file="" fileLabel="">
      <p className="text-xs text-ink-3">
        These are preferences of this machine, kept by Shepherd rather than in the project. They do
        not travel with the repository and change nothing about the work.
      </p>
      <div className="mt-3 grid gap-5 sm:grid-cols-2">
        <Pref label="Theme">
          <ThemeToggle note="System follows the operating system's light or dark setting." />
        </Pref>
        <Pref label="Density">
          <DensityToggle note="Compact tightens the rhythm; the sidebar and chat keep their width." />
        </Pref>
        <Pref label="Animations">
          <MotionToggle note="Auto follows the operating system's reduced-motion setting. On is an opt-in that overrides it; Off turns every animation off." />
          <p className="mt-2 text-xs text-ink-3">Opening flourishes quieten after the first ten opens.</p>
          <Button
            variant="ghost"
            size="sm"
            className="mt-1"
            onClick={replayOpening}
            disabled={projectKey === ''}
            disabledReason={projectKey === '' ? 'Open a project first — the opening belongs to a project.' : undefined}
          >
            Play the opening again
          </Button>
        </Pref>
        <Pref label="Visuals">
          <Segmented<SceneSurfaceValue>
            label="Visuals default"
            options={[...SURFACE_OPTIONS]}
            value={surface}
            onChange={(next) => { writeSurfaceDefault(next); setSurface(next) }}
            tone="neutral"
            size="sm"
            data-testid="surface-default"
          />
          <p className="mt-1 text-xs text-ink-3">Which surface the Sprint constellation opens on. The table and the graph show the same data.</p>
        </Pref>
      </div>
    </Section>
  )
}

/** A labelled preference. The Segmented inside already carries its own `aria-label`, so the label
 * here is a visible eyebrow rather than a `<label for>` pointing at a group. */
function Pref({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <Eyebrow className="mb-1">{label}</Eyebrow>
      {children}
    </div>
  )
}
