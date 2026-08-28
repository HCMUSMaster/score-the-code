---
name: essay-scoring
description: Score a student essay against a provided question and rubric using a two-phase extract-then-score pipeline performed directly, without subagents. Use when the user gives an essay, a question, and a rubric and wants evidence-backed scoring. Trigger on phrases like "score this essay", "grade this response", "rubric", "extract evidence then score".
---

# Essay Scoring (extract-then-score pipeline)

Do the full pipeline yourself in one pass — do not delegate to subagents, do not use the task tool. Evidence extraction must precede the final decision.

Inputs required: the question/context, the scoring rubric, and the full student essay text (verbatim). If any are missing, ask for them before starting. Do not proceed with placeholders.

## Phase 1: Extract evidence

Act as the evidence extractor. Your task: pull evidence and verbatim quotes from the student's response and map them to the provided rubric. Then suggest a score.

Workflow:
1. Read the question/context and the scoring rubric carefully. Note what each rubric level requires.
2. Scan the student essay. For every rubric criterion, collect the matching evidence as short verbatim quotes from the essay text.
3. For each quote, state which rubric criterion it satisfies and why.
4. Note any rubric criteria the essay fails to address.
5. Using only what the quotes support, suggest a score and justify it against the rubric. This is a recommendation only — the final decision happens in Phase 2.

Rules:
- Quotes must be verbatim from the essay. Never paraphrase inside quotation marks.
- Only count evidence that genuinely satisfies the rubric. Do not stretch weak matches.
- If a criterion has no supporting quote, say so explicitly. Do not invent evidence.
- Output structured text: for each criterion, the quote(s) plus a rubric-match note, then your suggested score with justification.
- End this phase with a single JSON object on its own line, in this exact shape (no markdown, no code fence):
{"suggested_score": 3, "evidence": [{"criterion": "short rubric criterion name", "quote": "verbatim essay quote", "matches": true}], "missed": ["criterion name with no supporting quote"]}

## Phase 2: Assign final score

Act as the final decision-maker. Decide the final score by comparing the question, the rubric, and the evidence extracted in Phase 1.

Workflow:
1. Read the question and rubric. Anchor on the rubric's definitions of each score level.
2. Review each piece of evidence from Phase 1. Validate every quote against the original essay text.
3. Resolve conflicts: if the Phase 1 evidence or suggested score conflicts with the rubric or the essay, re-check the essay directly and prioritize the essay text plus rubric over the extraction.
4. Assign the final score, level by level, against the rubric. If no evidence satisfies a higher level, do not award it.
5. Justify the final score with the specific rubric criteria and the evidence that supports or fails it.

## Output format

End your reply with a single JSON object on its own line, in this exact shape (no markdown, no code fence):
{"score": 3, "justification": "one or two sentences citing rubric criteria and supporting evidence"}

Then present to the user, concisely:

- The final score.
- A short justification: which rubric criteria were met, with the supporting quotes.
- Which criteria were missed (if any).

Keep the write-up concise; the user asked for scoring, not a tutorial.
