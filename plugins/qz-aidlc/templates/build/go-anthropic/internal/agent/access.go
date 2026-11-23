package agent

import (
	"fmt"
	"net/url"
	"strings"
)

// ToolsFor is go-live gate 2: only the tools this role may use reach the model. A role not in Roles gets none.
func ToolsFor(role string, tools []Tool) []Tool {
	allowed := map[string]bool{}
	for _, n := range Roles[role] {
		allowed[n] = true
	}
	out := []Tool{}
	for _, t := range tools {
		if allowed[t.Name] {
			out = append(out, t)
		}
	}
	return out
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
