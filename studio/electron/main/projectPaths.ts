// Which files in a project Studio may touch, and where they are actually allowed to point.
//
// This is one module rather than a helper inside sync.ts because the same two questions have
// to be answered in three places — syncing, documents, and history — and answering them in
// only one was the gap spec 0010's security pass found. The list lived in sync.ts and was
// enforced by sync.ts alone; every document and history call took whatever relative path it
// was handed and joined it to the project folder.
//
// Two separate checks, both needed, for different attacks:
//
//   isAllowlisted  — is this the KIND of file Studio edits? A path-string question.
//   resolveInProject — does this path actually END UP inside the project? A filesystem
//                      question, and the one a path string cannot answer. A repository can
//                      check in a file that is really a link to somewhere else on the
//                      machine, and every ordinary read or write follows it: reading would
//                      pull a private key into a merge screen and then push it to whoever
//                      owns the repository, and writing would drop remote-controlled content
//                      at a path of their choosing.
//
// (That link case needs git to materialize links, which is standard on macOS and Linux and
// usually off on Windows. Studio ships on all three.)

import { existsSync, lstatSync, realpathSync } from 'node:fs'
import { resolve, sep } from 'node:path'

const ALLOWLIST_PATTERNS: RegExp[] = [
  /^\.sdlc\/artifacts\//,
  /^\.sdlc\/[^/]+\.md$/,
  /^\.sdlc\/state\.yaml$/,
  /^\.sdlc\/decision-log\.md$/,
  /^\.sdlc\/metrics\/.+\.jsonl$/,
  /^\.sdlc\/approval-settings\.yaml$/,
  // The team roster. Added when spec 0012 needed to WRITE it: the settings screen edits
  // people and teams, and spec 0012 requires that change to reach the repository as an
  // ordinary commit. Without this entry the file could be read but never synced or saved —
  // an edit would have stayed on one person's machine, silently.
  /^\.sdlc\/team\.yaml$/,
  // The frozen-layer summary a phase sign-off writes. Without this a layer Studio generated
  // would sit on one machine forever — save() only ever pushes what this list allows. Narrowed
  // to `*.md` (studio-improvements F5): the `.superseded` copy a re-sign-off leaves beside it is
  // this machine's safety net, not a shared document.
  /^\.sdlc\/context\/layers\/[^/]+\.md$/,
  // Sprint records (`sprint.py new` writes `.sdlc/sprints/S07.md`). The spec keys and the
  // ledger it writes were already here; the record itself was not, so a sprint planned on one
  // machine stayed there (F5).
  /^\.sdlc\/sprints\/S\d{2,}\.md$/,
  // The reference-document catalogue and per-document summaries (spec 0026): the DOC-NNN ids a
  // person froze are other people's ids too, so they are shared like the rest of the project.
  // `.sdlc/reports/` is deliberately NOT here — generated report pages stay on this computer.
  /^\.sdlc\/context\/intake\/.+$/,
  /^specs\//,
]

/** A path with a `.` or `..` segment, or an empty one (`a//b`), is never one of this project's
 * documents, whatever it resolves to. Checked BEFORE the pattern match (studio-improvements F8):
 * `specs/../.git/config` matched `^specs/` and resolved inside the project, so both checks
 * passed and a file Studio must never touch was in reach. */
export function hasDotSegment(relPath: string): boolean {
  return relPath.replace(/\\/g, '/').split('/').some((seg) => seg === '' || seg === '.' || seg === '..')
}

export function isAllowlisted(relPath: string): boolean {
  const normalized = relPath.replace(/\\/g, '/')
  if (hasDotSegment(normalized)) return false
  return ALLOWLIST_PATTERNS.some((p) => p.test(normalized))
}

/** The real location of `path`, with as much of it resolved as actually exists — so this
 * works for a file about to be created as well as one already there. */
function realDeepestExisting(path: string): string {
  let probe = path
  const trailing: string[] = []
  while (!existsSync(probe)) {
    const parent = resolve(probe, '..')
    if (parent === probe) return path // reached the root without finding anything
    trailing.unshift(probe.slice(parent.length + 1))
    probe = parent
  }
  return [realpathSync.native(probe), ...trailing].join(sep)
}

export class UnsafePathError extends Error {}

/** The absolute path for `relPath` inside `projectPath`, or a throw.
 *
 * Refuses three things: a path that climbs out of the project, a path that is itself a link
 * (never legitimate for a document Studio edits — refuse it and say so rather than quietly
 * following it), and a path whose real destination is outside the project. */
export function resolveInProject(projectPath: string, relPath: string): string {
  const root = existsSync(projectPath) ? realpathSync.native(projectPath) : resolve(projectPath)
  const full = resolve(root, relPath)

  const inside = (p: string) => p === root || p.startsWith(root + sep)
  if (!inside(full)) {
    throw new UnsafePathError(`${relPath} is outside this project.`)
  }
  if (existsSync(full) && lstatSync(full).isSymbolicLink()) {
    throw new UnsafePathError(`${relPath} is a link to somewhere else, so Shepherd will not read or write it.`)
  }
  if (!inside(realDeepestExisting(full))) {
    throw new UnsafePathError(`${relPath} leads outside this project, so Shepherd will not read or write it.`)
  }
  return full
}

/** The same check as a yes/no, for the walking and listing paths where one bad entry should
 * be skipped rather than abandon the whole sync. */
export function isSafeInProject(projectPath: string, relPath: string): boolean {
  try {
    resolveInProject(projectPath, relPath)
    return true
  } catch {
    return false
  }
}

/** Both questions at once — what every document, history and sync entry point should ask. */
export function resolveProjectDocument(projectPath: string, relPath: string): string {
  const normalized = relPath.replace(/\\/g, '/')
  if (!isAllowlisted(normalized)) {
    throw new UnsafePathError(`${relPath} is not one of this project's editable documents.`)
  }
  return resolveInProject(projectPath, normalized)
}
