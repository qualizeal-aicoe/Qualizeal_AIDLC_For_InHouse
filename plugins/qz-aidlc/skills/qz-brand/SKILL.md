---
name: qz-brand
description: QualiZeal brand rules for any UI, demo, splash screen, report, deck or document QualiZeal produces - logos, colours, type, where the logo goes
user-invocable: false
---

Assets: `${CLAUDE_PLUGIN_ROOT}/assets/brand/` — `qz-mark.png` (the Q mark), `qz-wordmark.png` (wordmark for screens), `qz-wordmark-hd.png` (print), `tokens.json` (colours, type, placement).

- Colours: blue `#0096FF` (primary, links, active), coral `#F43D59` (accent, human gates, one highlight per view), navy `#0B1F3A` (headers, dark panels), ink `#16243A` (text), slate `#5B6B82` (secondary text), line `#DCE3EE`, mist `#F4F7FB`.
- Type: Space Grotesk for headings, Inter for text, JetBrains Mono for code and labels.
- Logo placement: app header = wordmark top-left, 28 px high; splash = mark centred (96 px) with the wordmark below; report card = wordmark in the navy header band; decks = the AI CoE template (`${CLAUDE_PLUGIN_ROOT}/templates/qz-aicoe-deck-template.pptx`); documents = wordmark in the header, left.
- Client demos: the client's logo top-left (only a file the person supplies), "Demonstration by QualiZeal" with the mark bottom-right. Never draw or approximate any company's logo.
- Never use another company's brand on QualiZeal's own material. Embed images as files from this folder, never redraw the mark.
