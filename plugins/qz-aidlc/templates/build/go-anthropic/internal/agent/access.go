package agent

import (
	"context"
	"fmt"
	"net/url"
	"strings"
)

// ToolsFor is go-live gate 2: only the tools this role may use reach the model. A role not in Roles gets none. The
// knowledge tool is on only where a knowledge service is (KNOWLEDGE_URL, knowledge.go).
func ToolsFor(role string, tools []Tool) []Tool {
	allowed := map[string]bool{}
	for _, n := range Roles[role] {
		allowed[n] = n != "search_knowledge" || KnowledgeOn()
	}
	out := []Tool{}
	for _, t := range tools {
		if allowed[t.Name] {
			out = append(out, t)
		}
	}
	return out
}

type whoKey struct{}

// WithWho returns ctx carrying who the run acts for and in which role: tools read it (the knowledge service applies
// their access). Set by RunAs and Answer from whoever started the agent, never from the message.
func WithWho(ctx context.Context, who Who) context.Context {
	return context.WithValue(ctx, whoKey{}, who)
}

// WhoOf is who the current run acts for; outside a run, the configured Role and Actor.
func WhoOf(ctx context.Context) Who {
	if w, ok := ctx.Value(whoKey{}).(Who); ok {
		return w
	}
	return Who{Role: Role(), Actor: Actor()}
}

// CheckEndpoint is go-live gates 3 and 6: the agent calls only the hosts on AllowedHosts. Anything else fails closed.
func CheckEndpoint(raw string) error {
	if !strings.Contains(raw, "://") {
		raw = "https://" + raw
	}
	host := ""
	if u, err := url.Parse(raw); err == nil {
		host = strings.ToLower(u.Hostname())
	}
	for _, h := range AllowedHosts {
		if host != "" && strings.EqualFold(h, host) {
			return nil
		}
	}
	return fmt.Errorf("%q is not on AllowedHosts: add it there, and to .qz/golive.json with its region, only once the data may go there", host)
}
