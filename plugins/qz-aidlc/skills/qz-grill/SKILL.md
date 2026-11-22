---
name: qz-grill
description: Question a plan or design until it holds up, one question at a time
argument-hint: "[plan, design, story or file]"
disable-model-invocation: true
---
Grill the plan in `$ARGUMENTS` (or the one in this conversation) until you and the person understand it the same way.

1. Read what exists first: the plan, the story, `project_memory [show]`, and the code it touches (`code_explore`).
   Never ask what the code or the documents already answer; look it up and say what you found.
2. Walk the decision tree from the root: goal and who it is for, then scope, then each design choice, then the
   risks. Resolve what a branch depends on before going down it.
3. Ask **one question at a time**, multiple choice where possible, and give your recommended answer with one line of
   why. Wait for the answer before the next question.
4. Push back where the answer is vague, contradicts an earlier one, or hides an assumption. Name the assumption.
5. Keep a running file `docs/questions.md` (or `docs/<KEY>/questions.md` for a story): question, your
   recommendation, the person's answer, and what it changed. File it with `project_file` at the end.
6. A word the team uses in a particular way goes into `docs/glossary.md`: the term, what it means here, what it does
   not mean. A choice that is hard to undo becomes a decision record (`arch [adr, new, --file F]` when the architect
   lane is in use).
7. Stop when the open questions are ones only someone else can answer. List them, with who should answer each.

End with three lines: what is now settled, what is still open, the next step.
