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

func TestBackendObservationIncludesVenvPythonWorker(t *testing.T) {
	cfg := Config{HermesRoot: `C:\Hermes Project`, HermesHome: `C:\Users\bob\.hermes`}
	parent := win32Process{ProcessID: 41, CreationTime: 100, Name: "python.exe",
		ExecutablePath: `C:\Hermes Project\.venv\Scripts\python.exe`,
		CommandLine:    `"C:\Hermes Project\.venv\Scripts\python.exe" -m hermes_cli.main --profile default serve --host 127.0.0.1 --port 0`}
	worker := win32Process{ProcessID: 42, ParentProcessID: 41, CreationTime: 200, Name: "python.exe",
		ExecutablePath: `C:\Users\bob\AppData\Roaming\uv\python\python.exe`,
		CommandLine:    `"C:\Users\bob\AppData\Roaming\uv\python\python.exe"  -m hermes_cli.main --profile default serve --host 127.0.0.1 --port 0`}
	cases := []struct {
		name   string
		mutate func(*win32Process, *win32Process)
		want   bool
	}{
		{name: "direct venv worker", want: true},
		{name: "reused parent pid", mutate: func(p *win32Process, _ *win32Process) { p.CreationTime = 300 }},
		{name: "unknown worker identity", mutate: func(_ *win32Process, w *win32Process) { w.CreationTime = 0 }},
		{name: "missing parent", mutate: func(_ *win32Process, w *win32Process) { w.ParentProcessID = 99 }},
		{name: "foreign checkout parent", mutate: func(p *win32Process, _ *win32Process) { p.ExecutablePath = `C:\OtherRepo\.venv\Scripts\python.exe` }},
		{name: "different profile", mutate: func(_ *win32Process, w *win32Process) {
			w.CommandLine = strings.Replace(w.CommandLine, "--profile default", "--profile other", 1)
		}},
		{name: "different service", mutate: func(_ *win32Process, w *win32Process) {
			w.CommandLine = strings.Replace(w.CommandLine, " serve ", " gateway ", 1)
		}},
		{name: "different interpreter", mutate: func(_ *win32Process, w *win32Process) { w.Name = "unrelated.exe" }},
		{name: "extra argument", mutate: func(_ *win32Process, w *win32Process) { w.CommandLine += " --other-option" }},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			p, w := parent, worker
			if tc.mutate != nil {
				tc.mutate(&p, &w)
			}
			found := false
			for _, candidate := range filterDesktopBackendCandidates(cfg, []win32Process{w, p}) {
				if candidate.ProcessID == w.ProcessID {
					found = true
				}
			}
			if found != tc.want {
				t.Fatalf("worker observed=%v, want %v", found, tc.want)
			}
		})
	}
}

func TestProcessImageFileAcceptsAliasWithoutTrustingDifferentFile(t *testing.T) {
	dir := t.TempDir()
	image, alias, other := filepath.Join(dir, "python.exe"), filepath.Join(dir, "alias.exe"), filepath.Join(dir, "other.exe")
	if err := os.WriteFile(image, []byte("image"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(other, []byte("image"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Link(image, alias); err != nil {
		t.Fatal(err)
	}
	if !sameProcessImageFile(image, alias) {
		t.Fatal("same file under two paths must retain its identity")
	}
	if sameProcessImageFile(image, other) {
		t.Fatal("identical bytes in a different file must not match")
	}
	if sameProcessImageFile(image, filepath.Join(dir, "missing.exe")) {
		t.Fatal("unknown image must fail closed")
	}
}

func TestDesktopBackendObservationQueryAcceptsWMIProcessRows(t *testing.T) {
	dir := t.TempDir()
	candidates, err := getDesktopBackendCandidates(Config{HermesRoot: dir, HermesHome: dir})
	if err != nil {
		t.Fatalf("native WMI observation failed: %v", err)
	}
	if len(candidates) != 0 {
		t.Fatal("unrelated processes must not belong to an empty configured root")
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

func TestSingleOwnerRunCycleObservesDesktopDownWithoutRelaunch(t *testing.T) {
	dir := t.TempDir()
	packaged := filepath.Join(dir, "Hermes.exe")
	if err := os.WriteFile(packaged, []byte{}, 0o644); err != nil {
		t.Fatal(err)
	}
	logPath := filepath.Join(dir, "watchdog.log")
	cfg := Config{
		HermesRoot:  dir,
		HermesHome:  dir,
		DataDir:     dir,
		PackagedExe: packaged,
		IntervalSec: 1,
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
	if !strings.Contains(logText, "observe only") {
		t.Fatal("single-owner cycle must log observe-only Desktop DOWN")
	}
}
