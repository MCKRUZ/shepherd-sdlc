# SDLC Configuration (auto-injected by /sprd-setup)

## SDLC Plugin Active
This project uses the Shepherd plugin for lifecycle management.
- State: `.sdlc/state.yaml`
- Profile: `microsoft-enterprise`
- Commands: `/sprd`, `/sprd-setup`, `/sprd-status`, `/sprd-next`, `/sprd-gate`

## Stack: Microsoft Enterprise
- **Backend:** C# / .NET 10 / Entity Framework Core / xUnit
- **Frontend:** TypeScript / Angular 22 / NgRx / Playwright
- **Database:** SQL Server with EF Core migrations
- **Cloud:** Azure (App Service, Azure SQL, Key Vault, App Insights)
- **CI/CD:** GitHub Actions

## Quality Standards
- Code coverage: minimum 80%, critical paths 100%
- Max file size: 800 lines, max function: 50 lines
- TDD required: write tests first
- Code review required before merge
- Security review required for auth/payment/sensitive code

## Coding Conventions
- Commits: `type: description` (feat, fix, refactor, docs, test, chore)
- Branches: `type/ticket-description`
- Immutability: prefer immutable patterns (records, `with`, spread operators)
- No console.log in production code

## Compliance: SOC 2
- Audit trail maintained in `.sdlc/state.yaml`
- Change approval: peer review required
- Security review per change inside the Build loop (the security rail blocks at merge)
- Documentation current at the Phase 7 (Documentation) gate

## Phase Awareness
Before making changes, check the current SDLC phase with `/sprd`:
- Opening phases (0 Discovery – 3 Foundation): produce and gate the documents; no feature code before Foundation
- Build loop: one spec at a time — Intent → Delegate → Discern; TDD required, checking happens per change, the author never approves their own work
- Closing phases (7 Documentation – 9 Monitoring, then Close & Transfer): prove docs by cold use, deploy through the existing pipeline, alerts from measured baselines
