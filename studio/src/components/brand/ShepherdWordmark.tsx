// The wordmark is the word "Shepherd" set as plain text, so it is read, searched and translated
// like any other word on the screen — never a logotype drawn as a picture (brand §6, §8). The
// brand rule is "one UI face, one display face for the wordmark only": Inter is the UI face
// everywhere, and Saira — the owner's pick at the identity's third stop (type-approve.json,
// 2026-10-12) — is the display face HERE and nowhere else. No heading, menu, label or token is
// set in it; `font-display` appears in this file alone. The glyphs render lowercase, "shepherd",
// as the owner's references show, through CSS `text-transform` rather than a second spelling: the
// DOM text stays `PRODUCT_NAME` ("Shepherd"), so the window title, the visually-hidden h1 prefix
// and the accessible name keep their capital. Weight 600 (Saira's approved wordmark weight) at
// −0.01em (brand §6). Never a letter-spaced all-caps treatment. `lang` is left as the document's
// (English): the name is an English word.
import type { HTMLAttributes } from 'react'
import { cn } from '../../ui'

/** The product's name as text — titles, aria, the h1 prefix. Capitalised: only the wordmark's
 * glyphs render lowercase, and that is CSS on this one span, not a second spelling of the name. */
export const PRODUCT_NAME = 'Shepherd'

/** The wordmark's class list, exported so a test can pin it and so the Welcome hero, should it
 * adopt the face, cannot drift from it: display face · 600 · lowercase glyphs · −0.01em. Size and
 * colour are deliberately absent — the caller sets them. */
export const WORDMARK_CLASS = 'font-display font-semibold lowercase tracking-[-0.01em]'

export interface ShepherdWordmarkProps extends Omit<HTMLAttributes<HTMLSpanElement>, 'children'> {}

/** Face, weight, case and tracking follow the brand; the caller sets size and colour, since the
 * wordmark appears at 12 px in window chrome and 22 px in the steering lockup. */
export function ShepherdWordmark({ className, ...rest }: ShepherdWordmarkProps) {
  return (
    <span className={cn(WORDMARK_CLASS, className)} {...rest}>
      {PRODUCT_NAME}
    </span>
  )
}
