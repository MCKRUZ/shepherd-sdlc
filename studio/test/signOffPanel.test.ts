/** The sign-off panel, as a person meets it before clicking anything.
 *
 * What it actually does when clicked is `signOffStage`'s job (`test/signOff.test.ts`, including
 * against a real Claude call) — this covers only what the initial render commits to: the name
 * field starts filled with whoever is signed in, nothing can be submitted with no name, and the
 * optional discipline-sign-off control is there and genuinely optional.
 */

import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { StageReadiness } from '../shared/types'
import { SignOffPanel } from '../src/components/SignOffPanel'

const READINESS: StageReadiness = {
  ok: true,
  stageId: '0',
  name: 'discovery',
  display: 'Phase 0: Discovery',
  isCurrent: true,
  documents: [],
  findings: [],
  judgement: [],
  signOff: { status: 'active', signedOffBy: null, completedAt: null },
  ready: true,
}

const render = (actor: string) =>
  renderToStaticMarkup(createElement(SignOffPanel, {
    projectPath: '/tmp/project', readiness: READINESS, actor, setOpening: () => {}, onSignedOff: () => {},
  }))

describe('SignOffPanel', () => {
  it('starts with the signed-in person\'s name already filled in', () => {
    expect(render('Matt K')).toContain('value="Matt K"')
  })

  it('cannot be submitted with no name', () => {
    const html = render('')
    const button = html.match(/<button[^>]*>\s*Sign off[^<]*<\/button>/)?.[0] ?? ''
    // Not a plain .toContain('disabled') — the button's own class includes the Tailwind
    // variant "disabled:opacity-40", which is a style rule, not the HTML attribute.
    expect(button).toMatch(/\sdisabled(?:[\s=>]|$)/)
  })

  it('can be submitted once a name is present', () => {
    const html = render('Matt K')
    const button = html.match(/<button[^>]*>\s*Sign off[^<]*<\/button>/)?.[0] ?? ''
    expect(button).not.toMatch(/\sdisabled(?:[\s=>]|$)/)
  })

  it('offers an optional discipline sign-off, starting with none', () => {
    const html = render('Matt K')
    expect(html).toContain('Add a discipline sign-off')
    expect(html).not.toMatch(/type="text"[^>]*value="[^"]/) // no discipline-row inputs pre-filled
  })

  it('names what it is about to do', () => {
    const text = render('Matt K').replace(/<[^>]+>/g, '')
    expect(text).toContain('Sign off Phase 0: Discovery')
    expect(text).toMatch(/sprd-next/)
  })
})
