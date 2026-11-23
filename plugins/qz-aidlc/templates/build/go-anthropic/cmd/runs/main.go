// Command runs answers a run that waits for a person, from another process: after a restart, from a script, or on
// the HTTP interface's host. The result is printed as JSON.
//
//	runs waiting
//	runs answer <thread> --approve|--decline [--by NAME]
package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"os"

	"__MODULE__/internal/agent"
)

const usage = "usage: runs waiting | runs answer <thread> --approve|--decline [--by NAME]"

func main() {
	stop := agent.Tracing()
	code := run(os.Args[1:])
	stop()
	os.Exit(code)
}

func run(args []string) int {
	out := json.NewEncoder(os.Stdout)
	switch {
	case len(args) == 1 && args[0] == "waiting":
		runs, err := agent.Waiting()
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			return 1
		}
		for _, r := range runs {
			waiting := []map[string]any{}
			for _, c := range r.Pending {
				waiting = append(waiting, map[string]any{"name": c.Name, "args": c.Args})
			}
			_ = out.Encode(map[string]any{"thread": r.Thread, "asked_by": r.Actor, "role": r.Role, "since": r.Created, "waiting_for": waiting})
		}
		return 0
	case len(args) >= 2 && args[0] == "answer":
		fs := flag.NewFlagSet("answer", flag.ContinueOnError)
		approve := fs.Bool("approve", false, "a person's yes")
		decline := fs.Bool("decline", false, "a person's no")
		by := fs.String("by", "", "who answers (default: who asked)")
		if err := fs.Parse(args[2:]); err != nil || *approve == *decline {
			fmt.Fprintln(os.Stderr, usage)
			return 2
		}
		res, err := agent.Answer(context.Background(), args[1], *approve, *by)
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			return 1
		}
		_ = out.Encode(res)
		return 0
	}
	fmt.Fprintln(os.Stderr, usage)
	return 2
}
