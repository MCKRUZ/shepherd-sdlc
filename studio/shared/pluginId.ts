/** The plugin this Studio drives, by the id its manifest declares (`.claude-plugin/plugin.json`
 * "name"). The id is one constant on each side: the plugin's is its manifest; Studio's is this
 * file — the plugin-cache scan, the `--agent` namespace fallback and every "plugin not found"
 * message read it from here, so a rename is one edit, not forty-five.
 *
 * Pure: no node imports, nothing spawned; both processes import it. */

/** `shepherd` — installed as `shepherd@mckruz`; agents are `shepherd:<agent>`. */
export const PLUGIN_ID = 'shepherd'

/** Ids the same plugin was installed under before 2.0. A packaged 2.x Studio beside a
 * not-yet-reinstalled plugin would otherwise report "no plugin", so the cache scan reads these
 * too — after the current id, never ahead of it. */
export const LEGACY_PLUGIN_IDS = ['claude-code-sdlc'] as const

/** The plugin's name as a person reads it in a sentence. */
export const PLUGIN_DISPLAY_NAME = 'Shepherd'

/** The one refusal every script-backed handler returns when no plugin `scripts/` directory
 * could be located — the same words everywhere, so the renderer can match on them. */
export const PLUGIN_NOT_FOUND = `${PLUGIN_DISPLAY_NAME} plugin scripts not found`
