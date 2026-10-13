---
sprint: "SNN"
goal: ""
start: "YYYY-MM-DD"
end: "YYYY-MM-DD"            # default: last business day of a 10-business-day window (start is day 1)
state: planning              # planning | ready | closed
target: 0                    # how many specs to slate (a count, never a size)
mix: ""                      # by risk tier, e.g. "HIGH:1,MEDIUM:2,LOW:3"; counts sum <= target
board_ref: ""                # manual mapping only, e.g. "ADO Iteration 6"; nothing reads it
readied_by: ""
closed_by: ""
created: "YYYY-MM-DD"
---
# Sprint SNN

## Goal

## Slate
<!-- Rendered by `sprint.py slate/unslate/ready/close` from spec frontmatter — never hand-edit; run /sprd-sprint status for the live view. -->

## Close
<!-- Written by `sprint.py close`: | spec | outcome (kept | carried → SNN | dropped) | by | reason | -->
