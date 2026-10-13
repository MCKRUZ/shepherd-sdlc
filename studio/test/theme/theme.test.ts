// @vitest-environment jsdom
/** The theme mechanics of studio-observatory.md §2.1: how a preference resolves, that the
 * attribute is applied synchronously (so dark never flashes light), that it persists, that the
 * OS is followed only for `system`, and that an environment with no matchMedia reads light. */
import { createElement } from 'react'
import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  THEME_STORAGE_KEY, THEME_SWITCH_MS, applyTheme, configureThemeRevealForTests, noteThemeRevealKeyboard,
  noteThemeRevealPointer, readThemePreference, resolveTheme, setThemePreference, subscribeSystemTheme, themeRevealOrigin,
} from '../../src/theme/theme'
import { DENSITY_STORAGE_KEY, applyDensity, readDensity, setDensity } from '../../src/theme/density'
import { ThemeProvider } from '../../src/theme/ThemeProvider'
import { useTheme } from '../../src/theme/useTheme'

type Listener = (e: { matches: boolean }) => void

/** A matchMedia stub whose answer for the dark query can be changed and whose change listeners
 * can be fired — setupTests' inert stub answers false and never fires. */
function stubMatchMedia(matches: boolean) {
  const listeners = new Set<Listener>()
  const state = { matches }
  window.matchMedia = (query: string) =>
    ({
      get matches() { return query.includes('dark') ? state.matches : false },
      media: query,
      onchange: null,
      addEventListener: (_: string, l: Listener) => { listeners.add(l) },
      removeEventListener: (_: string, l: Listener) => { listeners.delete(l) },
      addListener: (l: Listener) => { listeners.add(l) },
      removeListener: (l: Listener) => { listeners.delete(l) },
      dispatchEvent: () => false,
    }) as unknown as MediaQueryList
  return {
    set(next: boolean) {
      state.matches = next
      for (const l of listeners) l({ matches: next })
    },
    get size() { return listeners.size },
  }
}

const originalMatchMedia = window.matchMedia
const html = () => document.documentElement

beforeEach(() => {
  localStorage.clear()
  html().removeAttribute('data-theme')
  html().removeAttribute('data-density')
  html().removeAttribute('data-view-transition')
  html().classList.remove('theme-switching')
  configureThemeRevealForTests(null)
})
afterEach(() => {
  window.matchMedia = originalMatchMedia
  configureThemeRevealForTests(null)
  vi.useRealTimers()
})

