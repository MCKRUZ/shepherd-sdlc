# Question List
<!-- fixture: a curated list with a block the shape does not declare (Compliance), an entry whose id is still a
     template token, an answer given inline (Q-02), an answer given only in the log (Q-03), and a log row that is
     still a template placeholder (Q-01). Generic names; every address is @example.com. -->

Generated: 2026-09-05T09:00:00Z
Corpus: 4 documents (see `document-registry.md`)
Status: curated-for-workshop <!-- draft | curated-for-workshop | answered -->

## Routing Summary

| Route | Count |
|-------|-------|
| workshop (only the room can answer) | 2 |
| pre-workshop (answerable by email before day 3) | 1 |
| interview (better asked 1:1 on day 5) | 1 |

## Questions

### Block: Problem

#### Q-01: Who owns the order desk?
- **Why it matters:** The desk's hours fix the support window.
- **Source:** DOC-001:section 2
- **Likely answerer:** @priya-n
- **Route:** workshop
- **Answer:** open

#### Q-02: Which carrier feeds are in scope?
- **Why it matters:** Sizing the integration work.
- **Source:** gap — no document addresses this
- **Likely answerer:** Carrier integration lead
- **Route:** pre-workshop
- **Answer:** Two feeds, confirmed on 2026-09-08 <!-- open | [answer, who, date] -->

### Block: Success Metric

#### Q-03: What is the baseline order turnaround?
- **Why it matters:** The one metric needs a starting number.
- **Source:** DOC-002:table 1
- **Likely answerer:** pat.example@example.com
- **Route:** interview
- **Answer:** open

### Block: Compliance

#### Q-04: Is there a data residency rule?
- **Why it matters:** It decides the hosting region.
- **Source:** gap
- **Likely answerer:** Legal
- **Route:** workshop
- **Answer:** ${ANSWER} <!-- open | [answer, who, date] -->

#### Q-${NN}: ${THE_QUESTION}
- **Why it matters:** ${WHAT_IS_BLOCKED_UNTIL_ANSWERED}
- **Source:** ${SOURCE}
- **Likely answerer:** ${ROLE_OR_NAME}
- **Route:** ${ROUTE}
- **Answer:** ${ANSWER}

## Answer Log

<!-- Filled during/after the workshop and interviews. -->

| ID | Answered by | Answer | Date |
|----|-------------|--------|------|
| Q-03 | Finance contact | Four days at the 2026-08 baseline | 2026-09-09 |
| Q-01 | ${WHO} | ${ANSWER} | ${DATE} |
