# SDLC Configuration (auto-injected by /sprd-setup)

## SDLC Plugin Active
This project uses the Shepherd plugin for lifecycle management.
- State: `.sdlc/state.yaml`
- Profile: `creative-tooling`
- Commands: `/sprd`, `/sprd-setup`, `/sprd-status`, `/sprd-next`, `/sprd-gate`

## Stack: Creative Tooling
- **Language:** Python (uv-run scripts)
- **Testing:** pytest
- **Domain:** creative-pipeline tooling — technique registry, model/node inventory, character profiles, skill prompts

## Quality Standards
- Code coverage: minimum 80%
- Max file size: 400 lines, max function: 50 lines
- TDD required: write tests first
- Code review required before merge
- Security review required for sensitive code

## Evaluation Criteria (enforced at gates)
- **Registry schema compliance** (fail): registry YAML validates against `registry/_schema.yaml`
- **Profile schema compliance** (fail): character profile YAML validates against `profiles/_schema.yaml` — no unrecognized keys, all required fields present
- **Skill prompt clarity** (fail): skill `.md` files use imperative RFC 2119 instructions, no vague language, no debug artifacts; every decision point has an explicit default
- **Inventory awareness** (fail): models, custom nodes, and ComfyUI endpoints resolve via `inventory.resolve()` — never hardcoded paths or string literals
- **Cross-reference integrity** (fail): no dangling references across registry, inventory, and profiles (`requires.custom_nodes`, `lora_stack`, `supersedes` all point at real entries)
- **Data freshness** (warn): no technique 'discovered' >30 days without a test result; no technique tested >90 days ago in an active character profile

## Coding Conventions
- Commits: `type: description` (feat, fix, refactor, docs, test, chore)
- Branches: `type/description`
- No debug remnants in skill files
- Validate at trust boundaries; trust internal code

## Compliance
- No compliance frameworks, but the audit trail in `.sdlc/state.yaml` is maintained

## Phase Awareness
Before making changes, check the current SDLC phase with `/sprd`:
- Opening phases (0 Discovery – 3 Foundation): produce and gate the documents; no feature code before Foundation
- Build loop: one spec at a time — Intent → Delegate → Discern; TDD required, checking happens per change, the author never approves their own work
- Closing phases (7 Documentation – 9 Monitoring, then Close & Transfer): prove docs by cold use, deploy through the existing pipeline, alerts from measured baselines
