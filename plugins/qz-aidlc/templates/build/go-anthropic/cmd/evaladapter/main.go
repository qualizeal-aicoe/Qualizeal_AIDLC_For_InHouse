// Command evaladapter is the evaluation adapter: one case in on stdin, one JSON result out on stdout.
package main

import (
	"context"
	"encoding/json"
	"fmt"
	"os"

	"__MODULE__/internal/agent"
)

type evalCase struct {
	Input json.RawMessage `json:"input"`
}

type input struct {
	Message string `json:"message"`
	Approve *bool  `json:"approve"`
	Role    string `json:"role"`
}

func main() {
	defer agent.Tracing()()
	var c evalCase
	if err := json.NewDecoder(os.Stdin).Decode(&c); err != nil {
		fmt.Fprintln(os.Stderr, "bad case:", err)
		os.Exit(2)
	}
	var in input
	if err := json.Unmarshal(c.Input, &in); err != nil {
		_ = json.Unmarshal(c.Input, &in.Message)
	}
	res, err := agent.RunAs(context.Background(), agent.NewModel(), in.Message, agent.Fixed(in.Approve), agent.Who{Role: in.Role})
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	_ = json.NewEncoder(os.Stdout).Encode(res)
}
