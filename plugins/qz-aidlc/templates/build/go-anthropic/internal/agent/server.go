package agent

// The agent over HTTP: ask, answer what waits for a person, and health. A waiting run lives in the state database
// (durable.go), so a restart, a deploy or a rollback does not lose it, and any instance can answer it.
//
//	GET  /health                          {"status": "ok", "waiting": n}: no sign-in, for the container check and the platform
//	POST /ask                {"message"}  the result; a run that waits says so (202), with its thread
//	GET  /runs/{thread}                   how the run stands and what waits (its asker or an approver)
//	POST /runs/{thread}/approve           the result after a person's yes
//	POST /runs/{thread}/decline           the result after a person's no
//
// Who is asking comes from the identity provider, never from the body (go-live gate 1, identity.go). The role is the
// first of Access.GroupRoles the person's groups name (gate 2); approving needs one of Access.ApproverGroups, and
// nobody approves a request they made.

import (
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"regexp"
	"slices"
	"sort"
	"strings"
	"syscall"
	"time"
)

const (
	maxBody    = 64 << 10
	maxMessage = 4000
)

var threadID = regexp.MustCompile(`^[0-9a-f]{32}$`)

func roleOf(groups []string) string {
	for _, gr := range Access.GroupRoles {
		if slices.Contains(groups, gr[0]) {
			return gr[1]
		}
	}
	return ""
}

func isApprover(groups []string) bool {
	for _, g := range Access.ApproverGroups {
		if slices.Contains(groups, g) {
			return true
		}
	}
	return false
}

func send(w http.ResponseWriter, status int, body any) {
	b, err := json.Marshal(body)
	if err != nil {
		status, b = http.StatusInternalServerError, []byte(`{"error":"the reply could not be written"}`)
	}
	h := w.Header()
	h.Set("Content-Type", "application/json")
	h.Set("X-Content-Type-Options", "nosniff")
	h.Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	_, _ = w.Write(b)
}

func fail(w http.ResponseWriter, err error) {
	var r Refused
	if errors.As(err, &r) {
		send(w, r.Status, map[string]any{"error": r.Reason})
		return
	}
	send(w, http.StatusInternalServerError, map[string]any{"error": fmt.Sprintf("the run failed (%T)", err)})
}

func caller(r *http.Request, keys []JWK) (Caller, error) {
	c := IdentityFromEnv()
	demo := r.Header.Get("X-Demo-User")
	if c.Mode == "demo" {
		if _, ok := Access.DemoUsers[demo]; !ok {
			names := make([]string, 0, len(Access.DemoUsers))
			for n := range Access.DemoUsers {
				names = append(names, n)
			}
			sort.Strings(names)
			return Caller{}, Refused{401, "name a demo user in X-Demo-User: " + strings.Join(names, ", ")}
		}
	}
	return Identify(r.Context(), c, r.Header, r.RemoteAddr, demo, Access.DemoUsers[demo], keys)
}

func waitingFor(calls []Call) []map[string]any {
	out := []map[string]any{}
	for _, c := range calls {
		out = append(out, map[string]any{"name": c.Name, "args": c.Args})
	}
	return out
}

