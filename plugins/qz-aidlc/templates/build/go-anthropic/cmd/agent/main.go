// Command agent runs one message through the agent and prints the result as JSON.
package main

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"strings"

	"__MODULE__/internal/agent"
)

func main() {
	defer agent.Tracing()()
	msg := strings.Join(os.Args[1:], " ")
	if msg == "" {
		msg = "Where is my order ORD-1001?"
	}
	res, err := agent.Run(context.Background(), agent.NewModel(), msg, agent.Fixed(nil))
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	out, _ := json.MarshalIndent(res, "", "  ")
	fmt.Println(string(out))
}
