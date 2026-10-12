# /sdlc-spike — Run a Bounded Spike When the Answer Isn't Known Yet

Open a **spike** (`spikes/NNNN-name.md`) for a question the pod cannot yet answer. This is the
escape hatch for the one situation `/sdlc-spec` cannot serve: a story that fails the Definition of
Ready not because it is badly written, but because **nobody knows the answer**.

Writing a confident spec about an unknown is the expensive mistake. It reads as ready, the grader
grades it against fiction, and the pod finds out at merge. A spike finds out first.

**The spike's deliverable is a written finding, not code.** The code is thrown away; the finding
is committed and outlives the branch.

## When this command applies

Use it when an acceptance check cannot be written because the behavior is unverified:

- An integration's real response is undocumented ("does the carrier API deduplicate on our
  idempotency key, or do retries create duplicate claims?").
- A design decision rests on an assumption nobody has tested.
- Two people at triage wrote two different acceptance lines for the same requirement — the
  vague-line test failing out loud because the ground truth is missing.

Do **not** use it as a way to start building without a spec. If the answer is known and the work
just feels large, that is a spec (possibly several).

## Steps

1. **Confirm it is genuinely an unknown, not a vague line.** Ask which acceptance check cannot be
   written, and why. If the answer is "we know, it just needs wording," stop and run `/sdlc-spec`
   instead. Say so plainly rather than opening a spike to avoid the harder conversation.

2. **Get the box and the opener from a human.** Both are required, and neither is yours to decide.
   > "How long should this be boxed — a time box or a token box? And who is opening it: the Pod
   > Lead at triage, or the Architect on a design decision?"

   A spike with no box is unsupervised building. Claude never decides to spike instead of build.

3. **Name what it unblocks.** A decision-list item id, the story that cannot be made ready, or the
   ADR whose assumption is under test. A spike that unblocks nothing is tinkering.

4. **Scaffold the file** (the command owns the script — the user never calls it directly):
   ```bash
   uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/new_spike.py \
     --repo <repo-root> --name "<short name>" --box "<agreed box>" \
     --opened-by "<named human>" --unblocks "<DL-id | story | ADR-NNNN>"
   ```
   In workflow mode pass `--state .sdlc/state.yaml` instead of `--repo`. Then write **The unknown**
   and **Why it can't be specced yet** into the body before any experiment starts — stating the
   question precisely is most of the work, and a spike that cannot state its question is not ready
   to run either.

5. **Work on the spike branch.** `spike/NNNN-name`, never a `spec/` branch:
   ```bash
   git checkout -b spike/<NNNN-name>
   ```
   Build whatever answers the question fastest. Normal quality bars do not apply — this code is
   going to be deleted, and pretending otherwise wastes the box.

6. **Write the finding.** Fill **What was tried**, **Finding**, and **Consequences**. Write it even
   when the answer is "we still don't know" — recording what was ruled out saves the next attempt.
   Then complete **Disposal**.

7. **Commit the finding, delete the branch.** The finding goes to the default branch on its own
   (or folded into the spec it unblocks). The spike branch is deleted.

   **Do not open a PR from the spike branch.** The `spike-guard` CI check fails any PR whose head
   branch matches `spike/`, and there is no label escape. If the work turns out to be worth
   shipping, it gets a spec via `/sdlc-spec` and is rebuilt under the loop.

8. **Close the loop.** Report to the human which decision-list item the finding answers, which spec
   is now writable, and whether any ADR needs revising. An ADR revision is a HIGH-risk spec —
   same bar as any other HIGH change, never a quiet edit.

## Arguments

- No arguments: workflow mode — open a spike in the current `.sdlc/` engagement.
- `--repo <path>`: standalone mode — open a spike in any repo with no `.sdlc/` present.

## Important

- The user runs `/sdlc-spike` — never `new_spike.py` by hand.
- **Claude never decides to spike, never sets the box, and never runs past it without asking.**
  Both the box and the opener are named-human inputs; the script refuses an empty value for either.
- **Spike code never merges.** This is enforced by `spike-guard` in CI, not by good intentions.
  The two named failure modes are the spike that ships (throwaway code talked onto the default
  branch because it "already works") and the spike with no finding (the code is deleted, nothing is
  written down, and the pod pays twice).
- A spike is not a phase and has no gate. It is bounded work inside the Build loop whose output is
  a decision — see the Build loop, section 3a.