describe('M10 dusk reveal', () => {
  it('flips synchronously, with no view transition, when the document has no startViewTransition', () => {
    const start = vi.fn().mockReturnValue(null)
    configureThemeRevealForTests({ motionOn: () => true, startViewTransition: start })
    applyTheme('light')
    applyTheme('dark')
    expect(start).toHaveBeenCalledTimes(1)
    expect(html().getAttribute('data-theme')).toBe('dark')
    expect(html().hasAttribute('data-view-transition')).toBe(false)
    expect(html().classList.contains('theme-switching')).toBe(true)
  })

  it('never starts a view transition when motion is off or reduced', () => {
    const start = vi.fn()
    configureThemeRevealForTests({ motionOn: () => false, startViewTransition: start })
    applyTheme('light')
    applyTheme('dark')
    expect(start).not.toHaveBeenCalled()
    expect(html().getAttribute('data-theme')).toBe('dark')
    // The default `motionOn` reads motion.ts, which is off in MODE=test — the same answer.
    configureThemeRevealForTests({ startViewTransition: start })
    applyTheme('light')
    expect(start).not.toHaveBeenCalled()
  })

  it('a transition the browser skips rejects `ready` — observed by the default environment, never an uncaught error', async () => {
    // The production walk saw "[pageerror] Transition was skipped" on every theme flip that was
    // superseded: Chromium rejects `ready` with an AbortError while `finished` still settles, and
    // nobody waited on `ready`. This goes through the DEFAULT environment's startViewTransition
    // (only motionOn is overridden), with the document stub a real browser would provide.
    const unhandled: unknown[] = []
    const onUnhandled = (e: PromiseRejectionEvent) => { unhandled.push(e.reason); e.preventDefault?.() }
    window.addEventListener('unhandledrejection', onUnhandled)
    const doc = document as unknown as { startViewTransition?: (cb: () => void) => unknown }
    const ready = Promise.reject(new DOMException('Transition was skipped', 'AbortError'))
    doc.startViewTransition = vi.fn((cb: () => void) => { cb(); return { finished: Promise.resolve(), ready, updateCallbackDone: Promise.resolve() } })
    try {
      configureThemeRevealForTests({ motionOn: () => true })
      applyTheme('light')
      expect(applyTheme('dark')).toBe('dark')
      expect(doc.startViewTransition).toHaveBeenCalledTimes(1)
      // Let every promise in the chain settle, then the microtask the browser would use to report.
      await new Promise((r) => setTimeout(r, 0))
      await new Promise((r) => setTimeout(r, 0))
      expect(unhandled).toEqual([])
      expect(html().getAttribute('data-theme')).toBe('dark')
      expect(html().hasAttribute('data-view-transition')).toBe(false)
    } finally {
      window.removeEventListener('unhandledrejection', onUnhandled)
      delete doc.startViewTransition
    }
  })

  it('with motion on runs the flip INSIDE startViewTransition, marks data-view-transition for its duration and writes the origin', async () => {
    let finish: () => void = () => {}
    const finished = new Promise<void>((resolve) => { finish = resolve })
    let callback: (() => void) | null = null
    const start = vi.fn((update: () => void) => { callback = update; return { finished } })
    configureThemeRevealForTests({ motionOn: () => true, startViewTransition: start })
    applyTheme('light')
    // The first application never animates: nothing to reveal from.
    expect(start).not.toHaveBeenCalled()
    noteThemeRevealPointer(120, 40)
    expect(applyTheme('dark')).toBe('dark')
    expect(start).toHaveBeenCalledTimes(1)
    expect(html().hasAttribute('data-view-transition')).toBe(true)
    expect(html().style.getPropertyValue('--theme-reveal-x')).toBe('120px')
    expect(html().style.getPropertyValue('--theme-reveal-y')).toBe('40px')
    // The attribute flips when the browser calls back, after it captured the old frame — not before.
    expect(html().getAttribute('data-theme')).toBe('light')
    callback!()
    expect(html().getAttribute('data-theme')).toBe('dark')
    finish()
    await finished
    await Promise.resolve()
    expect(html().hasAttribute('data-view-transition')).toBe(false)
    expect(html().style.getPropertyValue('--theme-reveal-x')).toBe('')
  })

  it('the origin is the last pointer, or the window centre after a key (⌘⇧D)', () => {
    expect(themeRevealOrigin()).toEqual({ x: '50%', y: '50%' })
    noteThemeRevealPointer(10.4, 20.6)
    expect(themeRevealOrigin()).toEqual({ x: '10px', y: '21px' })
    noteThemeRevealKeyboard()
    expect(themeRevealOrigin()).toEqual({ x: '50%', y: '50%' })
    noteThemeRevealPointer(3, 4)
    expect(themeRevealOrigin()).toEqual({ x: '3px', y: '4px' })
  })
})

describe('resolution', () => {
  it('defaults to system, which reads light when the OS does not ask for dark', () => {
    expect(readThemePreference()).toBe('system')
    expect(resolveTheme()).toBe('light')
  })

  it('system follows the OS when it asks for dark', () => {
    stubMatchMedia(true)
    expect(resolveTheme('system')).toBe('dark')
    expect(resolveTheme('light')).toBe('light')
  })

  it('reads light, without throwing, when matchMedia is not a function at all', () => {
    ;(window as { matchMedia?: unknown }).matchMedia = undefined
    expect(resolveTheme('system')).toBe('light')
    expect(applyTheme('system')).toBe('light')
    expect(html().getAttribute('data-theme')).toBe('light')
    expect(subscribeSystemTheme()).toBeTypeOf('function')
  })

  it('treats an unknown stored value as system', () => {
    localStorage.setItem(THEME_STORAGE_KEY, 'sepia')
    expect(readThemePreference()).toBe('system')
  })
})

