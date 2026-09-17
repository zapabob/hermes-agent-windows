//go:build windows

package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestDesktopObservationRequiresExactExecutablePath(t *testing.T) {
	cfg := Config{PackagedExe: filepath.Join(`C:\\Hermes`, "Hermes.exe")}
	if !isOwnedDesktopExecutable(cfg, filepath.Join(`C:\\Hermes`, "Hermes.exe")) {
		t.Fatal("configured packaged executable should be observed")
	}
	if isOwnedDesktopExecutable(cfg, filepath.Join(`C:\\OtherApp`, "Hermes.exe")) {
		t.Fatal("same-basename foreign executable must not be observed as this Desktop")
	}
	if isOwnedDesktopExecutable(cfg, "") {
		t.Fatal("unknown executable path must fail closed")
	}
}

func TestBackendObservationRequiresConfiguredRoot(t *testing.T) {
	cfg := Config{HermesRoot: `C:\\Hermes`, HermesHome: `C:\\Users\\bob\\.hermes`}
	owned := win32Process{
		CommandLine:    `C:\\Hermes\\.venv\\Scripts\\python.exe -m hermes_cli.main serve --port 0`,
		ExecutablePath: `C:\\Hermes\\.venv\\Scripts\\python.exe`,
	}
	foreign := owned
	foreign.ExecutablePath = `C:\\OtherRepo\\.venv\\Scripts\\python.exe`
	if !isOwnedDesktopBackendProcess(cfg, owned) {
		t.Fatal("backend under the configured root should be observable")
	}
	if isOwnedDesktopBackendProcess(cfg, foreign) {
		t.Fatal("same command line from another checkout must not be classified as this Desktop backend")
	}
}

func TestWatchdogProductionHasNoDesktopBackendDestructiveAuthority(t *testing.T) {
	for _, name := range []string{"process_windows.go", "watchdog.go", "main.go", "config.go"} {
		raw, err := os.ReadFile(name)
		if err != nil {
			t.Fatal(err)
		}
		source := string(raw)
		for _, forbidden := range []string{
			"PROCESS_TERMINATE",
			"windows.TerminateProcess(",
			"restartPackagedDesktop",
			"stopOrphanDesktopBackends",
			"BackendManager",
			"PrewarmBackend",
			"HERMES_WATCHDOG_MANAGED",
		} {
			if strings.Contains(source, forbidden) {
				t.Fatalf("%s retains forbidden Desktop backend authority %q", name, forbidden)
			}
		}
	}
	if _, err := os.Stat("backend.go"); !os.IsNotExist(err) {
		t.Fatal("legacy watchdog-owned Desktop backend manager source must be removed")
	}
}

func TestDesktopLaunchEnvCannotInjectBackendCredentials(t *testing.T) {
	env := strings.Join(desktopLaunchEnv(Config{HermesRoot: `C:\\Hermes`, HermesHome: `C:\\Users\\bob\\.hermes`}), "\n")
	if !strings.Contains(env, "HERMES_DESKTOP_REMOTE_URL=") || !strings.Contains(env, "HERMES_DESKTOP_REMOTE_TOKEN=") {
		t.Fatal("watchdog Desktop launch must explicitly clear inherited remote backend overrides")
	}
	if strings.Contains(env, "HERMES_WATCHDOG_MANAGED") {
		t.Fatal("watchdog-managed backend marker must never reach Desktop")
	}
}

func TestSingleOwnerRunCycleObservesDesktopDownWithoutRelaunch(t *testing.T) {
	dir := t.TempDir()
	packaged := filepath.Join(dir, "Hermes.exe")
	if err := os.WriteFile(packaged, []byte{}, 0o644); err != nil {
		t.Fatal(err)
	}
	logPath := filepath.Join(dir, "watchdog.log")
	cfg := Config{
		HermesRoot:     dir,
		HermesHome:     dir,
		DataDir:        dir,
		PackagedExe:    packaged,
		PrewarmBackend: false,
		IntervalSec:    1,
		FailThreshold:  2,
	}
	logger := NewLogger(logPath)
	wd := NewWatchdog(cfg, logger)
	res := wd.RunCycle()
	if res.Desktop == "relaunched" || res.Desktop == "restarted" {
		t.Fatalf("single-owner mode must not relaunch Desktop, got desktop=%q", res.Desktop)
	}
	if res.Desktop != "down" {
		t.Fatalf("expected observe-only desktop=down for foreign/absent packaged path, got %q", res.Desktop)
	}
	raw, err := os.ReadFile(logPath)
	if err != nil {
		t.Fatal(err)
	}
	logText := string(raw)
	if strings.Contains(logText, "Desktop DOWN — relaunch") {
		t.Fatal("single-owner cycle must not emit Desktop relaunch")
	}
	if !strings.Contains(logText, "observe only (Electron owns Desktop lifecycle)") {
		t.Fatal("single-owner cycle must log observe-only Desktop DOWN")
	}
}

func TestWatchdogSourceKeepsDesktopRelaunchBehindPrewarm(t *testing.T) {
	raw, err := os.ReadFile("watchdog.go")
	if err != nil {
		t.Fatal(err)
	}
	source := string(raw)
	observeIdx := strings.Index(source, "Desktop DOWN — observe only (Electron owns Desktop lifecycle)")
	relaunchIdx := strings.Index(source, `w.logger.Infof("Desktop DOWN — relaunch")`)
	if observeIdx < 0 {
		t.Fatal("single-owner observe-only Desktop DOWN path missing")
	}
	if relaunchIdx < 0 {
		t.Fatal("legacy prewarm Desktop relaunch path missing")
	}
	if observeIdx > relaunchIdx {
		t.Fatal("observe-only single-owner path must precede legacy Desktop relaunch")
	}
	tokenIdx := strings.Index(source, "w.cfg.PrewarmBackend && w.back.TokenRotationPending()")
	if tokenIdx < 0 {
		t.Fatal("token-rotation Desktop restart must remain gated on PrewarmBackend")
	}
}
