package agent

// Input and output filters: gates 1 and 2 of the six. What a person sends is checked before the agent reads it, and
// the reply before anyone sees it. Pattern-based, offline and fast; a team can put a classifier behind the same calls.
//
// Input: a message that reads like an instruction to change how the agent works is refused before the model sees it.
// Payment card numbers and national ID numbers are masked, so the model, the trace and the logs never hold them.
// Output: the same numbers are masked in the reply, and a reply containing a term on the team's blocked list
// (BlockedTerms, empty by default) is replaced, never sent.
//
// The three levels the evals and the live monitor score (qz eval run, qz eval monitor): each tool call carries what
// the tool returned (tool level); Ungrounded finds facts in a reply that no tool result and not the person's message
// holds, on every reply (response level); Outcome and Effects say how the run ended and what it changed: a tool that
// changes something says so in its result, as "effect" (outcome level).

import (
	"fmt"
	"regexp"
	"sort"
	"strconv"
	"strings"
)

const (
	Refusal  = "I can't act on that: it reads like an instruction to change how I work, not a question about an order. Ask me about an order instead."
	Withheld = "I can't send that reply. A person will follow up."
	// AINotice is shown before the first reply (EU AI Act Article 50(1)).
	AINotice = "You're chatting with an AI assistant, not a person."
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

var (
	factToken  = regexp.MustCompile(`\b[A-Z0-9][A-Z0-9-]{3,}\b`)
	factAmount = regexp.MustCompile(`\b\d+\.\d{2}\b`)
	factNumber = regexp.MustCompile(`\d+(?:\.\d+)?`)
	hasDigit   = regexp.MustCompile(`\d`)
	hasUpper   = regexp.MustCompile(`[A-Z]`)
	allDigits  = regexp.MustCompile(`^\d+$`)
)

// Facts are what a reply can get wrong: codes (ORD-1001, RF-7001: capitals with a digit), amounts (42.50) and long
// digit runs. Words, dates and small counts are not checked.
func Facts(text string) []string {
	var out []string
	for _, t := range factToken.FindAllString(text, -1) {
		if hasDigit.MatchString(t) && (hasUpper.MatchString(t) || (allDigits.MatchString(t) && len(t) >= 5)) {
			out = append(out, t)
		}
	}
	return append(out, factAmount.FindAllString(text, -1)...)
}

func twoPlaces(s string) string {
	f, err := strconv.ParseFloat(s, 64)
	if err != nil {
		return s
	}
	return fmt.Sprintf("%.2f", f)
}

// Ungrounded returns the facts in text that none of the sources holds (the same rule as qz eval's grounded check).
func Ungrounded(text string, sources []string) []string {
	src := strings.Join(sources, " ")
	up := strings.ToUpper(src)
	nums := map[string]bool{}
	for _, n := range factNumber.FindAllString(src, -1) {
		nums[twoPlaces(n)] = true
	}
	seen := map[string]bool{}
	var bad []string
	for _, f := range Facts(text) {
		miss := !strings.Contains(up, strings.ToUpper(f))
		if factAmount.MatchString(f) && len(factAmount.FindString(f)) == len(f) {
			miss = !nums[twoPlaces(f)]
		}
		if miss && !seen[f] {
			seen[f] = true
			bad = append(bad, f)
		}
	}
	sort.Strings(bad)
	return bad
}

// Effects is what the run changed: every tool that changed something says so in its result, as "effect".
func Effects(calls []Call) []map[string]any {
	out := []map[string]any{}
	for _, c := range calls {
		if e, ok := c.Result["effect"].(map[string]any); ok && c.Status == "ok" {
			out = append(out, e)
		}
	}
	return out
}

// Outcome says how a run ended: acted, answered, refused, withheld, awaiting_approval or declined.
func Outcome(res Result, refused bool) string {
	switch {
	case refused:
		return "refused"
	case res.Output == Withheld:
		return "withheld"
	case res.AwaitingApproval:
		return "awaiting_approval"
	case len(res.Effects) > 0:
		return "acted"
	}
	for _, c := range res.ToolCalls {
		if c.Status == "denied" {
			return "declined"
		}
	}
	return "answered"
}
