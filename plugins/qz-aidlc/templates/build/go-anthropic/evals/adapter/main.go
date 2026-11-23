// Command adapter is the evaluation adapter (go run ./evals/adapter): one case in on stdin, one JSON result out on
// stdout. It is eval tooling, kept under evals/ with the gold set: the agent itself never starts a process.
//
// Each case starts from its own empty state database unless AGENT_STATE_DB is set. Two inputs exercise durable runs:
//
//	approve_after_restart  the run waits for a person in this process; the answer comes from a new process (this
//	                       adapter again, with `answer`), which carries the run on from the state database
//	crash_after_refund     that new process dies right after the refund is made, before it is recorded as done; a
//	                       third process answers again, and the refund must still have been made exactly once
package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"

	"__MODULE__/internal/agent"
)

type evalCase struct {
	Input json.RawMessage `json:"input"`
}

type input struct {
	Message             string `json:"message"`
	Approve             *bool  `json:"approve"`
	Role                string `json:"role"`
	ApproveAfterRestart *bool  `json:"approve_after_restart"`
	CrashAfterRefund    bool   `json:"crash_after_refund"`
}

func main() {
	stop := agent.Tracing()
	var code int
	if len(os.Args) == 4 && os.Args[1] == "answer" { // the new process that answers a waiting run
		code = answer(os.Args[2], os.Args[3] == "--approve")
	} else {
		code = evaluate()
	}
	stop()
	os.Exit(code)
}

func evaluate() int {
	var c evalCase
	if err := json.NewDecoder(os.Stdin).Decode(&c); err != nil {
		fmt.Fprintln(os.Stderr, "bad case:", err)
		return 2
	}
	var in input
	if err := json.Unmarshal(c.Input, &in); err != nil {
		_ = json.Unmarshal(c.Input, &in.Message)
	}
	if os.Getenv("AGENT_STATE_DB") == "" {
		dir, err := os.MkdirTemp("", "agent-case-")
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			return 1
		}
		defer os.RemoveAll(dir)
		_ = os.Setenv("AGENT_STATE_DB", filepath.Join(dir, "state.db"))
	}
	approve := in.Approve
	if in.ApproveAfterRestart != nil {
		approve = nil // nobody answers in this process: the answer comes from another one
	}
	res, err := agent.RunAs(context.Background(), agent.NewModel(), in.Message, agent.Fixed(approve), agent.Who{Role: in.Role})
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	if in.ApproveAfterRestart != nil && res.AwaitingApproval {
		yes := *in.ApproveAfterRestart
		if in.CrashAfterRefund {
			if _, code := again(res.Thread, yes, "issue_refund"); code != 75 {
				fmt.Fprintf(os.Stderr, "the crash did not happen where it should (exit %d)\n", code)
				return 1
			}
		}
		out, code := again(res.Thread, yes, "")
		if code != 0 {
			fmt.Fprintf(os.Stderr, "answering in a new process failed (exit %d)\n", code)
			return 1
		}
		res = agent.Result{}
		if err := json.Unmarshal(out, &res); err != nil {
			fmt.Fprintln(os.Stderr, "the new process did not return a result:", err)
			return 1
		}
	}
	_ = json.NewEncoder(os.Stdout).Encode(res)
	return 0
}

// again answers the run in a new process of this adapter. crashAfter, when set, makes that process die right after
// that tool's change is made.
func again(thread string, approve bool, crashAfter string) ([]byte, int) {
	self, err := os.Executable()
	if err != nil {
		return nil, -1
	}
	verb := "--decline"
	if approve {
		verb = "--approve"
	}
	cmd := exec.Command(self, "answer", thread, verb)
	for _, kv := range os.Environ() {
		if !strings.HasPrefix(kv, "AGENT_CRASH_AFTER_EFFECT=") {
			cmd.Env = append(cmd.Env, kv)
		}
	}
	if crashAfter != "" {
		cmd.Env = append(cmd.Env, "AGENT_CRASH_AFTER_EFFECT="+crashAfter)
	}
	cmd.Stderr = os.Stderr
	out, err := cmd.Output()
	var exit *exec.ExitError
	switch {
	case err == nil:
		return out, 0
	case errors.As(err, &exit):
		return out, exit.ExitCode()
	}
	return out, -1
}

func answer(thread string, approve bool) int {
	res, err := agent.Answer(context.Background(), thread, approve, "")
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	_ = json.NewEncoder(os.Stdout).Encode(res)
	return 0
}
