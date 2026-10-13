// The Azure Boards mirror's spawn side (build kit §5 B4-P2; house rules 8 and 9). The renderer hands over an
// `AdoVerbRequest` (a closed union); `shared/adoVerbArgv.ts` (pure, golden-tested) turns it into exactly
// `[verb, …flags, '--json']` plus `'--by', actor` on a write, or the reasons it refuses to; this file adds the
// `--repo`/`--state` source after the verb, spawns `ado_sync.py` ONCE through `runPluginScript` (an argv list:
// no shell, no joined string, and never `az` — the plugin owns every call to the board), and reports the exit
// code as the truth: 0 "Done", 1 "Not done", 2 "Refused by the plugin".
//
// One spawn per call. The composer is the one flow with two: `comment` drafts a plan and prints its 12-hex
// hash (`json.plan`), then — after the person reads the preview and confirms — a second call `apply` sends that
// hash back; this file never chains them, so a plan is never sent without a person's second click.
//
// Refused HERE, before any spawn, with `exitCode: null` so a dialog can tell "the plugin said no" (exit 1/2)
// from "Shepherd did not ask": a request that is not one of the seven verbs, a missing plugin
// (`PLUGIN_NOT_FOUND`), no identified person (`NO_ACTOR`: like `runSprintVerb`, one rule for every verb), a
// plugin whose capabilities are known and lack the verb's (`newerPlugin(cap)`), or a request the table
// refuses (a bad hash or ref, a missing owner or reason — the table's own sentence). `--by` is always the
// actor main resolved: the request has no field for it, and an extra key on it is never read.
//
// Every spawn, whatever its exit, invalidates the command center's local blocks (the Boards block is one) so
// the next read is fresh; an exit 0 also warms that read so the renderer's post-verb re-read joins one fan-out.

import { runPluginScript } from './project'
import { rawStdout } from './commandRunner'
import { sourceArgs } from './sprint'
import { invalidateCommandCenter, warmCommandCenter } from './commandCenter'
import { ADO_VERB_CAPABILITY, ADO_VERBS, buildAdoVerbArgv, SCRIPT, type AdoVerb, type AdoVerbRequest } from '../../shared/adoVerbArgv'
import { PLUGIN_NOT_FOUND } from '../../shared/pluginId'
import { NO_ACTOR, newerPlugin } from '../../shared/reasons'
import type { ActorInfo, AdoVerbResult, ConsoleEntry } from '../../shared/types'

export const NOT_A_BOARDS_VERB = 'That is not a Boards verb Shepherd runs.'

const isVerb = (v: unknown): v is AdoVerb => typeof v === 'string' && (ADO_VERBS as readonly string[]).includes(v)

/** A refusal decided in Shepherd before the plugin was asked: `exitCode: null`. The `verb` is the request's when
 * it is one of the seven, else `show` (a read) so the envelope keeps its closed type. */
function notRun(req: unknown, stderr: string): AdoVerbResult {
  const named = (req as { verb?: unknown } | null | undefined)?.verb
  return { ok: false, exitCode: null, refused: false, stdout: '', stderr, argv: [], verb: isVerb(named) ? named : 'show', json: null }
}

/** The full argv `ado_sync.py` ran (after the script path): the verb, the project source, the table's flags,
 * `--json` and — on a write — `--by <actor>` last. Pure, so the console line and the dialog agree. */
export function adoVerbArgv(
  projectPath: string, req: AdoVerbRequest, actor: string,
): { ok: true; argv: string[] } | { ok: false; errors: string[] } {
  const built = buildAdoVerbArgv(req, actor)
  if (!built.ok) return built
  const [verb, ...rest] = built.argv
  return { ok: true, argv: [verb, ...sourceArgs(projectPath), ...rest] }
}

/** The one JSON object `--json` printed, read from the exact output (the masked copy is for display); null when
 * stdout is prose, an array, or nothing. */
function documentOf(entry: ConsoleEntry): Record<string, unknown> | null {
  try {
    const parsed: unknown = JSON.parse(rawStdout(entry))
    return typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed) ? (parsed as Record<string, unknown>) : null
  } catch {
    return null
  }
}

/** `scriptsDir` null is a Shepherd plugin that was not found; `capabilities` undefined is "not known" (the
 * plugin decides), an array is `generate_status.py`'s own declaration. */
export async function runAdoVerb(
  projectPath: string,
  scriptsDir: string | null,
  req: AdoVerbRequest,
  actor: ActorInfo | null,
  capabilities?: readonly string[],
): Promise<AdoVerbResult> {
  if (!req || typeof req !== 'object' || !isVerb(req.verb)) return notRun(req, NOT_A_BOARDS_VERB)
  if (!scriptsDir) return notRun(req, PLUGIN_NOT_FOUND)
  if (!actor) return notRun(req, NO_ACTOR)
  const cap = ADO_VERB_CAPABILITY[req.verb]
  if (capabilities && !capabilities.includes(cap)) return notRun(req, newerPlugin(cap))
  const built = adoVerbArgv(projectPath, req, actor.name)
  if (!built.ok) return notRun(req, built.errors.join('\n'))

  let entry: ConsoleEntry
  try {
    entry = await runPluginScript(scriptsDir, SCRIPT, built.argv)
  } finally {
    // Whatever happened, the plugin may have written: the next read must not be a pre-write cache hit.
    invalidateCommandCenter(projectPath)
  }
  if (entry.exitCode === 0) warmCommandCenter(projectPath)
  return {
    ok: entry.exitCode === 0,
    exitCode: entry.exitCode,
    refused: entry.exitCode === 2,
    stdout: entry.stdout,
    stderr: entry.stderr,
    argv: built.argv,
    verb: req.verb,
    json: documentOf(entry),
  }
}
