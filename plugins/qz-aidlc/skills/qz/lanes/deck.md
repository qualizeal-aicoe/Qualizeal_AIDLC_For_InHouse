# Deck lane · a deck that gets its decision

Read the `qz-deck-craft` skill first. A priced proposal belongs in the bid lane, which uses this lane's steps for
its deck. This lane is for any other deck: a leadership or steering-committee update, a solution walkthrough, an
internal demo of this system, a kick-off.

**Review only** (someone hands you a `.pptx`): `deck_review` with `pptx`, `demo_check` on the same file, then
`qz-deck-rehearsal`. Report the findings; do not rebuild the deck unless asked.

1. **Context** (`stage brief`). Audience by role and what each cares about, the decision wanted, the minutes
   available, whether it is presented or sent, and who presents. Ask what is missing, one question at a time.
2. **Message and titles** (`stage storyline`). Write the governing message in one sentence, then the title of every
   slide as a claim, in order (`references/storyline.md`). Show the person that list and nothing else. Do not build
   until they agree the argument.
3. **Spec** (`stage draft`). Pick a kind for each point (`references/slide-kinds.md`); write the deck spec JSON with
   `context`, a `source` on every slide that carries numbers, and notes that are the spoken narrative. Facts come
   from `kf_search` (purpose `recommend`) or from the person; comparable work is described without naming a client.
4. **Build** (`stage render`). `deck_build`. Architecture and screens go in as `image` slides with `alt` text, drawn
   once in `arch-flow` or captured from the demo.
5. **Review** (`stage verify`). `deck_review` with both `spec` and `pptx`, then `demo_check` on the `.pptx`. Fix
   every FAIL; fix each REVIEW or write one line on why it stays. Rebuild and run both again.
6. **Rehearse** (`stage review`). Give `qz-deck-rehearsal` the context, the titles and the notes. For each question
   it returns: answer on a slide, add a backup slide (`"backup": true`, after the close), or put a line in the
   notes. Write `meeting-prep.md` from `references/meeting-prep.md`. It is internal and never goes to the client.
7. **Deliver** (`stage deliver`). The `.pptx`, the narration file, `deck-review.html`, and the meeting preparation,
   in one short list with what is still open. `output_seal` the deck; `report_card`. Sending it to anyone waits for
   the person's yes on the exact file and recipients.
