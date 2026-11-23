package agent

import (
	"context"
	"fmt"
	"regexp"
	"strings"
)

var (
	orderRx  = regexp.MustCompile(`(?i)\bORD-\d+\b`)
	refundRx = regexp.MustCompile(`(?i)\brefund`)
)

// StubModel is a scripted stand-in for the model, for offline runs and CI. It follows fixed rules, so it proves
// the wiring (tools, approval gate, limits, tracing), not the quality of a model's answers.
type StubModel struct{}

// NotAllowed is what the stub says when the call it wants is not among the role's tools.
const NotAllowed = "That needs access your role does not have, so I have not done it. A colleague who handles refunds can help."

// Next implements Model. A model only calls the tools it was given, so a tool outside the list is never called.
func (StubModel) Next(_ context.Context, transcript []Turn, tools []Tool) (Step, error) {
	given := map[string]bool{}
	for _, t := range tools {
		given[t.Name] = true
	}
	user := transcript[0].Text
	results := map[string]map[string]any{}
	size := 0
	for _, t := range transcript {
		size += len(t.Text) + len(toJSON(t.Result))
		if t.Role == "tool" {
			results[t.Call.Name] = t.Result
		}
	}
	step := Step{InputTokens: int64(size/4 + 60), OutputTokens: 24}
	say := func(format string, a ...any) (Step, error) { step.Say = fmt.Sprintf(format, a...); return step, nil }
	call := func(name string, args map[string]any) (Step, error) {
		if !given[name] {
			step.Say = NotAllowed
			return step, nil
		}
		step.Call = &Call{ID: fmt.Sprintf("tu_%d", len(results)+1), Name: name, Args: args}
		return step, nil
	}
	oid := strings.ToUpper(orderRx.FindString(user))
	if oid == "" {
		return say("I can help once I have an order number, for example ORD-1001.")
	}
	order, looked := results["get_order"]
	if !looked {
		return call("get_order", map[string]any{"order_id": oid})
	}
	if found, _ := order["found"].(bool); !found {
		return say("I could not find order %s. Please check the number.", oid)
	}
	refund, tried := results["issue_refund"]
	if refundRx.MatchString(user) && !tried {
		return call("issue_refund", map[string]any{"order_id": oid, "amount": order["total"], "reason": "customer request"})
	}
	if tried {
		if ok, _ := refund["ok"].(bool); ok {
			return say("Refund %v of %v has been issued for order %s.", refund["refund_id"], refund["amount"], oid)
		}
		return say("The refund for order %s was not issued: %v.", oid, refund["error"])
	}
	if c, _ := order["carrier"].(string); c != "" {
		return say("Order %s is %v with %s.", oid, order["status"], c)
	}
	return say("Order %s is %v.", oid, order["status"])
}
