package agent

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"strings"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
)

// Call is one tool request from the model. Status is ok, pending, denied (a person said no) or not_allowed (not on
// the role's tool list). Result is what the tool returned, when it ran: the grounded check and the effects read it.
type Call struct {
	ID     string         `json:"-"`
	Name   string         `json:"name"`
	Args   map[string]any `json:"args"`
	Status string         `json:"status"`
	Result map[string]any `json:"result,omitempty"`
}

// Turn is one entry of the transcript, independent of any provider's message format.
type Turn struct {
	Role   string // user, assistant, tool
	Text   string
	Call   *Call          // assistant asked for a tool
	Result map[string]any // tool answered (Role == "tool")
}

// Step is the model's decision for one turn: say something, or call a tool.
type Step struct {
	Say                       string
	Call                      *Call
	InputTokens, OutputTokens int64
}

// Model is the seam between the loop and a provider. The stub implements it for offline runs.
type Model interface {
	Next(ctx context.Context, transcript []Turn, tools []Tool) (Step, error)
}

// Approver answers an approval request. Return (approved, answered): answered false leaves the action waiting.
type Approver func(ctx context.Context, call Call) (approved bool, answered bool)

// Result is what a run returns.
type Result struct {
	Output           string `json:"output"`
	ToolCalls        []Call `json:"tool_calls"`
	Usage            Usage  `json:"usage"`
	AwaitingApproval bool   `json:"awaiting_approval"`
	Guard            *Guard `json:"guard,omitempty"`
	AINotice         string `json:"ai_notice"`    // EU AI Act Article 50(1): show it before the first reply
	AIGenerated      bool   `json:"ai_generated"` // Article 50(2): a machine-readable mark; false for fixed texts
	Role             string `json:"role"`
	// The three levels the evals and the live monitor score: what the run changed, how it ended, and whether the
	// reply held only facts the tools or the person gave (see guardrails.go).
	Effects []map[string]any `json:"effects"`
	Outcome string           `json:"outcome"`
	Checks  *Checks          `json:"checks,omitempty"`
}

// Checks is the response-level check run on every reply.
type Checks struct {
	Grounded   bool `json:"grounded"`
	Ungrounded int  `json:"ungrounded"`
}

// Who is asking: set by whoever starts the agent (an interface: the identity provider's groups), never by the message.
type Who struct {
	Role  string
	Actor string
}

// Guard says what the input and output filters found.
type Guard struct {
	Input  []string `json:"input"`
	Output []string `json:"output"`
}

// Usage counts tokens across the run.
type Usage struct {
	InputTokens  int64 `json:"input_tokens"`
	OutputTokens int64 `json:"output_tokens"`
}

// NewModel picks the stub unless AGENT_MODE=live.
func NewModel() Model {
	if os.Getenv("AGENT_MODE") == "live" {
		return NewAnthropicModel()
	}
	return StubModel{}
}

// Run drives the loop behind the two filters in the configured role (Role, Actor). See RunAs.
func Run(ctx context.Context, model Model, message string, approve Approver) (Result, error) {
	return RunAs(ctx, model, message, approve, Who{})
}

// RunAs drives the loop behind the two filters: the input is checked before the model reads it (gate 1), the reply
// before it is returned (gate 2). The model sees only the role's tools, and the run goes to the audit log.
func RunAs(ctx context.Context, model Model, message string, approve Approver, who Who) (Result, error) {
	if who.Role == "" {
		who.Role = Role()
	}
	if who.Actor == "" {
		who.Actor = Actor()
	}
	in := ScreenInput(message)
	var res Result
	var err error
	if in.Blocked {
		res = Result{Output: in.Text, ToolCalls: []Call{}, Guard: &Guard{Input: in.Findings, Output: []string{}}, AINotice: AINotice}
	} else {
		res, err = run(ctx, model, in.Text, approve, who.Role)
		out := ScreenOutput(res.Output)
		res.Output = out.Text
		res.Guard = &Guard{Input: in.Findings, Output: out.Findings}
		res.AINotice = AINotice
		res.AIGenerated = !out.Blocked && !res.AwaitingApproval
	}
	res.Role = who.Role
	res.Effects = Effects(res.ToolCalls)
	res.Outcome = Outcome(res, in.Blocked)
	if err != nil {
		res.Outcome = "failed"
	}
	if res.Outcome == "acted" || res.Outcome == "answered" || res.Outcome == "declined" {
		sources := []string{in.Text, System}
		for _, c := range res.ToolCalls {
			if c.Result != nil {
				sources = append(sources, toJSON(c.Result))
			}
		}
		bad := Ungrounded(res.Output, sources)
		res.Checks = &Checks{Grounded: len(bad) == 0, Ungrounded: len(bad)}
	}
	masked, _ := Mask(message)
	if aerr := record(who, masked, res, err); aerr != nil && err == nil {
		err = fmt.Errorf("audit log: %w", aerr)
	}
	return res, err
}

