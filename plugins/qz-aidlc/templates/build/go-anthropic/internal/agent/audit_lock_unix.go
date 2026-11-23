//go:build unix

package agent

import (
	"os"
	"syscall"
)

// lockFile holds an exclusive lock on the audit log until the returned function runs: one writer at a time, across
// processes (the HTTP interface and a `runs answer` side by side).
func lockFile(f *os.File) func() {
	if err := syscall.Flock(int(f.Fd()), syscall.LOCK_EX); err != nil {
		return func() {}
	}
	return func() { _ = syscall.Flock(int(f.Fd()), syscall.LOCK_UN) }
}
