# Day 1 — getting this repo working on your machine

The harness is installed. This is the shortest path from a fresh clone to a change that can
actually merge, plus the handful of things that fail silently if you skip them.

**The fast version:** run `/sprd-doctor`. It checks everything on this page and prints the fix for
anything that is wrong. The rest of this document is what it checks and why each one matters.

---

## 1. Install the tools

| Tool | Why it matters | Get it |
|---|---|---|
| **git** | everything | https://git-scm.com |
| **gh** | branch protection, repo secrets, PR gates | https://cli.github.com |
| **pwsh** (PowerShell 7) | **the hooks run through it** | https://aka.ms/powershell |
| **uv** | runs the harness scripts | https://docs.astral.sh/uv |
| your stack toolchain | build and test (`dotnet`, `node`, `python`…) | per the project |

**`pwsh` is the one people skip**, because PowerShell sounds like a Windows thing. It is
cross-platform, and `.claude/settings.json` registers the hooks through it. Without `pwsh`, the
Stop hook never fires — meaning an agent can end its turn on a red build and nothing stops it. The
repo will look completely normal. This is the single most valuable rung of the checking ladder and
it fails silently.

## 2. Authenticate

```bash
gh auth login      # GitHub: PRs, gates, secrets
az login           # only on Azure DevOps engagements — the ADO MCP server uses your own identity
```

Authentication is **per developer**. Never commit a token or a PAT; nothing in this repo should
ever contain one.

## 3. Approve the MCP servers

On first use, Claude Code asks you to approve the servers in `.mcp.json`. Approve them — they are
the project's shared tooling, committed deliberately. The GitHub server will ask you to sign in
separately the first time you use it; that is expected and per developer.

## 4. Make the scripts executable (macOS / Linux)

```bash
chmod +x .claude/hooks/*.sh scripts/rails/*.sh
```

Git does not reliably carry the executable bit across platforms. Without it the hooks and rails
scripts fail with `Permission denied`, and because the gates fail closed, that surfaces as a
blocked merge with a confusing reason rather than an obvious error. `/sprd-doctor` checks this.

Windows users can skip this — the bit does not exist there, which is also why it is easy to ship
broken from a Windows machine.

## 5. Check the repo secrets

The reviewer workflows need an API credential. Which one depends on what this repo adapted to —
`/sprd-doctor` reads your workflows and names the secret they actually reference. Typically:

```bash
gh secret list                                   # what is already set
gh secret set CLAUDE_CODE_OAUTH_TOKEN            # or ANTHROPIC_API_KEY
```

Without it the grader, correctness and security gates fail closed on every PR. That is the correct
behaviour and a confusing first day.

## 6. Finish the setup tokens

Some values are deliberately left for a human, because only your team knows them — the gated
security paths, the deploy step, the CI artifact name. They look like `<<GATED_PATHS>>` in the
files that need them.

A few placeholders that end up on a command line use a plain `NAME_NOT_SET` sentinel instead —
Windows `cmd.exe` reads `<<` as a redirect and would fail before the tool even starts.

`/sprd-doctor` lists every placeholder still unfilled, in either form, and which phase fills it.
They are not bugs; they are the unfinished half of setup.

## 7. Prove it works before you trust it

Run the doctor:

```bash
/sprd-doctor
```

Then read **`CLAUDE.md`** (the rules every agent session loads) and **`.github/RAILS.md`** (what
each gate does and how to prove it fires). A gate you have never seen fire is a gate you are
guessing about.

---

## What to do when a gate blocks you

**Do not work around it.** The gates exist because agent-written code needs checking that does not
depend on anyone remembering. If a gate is wrong, fix the gate in a PR — with a named human
reviewing the change — rather than bypassing it for this one merge. The exception taken quietly is
how a gate stops being a gate.

If a gate blocks you and you cannot tell why, that is a real bug worth reporting: an unexplainable
block is as much a defect as a missed one.

## Where things live

| Path | What it is |
|---|---|
| `CLAUDE.md` | the rules every agent session loads first |
| `.claude/settings.json` | permissions and hook registration |
| `.claude/hooks/` | the Stop and review gates |
| `.github/workflows/` | CI, grader, correctness, security |
| `.github/RAILS.md` | what each gate does, and the shakedown drills that prove it |
| `scripts/rails/` | branch protection and diff helpers |
| `specs/` | one spec per change — no spec, no build |
| `docs/harness.md` | the tour of what was installed and why |
