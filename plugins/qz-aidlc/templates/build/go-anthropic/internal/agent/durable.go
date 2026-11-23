package agent

// Durable runs: a run that waits for a person survives a restart, and a change is never made twice.
//
// The state database is SQLite (AGENT_STATE_DB, default .agent/state.db) through modernc.org/sqlite, a pure Go driver:
// nothing to install, no cgo, no server to run. Postgres is the step up when several machines share the runs (the
// same two tables).
//
//	runs     one row per thread: the message, who asked and in which role, how it stands, the calls so far and what
//	         waits for a person, so another process (after a restart, a deploy, or the HTTP interface) finishes it
//	effects  one row per change a tool makes, keyed by the thread, the tool and its arguments. A step retried after a
//	         crash finds the row and returns what the first call returned. The key also goes to the system that makes
//	         the change, as its idempotency key, so a crash between the change and the row cannot make it twice either
//
// Temporary errors (a timeout, a dropped connection, a 408, 425, 429 or 5xx) are retried after a short wait that
// grows; anything else stops at once with the reason. Both are events on the trace and lines in the audit log.

import (
	"context"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math/rand/v2"
	"net"
	"os"
	"path/filepath"
	"syscall"
	"time"

	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/trace"
	_ "modernc.org/sqlite" // registers the "sqlite" driver
)

// Retries is how many times a temporary error is tried, the first included.
const Retries = 3

// RetryWait is the wait before the first retry; it doubles for each one after, with a little jitter.
var RetryWait = 500 * time.Millisecond

const schema = `
CREATE TABLE IF NOT EXISTS runs (thread TEXT PRIMARY KEY, created TEXT, updated TEXT, status TEXT, message TEXT, role TEXT,
  actor TEXT, calls TEXT, pending TEXT, state TEXT, answer TEXT, answered_by TEXT);
CREATE TABLE IF NOT EXISTS effects (key TEXT PRIMARY KEY, thread TEXT, tool TEXT, args TEXT, status TEXT, result TEXT,
  error TEXT, created TEXT, updated TEXT);`

// Saved is one run in the state database.
type Saved struct {
	Thread     string
	Status     string // awaiting_approval, done or failed
	Message    string // as the agent read it: card and ID numbers masked
	Role       string
	Actor      string // who asked
	Calls      []Call
	Pending    []Call // what waits for a person
	Answer     *Result
	AnsweredBy string
	Created    string
}

type threadKey struct{}

// WithThread returns ctx carrying the run's thread: a change made under it is made once.
func WithThread(ctx context.Context, thread string) context.Context {
	return context.WithValue(ctx, threadKey{}, thread)
}

// ThreadOf is the run's thread, or "" outside a run.
func ThreadOf(ctx context.Context) string {
	t, _ := ctx.Value(threadKey{}).(string)
	return t
}

// NewThread names a new run: 32 hex characters.
func NewThread() string { return runID() }

// StatePath is the state database's file: AGENT_STATE_DB, or .agent/state.db (which git ignores).
func StatePath() string {
	if p := os.Getenv("AGENT_STATE_DB"); p != "" {
		return p
	}
	return filepath.Join(".agent", "state.db")
}

// OpenState opens the state database, creating its folder and its tables. Close it when done.
func OpenState() (*sql.DB, error) {
	p := StatePath()
	if err := os.MkdirAll(filepath.Dir(p), 0o750); err != nil {
		return nil, err
	}
	db, err := sql.Open("sqlite", p+"?_pragma=busy_timeout(30000)&_pragma=journal_mode(WAL)")
	if err != nil {
		return nil, err
	}
	if _, err := db.Exec(schema); err != nil {
		_ = db.Close()
		return nil, err
	}
	return db, nil
}

func now() string { return time.Now().UTC().Format(time.RFC3339) }

func clip(s string, n int) string {
	if len(s) > n {
		return s[:n]
	}
	return s
}

func orNull(s string) any {
	if s == "" {
		return nil
	}
	return s
}

