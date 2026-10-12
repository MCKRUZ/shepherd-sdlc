// A name a person typed because the code host could not say who they are (D-OWNER-5).
//
// Azure DevOps signed in with a PAT alone, or either host signed out, gives Studio no identity —
// and every actor-gated control (sign-off, restore, confirm) would stay dark. The owner's ruling:
// a typed name is allowed in exactly that situation, held here per project for THIS process only
// (never in settings.json — a name that outlives the session would be mistaken for an identity
// the host vouched for), and labelled wherever it leaves Studio: `ConnectionInfo.accountSource`
// says 'typed', and Studio's own commit messages carry TYPED_NAME_SUFFIX. The plugin's ledgers
// receive the plain name, because the plugin has no provenance field and a suffix there would
// break `@handle` matching.
//
// Validation is the main process's job (the renderer cannot be trusted to refuse), and it
// mirrors scripts/findings_model.py's `is_ai_actor` word list: this is labelling, not a lock —
// it cannot verify identity, only refuse the obvious.

export const TYPED_ACTOR_MIN = 2
export const TYPED_ACTOR_MAX = 80

/** Appended to Studio's own commit messages when the actor was typed rather than signed in, so
 * the repository's history says which saves carried an unverified name. */
export const TYPED_NAME_SUFFIX = ' (typed name)'

/** scripts/findings_model.py `_AI_ACTOR_RE`, kept in step by hand — the plugin owns the list. */
const AI_LOOKING = /\b(ai|agent|claude|gpt|codex|llm|bot|automated|assistant|copilot)\b/i

export type TypedActorCheck = { ok: true; name: string } | { ok: false; error: string }

/** Trimmed, 2–80 characters, one line, not an AI-looking name. Anything else is refused with a
 * sentence the renderer can show as-is. */
export function validateTypedActor(raw: unknown): TypedActorCheck {
  const name = typeof raw === 'string' ? raw.trim() : ''
  if (name.length < TYPED_ACTOR_MIN) {
    return { ok: false, error: `A name needs at least ${TYPED_ACTOR_MIN} characters — it is recorded against every change you make.` }
  }
  if (name.length > TYPED_ACTOR_MAX) {
    return { ok: false, error: `A name can be at most ${TYPED_ACTOR_MAX} characters.` }
  }
  if (/[\r\n]/.test(name)) {
    return { ok: false, error: 'A name is one line.' }
  }
  if (AI_LOOKING.test(name)) {
    return {
      ok: false,
      error: `Refused: '${name}' reads as an AI/automation, not a named human. Shepherd records who is accountable; an agent may not be that name.`,
    }
  }
  return { ok: true, name }
}

const typedActors = new Map<string, string>()

export function getTypedActor(projectPath: string): string | null {
  return typedActors.get(projectPath) ?? null
}

/** Stores an ALREADY-VALIDATED name. Callers go through validateTypedActor first; this does not
 * re-check so that the refusal reason is decided in one place. */
export function rememberTypedActor(projectPath: string, name: string): void {
  typedActors.set(projectPath, name)
}

/** When a project closes, or when the host turns out to know the person after all. */
export function forgetTypedActor(projectPath?: string): void {
  if (projectPath === undefined) typedActors.clear()
  else typedActors.delete(projectPath)
}
