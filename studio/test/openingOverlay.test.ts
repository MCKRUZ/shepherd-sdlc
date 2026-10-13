/** Opening a project takes long enough to look like nothing happened — it reads the project's
 * status through the plugin, which can take several seconds on a large one. While it runs the
 * window shows an overlay that says what is happening, counts the seconds, and blocks the rest
 * of the interface so a second click cannot start a second open.
 */

import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { formatElapsed } from '../shared/elapsed'
import { OpeningOverlay } from '../src/components/OpeningOverlay'

describe('formatElapsed', () => {
  it('counts whole seconds under a minute', () => {
    expect(formatElapsed(0)).toBe('0s')
    expect(formatElapsed(999)).toBe('0s')
    expect(formatElapsed(1000)).toBe('1s')
    expect(formatElapsed(42_400)).toBe('42s')
  })

  it('switches to minutes and seconds from a minute on', () => {
    expect(formatElapsed(60_000)).toBe('1:00')
    expect(formatElapsed(125_000)).toBe('2:05')
  })

  it('never shows a negative time if the clock steps back', () => {
    expect(formatElapsed(-5000)).toBe('0s')
  })
})

describe('OpeningOverlay', () => {
  const render = (startedAt: number) =>
    renderToStaticMarkup(createElement(OpeningOverlay, { projectName: 'token-tracker', startedAt }))

  it('names the project being opened', () => {
    expect(render(Date.now())).toContain('token-tracker')
  })

  it('shows how long it has been running', () => {
    expect(render(Date.now() - 7_000)).toMatch(/\b7s\b/)
  })

  it('covers the whole window, so nothing behind it can be clicked', () => {
    const html = render(Date.now())
    expect(html).toContain('fixed')
    expect(html).toContain('inset-0')
  })

  it('is announced to assistive technology as a busy, modal state', () => {
    const html = render(Date.now())
    expect(html).toContain('aria-busy="true"')
    expect(html).toContain('aria-modal="true"')
    expect(html).toContain('data-testid="opening-overlay"')
    expect(html).toContain('role="alertdialog"')
  })

  it('draws its mark at 48 px in the Depth treatment: exactly one gradient, hooks for the draw-in', () => {
    const html = render(Date.now())
    expect(html.match(/<linearGradient/g)?.length).toBe(1)
    expect(html).toContain('gradientUnits="userSpaceOnUse"')
    expect(html).toContain('h-12 w-12')
    expect(html).toContain('data-mark-frame')
    expect(html).toContain('data-mark-s')
    expect(html).toContain('stroke-dashoffset="100"')
  })
})
