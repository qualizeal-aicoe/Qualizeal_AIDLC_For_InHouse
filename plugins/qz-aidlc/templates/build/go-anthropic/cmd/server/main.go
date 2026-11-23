// Command server serves the agent over HTTP: ask, answer what waits for a person, and health
// (internal/agent/server.go). Who is asking comes from the identity provider: set AGENT_IDENTITY (demo, oidc or
// proxy) before anyone but you can reach it.
//
//	server [--host 127.0.0.1] [--port 8080]
//	server --health      the image's health check: 0 when healthy
package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"net"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"syscall"
	"time"

	"__MODULE__/internal/agent"
)

func main() {
	host := flag.String("host", envOr("AGENT_HOST", "127.0.0.1"), "address to listen on")
	port := flag.Int("port", portOr("AGENT_PORT", 8080), "port to listen on")
	health := flag.Bool("health", false, "check the server here (or, with none running, the state database) and exit")
	flag.Parse()
	if *health {
		os.Exit(agent.Health(*port))
	}
	stopTracing := agent.Tracing()
	defer stopTracing()
	srv := &http.Server{Addr: net.JoinHostPort(*host, strconv.Itoa(*port)), Handler: agent.NewServer(nil),
		ReadHeaderTimeout: 10 * time.Second, ReadTimeout: 30 * time.Second, WriteTimeout: 5 * time.Minute, IdleTimeout: 60 * time.Second}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	go func() { // a deploy's SIGTERM finishes the requests in flight; waiting runs are already in the state database
		<-ctx.Done()
		shut, cancel := context.WithTimeout(context.Background(), 30*time.Second)
		defer cancel()
		_ = srv.Shutdown(shut)
	}()
	fmt.Fprintf(os.Stderr, "Serving on http://%s (identity: %s); Ctrl+C stops it.\n", srv.Addr, agent.IdentityFromEnv().Mode)
	if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
		fmt.Fprintln(os.Stderr, err)
		stop()
		stopTracing()
		os.Exit(1)
	}
}

func envOr(k, d string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return d
}

func portOr(k string, d int) int {
	if n, err := strconv.Atoi(os.Getenv(k)); err == nil && n > 0 {
		return n
	}
	return d
}
