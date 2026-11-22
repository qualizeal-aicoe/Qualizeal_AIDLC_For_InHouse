# Report lane

- `report_card` writes the HTML card for the current run (or `run` = a run id) and returns the headline numbers. Tell the person the HTML path in one line and the two numbers that matter most.
- Every number on the card is labelled MEASURED, ESTIMATED, ASSUMED or NOT KNOWN. Never present an ESTIMATED, ASSUMED or NOT KNOWN number as measured.
- `audit_verify` checks the audit chain; `redteam` runs the guard's red-team suite.
- Record a takeover with `takeover` (stage, layer, why) only when the person says they took over; ask for the layer with five options if they did not say.
- Asked where the tokens went: `report_card` returns `context_tokens_estimated` and `do_next`. Give the per-stage split from the card and the `do_next` lines as they are; the context figure is ESTIMATED, the per-stage counts are MEASURED.
