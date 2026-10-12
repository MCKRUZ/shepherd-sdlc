# Acceptance Criteria

Quality benchmarks for the Shepherd plugin, following Microsoft Skills conventions.

## Plugin Installation
- Plugin installs via symlink to `~/.claude/skills/`
- `uv sync` installs Python dependencies without errors
- `uv run scripts/validate_profile.py` executes successfully

## Profile Validation
- Valid profiles pass validation with no errors
- Invalid profiles report specific, actionable error messages
- Both `microsoft-enterprise` and `starter` profiles validate

## State Management
- `init_project.py` creates `.sdlc/` with correct structure
- State file is valid YAML that round-trips without data loss
- Phase transitions are atomic (no partial updates)
- History is append-only

## Gate System
- Gate 1 (Integrity): Catches missing files and empty directories
- Gate 2 (Completeness): Detects TODO, TBD, ${}, PLACEHOLDER, [INSERT] tokens
- Gate 3 (Metrics): Reports coverage thresholds from profile
- Gate 4 (Compliance): Loads and checks compliance-specific gates
- Gate 5 (Consistency): Checks locked metrics against frozen layers from prior phases
- Gate 6 (Quality): Assessed during manual review

## Compliance
- SOC 2 gates fire at correct phases (1, 2, 4, 5, 6, 7, 8, 9)
- Content checks verify required keywords exist in artifacts
- Manual gates clearly state what needs human verification
- Override protocol requires documented justification

## Commands
- `/sprd-setup`: Creates `.sdlc/`, updates CLAUDE.md, validates profile
- `/sprd`: Reads state, loads phase definition, shows actionable guidance
- `/sprd-status`: Generates markdown dashboard with progress bar
- `/sprd-gate`: Runs gate checks, records results, does NOT advance
- `/sprd-next`: Runs gates AND advances if all MUST gates pass

## Microsoft Enterprise Profile
- Stack: C#/.NET 8, Angular 17, Azure, SQL Server
- Quality: 80% coverage min, 100% critical, TDD required
- Compliance: SOC 2 gates at every applicable phase
- Conventions: Conventional commits, immutability, no console.log
- Azure services: App Service, Azure SQL, Key Vault, App Insights, Entra ID
- Authentication: DefaultAzureCredential pattern for Azure services
- Security: OWASP Top 10 mitigations, security review mandatory

## Test Coverage
- 92 unit tests covering all 4 Python scripts
- 89% overall code coverage
- All test scenarios in `references/scenarios.yaml` are testable
