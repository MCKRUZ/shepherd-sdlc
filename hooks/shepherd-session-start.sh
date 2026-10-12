#!/usr/bin/env bash
# sdlc-session-start.sh
# Hook: Runs at session start to load SDLC context (bash twin of sdlc-session-start.ps1 —
# same output contract; used as the fallback on hosts without PowerShell 7).
# Reads .sdlc/state.yaml and outputs current phase context.

set -u

sdlc_dir="$PWD/.sdlc"
state_file="$sdlc_dir/state.yaml"

# No SDLC state — silently exit (project may not use SDLC)
[ -f "$state_file" ] || exit 0

content=$(cat "$state_file")

# Extract key fields (basic YAML parsing, mirrors the ps1 regexes)
extract_field() {
    printf '%s\n' "$content" | grep -m1 -E "$1:[[:space:]]*" \
        | sed -E "s/^.*$1:[[:space:]]*\"?([^\"]*)\"?[[:space:]]*$/\1/" \
        | sed -E 's/[[:space:]]+$//'
}

phase_id=$(extract_field "current_phase")
[ -n "$phase_id" ] || exit 0

phase_name=$(extract_field "phase_name");    [ -n "$phase_name" ] || phase_name="unknown"
profile_id=$(extract_field "profile_id");    [ -n "$profile_id" ] || profile_id="unknown"
project_name=$(extract_field "project_name"); [ -n "$project_name" ] || project_name="unknown"

# Phase id -> canonical display name
display_name=""
case "$phase_id" in
    0) display_name="Discovery" ;;
    1) display_name="Requirements" ;;
    2) display_name="Design" ;;
    3) display_name="Foundation" ;;
    build) display_name="Build Loop" ;;
    7) display_name="Documentation" ;;
    8) display_name="Deployment" ;;
    9) display_name="Monitoring" ;;
    close) display_name="Close & Transfer" ;;
esac
[ -n "$display_name" ] || display_name="$phase_name"

# Lifecycle order — used to sort frozen layers and gate the health check
phase_order() {
    case "$1" in
        0) echo 0 ;; 1) echo 1 ;; 2) echo 2 ;; 3) echo 3 ;;
        build) echo 4 ;; 7) echo 5 ;; 8) echo 6 ;; 9) echo 7 ;; close) echo 8 ;;
        *) echo -1 ;;
    esac
}

# Count artifacts in current phase directory (slug = NN-name for numbered phases, bare for build/close)
case "$phase_id" in
    ''|*[!0-9]*) artifact_slug="$phase_id" ;;
    *) artifact_slug=$(printf '%02d-%s' "$phase_id" "$phase_name") ;;
esac
artifact_dir="$sdlc_dir/artifacts/$artifact_slug"
artifact_count=0
if [ -d "$artifact_dir" ]; then
    artifact_count=$(find "$artifact_dir" -type f 2>/dev/null | wc -l | tr -d '[:space:]')
fi

# Output context for Claude
echo "[SDLC] Project: $project_name | Profile: $profile_id | Phase $phase_id: $display_name | Artifacts: $artifact_count"
echo "[SDLC] Commands: /sdlc (guidance) | /sdlc-status (dashboard) | /sdlc-gate (check) | /sdlc-next (advance) | /sdlc-coach (coaching)"

# Phase-specific behavioral reminder
phase_reminder=""
case "$phase_id" in
    0) phase_reminder="Focus on understanding the problem, not writing code." ;;
    1) phase_reminder="Ensure changes trace back to documented requirements." ;;
    2) phase_reminder="Document architectural decisions as ADRs." ;;
    3) phase_reminder="Build the factory (harness, rails, dev infra) and a thin walking skeleton." ;;
    build) phase_reminder="One spec at a time: Intent -> Delegate -> Discern. Check per change, never in a batch. The author never approves their own work. Refinement for the next sprint runs alongside — /sdlc-refine; the board is /sdlc-sprint." ;;
    7) phase_reminder="Prove docs by cold use. Finalize ADRs." ;;
    8) phase_reminder="Promote the proven artifact. Document the rollback plan." ;;
    9) phase_reminder="Configure alerts from measured baselines. Run the drill." ;;
    close) phase_reminder="Prove the client can run it without us. Audit the harness, revoke access, harvest." ;;
esac
[ -n "$phase_reminder" ] && echo "[SDLC-PHASE] $phase_reminder"

