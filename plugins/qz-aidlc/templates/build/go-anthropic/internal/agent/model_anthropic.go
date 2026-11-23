package agent

import (
	"context"
	"encoding/json"
	"time"

	"github.com/anthropics/anthropic-sdk-go"
	"github.com/anthropics/anthropic-sdk-go/option"
)

// AnthropicModel calls the Messages API. The key is read from ANTHROPIC_API_KEY by the SDK.
type AnthropicModel struct {
	client anthropic.Client
	err    error // set when the endpoint is not allowed: every call then fails closed
}

// NewAnthropicModel builds the live model with a timeout and retries, for an endpoint on AllowedHosts (go-live gates 3 and 6).
func NewAnthropicModel() AnthropicModel {
	return AnthropicModel{client: anthropic.NewClient(option.WithMaxRetries(2), option.WithRequestTimeout(RequestTimeoutS*time.Second)),
		err: CheckEndpoint(ModelURL())}
}

// Next implements Model: it converts the transcript to messages, sends it with the tool list and reads one decision.
func (m AnthropicModel) Next(ctx context.Context, transcript []Turn, tools []Tool) (Step, error) {
	if m.err != nil {
		return Step{}, m.err
	}
	var msgs []anthropic.MessageParam
	for _, t := range transcript {
		switch t.Role {
		case "user":
			msgs = append(msgs, anthropic.NewUserMessage(anthropic.NewTextBlock(t.Text)))
		case "assistant":
			var blocks []anthropic.ContentBlockParamUnion
			if t.Text != "" {
				blocks = append(blocks, anthropic.NewTextBlock(t.Text))
			}
			if t.Call != nil {
				blocks = append(blocks, anthropic.NewToolUseBlock(t.Call.ID, t.Call.Args, t.Call.Name))
			}
			msgs = append(msgs, anthropic.NewAssistantMessage(blocks...))
		case "tool":
			failed := t.Call.Status == "denied"
			msgs = append(msgs, anthropic.NewUserMessage(anthropic.NewToolResultBlock(t.Call.ID, toJSON(t.Result), failed)))
		}
	}
	var defs []anthropic.ToolUnionParam
	for _, t := range tools {
		defs = append(defs, anthropic.ToolUnionParam{OfTool: &anthropic.ToolParam{
			Name: t.Name, Description: anthropic.String(t.Description),
			InputSchema: anthropic.ToolInputSchemaParam{Properties: t.Properties, Required: t.Required},
		}})
	}
	resp, err := m.client.Messages.New(ctx, anthropic.MessageNewParams{
		Model: anthropic.Model(PickModel(firstUser(transcript))), MaxTokens: MaxOutputTokens,
		// The cache breakpoint on the system prompt covers the tools before it: every turn of the loop reuses both.
		System: []anthropic.TextBlockParam{{Text: System, CacheControl: anthropic.NewCacheControlEphemeralParam()}}, Messages: msgs, Tools: defs,
	})
	if err != nil {
		return Step{}, err
	}
	step := Step{InputTokens: resp.Usage.InputTokens, OutputTokens: resp.Usage.OutputTokens}
	for _, block := range resp.Content {
		switch b := block.AsAny().(type) {
		case anthropic.TextBlock:
			step.Say += b.Text
		case anthropic.ToolUseBlock:
			if step.Call == nil { // one tool per turn keeps the approval gate simple
				args := map[string]any{}
				_ = json.Unmarshal(b.Input, &args)
				step.Call = &Call{ID: b.ID, Name: b.Name, Args: args}
			}
		}
	}
	return step, nil
}

// firstUser is the person's message that started the run: the model for the whole run is chosen from it.
func firstUser(transcript []Turn) string {
	for _, t := range transcript {
		if t.Role == "user" {
			return t.Text
		}
	}
	return ""
}
