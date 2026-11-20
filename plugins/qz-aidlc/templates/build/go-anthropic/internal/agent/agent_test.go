package agent

import (
	"context"
	"strings"
	"testing"
)

// Wiring tests against the offline stub: tools, approval gate and limits. No key, no network.

func yes() *bool { b := true; return &b }
func no() *bool  { b := false; return &b }

func TestLookupCallsTheReadToolOnly(t *testing.T) {
	r, err := Run(context.Background(), StubModel{}, "Where is my order ORD-1001?", Fixed(nil))
	if err != nil || len(r.ToolCalls) != 1 || r.ToolCalls[0].Name != "get_order" || !strings.Contains(r.Output, "shipped") {
		t.Fatalf("unexpected: %+v %v", r, err)
	}
}

func TestRefundWaitsForAPerson(t *testing.T) {
	r, _ := Run(context.Background(), StubModel{}, "ORD-1002 arrived damaged. Please refund it.", Fixed(nil))
	if !r.AwaitingApproval || r.ToolCalls[len(r.ToolCalls)-1].Status != "pending" {
		t.Fatalf("refund did not wait: %+v", r)
	}
}

func TestApprovedRefundRunsAndDeclinedRefundDoesNot(t *testing.T) {
	ok, _ := Run(context.Background(), StubModel{}, "ORD-1002 arrived damaged. Please refund it.", Fixed(yes()))
	if !strings.Contains(ok.Output, "RF-") || !strings.Contains(ok.Output, "42.50") {
		t.Fatalf("approved refund missing: %+v", ok)
	}
	denied, _ := Run(context.Background(), StubModel{}, "ORD-1002 arrived damaged. Please refund it.", Fixed(no()))
	if denied.ToolCalls[len(denied.ToolCalls)-1].Status != "denied" || strings.Contains(denied.Output, "RF-") {
		t.Fatalf("declined refund moved money: %+v", denied)
	}
}

type loopModel struct{}

func (loopModel) Next(context.Context, []Turn, []Tool) (Step, error) {
	return Step{Call: &Call{ID: "x", Name: "get_order", Args: map[string]any{"order_id": "ORD-1001"}}}, nil
}

func TestTurnLimitStopsARunawayLoop(t *testing.T) {
	r, _ := Run(context.Background(), loopModel{}, "loop", Fixed(nil))
	if len(r.ToolCalls) != MaxTurns || !strings.Contains(r.Output, "turn limit") {
		t.Fatalf("loop was not stopped: %d calls, %q", len(r.ToolCalls), r.Output)
	}
}
