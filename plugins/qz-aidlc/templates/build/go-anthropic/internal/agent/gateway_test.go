package agent

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
)

// The model gateway (AGENT_GATEWAY=litellm): every model call goes to the gateway, by the gateway's model name, with the
// gateway's key and the run's trace context; the agent refuses to start while it holds a provider key; the tools, the
// approval gate and the limits are the same. A stand-in plays the gateway here (Anthropic's Messages API, answering by
// the stub's rules); CI runs the real LiteLLM proxy.

type seenCall struct{ Model, Auth, APIKey, TraceParent string }

func gatewayStandin(t *testing.T) (*httptest.Server, func() []seenCall) {
	var mu sync.Mutex
	var seen []seenCall
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			Model    string `json:"model"`
			Messages []struct {
				Role    string            `json:"role"`
				Content []json.RawMessage `json:"content"`
			} `json:"messages"`
			Tools []struct {
				Name string `json:"name"`
			} `json:"tools"`
		}
		_ = json.NewDecoder(r.Body).Decode(&req)
		mu.Lock()
		seen = append(seen, seenCall{req.Model, r.Header.Get("Authorization"), r.Header.Get("X-Api-Key"), r.Header.Get("traceparent")})
		mu.Unlock()
		names := map[string]string{}
		var transcript []Turn
		for _, m := range req.Messages {
			for _, raw := range m.Content {
				var b struct {
					Type      string          `json:"type"`
					Text      string          `json:"text"`
					ID        string          `json:"id"`
					Name      string          `json:"name"`
					Input     map[string]any  `json:"input"`
					ToolUseID string          `json:"tool_use_id"`
					Content   json.RawMessage `json:"content"`
				}
				_ = json.Unmarshal(raw, &b)
				switch b.Type {
				case "text":
					if m.Role == "user" {
						transcript = append(transcript, Turn{Role: "user", Text: b.Text})
					}
				case "tool_use":
					names[b.ID] = b.Name
					transcript = append(transcript, Turn{Role: "assistant", Call: &Call{ID: b.ID, Name: b.Name, Args: b.Input}})
				case "tool_result":
					text := string(b.Content)
					var parts []struct {
						Text string `json:"text"`
					}
					var s string
					if json.Unmarshal(b.Content, &parts) == nil && len(parts) > 0 {
						text = parts[0].Text
					} else if json.Unmarshal(b.Content, &s) == nil {
						text = s
					}
					result := map[string]any{}
					_ = json.Unmarshal([]byte(text), &result)
					transcript = append(transcript, Turn{Role: "tool", Call: &Call{ID: b.ToolUseID, Name: names[b.ToolUseID]}, Result: result})
				}
			}
		}
		var tools []Tool
		for _, x := range req.Tools {
			tools = append(tools, Tool{Name: x.Name})
		}
		step, _ := StubModel{}.Next(r.Context(), transcript, tools)
		content, stop := []map[string]any{{"type": "text", "text": step.Say}}, "end_turn"
		if step.Call != nil {
			content, stop = []map[string]any{{"type": "tool_use", "id": step.Call.ID, "name": step.Call.Name, "input": step.Call.Args}}, "tool_use"
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]any{"id": "msg_test", "type": "message", "role": "assistant", "model": req.Model, "content": content,
			"stop_reason": stop, "usage": map[string]any{"input_tokens": step.InputTokens, "output_tokens": step.OutputTokens}})
	}))
	t.Cleanup(srv.Close)
	return srv, func() []seenCall { mu.Lock(); defer mu.Unlock(); return append([]seenCall(nil), seen...) }
}

func withGateway(t *testing.T, url string) {
	for _, k := range ProviderKeys {
		t.Setenv(k, "")
	}
	t.Setenv("AGENT_MODE", "live")
	t.Setenv("AGENT_GATEWAY", "litellm")
	t.Setenv("AGENT_GATEWAY_URL", url)
	t.Setenv("AGENT_GATEWAY_KEY", "sk-gateway-test")
	stop := Tracing()
	t.Cleanup(stop)
}

func TestAQuestionGoesThroughTheGatewayWithItsKeyAndTheTrace(t *testing.T) {
	srv, seen := gatewayStandin(t)
	withGateway(t, srv.URL)
	r, err := Run(context.Background(), NewModel(), "Where is my order ORD-1001?", Fixed(nil))
	if err != nil || !strings.Contains(r.Output, "shipped") || len(r.ToolCalls) != 1 || r.ToolCalls[0].Name != "get_order" {
		t.Fatalf("run through the gateway: %v %+v", err, r)
	}
	calls := seen()
	if len(calls) == 0 {
		t.Fatal("no call reached the gateway")
	}
	for _, c := range calls {
		if c.Model != "agent-model" || c.Auth != "Bearer sk-gateway-test" || c.APIKey != "" || !strings.HasPrefix(c.TraceParent, "00-") {
			t.Fatalf("a call reached the gateway without its model name, its key alone or the run's trace: %+v", c)
		}
	}
}

func TestARefundThroughTheGatewayStillWaitsForAPerson(t *testing.T) {
	srv, _ := gatewayStandin(t)
	withGateway(t, srv.URL)
	r, _ := Run(context.Background(), NewModel(), "ORD-1002 arrived damaged. Please refund it.", Fixed(nil))
	if !r.AwaitingApproval || r.ToolCalls[len(r.ToolCalls)-1].Status != "pending" || strings.Contains(r.Output, "RF-") {
		t.Fatalf("a refund through the gateway did not wait: %+v", r)
	}
}

func TestAnEasyQuestionCanGoToTheGatewaysSmallModel(t *testing.T) {
	srv, seen := gatewayStandin(t)
	withGateway(t, srv.URL)
	t.Setenv("AGENT_GATEWAY_MODEL_SMALL", "agent-model-small")
	_, _ = Run(context.Background(), NewModel(), "Where is my order ORD-1001?", Fixed(nil))
	_, _ = Run(context.Background(), NewModel(), "ORD-1002 arrived damaged. Please refund it.", Fixed(nil))
	calls := seen()
	if calls[0].Model != "agent-model-small" || calls[len(calls)-1].Model != "agent-model" {
		t.Fatalf("models by question: %+v", calls)
	}
}

func TestTheAgentWillNotHoldAProviderKeyBehindTheGateway(t *testing.T) {
	for _, held := range []string{"ANTHROPIC_API_KEY", "OPENAI_API_KEY", "AWS_SECRET_ACCESS_KEY"} {
		t.Run(held, func(t *testing.T) {
			srv, seen := gatewayStandin(t)
			withGateway(t, srv.URL)
			t.Setenv(held, "sk-not-for-the-agent")
			_, err := Run(context.Background(), NewModel(), "Where is my order ORD-1001?", Fixed(nil))
			if err == nil || !strings.Contains(err.Error(), "gateway holds the provider keys") || len(seen()) != 0 {
				t.Fatalf("with %s set the agent still called: %v", held, err)
			}
		})
	}
}