func runID() string {
	b := make([]byte, 16)
	_, _ = rand.Read(b)
	return hex.EncodeToString(b)
}

// record writes one audit line per tool call and one for the run: masked arguments, never the reply or the message.
// The run line carries what the live monitor scores: how it ended, what it changed, whether the reply was grounded.
func record(who Who, message string, res Result, runErr error) error {
	id := runID()
	for _, c := range res.ToolCalls {
		args, _ := Mask(toJSON(c.Args))
		if len(args) > 500 {
			args = args[:500]
		}
		if err := Audit("tool", who.Actor, who.Role, map[string]any{"run_id": id, "tool": c.Name, "status": c.Status, "args": args}); err != nil {
			return err
		}
	}
	effects := make([]any, 0, len(res.Effects))
	for _, e := range res.Effects {
		m, _ := Mask(toJSON(e))
		var v any
		_ = json.Unmarshal([]byte(m), &v)
		effects = append(effects, v)
	}
	sum := sha256.Sum256([]byte(message))
	fields := map[string]any{"run_id": id, "outcome": res.Outcome, "checks": res.Checks, "effects": effects, "tool_calls": len(res.ToolCalls),
		"message_sha": hex.EncodeToString(sum[:])[:16], "message_chars": len(message), "guard": res.Guard}
	if runErr != nil {
		fields["error"] = fmt.Sprintf("%T", runErr)
	}
	return Audit("run", who.Actor, who.Role, fields)
}

// run drives the loop: model decides, the gate checks, tools run, until the model answers or a limit is reached.
func run(ctx context.Context, model Model, message string, approve Approver, role string) (Result, error) {
	ctx, span := otel.Tracer("__SLUG__").Start(ctx, "agent.run")
	defer span.End()
	tools := ToolsFor(role, Tools())
	byName := map[string]Tool{}
	for _, t := range tools {
		byName[t.Name] = t
	}
	transcript := []Turn{{Role: "user", Text: message}}
	res := Result{ToolCalls: []Call{}}
	for turn := 0; turn < MaxTurns; turn++ {
		step, err := model.Next(ctx, transcript, tools)
		if err != nil {
			return res, fmt.Errorf("model call failed: %w", err)
		}
		res.Usage.InputTokens += step.InputTokens
		res.Usage.OutputTokens += step.OutputTokens
		if step.Call == nil {
			res.Output = step.Say
			break
		}
		call := *step.Call
		tool, known := byName[call.Name]
		var out map[string]any
		switch {
		case !known:
			call.Status, out = "not_allowed", map[string]any{"ok": false, "error": call.Name + " is not on this agent's tool list."}
		case NeedsApproval[call.Name]:
			approved, answered := approve(ctx, call)
			switch {
			case !answered:
				call.Status = "pending"
				res.ToolCalls = append(res.ToolCalls, call)
				res.AwaitingApproval = true
				res.Output = "This needs approval from a person before it can go ahead: " + call.Name + ". It is waiting; nothing has been changed."
				span.SetAttributes(attribute.String("agent.gate", "pending"))
				return res, nil
			case approved:
				call.Status, out = "ok", tool.Run(call.Args)
			default:
				call.Status, out = "denied", map[string]any{"ok": false, "error": "A person declined this action. Do not retry it."}
			}
		default:
			call.Status, out = "ok", tool.Run(call.Args)
		}
		if call.Status == "ok" {
			call.Result = out // what the tool returned: the grounded check and the effects read it
		}
		res.ToolCalls = append(res.ToolCalls, call)
		transcript = append(transcript, Turn{Role: "assistant", Text: step.Say, Call: &call}, Turn{Role: "tool", Call: &call, Result: out})
		if turn == MaxTurns-1 {
			res.Output = "I stopped because the turn limit was reached."
		}
	}
	names := make([]string, len(res.ToolCalls))
	for i, c := range res.ToolCalls {
		names[i] = c.Name + ":" + c.Status
	}
	span.SetAttributes(attribute.String("agent.tool_calls", strings.Join(names, ",")), attribute.Int64("gen_ai.usage.input_tokens", res.Usage.InputTokens), attribute.Int64("gen_ai.usage.output_tokens", res.Usage.OutputTokens))
	return res, nil
}

// Fixed returns an Approver with a fixed answer; nil means nobody has answered yet.
func Fixed(answer *bool) Approver {
	return func(context.Context, Call) (bool, bool) {
		if answer == nil {
			return false, false
		}
		return *answer, true
	}
}

func toJSON(v any) string { b, _ := json.Marshal(v); return string(b) }
