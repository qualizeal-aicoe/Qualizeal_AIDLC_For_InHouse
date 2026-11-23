//go:build !unix

package agent

import "os"

// lockFile does nothing here: on Windows one process writes a given log, and auditMu keeps its goroutines in line.
func lockFile(*os.File) func() { return func() {} }
