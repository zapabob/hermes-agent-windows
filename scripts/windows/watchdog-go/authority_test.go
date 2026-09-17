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
		t.Fatal("foreign same-basename executable must not be observed as this Desktop")
	}
	if isOwnedDesktopExecutable(cfg, "") {
		t.Fatal("unknown executable path must fail closed")
	}
}

func TestBackendObservationRequiresConfiguredRoot(t *testing.T) {
	cfg := Config{HermesRoot: `C:\\Hermes`, HermesHome: `C:\\Users\\bob\\.hermes`}
	owned := win32Process{CommandLine: `C:\\Hermes\\.venv\\Scripts\\python.exe -m hermes_cli.main serve --port 0`, ExecutablePath: `C:\\Hermes\\.venv\\Scripts\\python.exe`}
	foreign := owned
	foreign.ExecutablePath = `C:\\OtherRepo\\.venv\\Scripts\\python.exe`
	if !isOwnedDesktopBackendProcess(cfg, owned) {
		t.Fatal("configured-root backend should be observable")
	}
	if isOwnedDesktopBackendProcess(cfg, foreign) {
		t.Fatal("foreign checkout must not be classified as this Desktop backend")
	}
}

func TestWatchdogProductionHasNoDesktopOrBackendLifecycleAuthority(t *testing.T) {
	for _, name := range []string{"process_windows.go", "watchdog.go", "main.go", "config.go"} {
		raw, err := os.ReadFile(name)
		if err != nil {
			t.Fatal(err)
		}
		source := string(raw)
		for _, forbidden := range []string{"PROCESS_TERMINATE", "windows.TerminateProcess(", "startPackagedDesktop", "restartPackagedDesktop", "stopOrphanDesktopBackends", "BackendManager", "PrewarmBackend", "EnsureHealthy()", "HERMES_WATCHDOG_MANAGED", "desktop-backend.json", "desktop_relaunch", "HermesDesktopAutoStart"} {
			if strings.Contains(source, forbidden) {
				t.Fatalf("%s retains forbidden Desktop/backend lifecycle authority %q", name, forbidden)
			}
		}
	}
	for _, removed := range []string{"backend.go", "health.go", "desktop_launch_env.go"} {
		if _, err := os.Stat(removed); !os.IsNotExist(err) {
			t.Fatalf("legacy lifecycle source %s must be removed", removed)
		}
	}
}