describe('applyTheme', () => {
  it('sets data-theme synchronously — the attribute is there the moment the call returns', () => {
    localStorage.setItem(THEME_STORAGE_KEY, 'dark')
    applyTheme()
    expect(html().getAttribute('data-theme')).toBe('dark')
  })

  it('does not cross-fade on the first application, only on a change, and takes the class off after 260 ms', () => {
    vi.useFakeTimers()
    applyTheme('light')
    expect(html().classList.contains('theme-switching')).toBe(false)
    applyTheme('dark')
    expect(html().getAttribute('data-theme')).toBe('dark')
    expect(html().classList.contains('theme-switching')).toBe(true)
    vi.advanceTimersByTime(THEME_SWITCH_MS - 1)
    expect(html().classList.contains('theme-switching')).toBe(true)
    vi.advanceTimersByTime(1)
    expect(html().classList.contains('theme-switching')).toBe(false)
  })

  it('is idempotent: re-applying the same theme adds no class', () => {
    applyTheme('dark')
    html().classList.remove('theme-switching')
    applyTheme('dark')
    expect(html().classList.contains('theme-switching')).toBe(false)
  })
})

describe('persistence', () => {
  it('setThemePreference writes studio.theme and applies it', () => {
    expect(setThemePreference('dark')).toBe('dark')
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark')
    expect(readThemePreference()).toBe('dark')
    expect(html().getAttribute('data-theme')).toBe('dark')
  })
})

describe('subscribeSystemTheme', () => {
  it('follows an OS change while the preference is system, and ignores it for an explicit choice', () => {
    const media = stubMatchMedia(false)
    applyTheme('system')
    const seen: string[] = []
    const off = subscribeSystemTheme((t) => seen.push(t))
    media.set(true)
    expect(html().getAttribute('data-theme')).toBe('dark')
    expect(seen).toEqual(['dark'])
    setThemePreference('light')
    media.set(false)
    media.set(true)
    expect(html().getAttribute('data-theme')).toBe('light')
    expect(seen).toEqual(['dark'])
    off()
    expect(media.size).toBe(0)
  })
})

describe('density', () => {
  it('defaults to comfortable, applies the attribute, and persists studio.density', () => {
    expect(readDensity()).toBe('comfortable')
    applyDensity()
    expect(html().getAttribute('data-density')).toBe('comfortable')
    setDensity('compact')
    expect(localStorage.getItem(DENSITY_STORAGE_KEY)).toBe('compact')
    expect(html().getAttribute('data-density')).toBe('compact')
    localStorage.setItem(DENSITY_STORAGE_KEY, 'cosy')
    expect(readDensity()).toBe('comfortable')
  })
})

describe('ThemeProvider / useTheme', () => {
  function Probe() {
    const { theme, resolved, setTheme } = useTheme()
    return createElement(
      'button',
      { type: 'button', onClick: () => setTheme('dark') },
      `${theme}/${resolved}`,
    )
  }

  it('exposes {theme, resolved, setTheme} and applies a change to the document', () => {
    render(createElement(ThemeProvider, null, createElement(Probe)))
    const button = screen.getByRole('button')
    expect(button.textContent).toBe('system/light')
    expect(html().getAttribute('data-theme')).toBe('light')
    act(() => { button.click() })
    expect(button.textContent).toBe('dark/dark')
    expect(html().getAttribute('data-theme')).toBe('dark')
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark')
  })

  it('reads light and tolerates setTheme outside a provider', () => {
    render(createElement(Probe))
    const button = screen.getByRole('button')
    expect(button.textContent).toBe('system/light')
    act(() => { button.click() })
    expect(button.textContent).toBe('system/light')
  })
})
