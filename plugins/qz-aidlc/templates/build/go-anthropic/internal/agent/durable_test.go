package agent

import (
	"bufio"
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// Durable runs, offline: a run that waits for a person is answered from another process after a restart; a crash
// right after the refund leads to exactly one refund on retry; temporary errors are retried and permanent ones stop.

const refundAsk = "ORD-1002 arrived damaged. Please refund it."

// TestMain gives the package its own state database and audit log, and is the "other process" the tests start: with
// AGENT_TEST_ANSWER set it answers that run, prints the result and exits, as `runs answer` does.
func TestMain(m *testing.M) {
	if t := os.Getenv("AGENT_TEST_ANSWER"); t != "" {
		res, err := Answer(context.Background(), t, true, "ana")
		if err != nil {
			os.Stderr.WriteString(err.Error() + "\n")
			os.Exit(1)
		}
		_ = json.NewEncoder(os.Stdout).Encode(res)
		os.Exit(0)
	}
	dir, err := os.MkdirTemp("", "agent-test-")
	if err != nil {
		panic(err)
	}
	_ = os.Setenv("AGENT_STATE_DB", filepath.Join(dir, "state.db"))
	if os.Getenv("AGENT_AUDIT_LOG") == "" {
		_ = os.Setenv("AGENT_AUDIT_LOG", filepath.Join(dir, "audit.jsonl"))
	}
	code := m.Run()
	_ = os.RemoveAll(dir)
	os.Exit(code)
}

// fresh gives one test its own empty state database and audit log.
func fresh(t *testing.T) string {
	t.Helper()
	d := t.TempDir()
	t.Setenv("AGENT_STATE_DB", filepath.Join(d, "state.db"))
	t.Setenv("AGENT_AUDIT_LOG", filepath.Join(d, "audit.jsonl"))
	return d
}

type refunded struct {
	OrderID string
	Amount  float64
}

func refunds(t *testing.T) []refunded {
	t.Helper()
	db, err := OpenState()
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	rows, err := db.Query(`SELECT order_id, amount FROM sample_refunds`)
	if err != nil {
		return nil // no refund has been made: the table is not there yet
	}
	defer rows.Close()
	var out []refunded
	for rows.Next() {
		var r refunded
		if err := rows.Scan(&r.OrderID, &r.Amount); err != nil {
			t.Fatal(err)
		}
		out = append(out, r)
	}
	return out
}

// answerInANewProcess answers the run as ana from a new process of this test binary.
func answerInANewProcess(t *testing.T, thread string, env ...string) (Result, int) {
	t.Helper()
	cmd := exec.Command(os.Args[0], "-test.run=^$")
	cmd.Env = append(os.Environ(), append([]string{"AGENT_TEST_ANSWER=" + thread}, env...)...)
	out, err := cmd.Output()
	var exit *exec.ExitError
	code := 0
	if errors.As(err, &exit) {
		code = exit.ExitCode()
	} else if err != nil {
		t.Fatal(err)
	}
	var res Result
	if code == 0 {
		line := strings.TrimSpace(string(out))
		if i := strings.LastIndex(line, "\n"); i >= 0 {
			line = line[i+1:]
		}
		if err := json.Unmarshal([]byte(line), &res); err != nil {
			t.Fatalf("not a result: %q (%v)", out, err)
		}
	}
	return res, code
}

func TestAWaitingRunIsAnsweredFromAnotherProcessAfterARestart(t *testing.T) {
	fresh(t)
	r, err := Run(context.Background(), StubModel{}, refundAsk, Fixed(nil))
	if err != nil || !r.AwaitingApproval || r.Thread == "" {
		t.Fatalf("did not wait: %+v %v", r, err)
	}
	if s, _ := Load(r.Thread); s == nil || s.Status != "awaiting_approval" || len(s.Pending) != 1 {
		t.Fatalf("not kept: %+v", s)
	}
	done, code := answerInANewProcess(t, r.Thread)
	if code != 0 || done.Outcome != "acted" || !strings.Contains(done.Output, "RF-") || done.AnsweredBy != "ana" {
		t.Fatalf("answer from another process: %d %+v", code, done)
	}
	if s, _ := Load(r.Thread); s == nil || s.Status != "done" || s.AnsweredBy != "ana" {
		t.Fatalf("not finished: %+v", s)
	}
	if got := refunds(t); len(got) != 1 || got[0] != (refunded{"ORD-1002", 42.5}) {
		t.Fatalf("refunds %+v", got)
	}
}

func TestACrashRightAfterTheRefundLeadsToExactlyOneRefund(t *testing.T) {
	fresh(t)
	r, _ := Run(context.Background(), StubModel{}, refundAsk, Fixed(nil))
	if _, code := answerInANewProcess(t, r.Thread, "AGENT_CRASH_AFTER_EFFECT=issue_refund"); code != 75 {
		t.Fatalf("the process did not crash where it should: exit %d", code)
	}
	if got := refunds(t); len(got) != 1 {
		t.Fatalf("the crash should leave the refund made once: %+v", got)
	}
	again, err := Answer(context.Background(), r.Thread, true, "ana")
	if err != nil || again.Outcome != "acted" || len(again.Effects) != 1 || again.Effects[0]["order_refunded"] != 42.5 {
		t.Fatalf("retry after the crash: %+v %v", again, err)
	}
	if got := refunds(t); len(got) != 1 {
		t.Fatalf("refunded twice: %+v", got)
	}
	if third, _ := Answer(context.Background(), r.Thread, true, "ana"); !third.AlreadyAnswered || len(refunds(t)) != 1 {
		t.Fatalf("a third answer must change nothing: %+v", third)
	}
}

func TestADeclinedRunMovesNoMoneyAndAnUnknownThreadIsRefused(t *testing.T) {
	fresh(t)
	r, _ := Run(context.Background(), StubModel{}, refundAsk, Fixed(nil))
	no, err := Answer(context.Background(), r.Thread, false, "ana")
	if err != nil || no.Outcome != "declined" || strings.Contains(no.Output, "RF-") || len(refunds(t)) != 0 {
		t.Fatalf("decline: %+v %v", no, err)
	}
	if _, err := Answer(context.Background(), strings.Repeat("0", 32), true, "ana"); err == nil {
		t.Fatal("an unknown thread was answered")
	}
}

func TestTheSameChangeInOneThreadIsMadeOnce(t *testing.T) {
	fresh(t)
	ctx := WithThread(context.Background(), strings.Repeat("t", 32))
	var seen []string
	do := func(key string) (map[string]any, error) {
		seen = append(seen, key)
		return map[string]any{"ok": true, "n": float64(len(seen))}, nil
	}
	a, _ := Once(ctx, "issue_refund", map[string]any{"order_id": "ORD-1"}, do)
	b, _ := Once(ctx, "issue_refund", map[string]any{"order_id": "ORD-1"}, do)
	c, _ := Once(ctx, "issue_refund", map[string]any{"order_id": "ORD-2"}, do)
	if a["n"] != b["n"] || c["n"] != float64(2) || len(seen) != 2 {
		t.Fatalf("a=%v b=%v c=%v seen=%v", a, b, c, seen)
	}
}

func TestTemporaryErrorsAreRetriedAndPermanentOnesStop(t *testing.T) {
	d := fresh(t)
	old := RetryWait
	RetryWait = time.Millisecond
	defer func() { RetryWait = old }()
	ctx := context.Background()
	tries := 0
	v, err := Retry(ctx, "issue_refund", func() (string, error) {
		tries++
		if tries < 3 {
			return "", StatusError{Code: 503, Err: errors.New("the payment system is busy")}
		}
		return "ok", nil
	})
	if err != nil || v != "ok" || tries != 3 {
		t.Fatalf("temporary: %q %v after %d tries", v, err, tries)
	}
	hard := 0
	if _, err := Retry(ctx, "issue_refund", func() (string, error) { hard++; return "", errors.New("the account is closed") }); err == nil || hard != 1 {
		t.Fatalf("a permanent error was tried %d times (%v)", hard, err)
	}
	if _, err := Retry(ctx, "issue_refund", func() (string, error) { return "", StatusError{Code: 400, Err: sql.ErrNoRows} }); err == nil {
		t.Fatal("a 400 must stop at once")
	}
	f, _ := os.Open(filepath.Join(d, "audit.jsonl"))
	defer f.Close()
	steps := map[string]int{}
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		var line map[string]any
		if json.Unmarshal(sc.Bytes(), &line) == nil {
			if s, ok := line["step"].(string); ok {
				steps[s]++
			}
		}
	}
	if steps["retry"] != 2 || steps["error.permanent"] != 2 || !VerifyAudit(filepath.Join(d, "audit.jsonl")).OK {
		t.Fatalf("audit steps %v", steps)
	}
}