// saveRun writes a run's row, creating it the first time.
func saveRun(s Saved) error {
	db, err := OpenState()
	if err != nil {
		return err
	}
	defer db.Close()
	if s.Calls == nil {
		s.Calls = []Call{}
	}
	if s.Pending == nil {
		s.Pending = []Call{}
	}
	calls, _ := json.Marshal(s.Calls)
	pending, _ := json.Marshal(s.Pending)
	var answer any
	if s.Answer != nil {
		b, _ := json.Marshal(s.Answer)
		answer = string(b)
	}
	at := now()
	_, err = db.Exec(`INSERT INTO runs (thread, created, updated, status, message, role, actor, calls, pending, answer, answered_by)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
		ON CONFLICT(thread) DO UPDATE SET updated = excluded.updated, status = excluded.status, message = excluded.message,
		  role = excluded.role, actor = excluded.actor, calls = excluded.calls, pending = excluded.pending,
		  answer = excluded.answer, answered_by = excluded.answered_by`,
		s.Thread, at, at, s.Status, s.Message, s.Role, s.Actor, string(calls), string(pending), answer, orNull(s.AnsweredBy))
	return err
}

// Load reads one run; nil when there is none.
func Load(thread string) (*Saved, error) {
	db, err := OpenState()
	if err != nil {
		return nil, err
	}
	defer db.Close()
	var created, status, message, role, actor, calls, pending, answer, answeredBy sql.NullString
	err = db.QueryRow(`SELECT created, status, message, role, actor, calls, pending, answer, answered_by FROM runs WHERE thread = ?`, thread).
		Scan(&created, &status, &message, &role, &actor, &calls, &pending, &answer, &answeredBy)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	s := &Saved{Thread: thread, Status: status.String, Message: message.String, Role: role.String, Actor: actor.String,
		AnsweredBy: answeredBy.String, Created: created.String, Calls: []Call{}, Pending: []Call{}}
	if calls.Valid {
		_ = json.Unmarshal([]byte(calls.String), &s.Calls)
	}
	if pending.Valid {
		_ = json.Unmarshal([]byte(pending.String), &s.Pending)
	}
	if answer.Valid {
		var r Result
		if json.Unmarshal([]byte(answer.String), &r) == nil {
			s.Answer = &r
		}
	}
	return s, nil
}

// Waiting lists the runs that wait for a person, oldest first.
func Waiting() ([]Saved, error) {
	db, err := OpenState()
	if err != nil {
		return nil, err
	}
	rows, err := db.Query(`SELECT thread FROM runs WHERE status = 'awaiting_approval' ORDER BY created`)
	if err != nil {
		_ = db.Close()
		return nil, err
	}
	var ids []string
	for rows.Next() {
		var t string
		if rows.Scan(&t) == nil {
			ids = append(ids, t)
		}
	}
	_ = rows.Close()
	_ = db.Close()
	out := []Saved{}
	for _, t := range ids {
		if s, err := Load(t); err == nil && s != nil {
			out = append(out, *s)
		}
	}
	return out, nil
}

// Key is the idempotency key of one change: the thread, the tool and its arguments.
func Key(thread, tool string, args map[string]any) string {
	b, _ := json.Marshal(map[string]any{"thread": thread, "tool": tool, "args": args}) // encoding/json sorts map keys
	sum := sha256.Sum256(b)
	return hex.EncodeToString(sum[:])[:32]
}

// Once makes the change do(key) at most once for this run's thread, tool and arguments: a second call (a retry after
// a crash, a replayed step) returns what the first one returned. Outside a run (no thread in ctx) every call is its own.
func Once(ctx context.Context, tool string, args map[string]any, do func(key string) (map[string]any, error)) (map[string]any, error) {
	thread := ThreadOf(ctx)
	if thread == "" {
		return do(runID())
	}
	k := Key(thread, tool, args)
	db, err := OpenState()
	if err != nil {
		return nil, err
	}
	defer db.Close()
	var status, result sql.NullString
	err = db.QueryRow(`SELECT status, result FROM effects WHERE key = ?`, k).Scan(&status, &result)
	seen := err == nil
	if err != nil && !errors.Is(err, sql.ErrNoRows) {
		return nil, err
	}
	if seen && status.String == "done" {
		var out map[string]any
		if json.Unmarshal([]byte(result.String), &out) == nil {
			event(ctx, "effect.replayed", map[string]any{"tool": tool, "key": k})
			return out, nil
		}
	}
	at := now()
	a, _ := json.Marshal(args)
	if _, err := db.Exec(`INSERT OR IGNORE INTO effects (key, thread, tool, args, status, created, updated) VALUES (?, ?, ?, ?, 'started', ?, ?)`,
		k, thread, tool, string(a), at, at); err != nil {
		return nil, err
	}
	if seen { // started before and never finished: the system's own idempotency key keeps it single
		event(ctx, "effect.resumed", map[string]any{"tool": tool, "key": k})
	}
	out, err := Retry(ctx, tool, func() (map[string]any, error) { return do(k) })
	if err != nil {
		_, _ = db.Exec(`UPDATE effects SET status = 'failed', error = ?, updated = ? WHERE key = ?`, clip(fmt.Sprintf("%T: %v", err, err), 300), now(), k)
		return nil, err
	}
	if os.Getenv("AGENT_CRASH_AFTER_EFFECT") == tool {
		os.Exit(75) // tests only: the change is made, the row is not
	}
	b, _ := json.Marshal(out)
	if _, err := db.Exec(`UPDATE effects SET status = 'done', result = ?, updated = ? WHERE key = ?`, string(b), now(), k); err != nil {
		// The change is made; a retry finds the row unfinished and the system's own key returns the same change.
		event(ctx, "effect.unrecorded", map[string]any{"tool": tool, "key": k, "error": fmt.Sprintf("%T", err)})
	}
	return out, nil
}

