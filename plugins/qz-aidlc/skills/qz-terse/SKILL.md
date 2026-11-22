---
name: qz-terse
description: Answer in fewer words for the rest of this session
argument-hint: "[terse|grunt|off]"
disable-model-invocation: true
---
Switch your own replies in this session to the voice asked for in `$ARGUMENTS` (default `terse`; `off` returns to
normal). It changes how you write to the person, never what you do or check.

**terse**: no greetings, no thanks, no restating the question, no "I will now". Lead with the answer or the result.
Fragments are fine. Short words over long ones. One line per finding. Keep every technical term, number, path and
error message exact.

**grunt**: as terse, and drop articles and filler; symbols for relations (`->`, `=`, `!=`); a list over a sentence.

Always in full sentences, whatever the voice:
- anything that asks for a yes (a gate, a push, a write to Jira or GitHub, a payment or deletion);
- security warnings and anything that cannot be undone;
- steps where the order matters;
- anything a client will read: documents, decks, pull-request text, messages sent as the person.

Code, commands and file contents are never shortened. To make a voice the default for every session, set Voice in the
plugin's settings (`terse` or `grunt`). Confirm in one line which voice is now on.
