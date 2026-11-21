package agent

// Input and output filters: gates 1 and 2 of the six. What a person sends is checked before the agent reads it, and
// the reply before anyone sees it. Pattern-based, offline and fast; a team can put a classifier behind the same calls.
//
// Input: a message that reads like an instruction to change how the agent works is refused before the model sees it.
// Payment card numbers and national ID numbers are masked, so the model, the trace and the logs never hold them.
// Output: the same numbers are masked in the reply, and a reply containing a term on the team's blocked list
// (BlockedTerms, empty by default) is replaced, never sent.

import (
	"regexp"
	"strings"
)

const (
	Refusal  = "I can't act on that: it reads like an instruction to change how I work, not a question about an order. Ask me about an order instead."
	Withheld = "I can't send that reply. A person will follow up."
)

// BlockedTerms lists words or phrases a reply must never contain (gate 2). Empty: off.
var BlockedTerms = []string{}

var (
	instruction = regexp.MustCompile(`(?i)\b(ignore|disregard|forget|override)\b[^.\n]{0,60}\b(instructions?|rules|prompts?|guidelines|guardrails?)\b|\byou are now\b|\b(system|developer) prompt\b|\b(jailbreak|dan mode|developer mode)\b|\breveal\b[^.\n]{0,60}\b(prompt|instructions?|passwords?|secrets?|keys?|credentials?)\b`)
	card        = regexp.MustCompile(`\b(?:\d[ -]?){12,18}\d\b`)
	nationalID  = regexp.MustCompile(`\b\d{3}-\d{2}-\d{4}\b`)
	nonDigit    = regexp.MustCompile(`\D`)
)

// Screened is a filtered text, whether it was blocked, and what the filter found.
type Screened struct {
	Text     string
	Blocked  bool
	Findings []string
}

func luhn(digits string) bool {
	total, alt := 0, false
	for i := len(digits) - 1; i >= 0; i-- {
		n := int(digits[i]-'0') * map[bool]int{true: 2, false: 1}[alt]
		if n > 9 {
			n -= 9
		}
		total += n
		alt = !alt
	}
	return total%10 == 0
}

// Mask removes payment card numbers (Luhn-valid) and national ID numbers.
func Mask(text string) (string, []string) {
	found := []string{}
	out := card.ReplaceAllStringFunc(text, func(m string) string {
		d := nonDigit.ReplaceAllString(m, "")
		if len(d) >= 13 && len(d) <= 19 && luhn(d) {
			found = append(found, "card number")
			return "[card number removed]"
		}
		return m
	})
	out = nationalID.ReplaceAllStringFunc(out, func(string) string {
		found = append(found, "ID number")
		return "[ID number removed]"
	})
	return out, found
}

// ScreenInput is gate 1.
func ScreenInput(message string) Screened {
	if instruction.MatchString(message) {
		return Screened{Text: Refusal, Blocked: true, Findings: []string{"instruction-like input"}}
	}
	t, f := Mask(message)
	return Screened{Text: t, Findings: f}
}

// ScreenOutput is gate 2.
func ScreenOutput(reply string) Screened {
	t, f := Mask(reply)
	low := strings.ToLower(t)
	for _, b := range BlockedTerms {
		if b != "" && strings.Contains(low, strings.ToLower(b)) {
			return Screened{Text: Withheld, Blocked: true, Findings: append(f, "blocked term")}
		}
	}
	return Screened{Text: t, Findings: f}
}
