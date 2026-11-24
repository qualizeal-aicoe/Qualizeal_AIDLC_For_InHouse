package agent

// The knowledge engine as a tool: a question about the client's own documents goes to the knowledge service (the
// hybrid kit in knowledge/, over HTTP), which answers only from what the caller may read and cites the section it
// used, or says what it looked for when the documents do not say.
//
// On only when KNOWLEDGE_URL is set (`qz build solution` sets it). Who is asking goes as an identity-aware proxy's
// headers: X-Forwarded-User (the person) and X-Forwarded-Groups (their role here). The knowledge service accepts those
// headers only from this agent's address (its trusted_proxies), so nobody else can claim a role. The call never goes
// through an HTTP proxy, the host must be on AllowedHosts, and the answer is data: text in it never changes the
// agent's rules, its tools or who it acts for.

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
	"time"
)

const (
	maxQuestion      = 500
	knowledgeTimeout = 30 * time.Second
)

// KnowledgeURL is the knowledge service's base address, or "" when there is none.
func KnowledgeURL() string {
	return strings.TrimRight(strings.TrimSpace(os.Getenv("KNOWLEDGE_URL")), "/")
}

// KnowledgeOn says whether the knowledge tool is offered at all.
func KnowledgeOn() bool { return KnowledgeURL() != "" }

// an internal service: never through a proxy, whatever HTTP_PROXY says.
var knowledgeClient = &http.Client{Timeout: knowledgeTimeout, Transport: &http.Transport{Proxy: nil}}

func failed(reason string) map[string]any {
	return map[string]any{"found": false, "answer": "", "citations": []any{}, "error": reason}
}

// Ask is what the knowledge service answered, trimmed to what the agent needs: found, the answer and up to three
// citations; or found false with the reason. Errors come back as data, so the agent says it could not look.
func Ask(ctx context.Context, question, user, role string) map[string]any {
	base := KnowledgeURL()
	if err := CheckEndpoint(base); err != nil { // go-live gates 3 and 6: a host not listed is never called
		return failed(err.Error())
	}
	q := strings.TrimSpace(question)
	if len([]rune(q)) > maxQuestion {
		q = string([]rune(q)[:maxQuestion])
	}
	body, _ := json.Marshal(map[string]string{"question": q})
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, base+"/api/ask", bytes.NewReader(body))
	if err != nil {
		return failed("the knowledge service address is not valid")
	}
	if user == "" {
		user = "unknown"
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Forwarded-User", user)
	req.Header.Set("X-Forwarded-Groups", role)
	resp, err := knowledgeClient.Do(req)
	if err != nil {
		return failed("the knowledge service could not be reached")
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 400 {
		return failed(fmt.Sprintf("the knowledge service answered %d", resp.StatusCode))
	}
	var data struct {
		Text      string           `json:"text"`
		Refused   bool             `json:"refused"`
		Citations []map[string]any `json:"citations"`
		Searched  []any            `json:"searched"`
		Contact   string           `json:"contact"`
	}
	raw, err := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if err != nil || json.Unmarshal(raw, &data) != nil {
		return failed("the knowledge service sent an answer that could not be read")
	}
	if data.Refused {
		searched := []any{}
		for i, s := range data.Searched {
			if i == 6 {
				break
			}
			searched = append(searched, fmt.Sprint(s))
		}
		return map[string]any{"found": false, "answer": "", "citations": []any{}, "searched": searched, "contact": data.Contact}
	}
	cites := []any{}
	for i, c := range data.Citations {
		if i == 3 {
			break
		}
		doc := fmt.Sprint(firstOf(c, "doc_title", "doc_id"))
		cites = append(cites, map[string]any{"document": doc, "section": fmt.Sprint(firstOf(c, "section"))})
	}
	return map[string]any{"found": true, "answer": data.Text, "citations": cites}
}

func firstOf(m map[string]any, keys ...string) any {
	for _, k := range keys {
		if v, ok := m[k]; ok && v != nil && fmt.Sprint(v) != "" {
			return v
		}
	}
	return ""
}

// KnowledgeReply is the sentence the offline stub says for a knowledge result: the answer with its source, or that
// the documents this person may read do not say, and who to ask.
func KnowledgeReply(r map[string]any) string {
	if found, _ := r["found"].(bool); found {
		src := []string{}
		cites, _ := r["citations"].([]any)
		for _, c := range cites {
			m, _ := c.(map[string]any)
			doc, _ := m["document"].(string)
			if sec, _ := m["section"].(string); sec != "" {
				src = append(src, doc+", "+sec)
			} else {
				src = append(src, doc)
			}
		}
		answer, _ := r["answer"].(string)
		if len(src) > 0 {
			return answer + " (Source: " + strings.Join(src, "; ") + ")"
		}
		return answer
	}
	if e, _ := r["error"].(string); e != "" {
		return "I could not look that up in the documents just now. Please try again in a moment."
	}
	if c, _ := r["contact"].(string); c != "" {
		return "The documents you may read do not say. " + c + " can help."
	}
	return "The documents you may read do not say."
}
