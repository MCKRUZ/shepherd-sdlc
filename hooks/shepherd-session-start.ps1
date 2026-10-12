# sdlc-session-start.ps1
# Hook: Runs at session start to load SDLC context
# Reads .sdlc/state.yaml and outputs current phase context

param()

# Claude Code reads this output as UTF-8. On Windows the console default is an OEM code page, which turns the
# em dash and arrow in the [SDLC-SPRINT] line into "-" and a control character; say what the output is.
try { [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false) } catch { }

$sdlcDir = Join-Path $PWD ".sdlc"
$stateFile = Join-Path $sdlcDir "state.yaml"

if (-not (Test-Path $stateFile)) {
    # No SDLC state — silently exit (project may not use SDLC)
    exit 0
}

# Read state.yaml (basic YAML parsing for key fields)
$content = Get-Content $stateFile -Raw

# Extract current phase (ids may be non-numeric: build, close)
$phaseMatch = [regex]::Match($content, 'current_phase:\s*"?([^"\r\n]+)"?')
$phaseNameMatch = [regex]::Match($content, 'phase_name:\s*"?([^"\r\n]+)"?')
$profileMatch = [regex]::Match($content, 'profile_id:\s*"?([^"\r\n]+)"?')
$projectMatch = [regex]::Match($content, 'project_name:\s*"?([^"\r\n]+)"?')

