# Manual checks · fifteen minutes that no tool replaces

Automated checks find perhaps a third of accessibility problems, and none of the ones about meaning. Before anyone
says a page is accessible, or a release is signed off, a person runs this script on the main flow and records
their name, the date, the browser and the result in the test evidence.

## 1. Keyboard only (4 minutes)
Put the mouse away.
- Tab from the top to the end of the page. Can you always see where focus is?
- Does focus move in the order you would read the page?
- Can every control be operated? Enter and Space on buttons, arrow keys in menus, tabs and radio groups.
- Open a dialog or menu. Does focus go into it, stay in it, and return to the button that opened it on Escape?
- Is there a way to skip repeated navigation and reach the content?
- Does anything trap you?

## 2. Screen reader (5 minutes)
VoiceOver on a Mac or iPhone, NVDA on Windows, TalkBack on Android. Close your eyes for part of it.
- Does the page announce a title that says what it is?
- Move by headings. Do they outline the page?
- Does each control say what it is, what it is called and its state ("Notifications, switch, on")?
- Submit a form with an error. Do you hear that there is an error, and which field?
- Trigger something that updates the page (a search, a save). Is the change announced?
- Do images say something useful, or stay silent when they are decoration?

## 3. Zoom and reflow (2 minutes)
- Browser zoom to 200%: is everything still there and usable?
- Zoom to 400% (or a 320px-wide window): does the content become one column, without scrolling sideways to read?
- Raise the system text size on a phone: does text grow without being cut off?

## 4. Seeing it differently (2 minutes)
- Switch the display to greyscale. Can you still tell good from bad, required from optional, selected from not?
- Turn on dark mode and, on Windows, a high-contrast theme. Is anything invisible?
- Turn on "reduce motion". Does anything still slide, bounce or loop?

## 5. On a real phone (2 minutes)
- Can you hit every control with a thumb, without hitting its neighbour?
- Does the keyboard cover the field you are typing in, or the button you need next?
- Does the right keyboard appear for email, numbers and phone fields?
- Turn the phone sideways.

## Recording the result
One line per section: pass, or what failed and where. Failures become cases in the test lane with the criterion
they break. Anything you could not check (no screen reader available, no device) is written down as **not checked**,
never left out.

## What to say afterwards
"Automated checks pass and a keyboard and VoiceOver pass was done on the refund flow on 14 November by Asha; zoom
and Android were not checked." Not "the page is accessible".
