//go:build windows

package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestProcessAliveUsesNativeProcessState(t *testing.T) {
	if !processAlive(os.Getpid()) {
		t.Fatal("current process must be reported alive")
	}
	if processAlive(0) {
		t.Fatal("PID zero must not be reported alive")
	}
}

func TestProcessIdentityUsesCreationTimeAndExecutable(t *testing.T) {
	identity, ok := readProcessIdentity(os.Getpid())
	if !ok {
		t.Fatal("current process identity must be readable")
	}
	executable, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	if identity.PID != os.Getpid() || identity.CreationTime == 0 {
		t.Fatalf("incomplete current process identity: %+v", identity)
	}
	if !sameExecutablePath(identity.ExecutablePath, executable) {
		t.Fatalf("identity executable %q does not match %q", identity.ExecutablePath, executable)
	}
}

func TestLockMatchesExactProcessIdentity(t *testing.T) {
	started := time.Date(2026, 9, 5, 8, 0, 0, 0, time.UTC)
	identity := processIdentity{
		PID:            31415,
		CreationTime:   424242,
		ExecutablePath: filepath.Join(`C:\Hermes`, "hermes-watchdog.exe"),
		StartedAt:      started,
	}
	lock := lockFile{
		PID:            identity.PID,
		ProcessCreated: identity.CreationTime,
		ExecutablePath: identity.ExecutablePath,
		StartedAt:      started.Format(time.RFC3339Nano),
		RepoRoot:       `C:\repo`,
	}

	if !lockMatchesProcess(lock, identity) {
		t.Fatal("exact lock identity must match")
	}
}

func TestLockRejectsReusedPIDAndForeignExecutable(t *testing.T) {
	started := time.Date(2026, 9, 5, 8, 0, 0, 0, time.UTC)
	lock := lockFile{
		PID:            27182,
		ProcessCreated: 111,
		ExecutablePath: `C:\Hermes\hermes-watchdog.exe`,
		StartedAt:      started.Format(time.RFC3339Nano),
	}

	reused := processIdentity{
		PID:            lock.PID,
		CreationTime:   222,
		ExecutablePath: lock.ExecutablePath,
		StartedAt:      started.Add(time.Minute),
	}
	if lockMatchesProcess(lock, reused) {
		t.Fatal("a reused PID with a different creation time must not match")
	}

	foreign := processIdentity{
		PID:            lock.PID,
		CreationTime:   lock.ProcessCreated,
		ExecutablePath: `C:\Windows\System32\notepad.exe`,
		StartedAt:      started,
	}
	if lockMatchesProcess(lock, foreign) {
		t.Fatal("a foreign executable must not match the watchdog lock")
	}
}

func TestLegacyLockRequiresNearCreationTimeAndMatchingExecutable(t *testing.T) {
	started := time.Date(2026, 9, 5, 8, 0, 0, 0, time.UTC)
	identity := processIdentity{
		PID:            16180,
		CreationTime:   987,
		ExecutablePath: `C:\Hermes\hermes-watchdog.exe`,
		StartedAt:      started,
	}
	legacy := lockFile{
		PID:            identity.PID,
		ExecutablePath: identity.ExecutablePath,
		StartedAt:      started.Add(time.Second).Format(time.RFC3339Nano),
	}

	if !lockMatchesProcess(legacy, identity) {
		t.Fatal("legacy lock should migrate only when its timestamp closely matches process creation")
	}
	legacy.StartedAt = started.Add(legacyLockStartTolerance + time.Second).Format(time.RFC3339Nano)
	if lockMatchesProcess(legacy, identity) {
		t.Fatal("stale legacy timestamp must not authorize process ownership")
	}
}

func TestAcquireLockIsExclusiveAndReleaseChecksIdentity(t *testing.T) {
	lockPath := filepath.Join(t.TempDir(), "watchdog.lock")
	logger := NewLogger(filepath.Join(t.TempDir(), "watchdog.log"))
	release, ok := acquireLock(lockPath, `C:\repo`, logger)
	if !ok || release == nil {
		t.Fatal("first owner must acquire the lock")
	}
	if secondRelease, secondOK := acquireLock(lockPath, `C:\repo`, logger); secondOK || secondRelease != nil {
		t.Fatal("a second owner must not acquire an existing live lock")
	}

	raw, err := os.ReadFile(lockPath)
	if err != nil {
		t.Fatal(err)
	}
	var lock lockFile
	if err := json.Unmarshal(raw, &lock); err != nil {
		t.Fatal(err)
	}
	lock.ProcessCreated++
	tampered, err := json.MarshalIndent(lock, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(lockPath, tampered, 0o600); err != nil {
		t.Fatal(err)
	}

	release()
	if _, err := os.Stat(lockPath); err != nil {
		t.Fatalf("release must preserve a lock whose process identity changed: %v", err)
	}
}

func TestConcurrentAcquireHasExactlyOneOwner(t *testing.T) {
	lockPath := filepath.Join(t.TempDir(), "watchdog.lock")
	logger := NewLogger(filepath.Join(t.TempDir(), "watchdog.log"))
	start := make(chan struct{})
	type result struct {
		release func()
		ok      bool
	}
	results := make(chan result, 8)
	for range 8 {
		go func() {
			<-start
			release, ok := acquireLock(lockPath, `C:\repo`, logger)
			results <- result{release: release, ok: ok}
		}()
	}
	close(start)

	owners := 0
	var release func()
	for range 8 {
		result := <-results
		if result.ok {
			owners++
			release = result.release
		}
	}
	if owners != 1 {
		t.Fatalf("expected exactly one lock owner, got %d", owners)
	}
	if release == nil {
		t.Fatal("winning owner must return a release function")
	}
	release()
}
