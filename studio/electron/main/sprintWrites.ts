// The closed argv table's spawn side (togo-command-center.md §2.4). The renderer hands over a
// `SprintVerbRequest`; `shared/sprintVerbArgv.ts` (pure, golden-tested) turns it into exactly
// `[verb, …flags, '--by', actor]` or a list of reasons it refuses to; this file adds the
// `--repo`/`--state` source after the verb, spawns `sprint.py` ONCE, and reports the exit code
// as the truth: 0 "Done", 1 "Not done", 2 "Refused by the plugin". No JSON is parsed — the write
// verbs print prose and the dialog shows stdout/stderr verbatim. `--field` has no row in the
// table and can never be emitted. No actor → refused here, before any spawn, with
// `reasons.NO_ACTOR`. Every spawn, whatever its exit, invalidates the command center's local
// blocks so the next read is fresh; an exit 0 also warms that read (`warmCommandCenter`) so the
// renderer's post-verb re-read joins one fan-out instead of starting a second.

import { runPluginScript } from './project'
import { sourceArgs } from './sprint'
import { cachedBoardSpecIds, invalidateCommandCenter, warmCommandCenter } from './commandCenter'
import { buildSprintVerbArgv, SCRIPT, VERB_CAPABILITY, WRITE_VERBS } from '../../shared/sprintVerbArgv'
import { NO_ACTOR, newerPlugin } from '../../shared/reasons'
import type { ActorInfo, SprintVerbRequest, SprintVerbResult } from '../../shared/types'

/** A refusal decided in Studio before the plugin was asked: `exitCode: null` so the dialog can
 * tell "the plugin said no" (exit 1/2) from "Studio did not ask". */
function notRun(req: SprintVerbRequest, stderr: string): SprintVerbResult {
  const verb = WRITE_VERBS.includes(req?.verb) ? req.verb : 'slate'
  return { ok: false, exitCode: null, refused: false, stdout: '', stderr, argv: [], verb }
}

/** The full argv `sprint.py` ran (after the script path): the verb, the project source, the
 * table's flags and `--by <actor>`. Pure, so the console line and the dialog agree. */
export function sprintVerbArgv(
  projectPath: string, req: SprintVerbRequest, actor: string, boardSpecIds?: readonly string[],
): { ok: true; argv: string[] } | { ok: false; errors: string[] } {
  const built = buildSprintVerbArgv(req, actor, boardSpecIds)
  if (!built.ok) return built
  const [verb, ...rest] = built.argv
  return { ok: true, argv: [verb, ...sourceArgs(projectPath), ...rest] }
}

export async function runSprintVerb(
  projectPath: string,
  scriptsDir: string,
  req: SprintVerbRequest,
  actor: ActorInfo | null,
  capabilities?: readonly string[],
  boardSpecIds: readonly string[] | undefined = cachedBoardSpecIds(projectPath),
): Promise<SprintVerbResult> {
  if (!req || typeof req !== 'object' || !WRITE_VERBS.includes(req.verb)) return notRun(req, 'That is not a sprint verb Shepherd runs.')
  if (!actor) return notRun(req, NO_ACTOR)
  const cap = VERB_CAPABILITY[req.verb]
  if (cap && capabilities && !capabilities.includes(cap)) return notRun(req, newerPlugin(cap))
  const built = sprintVerbArgv(projectPath, req, actor.name, boardSpecIds)
  if (!built.ok) return notRun(req, built.errors.join('\n'))

  const entry = await runPluginScript(scriptsDir, SCRIPT, built.argv)
  invalidateCommandCenter(projectPath)
  // Warm the read the renderer is about to make (it re-reads after exit 0 — never before), so the
  // refreshed truth arrives as one fan-out. Nothing is shown from here; the exit code below is.
  if (entry.exitCode === 0) warmCommandCenter(projectPath)
  return {
    ok: entry.exitCode === 0,
    exitCode: entry.exitCode,
    refused: entry.exitCode === 2,
    stdout: entry.stdout,
    stderr: entry.stderr,
    argv: built.argv,
    verb: req.verb,
  }
}
