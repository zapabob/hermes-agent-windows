//go:build windows

package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestDesktopOwnershipRequiresExactExecutablePath(t *testing.T) {
	cfg := Config{PackagedExe: filepath.Join(`C:\\Hermes`, "Hermes.exe")}
	if !isOwnedDesktopExecutable(cfg, filepath.Join(`C:\\Hermes`, "Hermes.exe")) {
		t.Fatal("configured packaged executable should be owned")
	}
	if isOwnedDesktopExecutable(cfg, filepath.Join(`C:\\OtherApp`, "Hermes.exe")) {
		t.Fatal("same-basename foreign executable must not be owned")
	}
	if isOwnedDesktopExecutable(cfg, "") {
		t.Fatal("unknown executable path must fail closed")
	}
}

func TestDesktopStopRequiresCreationTimeAndExecutable(t *testing.T) {
	self, ok := readProcessIdentity(os.Getpid())
	if !ok {
		t.Fatal("current process identity unavailable")
	}
	wrongCreation := win32Process{
		ProcessID: uint32(self.PID), CreationTime: self.CreationTime + 1,
		ExecutablePath: self.ExecutablePath,
	}
	if stopProcessTreeIfIdentityMatches(wrongCreation, nil) {
		t.Fatal("creation-time mismatch must fail closed")
	}
	wrongPath := wrongCreation
	wrongPath.CreationTime = self.CreationTime
	wrongPath.ExecutablePath = filepath.Join(t.TempDir(), "foreign.exe")
	if stopProcessTreeIfIdentityMatches(wrongPath, nil) {
		t.Fatal("executable-path mismatch must fail closed")
	}
}

func TestBackendCandidateRequiresConfiguredRoot(t *testing.T) {
	cfg := Config{HermesRoot: `C:\\Hermes`, HermesHome: `C:\\Users\\bob\\.hermes`}
	owned := win32Process{
		CommandLine:    `C:\\Hermes\\.venv\\Scripts\\python.exe -m hermes_cli.main serve --port 9119`,
		ExecutablePath: `C:\\Hermes\\.venv\\Scripts\\python.exe`,
	}
	foreign := owned
	foreign.ExecutablePath = `C:\\OtherRepo\\.venv\\Scripts\\python.exe`
	if !isOwnedDesktopBackendProcess(cfg, owned) {
		t.Fatal("backend under the configured root should be observable as a candidate")
	}
	if isOwnedDesktopBackendProcess(cfg, foreign) {
		t.Fatal("same command line from another checkout must be preserved")
	}
}

func TestOrphanReaperHasNoDestructiveAuthority(t *testing.T) {
	dir := t.TempDir()
	if stopped := stopOrphanDesktopBackends(NewLogger(filepath.Join(dir, "t.log")), Config{}); stopped != 0 {
		t.Fatalf("manual backend candidates must be preserved, stopped=%d", stopped)
	}
	raw, err := os.ReadFile("process_windows.go")
	if err != nil {
		t.Fatal(err)
	}
	source := string(raw)
	start := strings.Index(source, "func stopOrphanDesktopBackends")
	end := strings.Index(source[start+1:], "\nfunc ")
	body := source[start:]
	if end >= 0 {
		body = source[start : start+1+end]
	}
	if strings.Contains(body, "stopProcessPID") || strings.Contains(body, "taskkill") {
		t.Fatal("orphan classification must never become process termination authority")
	}
}

func TestDesktopTerminationNeverReentersThroughNumericPID(t *testing.T) {
	raw, err := os.ReadFile("process_windows.go")
	if err != nil {
		t.Fatal(err)
	}
	source := string(raw)
	start := strings.Index(source, "func stopProcessTreeIfIdentityMatches")
	end := strings.Index(source[start+1:], "\nfunc ")
	body := source[start:]
	if end >= 0 {
		body = source[start : start+1+end]
	}
	if strings.Contains(body, "taskkill") || strings.Contains(body, "stopProcessPID") {
		t.Fatal("validated Desktop identity must not be converted back to a numeric PID kill")
	}
	if !strings.Contains(body, "TerminateProcess(handle") ||
		!strings.Contains(body, "readProcessIdentityFromHandle(handle") {
		t.Fatal("Desktop stop must validate and terminate through the same kernel handle")
	}
}

func TestDestructiveProcessCodeHasNoImageKillOrNetstatFallback(t *testing.T) {
	raw, err := os.ReadFile("process_windows.go")
	if err != nil {
		t.Fatal(err)
	}
	source := string(raw)
	if strings.Contains(source, `taskkill", "/IM"`) {
		t.Fatal("image-name taskkill can terminate a foreign Hermes.exe")
	}
	start := strings.Index(source, "func stopListenersOnPort")
	if start >= 0 {
		end := strings.Index(source[start+1:], "\nfunc ")
		body := source[start:]
		if end >= 0 {
			body = source[start : start+1+end]
		}
		if strings.Contains(body, "listeningPIDsOnPort") {
			t.Fatal("netstat-only listener PIDs must never become kill authority")
		}
	}
}

func TestWatchdogDefaultDisablesDesktopBackendPrewarm(t *testing.T) {
	cfg := Config{}
	if cfg.PrewarmBackend {
		t.Fatal("PrewarmBackend default must be false for single-owner Desktop backend architecture")
	}
}

func TestEmbeddingSupervisorDoesNotSpawnOrKillDesktopBackend(t *testing.T) {
	dir := t.TempDir()
	cfg := Config{
		HermesRoot:     dir,
		HermesHome:     dir,
		DataDir:        dir,
		PrewarmBackend: false, // single-owner mode
	}
	logger := NewLogger(filepath.Join(dir, "test.log"))
	wd := NewWatchdog(cfg, logger)

	// PrewarmBackend must be a no-op
	wd.PrewarmBackend()
	if wd.back.currentHealthy() != nil {
		t.Fatal("embedding supervisor must not prewarm desktop backend")
	}

	// Desktop backend manifest must not exist
	if _, err := os.Stat(wd.back.ManifestPath()); !os.IsNotExist(err) {
		t.Fatal("embedding supervisor must not write desktop-backend.json")
	}
}
