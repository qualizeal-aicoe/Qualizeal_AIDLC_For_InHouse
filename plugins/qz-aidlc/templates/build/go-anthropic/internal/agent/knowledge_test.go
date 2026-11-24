package agent

// The knowledge tool against a stand-in knowledge service: off until KNOWLEDGE_URL is set; on, it asks with the
// person's identity and role in the proxy headers, says the answer with its source or that the documents do not say,
// never calls a host that is not on AllowedHosts, and its answer goes through the same output filter as any reply.
// No key, no network beyond this machine.

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
)

const question = "What is the refund window policy for damaged items?"

var found = map[string]any{"text": "Damaged items can be returned within 30 days of delivery.", "refused": false,
	"citations": []any{map[string]any{"doc_id": "returns", "doc_title": "Returns policy", "section": "Refund window", "node_id": "n1"}}}

type seen struct {
	Path, User, Groups string
	Body               map[string]any
}

type service struct {
	mu     sync.Mutex
	calls  []seen
	answer map[string]any
	srv    *httptest.Server
}

func newService(t *testing.T) *service {
	s := &service{answer: found}
	s.srv = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var body map[string]any
		_ = json.NewDecoder(r.Body).Decode(&body)
		s.mu.Lock()
		s.calls = append(s.calls, seen{Path: r.URL.Path, User: r.Header.Get("X-Forwarded-User"), Groups: r.Header.Get("X-Forwarded-Groups"), Body: body})
		answer := s.answer
		s.mu.Unlock()
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(answer)
	}))
	t.Cleanup(s.srv.Close)
	t.Setenv("KNOWLEDGE_URL", s.srv.URL)
	t.Setenv("AGENT_AUDIT_LOG", filepath.Join(t.TempDir(), "audit.jsonl"))
	return s
}

func (s *service) count() int { s.mu.Lock(); defer s.mu.Unlock(); return len(s.calls) }

func TestKnowledgeIsOffUntilAServiceIsSet(t *testing.T) {
	t.Setenv("KNOWLEDGE_URL", "")
	t.Setenv("AGENT_AUDIT_LOG", filepath.Join(t.TempDir(), "audit.jsonl"))
	for _, tool := range ToolsFor("support", Tools()) {
		if tool.Name == "search_knowledge" {
			t.Fatal("the knowledge tool is offered with no knowledge service")
		}
	}
	r, err := Run(context.Background(), StubModel{}, question, Fixed(nil))
	if err != nil || len(r.ToolCalls) != 0 || !strings.Contains(r.Output, "order number") {
		t.Fatalf("unexpected: %+v %v", r, err)
	}
}

func TestAPolicyQuestionIsAnsweredFromTheDocumentsWithItsSource(t *testing.T) {
	s := newService(t)
	r, err := RunAs(context.Background(), StubModel{}, question, Fixed(nil), Who{Actor: "asha@example.com"})
	if err != nil || len(r.ToolCalls) != 1 || r.ToolCalls[0].Name != "search_knowledge" {
		t.Fatalf("unexpected: %+v %v", r, err)
	}
	if !strings.Contains(r.Output, "30 days") || !strings.Contains(r.Output, "Returns policy, Refund window") {
		t.Fatalf("no answer with its source: %q", r.Output)
	}
	if r.Outcome != "answered" || r.Checks == nil || !r.Checks.Grounded {
		t.Fatalf("outcome %q checks %+v", r.Outcome, r.Checks)
	}
	if s.count() != 1 || s.calls[0].Path != "/api/ask" || s.calls[0].Body["question"] != question {
		t.Fatalf("calls: %+v", s.calls)
	}
	if s.calls[0].User != "asha@example.com" || s.calls[0].Groups != "support" {
		t.Fatalf("identity headers: %+v", s.calls[0])
	}
}

func TestTheKnowledgeServiceAppliesTheCallersRole(t *testing.T) {
	s := newService(t)
	if _, err := RunAs(context.Background(), StubModel{}, question, Fixed(nil), Who{Role: "viewer", Actor: "vic@example.com"}); err != nil {
		t.Fatal(err)
	}
	if last := s.calls[s.count()-1]; last.Groups != "viewer" || last.User != "vic@example.com" {
		t.Fatalf("identity headers: %+v", last)
	}
}

func TestWhenTheDocumentsDoNotSayTheAgentSaysSoAndWhoCanHelp(t *testing.T) {
	s := newService(t)
	s.answer = map[string]any{"refused": true, "searched": []any{"refund window"}, "contact": "The support lead"}
	r, _ := Run(context.Background(), StubModel{}, question, Fixed(nil))
	if !strings.Contains(r.Output, "do not say") || !strings.Contains(r.Output, "The support lead can help") {
		t.Fatalf("reply: %q", r.Output)
	}
}

func TestAnOrderQuestionStillGoesToTheOrderTools(t *testing.T) {
	s := newService(t)
	r, _ := Run(context.Background(), StubModel{}, "Where is my order ORD-1001?", Fixed(nil))
	if len(r.ToolCalls) != 1 || r.ToolCalls[0].Name != "get_order" || s.count() != 0 {
		t.Fatalf("unexpected: %+v (knowledge calls %d)", r, s.count())
	}
}

func TestAHostNotOnTheAllowedListIsNeverCalled(t *testing.T) {
	s := newService(t)
	t.Setenv("KNOWLEDGE_URL", "https://docs.example.com")
	out := Ask(context.Background(), question, "asha@example.com", "support")
	if f, _ := out["found"].(bool); f || !strings.Contains(out["error"].(string), "AllowedHosts") || s.count() != 0 {
		t.Fatalf("unexpected: %+v", out)
	}
	if !strings.Contains(KnowledgeReply(out), "could not look that up") {
		t.Fatalf("reply: %q", KnowledgeReply(out))
	}
}

func TestAnAnswerGoesThroughTheOutputFilterLikeAnyReply(t *testing.T) {
	s := newService(t)
	s.answer = map[string]any{"text": "The card on file, 4111 1111 1111 1111, is refunded within 30 days.", "citations": found["citations"]}
	r, _ := Run(context.Background(), StubModel{}, question, Fixed(nil))
	if strings.Contains(r.Output, "4111") || !strings.Contains(r.Output, "[card number removed]") {
		t.Fatalf("reply: %q", r.Output)
	}
}

func TestTheAuditLogRecordsTheLookup(t *testing.T) {
	newService(t)
	if _, err := RunAs(context.Background(), StubModel{}, question, Fixed(nil), Who{Actor: "asha@example.com"}); err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile(os.Getenv("AGENT_AUDIT_LOG"))
	if err != nil {
		t.Fatal(err)
	}
	var events, tools []string
	for _, line := range strings.Split(strings.TrimSpace(string(raw)), "\n") {
		var x map[string]any
		_ = json.Unmarshal([]byte(line), &x)
		events = append(events, x["event"].(string))
		if x["event"] == "tool" {
			tools = append(tools, x["tool"].(string))
		}
	}
	if strings.Join(events, ",") != "tool,run" || strings.Join(tools, ",") != "search_knowledge" {
		t.Fatalf("audit: %v %v", events, tools)
	}
}