# --- Active sprints (Sprint Team Layer): one line per .sdlc/sprints/*.md whose state is not closed ---
# grep/sed only — no date arithmetic, no JSON, no uv. Silent when the directory is absent.
sprint_field() {
    # $1 = file, $2 = key. First "key:" line wins; a quoted value is taken verbatim, else a trailing "# comment" is stripped.
    grep -a -m1 -E "^$2:" "$1" 2>/dev/null | tr -d '\r' | sed -E "s/^$2:[[:space:]]*//" \
        | sed -E -e 's/^"([^"]*)".*$/\1/' -e 't' -e 's/[[:space:]]*#.*$//' -e 's/[[:space:]]+$//'
}
sprints_dir="$sdlc_dir/sprints"
if [ -d "$sprints_dir" ]; then
    for f in "$sprints_dir"/*.md; do
        [ -f "$f" ] || continue
        sprint_state=$(sprint_field "$f" "state")
        [ -n "$sprint_state" ] || continue            # no state line — not a sprint record we understand
        [ "$sprint_state" = "closed" ] && continue
        sprint_id=$(sprint_field "$f" "sprint"); [ -n "$sprint_id" ] || sprint_id=$(basename "$f" .md)
        sprint_goal=$(sprint_field "$f" "goal")
        sprint_start=$(sprint_field "$f" "start")
        sprint_end=$(sprint_field "$f" "end")
        echo "[SDLC-SPRINT] $sprint_id ($sprint_state) — \"$sprint_goal\" — $sprint_start → $sprint_end"
    done
fi

# Take the first N whitespace-separated words of stdin, joined by single spaces
first_words() {
    tr -s '[:space:]' ' ' | sed -E 's/^ //; s/ $//' | cut -d' ' -f1-"$1"
}

# --- Tier 1: Foundation Context ---
constitution_path="$sdlc_dir/constitution.md"
if [ -f "$constitution_path" ]; then
    foundation=$(first_words 375 < "$constitution_path")
    if [ -n "$foundation" ]; then
        echo "[SDLC-CONTEXT:FOUNDATION] $foundation"
    fi
fi

# --- Tier 2: Frozen Layers (most recent 3, loaded oldest-first) ---
layers_dir="$sdlc_dir/context/layers"
if [ -d "$layers_dir" ]; then
    layer_list=""
    for f in "$layers_dir"/phase*.md; do
        [ -f "$f" ] || continue
        base=$(basename "$f" .md)
        id_part=${base#phase}; id_part=${id_part%%-*}
        order=$(phase_order "$id_part")
        [ "$order" -lt 0 ] && order=999
        layer_list="$layer_list$order|$f
"
    done
    if [ -n "$layer_list" ]; then
        selected=$(printf '%s' "$layer_list" | sort -t'|' -k1,1n | tail -n 3 | cut -d'|' -f2-)
        count=$(printf '%s\n' "$selected" | grep -c .)
        echo "[SDLC-CONTEXT:LAYERS] Loading $count frozen layer(s)"
        printf '%s\n' "$selected" | while IFS= read -r layer; do
            [ -f "$layer" ] || continue
            echo "[SDLC-CONTEXT:LAYER:$(basename "$layer" .md)]"
            cat "$layer"
            echo ""
            echo "[/SDLC-CONTEXT:LAYER]"
        done
    fi
fi

# --- Tier 1.5: Document Intake Index (opt-in) ---
intake_index="$sdlc_dir/context/intake/index.md"
if [ -f "$intake_index" ]; then
    intake_words=$(wc -w < "$intake_index" | tr -d '[:space:]')
    if [ "$intake_words" -gt 0 ]; then
        echo "[SDLC-CONTEXT:INTAKE] Document intake index loaded ($intake_words words)"
        echo "[SDLC-CONTEXT:INTAKE-INDEX]"
        if [ "$intake_words" -gt 3750 ]; then
            # Respect token budget — truncate at ~3750 words (~5000 tokens)
            first_words 3750 < "$intake_index"
            echo "[TRUNCATED — full index at .sdlc/context/intake/index.md]"
        else
            cat "$intake_index"
            echo ""
        fi
        echo "[/SDLC-CONTEXT:INTAKE-INDEX]"
    fi
fi

# --- Session Health Check (opt-in, Build loop and later) + convention reminders ---
profile_file="$sdlc_dir/profile.yaml"
if [ -f "$profile_file" ]; then
    if grep -qE 'immutability:[[:space:]]*true' "$profile_file"; then
        echo "[SDLC-CONVENTION] Use immutable patterns (records, with-expressions, spread operators)."
    fi
    if grep -qE 'no_console_log:[[:space:]]*true' "$profile_file"; then
        echo "[SDLC-CONVENTION] No console.log in production code."
    fi

    health_enabled=$(awk '/session_health_check:/{f=1} f && /enabled:/{gsub(/[" ]/,"",$2); print $2; exit}' "$profile_file")
    health_min_phase=$(awk '/session_health_check:/{f=1} f && /min_phase:/{gsub(/[" ]/,"",$2); print $2; exit}' "$profile_file")
    [ -n "$health_min_phase" ] || health_min_phase="build"

    cur_order=$(phase_order "$phase_id")
    min_order=$(phase_order "$health_min_phase")
    [ "$min_order" -lt 0 ] && min_order=4

    if [ "$health_enabled" = "true" ] && [ "$cur_order" -ge "$min_order" ]; then
        echo "[SDLC-HEALTH] Health check is enabled. Run the configured smoke test before starting new work (Build loop pre-flight check)."
    fi
fi

exit 0
