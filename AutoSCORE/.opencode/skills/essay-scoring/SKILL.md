---
name: essay-scoring
description: Score a student essay against a provided question and rubric by combining the rubric-extractor and scorer agents. Use when the user gives an essay, a question, and a rubric and wants evidence-backed scoring. Trigger on phrases like "score this essay", "grade this response", "rubric", "extract evidence then score".
---

# Essay Scoring (extract-then-score pipeline)

Score any student essay by running the two subagents in sequence: `@rubric-extractor` first, then `@scorer`. Do not score in a single ad-hoc pass — evidence extraction must precede the final decision.

## Step 1: rubric-extractor

Invoke `@rubric-extractor` with the inputs in this order:

1. The question/context.
2. The scoring rubric.
3. The full student essay text (verbatim).

What it returns: verbatim quotes mapped to rubric criteria, unmet criteria flagged, and a suggested score. This is a recommendation only.

## Step 2: scorer

Invoke `@scorer` with:

1. The same question/context.
2. The same rubric.
3. rubric-extractor's full evidence output (all quotes + suggested score).
4. The original essay text, if the extractor's claims need verification.

What it returns: the final score with justification citing rubric criteria and supporting evidence.

## Handoff rules

- Never skip Step 1. The scorer must see extractor evidence.
- If the user supplies no rubric, ask for one before starting. The rubric is mandatory for both steps.
- If the user supplies no essay or question, ask for them. Do not proceed with placeholders.
- Preserve verbatim quotes exactly between the two agents — do not paraphrase evidence in the handoff.
- If the extractor and scorer conflict, the scorer resolves by prioritizing essay text + rubric (per its instructions).

## Output format

Present to the user:

- The final score.
- A short justification: which rubric criteria were met, with the supporting quotes.
- Which criteria were missed (if any).

Keep the write-up concise; the user asked for scoring, not a tutorial.
