// The ONE place Studio ever shells out from. Every plugin-script call and every
// claude/uv/git/gh invocation goes through runCommand() — that is what makes "every command
// Studio runs appears in the console... nothing runs that does not appear there" true by
// construction rather than by convention: there is nowhere else in the app that can spawn
// a process. The renderer never gets direct process-spawning access at all (see preload).

import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process'
import { performance } from 'node:perf_hooks'
import type { ConsoleEntry } from '../../shared/types'

export type { ConsoleEntry }

// The console log is kept in memory and shown in a panel. Studio pulls every two minutes and
// runs several commands per document each time, so an app left open all day accumulates
// thousands of entries holding every byte those commands printed. Two caps, both about
// keeping a long session healthy rather than about any attack:
//
//   MAX_LOG_ENTRIES — oldest entries fall off. Nobody scrolls back past a few hundred, and
//                     the alternative is a window that slowly eats the machine.
//   MAX_CAPTURED    — one command's output. A project can legitimately contain a very large
//                     file, and reading one whole into a string can take the app down.
const MAX_LOG_ENTRIES = 500
const MAX_CAPTURED = 1_000_000

const log: ConsoleEntry[] = []
const listeners = new Set<(entry: ConsoleEntry) => void>()

/** Keeps the first MAX_CAPTURED characters and says plainly that it stopped there, rather
 * than silently handing back a truncated value that reads like the whole thing. */
function capture(text: string, dropped: number): string {
  return dropped > 0 ? `${text}\n…[${dropped} more characters not captured]` : text
}

