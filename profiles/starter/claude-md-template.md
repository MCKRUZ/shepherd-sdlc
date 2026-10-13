# SDLC Configuration (auto-injected by /sprd-setup)

## SDLC Plugin Active
This project uses the Shepherd plugin for lifecycle management.
- State: `.sdlc/state.yaml`
- Profile: `starter`
- Commands: `/sprd`, `/sprd-setup`, `/sprd-status`, `/sprd-next`, `/sprd-gate`

## Quality Standards
- Code coverage: minimum 60%
- Max file size: 800 lines, max function: 50 lines
- TDD and formal code review are optional under this profile — raise the bars in
  `.sdlc/profile.yaml` as the project matures

## Coding Conventions
- Commits: `type: description` (feat, fix, refactor, docs, test, chore)
- Branches: `type/description`

## Phase Awareness
Before making changes, check the current SDLC phase with `/sprd`:
- Opening phases (0 Discovery – 3 Foundation): produce and gate the documents; no feature code before Foundation
- Build loop: one spec at a time — Intent → Delegate → Discern; checking happens per change, the author never approves their own work
- Closing phases (7 Documentation – 9 Monitoring, then Close & Transfer): prove docs by cold use, deploy through the existing pipeline, alerts from measured baselines