if ($phaseMatch.Success) {
    $phaseId = $phaseMatch.Groups[1].Value.Trim()
    $phaseName = if ($phaseNameMatch.Success) { $phaseNameMatch.Groups[1].Value } else { "unknown" }
    $profileId = if ($profileMatch.Success) { $profileMatch.Groups[1].Value } else { "unknown" }
    $projectName = if ($projectMatch.Success) { $projectMatch.Groups[1].Value } else { "unknown" }

    $phaseNames = @{
        "0"     = "Discovery"
        "1"     = "Requirements"
        "2"     = "Design"
        "3"     = "Foundation"
        "build" = "Build Loop"
        "7"     = "Documentation"
        "8"     = "Deployment"
        "9"     = "Monitoring"
        "close" = "Close & Transfer"
    }

    # Lifecycle order — used to sort frozen layers and gate the health check
    $phaseOrder = @{ "0"=0; "1"=1; "2"=2; "3"=3; "build"=4; "7"=5; "8"=6; "9"=7; "close"=8 }

    $displayName = $phaseNames[$phaseId]
    if (-not $displayName) { $displayName = $phaseName }

    # Count artifacts in current phase directory (slug = NN-name for numbered phases, bare for build/close)
    $artifactSlug = if ($phaseId -match '^\d+$') { "{0:D2}-{1}" -f [int]$phaseId, $phaseName } else { $phaseId }
    $artifactDir = Join-Path $sdlcDir "artifacts" $artifactSlug
    $artifactCount = 0
    if (Test-Path $artifactDir) {
        $artifactCount = (Get-ChildItem $artifactDir -File -Recurse -ErrorAction SilentlyContinue | Measure-Object).Count
    }

    # Output context for Claude
    Write-Output "[SDLC] Project: $projectName | Profile: $profileId | Phase $phaseId`: $displayName | Artifacts: $artifactCount"
    Write-Output "[SDLC] Commands: /sdlc (guidance) | /sdlc-status (dashboard) | /sdlc-gate (check) | /sdlc-next (advance) | /sdlc-coach (coaching)"

    # Phase-specific behavioral reminder (folded in from the retired PreToolUse phase-inject hook,
    # which could not inject context — PreToolUse stdout is not shown to Claude. SessionStart is.)
    $phaseReminders = @{
        "0"     = "Focus on understanding the problem, not writing code."
        "1"     = "Ensure changes trace back to documented requirements."
        "2"     = "Document architectural decisions as ADRs."
        "3"     = "Build the factory (harness, rails, dev infra) and a thin walking skeleton."
        "build" = "One spec at a time: Intent -> Delegate -> Discern. Check per change, never in a batch. The author never approves their own work. Refinement for the next sprint runs alongside — /sdlc-refine; the board is /sdlc-sprint."
        "7"     = "Prove docs by cold use. Finalize ADRs."
        "8"     = "Promote the proven artifact. Document the rollback plan."
        "9"     = "Configure alerts from measured baselines. Run the drill."
        "close" = "Prove the client can run it without us. Audit the harness, revoke access, harvest."
    }
    $phaseReminder = $phaseReminders[$phaseId]
    if ($phaseReminder) { Write-Output "[SDLC-PHASE] $phaseReminder" }

    # --- Active sprints (Sprint Team Layer): one line per .sdlc/sprints/*.md whose state is not closed ---
    # Regex only — no date arithmetic, no JSON. Silent when the directory is absent. Wrapped in try/catch
    # so a malformed file never throws: a thrown error would make hooks.json's `pwsh ... || bash ...`
    # run the bash twin too and double-print.
    function Get-SprintField([string]$text, [string]$key) {
        # First "key:" line wins; a quoted value is taken verbatim, else a trailing "# comment" is stripped.
        $m = [regex]::Match($text, '(?m)^' + $key + ':[ \t]*(?:"([^"\r\n]*)"|([^#\r\n]*))')
        if (-not $m.Success) { return $null }
        if ($m.Groups[1].Success) { return $m.Groups[1].Value.Trim() }
        return $m.Groups[2].Value.Trim()
    }
    $sprintsDir = Join-Path $sdlcDir "sprints"
    if (Test-Path $sprintsDir) {
        try {
            $sprintFiles = @(Get-ChildItem $sprintsDir -Filter "*.md" -File -ErrorAction SilentlyContinue | Sort-Object Name)
            foreach ($sprintFile in $sprintFiles) {
                try {
                    $sprintText = Get-Content $sprintFile.FullName -Raw -ErrorAction SilentlyContinue
                    if (-not $sprintText) { continue }
                    $sprintState = Get-SprintField $sprintText "state"
                    if (-not $sprintState) { continue }            # no state line — not a sprint record we understand
                    if ($sprintState -eq "closed") { continue }
                    $sprintId = Get-SprintField $sprintText "sprint"
                    if (-not $sprintId) { $sprintId = $sprintFile.BaseName }
                    $sprintGoal = Get-SprintField $sprintText "goal"
                    $sprintStart = Get-SprintField $sprintText "start"
                    $sprintEnd = Get-SprintField $sprintText "end"
                    Write-Output "[SDLC-SPRINT] $sprintId ($sprintState) — `"$sprintGoal`" — $sprintStart → $sprintEnd"
                } catch { }
            }
        } catch { }
    }

    # --- Tier 1: Foundation Context ---
    $constitutionPath = Join-Path $sdlcDir "constitution.md"
    if (Test-Path $constitutionPath) {
        $constitutionContent = Get-Content $constitutionPath -Raw -ErrorAction SilentlyContinue
        if ($constitutionContent) {
            # Extract mission/principles (first ~375 words for ~500 token budget)
            $words = ($constitutionContent -split '\s+') | Select-Object -First 375
            $foundation = ($words -join ' ')
            Write-Output "[SDLC-CONTEXT:FOUNDATION] $foundation"
        }
    }

    # --- Tier 2: Frozen Layers (most recent 3) ---
    $layersDir = Join-Path $sdlcDir "context" "layers"
    if (Test-Path $layersDir) {
        $layers = Get-ChildItem $layersDir -Filter "phase*.md" -ErrorAction SilentlyContinue |
            Sort-Object { $idPart = (($_.BaseName -replace '^phase','') -replace '-.*$',''); if ($phaseOrder.ContainsKey($idPart)) { $phaseOrder[$idPart] } else { 999 } } -Descending |
            Select-Object -First 3
        if ($layers) {
            # Reverse to load oldest first (chronological order)
            [array]::Reverse($layers)
            Write-Output "[SDLC-CONTEXT:LAYERS] Loading $($layers.Count) frozen layer(s)"
            foreach ($layer in $layers) {
                $layerContent = Get-Content $layer.FullName -Raw -ErrorAction SilentlyContinue
                if ($layerContent) {
                    Write-Output "[SDLC-CONTEXT:LAYER:$($layer.BaseName)]"
                    Write-Output $layerContent
                    Write-Output "[/SDLC-CONTEXT:LAYER]"
                }
            }
        }
    }

    # --- Tier 1.5: Document Intake Index (opt-in) ---
    $intakeIndexPath = Join-Path $sdlcDir "context" "intake" "index.md"
    if (Test-Path $intakeIndexPath) {
        $intakeContent = Get-Content $intakeIndexPath -Raw -ErrorAction SilentlyContinue
        if ($intakeContent) {
            # Respect token budget — truncate at ~3750 words (~5000 tokens)
            $intakeWords = ($intakeContent -split '\s+')
            if ($intakeWords.Count -gt 3750) {
                $intakeContent = ($intakeWords | Select-Object -First 3750) -join ' '
                $intakeContent += "`n[TRUNCATED — full index at .sdlc/context/intake/index.md]"
            }
            Write-Output "[SDLC-CONTEXT:INTAKE] Document intake index loaded ($($intakeWords.Count) words)"
            Write-Output "[SDLC-CONTEXT:INTAKE-INDEX]"
            Write-Output $intakeContent
            Write-Output "[/SDLC-CONTEXT:INTAKE-INDEX]"
        }
    }

    # --- Session Health Check (opt-in, Phase 4+) ---
    # Detects if health check is configured and reminds the agent to run it.
    # The actual check is executed by the agent in Phase 4 Step 0 (not in this hook)
    # because: (1) the agent's Bash tool is cross-platform, (2) the agent can react
    # to failures intelligently, (3) the user sees what's happening.
    $profileFile = Join-Path $sdlcDir "profile.yaml"
    if (Test-Path $profileFile) {
        $profileContent = Get-Content $profileFile -Raw -ErrorAction SilentlyContinue

        # Convention reminders (folded in from the retired phase-inject hook)
        if ($profileContent -match 'immutability:\s*true') {
            Write-Output "[SDLC-CONVENTION] Use immutable patterns (records, with-expressions, spread operators)."
        }
        if ($profileContent -match 'no_console_log:\s*true') {
            Write-Output "[SDLC-CONVENTION] No console.log in production code."
        }

        $healthEnabled = [regex]::Match($profileContent, 'session_health_check:[\s\S]*?enabled:\s*(true|false)')
        $healthMinPhase = [regex]::Match($profileContent, 'session_health_check:[\s\S]*?min_phase:\s*"?([^"\s\r\n]+)"?')

        $isEnabled = $healthEnabled.Success -and $healthEnabled.Groups[1].Value -eq "true"
        $minPhaseId = if ($healthMinPhase.Success) { $healthMinPhase.Groups[1].Value.Trim() } else { "build" }
        $curOrder = if ($phaseOrder.ContainsKey($phaseId)) { $phaseOrder[$phaseId] } else { -1 }
        $minOrder = if ($phaseOrder.ContainsKey($minPhaseId)) { $phaseOrder[$minPhaseId] } else { 4 }

        if ($isEnabled -and $curOrder -ge $minOrder) {
            Write-Output "[SDLC-HEALTH] Health check is enabled. Run the configured smoke test before starting new work (Build loop pre-flight check)."
        }
    }
}