// NewServer is the HTTP interface. keys, when given, stand in for the identity provider's published keys (tests).
func NewServer(keys []JWK) http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, _ *http.Request) {
		runs, err := Waiting()
		if err != nil {
			send(w, http.StatusServiceUnavailable, map[string]any{"status": "unavailable", "error": fmt.Sprintf("%T", err)})
			return
		}
		send(w, http.StatusOK, map[string]any{"status": "ok", "waiting": len(runs)})
	})
	mux.HandleFunc("POST /ask", func(w http.ResponseWriter, r *http.Request) {
		who, err := caller(r, keys)
		if err != nil {
			fail(w, err)
			return
		}
		role := roleOf(who.Groups)
		if role == "" {
			send(w, http.StatusForbidden, map[string]any{"error": "none of your groups may use this agent"})
			return
		}
		var body struct {
			Message string `json:"message"`
		}
		if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, maxBody)).Decode(&body); err != nil {
			send(w, http.StatusBadRequest, map[string]any{"error": `send JSON: {"message": "..."}`})
			return
		}
		msg := strings.TrimSpace(body.Message)
		if msg == "" || len(msg) > maxMessage {
			send(w, http.StatusBadRequest, map[string]any{"error": fmt.Sprintf("the message must be 1 to %d characters", maxMessage)})
			return
		}
		res, err := RunAs(r.Context(), NewModel(), msg, Fixed(nil), Who{Role: role, Actor: who.User})
		if err != nil {
			fail(w, err)
			return
		}
		status := http.StatusOK
		if res.AwaitingApproval {
			status = http.StatusAccepted
		}
		send(w, status, res)
	})
	mux.HandleFunc("GET /runs/{thread}", func(w http.ResponseWriter, r *http.Request) {
		who, err := caller(r, keys)
		if err != nil {
			fail(w, err)
			return
		}
		t := r.PathValue("thread")
		s, err := loadRun(t)
		if err != nil {
			fail(w, err)
			return
		}
		if s == nil || (s.Actor != who.User && !isApprover(who.Groups)) {
			send(w, http.StatusNotFound, map[string]any{"error": "no such run"})
			return
		}
		send(w, http.StatusOK, map[string]any{"thread": s.Thread, "status": s.Status, "asked_by": s.Actor, "role": s.Role,
			"waiting_for": waitingFor(s.Pending), "answered_by": orNull(s.AnsweredBy), "result": s.Answer})
	})
	mux.HandleFunc("POST /runs/{thread}/{verb}", func(w http.ResponseWriter, r *http.Request) {
		verb := r.PathValue("verb")
		if verb != "approve" && verb != "decline" {
			send(w, http.StatusNotFound, map[string]any{"error": "not found"})
			return
		}
		who, err := caller(r, keys)
		if err != nil {
			fail(w, err)
			return
		}
		if !isApprover(who.Groups) {
			send(w, http.StatusForbidden, map[string]any{"error": "only an approver may answer a waiting action"})
			return
		}
		t := r.PathValue("thread")
		s, err := loadRun(t)
		if err != nil {
			fail(w, err)
			return
		}
		if s == nil {
			send(w, http.StatusNotFound, map[string]any{"error": "no such run"})
			return
		}
		if s.Actor == who.User && !Access.SelfApproval {
			send(w, http.StatusForbidden, map[string]any{"error": "nobody approves a request they made: ask another approver"})
			return
		}
		if s.Status != "awaiting_approval" {
			send(w, http.StatusConflict, map[string]any{"error": "the run is " + s.Status + ", not waiting", "answered_by": orNull(s.AnsweredBy)})
			return
		}
		res, err := Answer(r.Context(), t, verb == "approve", who.User)
		if err != nil {
			fail(w, err)
			return
		}
		send(w, http.StatusOK, res)
	})
	mux.HandleFunc("/", func(w http.ResponseWriter, _ *http.Request) {
		send(w, http.StatusNotFound, map[string]any{"error": "not found"})
	})
	return mux
}

// loadRun is Load for a thread named in a request: anything that is not a thread is no run.
func loadRun(t string) (*Saved, error) {
	if !threadID.MatchString(t) {
		return nil, nil
	}
	return Load(t)
}

// Health is the image's health check: a server here must answer /health; with none running (the image answers one
// question or runs its gold set instead), the state database must open. 0 is healthy.
func Health(port int) int {
	client := http.Client{Timeout: 5 * time.Second}
	resp, err := client.Get(fmt.Sprintf("http://127.0.0.1:%d/health", port))
	if err != nil {
		if !errors.Is(err, syscall.ECONNREFUSED) {
			return 1
		}
		db, err := OpenState()
		if err != nil {
			return 1
		}
		_ = db.Close()
		return 0
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return 1
	}
	return 0
}