export function onConsoleEntry(listener: (entry: ConsoleEntry) => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function getConsoleLog(): ConsoleEntry[] {
  return log
}

let nextId = 1

// Spec 0009's first acceptance check: Studio "never prompts for, stores or displays a
// password or token." An HTTPS git remote routinely embeds one directly in the URL, and
// ordinary git/gh output (git remote -v, push progress, most push failures) echoes it back
// verbatim — so redaction runs centrally here, on every command/arg/stdout/stderr, before
// anything reaches the log. This is a defense-in-depth backstop: Studio's own git/gh calls
// never pass a credential explicitly, but nothing upstream of this function is trusted to
// guarantee that on its own.
//
// The list below covers more than GitHub because Studio spawns more than git and gh. The
// `claude` CLI runs through here too and prints its own credential errors; a repository's
// git remote can point anywhere; and a person pasting a console excerpt into a bug report
// has no idea which line carried a secret. Anything that gets this wrong is unrecoverable
// by redacting later — a token that has already been shown must be rotated, not hidden.
const REDACTIONS: Array<[RegExp, string]> = [
  // A credential embedded in a remote URL — the original case, and still the likeliest.
  [/(https?:\/\/)[^/@\s]+@/g, '$1***@'],
  // GitHub's own token shapes.
  [/\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b/g, '***'],
  [/\bgithub_pat_[A-Za-z0-9_]{20,}\b/g, '***'],
  // Other hosts and vendors Studio or its child processes can encounter.
  [/\bglpat-[A-Za-z0-9_-]{20,}\b/g, '***'],
  [/\bsk-ant-[A-Za-z0-9_-]{20,}\b/g, '***'],
  [/\b(AKIA|ASIA)[A-Z0-9]{16}\b/g, '***'],
  // Bearer headers and JSON Web Tokens, which carry the credential in the clear.
  [/\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]{20,}/gi, '$1 ***'],
  [/\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b/g, '***'],
  // The Azure DevOps extension's own credential variables (code-host providers). An ADO PAT has
  // no fixed prefix to match on, so the VARIABLE is what is recognised — and `AUTH_TOKEN=`
  // slips past the catch-all below because `_` is a word character, so `\btoken` never matches
  // inside it. A bare PAT in prose still relies on the Basic/Bearer/token= backstops.
  [/\b(AZURE_DEVOPS_EXT_PAT|AZURE_DEVOPS_EXT_AUTH_TOKEN)\s*[=:]\s*("[^"]*"|'[^']*'|\S+)/g, '$1=***'],
  // A labelled secret in any shape — the catch-all, deliberately last so a more precise
  // pattern above gets to describe what it matched first.
  [/\b(pass(?:word)?|token|secret|api[_-]?key|auth)\s*[=:]\s*("[^"]*"|'[^']*'|\S+)/gi, '$1=***'],
]

export function redact(text: string): string {
  return REDACTIONS.reduce((out, [pattern, replacement]) => out.replace(pattern, replacement), text)
}

// Masking is for what a person SEES. It rewrites anything shaped like `token: value`, which is right
// for a console panel and an error message and wrong for data: a document that mentions
// `id-token: write` (a GitHub Actions permission) came back from `git show` as `id-token=***` and
// was written into the file that way. So an entry carries two things. `stdout` and `stderr` are
// masked, safe to show or log anywhere. The exact output rides along under this key, for the caller
// that uses it AS data (a document's content, the plugin's JSON about a document, text Claude wrote
// for one) and reads it with rawStdout().
//
// A symbol, so it cannot collide with a field; and it is not serialized, by JSON or by the
// structured clone that carries an entry to the window, so the exact text can never reach the
// screen or the log by accident. Forgetting to use it fails safe: the caller gets the masked text.
const RAW_OUTPUT = Symbol('exactCommandOutput')

/** The command's output exactly as it was written, for a caller that uses it as data. Never show
 * this or put it in a log; `entry.stdout` is the masked copy meant for that. */
export function rawStdout(entry: ConsoleEntry): string {
  return (entry as { [RAW_OUTPUT]?: { stdout: string } })[RAW_OUTPUT]?.stdout ?? entry.stdout
}

// Whether a command ended because its caller aborted it (RunCommandOptions.signal) rather than failing
// on its own. Carried the same way as RAW_OUTPUT, and for the same reason: ConsoleEntry is the shape
// the window renders, and "cancelled" is a fact for the code that asked, not a column for the console.
const CANCELLED = Symbol('cancelledByCaller')

/** True when the command was stopped by its caller's AbortSignal. Anything else that ends with
 * ok:false is a failure. */
export function wasCancelled(entry: ConsoleEntry): boolean {
  return (entry as { [CANCELLED]?: true })[CANCELLED] === true
}

/** Stops a child that was aborted. On Windows `child.kill()` ends only the process it started, and a
 * model run is a tree (the CLI, its hooks, anything a hook launched), so the whole tree goes with
 * `taskkill /T /F`. The only argument is the child's numeric pid, which Node itself assigned. */
/** Every child this module has started and not yet seen end. Electron only quits once its
 * children are gone, and a plugin script or a model run can outlive the window the person
 * closed — the e2e job's worker teardown timed out on exactly that. `killLiveChildren()` runs on
 * `before-quit` (index.ts) so quitting is prompt; nothing else reads this set. */
const liveChildren = new Set<ChildProcessWithoutNullStreams>()

export function liveChildCount(): number {
  return liveChildren.size
}

/** Ends every child still running — the whole tree on Windows — and forgets them. */
export function killLiveChildren(): number {
  const n = liveChildren.size
  for (const child of liveChildren) killChildTree(child)
  liveChildren.clear()
  return n
}

function killChildTree(child: ChildProcessWithoutNullStreams): void {
  if (process.platform === 'win32' && typeof child.pid === 'number') {
    const killer = spawn('taskkill', ['/pid', String(child.pid), '/T', '/F'], { windowsHide: true, stdio: 'ignore' })
    killer.on('error', () => child.kill())
    return
  }
  child.kill()
}

// Windows installs of git and gh from scoop, npm or Chocolatey are batch shims, and a batch
// file can only be started through the command interpreter — so tooling.ts resolves those to
// `cmd.exe /c <shim>`. That hands the interpreter the arguments, and it re-reads them:
// Node quotes an argument only when it contains a space or a quote, so a value with none,
// like a branch name, arrives unquoted and its `&` starts a second command.
//
// Measured on this machine, with a control. Through `cmd.exe /c <shim>`, an argument of
// `main&echo>FILE` reached the shim as just `main` and the injected command RAN. Spawned
// directly against an executable, the identical value arrived intact as one argument and
// nothing ran. So this is the shim routing, not the payload — and git happily permits these
// characters in a branch name, which a cloned repository chooses.
//
// Refused here rather than in git.ts because this is the only function that can start a
// process, so this is the only place the guarantee can actually hold. Nothing Studio does
// needs a branch name or document path containing these characters.
const CMD_METACHARACTERS = /[&|<>^%\r\n"]/

export class UnsafeArgumentError extends Error {}

function isCommandInterpreter(command: string): boolean {
  return /(^|[\\/])cmd(\.exe)?$/i.test(command.trim())
}

export interface RunCommandOptions {
  /** Merged ONTO process.env (never replaces it) — for e.g. GIT_INDEX_FILE, matching the
   * plugin's own run_git() contract exactly. */
  env?: Record<string, string>
  /** Written to the child's stdin, then stdin is closed — for e.g. `git hash-object --stdin`.
   * Stdin is always closed even when this is omitted, so a command that happens to read
   * stdin can never hang Studio waiting for input that will never come. */
  input?: string
  /** Kills the child and records a timeout failure after this many milliseconds. Only for
   * probes that must never hang the app (a broken PATH entry with no such command) —
   * ordinary git/gh/plugin-script calls have no ceiling here, since a slow clash resolution
   * or npm audit taking a while is normal, not a hang. */
  timeoutMs?: number
  /** Called with the REDACTED stdout accumulated so far, as it arrives — spec 0016's chat
   * turns run long enough (a real model call) that a person waiting for the console to show
   * anything at all until the whole command exits would be indistinguishable from a hang.
   * This is the ONE extension point that makes streaming go through runCommand() rather than
   * around it (spec 0016's own Delegation Plan): every other guarantee runCommand makes —
   * recorded to the console, redacted, refused on an unsafe cmd.exe argument — is unchanged
   * and still applies to the final entry. Never called after the command finishes; the final
   * ConsoleEntry from the returned promise is always the complete, authoritative record. */
  onChunk?: (stdoutSoFarRedacted: string) => void
  /** Aborting kills the child (its whole process tree on Windows) and records a failed entry that
   * `wasCancelled()` recognises, once the child has exited (at most CANCEL_EXIT_WAIT_MS later).
   * Already aborted on entry: nothing is started, and the same entry is recorded. Every other
   * guarantee is unchanged: the stop is in the console like any other outcome. */
  signal?: AbortSignal
}

/** How long a cancel waits for the stopped child to exit before it settles anyway. A cancel used to
 * settle the moment the kill was sent, but the kill is asynchronous (on Windows `taskkill` is a
 * process of its own), so the child could still be running when the caller moved on — and Windows
 * refuses to remove a folder that a live process has as its working directory (the Windows CI job's
 * `EBUSY ... rmdir`). Bounded, so a child that ignores the stop cannot hold its caller forever; the
 * entry then says it had not exited. */
export const CANCEL_EXIT_WAIT_MS = 5_000

// A chunk-by-chunk broadcast for every stdout byte would flood the IPC channel to the
// renderer for a chatty command — a real model reply streams in dozens of small pieces.
// Gating by elapsed time keeps "shown as it arrives" honest (nobody waits more than this to
// see the first sign of life) without turning a five-second reply into fifty IPC messages.
const STREAM_MIN_INTERVAL_MS = 150

/** Runs `command args` in `cwd`, records the full result to the console log (always —
 * success or failure), and returns it. Never throws: a failed command is a normal,
 * recorded ConsoleEntry with ok:false, not an exception the caller has to remember to
 * catch — a command that fails must still show up in the console and leave the project
 * untouched, per spec 0008's own acceptance check. */
export function runCommand(
  command: string,
  args: string[],
  cwd: string,
  opts?: RunCommandOptions,
): Promise<ConsoleEntry> {
  // Allocated up front, not at finish, so a live (pending) broadcast and the eventual
  // finished entry share one id — the renderer replaces the placeholder row in place instead
  // of leaving a stale "still running" duplicate behind it.
  const id = String(nextId++)
  const startedAt = new Date().toISOString()
  const start = performance.now()

  return new Promise((resolve) => {
    let stdout = ''
    let stderr = ''
    let settled = false
    let timeoutHandle: ReturnType<typeof setTimeout> | undefined
    let cancelWaitHandle: ReturnType<typeof setTimeout> | undefined
    let lastStreamedAt = 0
    let cancelled = false
    let onAbort: (() => void) | undefined

    const finish = (exitCode: number | null, extraStderr?: string) => {
      // A timeout kill() triggers 'close' too — without this guard that would record and
      // notify twice for one actual command.
      if (settled) return
      settled = true
      if (timeoutHandle) clearTimeout(timeoutHandle)
      if (cancelWaitHandle) clearTimeout(cancelWaitHandle)
      if (onAbort) opts?.signal?.removeEventListener('abort', onAbort)

      const fullStdout = redact(stdout)
      const fullStderr = redact(extraStderr ? `${stderr}\n${extraStderr}`.trim() : stderr)
      const base = {
        id,
        command: redact(command),
        args: args.map(redact),
        cwd,
        startedAt,
        durationMs: Math.round(performance.now() - start),
        exitCode,
        ok: exitCode === 0,
      }

      // The CALLER gets everything. Its stdout is parsed as JSON, and for `git show` it is
      // the actual content of a document being merged — truncating that would silently
      // corrupt someone's work, which is far worse than the memory it costs.
      const entry: ConsoleEntry = { ...base, stdout: fullStdout, stderr: fullStderr }
      Object.defineProperty(entry, RAW_OUTPUT, { value: { stdout }, enumerable: true })
      if (cancelled) Object.defineProperty(entry, CANCELLED, { value: true, enumerable: true })

      // The LOG gets a bounded copy. It is for a person reading a panel, and it is the part
      // that accumulates for as long as the app is open.
      log.push({
        ...base,
        stdout: capture(fullStdout.slice(0, MAX_CAPTURED), fullStdout.length - MAX_CAPTURED),
        stderr: capture(fullStderr.slice(0, MAX_CAPTURED), fullStderr.length - MAX_CAPTURED),
      })
      if (log.length > MAX_LOG_ENTRIES) log.splice(0, log.length - MAX_LOG_ENTRIES)

      for (const listener of listeners) listener(log[log.length - 1])
      resolve(entry)
    }

    if (isCommandInterpreter(command)) {
      // args[0] is '/c' and args[1] is the shim's own path, both Studio's; everything after
      // is caller data, which is what must not be re-read as commands. A refusal is recorded
      // like any other outcome — a command Studio declined to run still belongs in the
      // console, and silently doing nothing would be the worse failure.
      const unsafe = args.slice(2).find((a) => CMD_METACHARACTERS.test(a))
      if (unsafe !== undefined) {
        finish(null, `Refused to run: ${JSON.stringify(unsafe)} contains characters the Windows command interpreter would read as commands.`)
        return
      }
    }

    if (opts?.signal?.aborted) {
      cancelled = true
      finish(null, 'Cancelled before it started.')
      return
    }

    // Python on Windows encodes a piped stdout in the console code page (cp1252), and the plugin
    // prints '→' and '·' — `sprint.py new` died with UnicodeEncodeError on the Windows runner.
    // PYTHONUTF8 makes every spawned script write UTF-8 regardless of the machine's locale; a
    // caller's own env still wins.
    const env = { ...process.env, PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8', ...(opts?.env ?? {}) }

    // spawn() usually reports a bad command through the 'error' event below, asynchronously —
    // but not always. Node's CVE-2024-27980 fix makes an invalid combination (a Windows .cmd
    // shim spawned without shell:true, which tooling.ts's resolved-binary path can produce)
    // throw EINVAL SYNCHRONOUSLY instead. Caught here rather than left to propagate, because
    // this function's whole contract — the one thing that makes "nothing runs that does not
    // appear in the console" true — is that it never throws. Found by this session's own
    // correctness review on the PR that removed tooling.ts's old, now-redundant try/catch.
    let child: ChildProcessWithoutNullStreams
    try {
      child = spawn(command, args, { cwd, windowsHide: true, env })
    } catch (err) {
      finish(null, err instanceof Error ? err.message : String(err))
      return
    }
    liveChildren.add(child)
    child.once('exit', () => liveChildren.delete(child))
    child.once('error', () => liveChildren.delete(child))

    if (opts?.timeoutMs) {
      timeoutHandle = setTimeout(() => {
        child.kill()
        finish(null, `Timed out after ${opts.timeoutMs}ms with no response.`)
      }, opts.timeoutMs)
    }

    if (opts?.signal) {
      onAbort = () => {
        cancelled = true
        // Already exited, only its output still draining: nothing left to wait for.
        if (child.exitCode !== null || child.signalCode !== null) { finish(null, 'Cancelled.'); return }
        // Settles on the child's own 'exit' (Node emits it before 'close', so the entry records the
        // cancel rather than the exit code the kill produced), or after CANCEL_EXIT_WAIT_MS without it.
        child.once('exit', () => finish(null, 'Cancelled.'))
        cancelWaitHandle = setTimeout(
          () => finish(null, `Cancelled. It had not exited ${CANCEL_EXIT_WAIT_MS / 1000} s after it was stopped.`),
          CANCEL_EXIT_WAIT_MS,
        )
        killChildTree(child)
      }
      opts.signal.addEventListener('abort', onAbort, { once: true })
    }

    // Decoded as a stream, not chunk by chunk: a multi-byte character (an em dash, a curly quote)
    // cut by a chunk boundary is otherwise turned into a replacement character, which for a
    // document read through `git show` is silent corruption.
    child.stdout.setEncoding('utf-8')
    child.stderr.setEncoding('utf-8')
    child.stdout.on('data', (chunk: string) => {
      stdout += chunk
      if (!opts?.onChunk) return
      const now = performance.now()
      if (now - lastStreamedAt < STREAM_MIN_INTERVAL_MS) return
      lastStreamedAt = now
      const soFar = redact(stdout)
      opts.onChunk(soFar) // the caller's own use (e.g. chat.ts's incremental stream-json parse)
      // ...and the SAME console-visibility path every other command uses — a live update to
      // the placeholder entry above, not a channel of its own.
      for (const listener of listeners) {
        listener({
          id, command: redact(command), args: args.map(redact), cwd, startedAt,
          durationMs: Math.round(now - start), exitCode: null, stdout: soFar, stderr: '',
          ok: true, pending: true,
        })
      }
    })
    child.stderr.on('data', (chunk: string) => { stderr += chunk })
    child.stdin.end(opts?.input)

    // A live placeholder, broadcast the same way a finished entry is (same listeners, same
    // shape) but never pushed into `log` — getConsoleLog() and the bounded history stay a
    // record of FINISHED commands only. `pending: true` is what tells the renderer this row
    // will be replaced, in place, by the real entry once the command exits.
    if (opts?.onChunk) {
      const placeholder: ConsoleEntry = {
        id, command: redact(command), args: args.map(redact), cwd, startedAt,
        durationMs: 0, exitCode: null, stdout: '', stderr: '', ok: true, pending: true,
      }
      for (const listener of listeners) listener(placeholder)
    }

    child.on('error', (err) => finish(null, err.message))
    child.on('close', (code) => finish(code))
  })
}