// Temporary marks an error worth another try: the system said so (a 429 or a 5xx), or the network failed on the way.
// Return it by value: Temporary{Err: err}.
type Temporary struct{ Err error }

func (t Temporary) Error() string { return t.Err.Error() }
func (t Temporary) Unwrap() error { return t.Err }

// StatusError is an error that says which HTTP status a system answered with: wrap a client's error in it, and a 408,
// 425, 429 or 5xx is tried again while any other status stops at once.
type StatusError struct {
	Code int
	Err  error
}

func (e StatusError) Error() string { return fmt.Sprintf("HTTP %d: %v", e.Code, e.Err) }
func (e StatusError) Unwrap() error { return e.Err }

var temporaryStatus = map[int]bool{408: true, 425: true, 429: true, 500: true, 502: true, 503: true, 504: true}

// IsTemporary says whether err is worth another try.
func IsTemporary(err error) bool {
	var t Temporary
	var s StatusError
	var ne net.Error
	switch {
	case errors.As(err, &t):
		return true
	case errors.As(err, &s):
		return temporaryStatus[s.Code]
	case errors.Is(err, context.DeadlineExceeded), errors.Is(err, io.ErrUnexpectedEOF), errors.Is(err, syscall.ECONNRESET),
		errors.Is(err, syscall.ECONNREFUSED), errors.Is(err, syscall.EPIPE):
		return true
	case errors.As(err, &ne) && ne.Timeout():
		return true
	}
	return false
}

// Retry calls fn; a temporary error is tried again after a short wait that grows, anything else stops at once.
func Retry[T any](ctx context.Context, what string, fn func() (T, error)) (T, error) {
	for attempt := 1; ; attempt++ {
		v, err := fn()
		if err == nil {
			return v, nil
		}
		kind := fmt.Sprintf("%T", err)
		if !IsTemporary(err) {
			event(ctx, "error.permanent", map[string]any{"tool": what, "error": kind, "reason": clip(err.Error(), 200)})
			return v, err
		}
		if attempt >= Retries {
			event(ctx, "retry.gave_up", map[string]any{"tool": what, "attempts": attempt, "error": kind})
			return v, err
		}
		wait := time.Duration(float64(RetryWait) * float64(int64(1)<<(attempt-1)) * (0.8 + 0.4*rand.Float64()))
		event(ctx, "retry", map[string]any{"tool": what, "attempt": attempt, "wait_ms": wait.Milliseconds(), "error": kind})
		select {
		case <-time.After(wait):
		case <-ctx.Done():
			return v, ctx.Err()
		}
	}
}

// event is an event on the current trace span, where there is one, and a line in the audit log.
func event(ctx context.Context, name string, attrs map[string]any) {
	kv := make([]attribute.KeyValue, 0, len(attrs))
	fields := map[string]any{"step": name, "thread": ThreadOf(ctx)}
	for k, v := range attrs {
		kv = append(kv, attribute.String(k, fmt.Sprint(v)))
		fields[k] = v
	}
	trace.SpanFromContext(ctx).AddEvent(name, trace.WithAttributes(kv...))
	_ = Audit("durable", Actor(), Role(), fields) // the run goes on if the line cannot be written
}
