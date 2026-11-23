package agent

// Go-live gate 5: who did what, and when. One JSON line per event, each carrying the SHA-256 of the line before it, so
// a line that was edited, taken out or moved shows when the chain is checked (VerifyAudit).
//
// A line holds the time, the actor, the role, the event (a run or a tool call), the tool, its arguments with card and
// ID numbers masked, and how it ended. Never the reply, never the message itself (only its hash), never a key.
// The file is AGENT_AUDIT_LOG (default .agent/audit.jsonl, which git ignores); "-" writes each line to standard error
// instead, for a container whose platform ships its logs (each process then starts its own chain). A chain shows
// tampering; it does not stop it, so production ships each line to the organisation's log store (a SIEM) as it is written.

import (
	"bufio"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

const genesis = "0000000000000000000000000000000000000000000000000000000000000000"

// AuditPath is the audit log's file.
func AuditPath() string {
	if p := os.Getenv("AGENT_AUDIT_LOG"); p != "" {
		return p
	}
	return filepath.Join(".agent", "audit.jsonl")
}

func digest(prev string, body map[string]any) string {
	b, _ := json.Marshal(body) // encoding/json writes map keys in sorted order
	sum := sha256.Sum256([]byte(prev + string(b)))
	return hex.EncodeToString(sum[:])
}

func auditLines(path string) []string {
	f, err := os.Open(path)
	if err != nil {
		return nil
	}
	defer f.Close()
	var out []string
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 1024*1024), 1024*1024)
	for sc.Scan() {
		if strings.TrimSpace(sc.Text()) != "" {
			out = append(out, sc.Text())
		}
	}
	return out
}

// stream is the chain so far, when lines go to standard error.
var stream = struct {
	sync.Mutex
	seq  int
	hash string
}{hash: genesis}

// Audit appends one chained event.
func Audit(event, actor, role string, fields map[string]any) error {
	path := AuditPath()
	seq, prev := 0, genesis
	if path == "-" {
		stream.Lock()
		defer stream.Unlock()
		seq, prev = stream.seq, stream.hash
	} else if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	if lines := auditLines(path); path != "-" && len(lines) > 0 {
		var last map[string]any
		if err := json.Unmarshal([]byte(lines[len(lines)-1]), &last); err == nil {
			if s, ok := last["seq"].(float64); ok {
				seq = int(s)
			}
			prev, _ = last["hash"].(string)
		}
	}
	body := map[string]any{"seq": seq + 1, "ts": time.Now().UTC().Format("2006-01-02T15:04:05Z"), "event": event, "actor": actor, "role": role}
	for k, v := range fields {
		body[k] = v
	}
	rec := map[string]any{}
	for k, v := range body {
		rec[k] = v
	}
	rec["prev"], rec["hash"] = prev, digest(prev, body)
	line, err := json.Marshal(rec)
	if err != nil {
		return err
	}
	if path == "-" {
		stream.seq, stream.hash = seq+1, rec["hash"].(string)
		_, err = os.Stderr.Write(append(line, '\n'))
		return err
	}
	f, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o640)
	if err != nil {
		return err
	}
	defer f.Close()
	_, err = f.Write(append(line, '\n'))
	return err
}

// AuditCheck is the result of VerifyAudit.
type AuditCheck struct {
	OK       bool `json:"ok"`
	Records  int  `json:"records"`
	BrokenAt int  `json:"broken_at,omitempty"`
}

// VerifyAudit walks the chain and reports the first line that does not fit.
func VerifyAudit(path string) AuditCheck {
	prev, n := genesis, 0
	for i, line := range auditLines(path) {
		var rec map[string]any
		if err := json.Unmarshal([]byte(line), &rec); err != nil {
			return AuditCheck{false, n, i + 1}
		}
		p, _ := rec["prev"].(string)
		h, _ := rec["hash"].(string)
		seq, _ := rec["seq"].(float64)
		delete(rec, "prev")
		delete(rec, "hash")
		if p != prev || int(seq) != n+1 || digest(prev, rec) != h {
			return AuditCheck{false, n, i + 1}
		}
		prev, n = h, n+1
	}
	return AuditCheck{true, n, 0}
}
