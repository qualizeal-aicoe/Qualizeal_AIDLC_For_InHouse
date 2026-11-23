package agent

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// Go-live gates the code carries, offline: a role gets only its own tools, every run and tool call is in a chained
// audit log that shows an edit, and the agent calls only the hosts it lists.
func TestARoleGetsOnlyItsOwnToolsAndAnUnknownRoleGetsNone(t *testing.T) {
	t.Setenv("AGENT_AUDIT_LOG", filepath.Join(t.TempDir(), "audit.jsonl"))
	r, err := RunAs(context.Background(), StubModel{}, "ORD-1002 arrived damaged. Please refund it.", Fixed(nil), Who{Role: "viewer"})
	if err != nil || len(r.ToolCalls) != 1 || r.ToolCalls[0].Name != "get_order" || !strings.Contains(r.Output, "role does not have") {
		t.Fatalf("viewer got %+v, %v", r, err)
	}
	r, err = RunAs(context.Background(), StubModel{}, "Where is my order ORD-1001?", Fixed(nil), Who{Role: "no-such-role"})
	if err != nil || len(r.ToolCalls) != 0 {
		t.Fatalf("unknown role got %+v, %v", r, err)
	}
}

func TestEveryRunIsChainedAndAnEditShows(t *testing.T) {
	log := filepath.Join(t.TempDir(), "audit.jsonl")
	t.Setenv("AGENT_AUDIT_LOG", log)
	if _, err := RunAs(context.Background(), StubModel{}, "Where is my order ORD-1001? Card 4111 1111 1111 1111.", Fixed(nil), Who{Actor: "asha@example.com"}); err != nil {
		t.Fatal(err)
	}
	b, _ := os.ReadFile(log)
	text := string(b)
	if strings.Contains(text, "4111") || !strings.Contains(text, `"actor":"asha@example.com"`) || !VerifyAudit(log).OK || VerifyAudit(log).Records != 2 {
		t.Fatalf("log %s / %+v", text, VerifyAudit(log))
	}
	_ = os.WriteFile(log, []byte(strings.Replace(text, `"get_order"`, `"issue_refund"`, 1)), 0o640)
	if c := VerifyAudit(log); c.OK || c.BrokenAt != 1 {
		t.Fatalf("an edit did not show: %+v", c)
	}
}

func TestTheAgentCallsOnlyTheHostsItLists(t *testing.T) {
	if err := CheckEndpoint(ModelURL()); err != nil {
		t.Fatal(err)
	}
	if err := CheckEndpoint("https://collector.example.net/v1"); err == nil {
		t.Fatal("an unlisted host was allowed")
	}
}
