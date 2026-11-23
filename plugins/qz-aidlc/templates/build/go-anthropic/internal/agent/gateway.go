package agent

import (
	"fmt"
	"os"
	"strings"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/propagation"
)

// The model gateway: one setting, AGENT_GATEWAY=litellm, sends every model call through the LiteLLM proxy described in
// gateway/litellm.yaml, at AGENT_GATEWAY_URL, with the gateway's own key (AGENT_GATEWAY_KEY).
//
// The provider keys live in the proxy's environment and nowhere else: in gateway mode the agent refuses to start while
// a provider key is in its own environment. Each model call carries the run's trace context (the Anthropic SDK sends
// traceparent), so the gateway's record of the call (model, tokens, cost) lands inside the run's trace in Langfuse.
// The tools, the approval gate and the limits are the same with or without the gateway.

// ProviderKeys are the variables only the gateway may hold.
var ProviderKeys = []string{"ANTHROPIC_API_KEY", "OPENAI_API_KEY", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AZURE_OPENAI_API_KEY",
	"AZURE_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "MISTRAL_API_KEY", "COHERE_API_KEY"}

// GatewayOn reports whether model calls go through the gateway.
func GatewayOn() bool {
	return strings.EqualFold(strings.TrimSpace(os.Getenv("AGENT_GATEWAY")), "litellm")
}

// GatewayURL is the gateway's address; on a laptop or as a sidecar it is 127.0.0.1:4000.
func GatewayURL() string {
	if u := os.Getenv("AGENT_GATEWAY_URL"); u != "" {
		return strings.TrimRight(u, "/")
	}
	return "http://127.0.0.1:4000"
}

// GatewayModel is the gateway's name for the model (model_name in gateway/litellm.yaml): the gateway picks the provider.
func GatewayModel(small bool) string {
	if s := os.Getenv("AGENT_GATEWAY_MODEL_SMALL"); small && s != "" {
		return s
	}
	if m := os.Getenv("AGENT_GATEWAY_MODEL"); m != "" {
		return m
	}
	return "agent-model"
}

// GatewayKey is the only credential the agent holds in gateway mode; it fails while a provider key is in reach.
func GatewayKey() (string, error) {
	var held []string
	for _, k := range ProviderKeys {
		if os.Getenv(k) != "" {
			held = append(held, k)
		}
	}
	if len(held) > 0 {
		return "", fmt.Errorf("with AGENT_GATEWAY=litellm the gateway holds the provider keys: unset %s where the agent runs", strings.Join(held, ", "))
	}
	k := os.Getenv("AGENT_GATEWAY_KEY")
	if k == "" {
		return "", fmt.Errorf("set AGENT_GATEWAY_KEY to the gateway's key: a LiteLLM virtual key (its master key only on a laptop)")
	}
	return k, nil
}

// ContentInTraces is true only when the team turns prompt and answer text on in traces (AGENT_TRACE_CONTENT=1).
func ContentInTraces() bool { return os.Getenv("AGENT_TRACE_CONTENT") == "1" }

// The Anthropic SDK sends the trace context of each call through the registered propagator: W3C trace context.
func init() { otel.SetTextMapPropagator(propagation.TraceContext{}) }
