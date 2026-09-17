package main

import (
	"path/filepath"
	"strings"
	"testing"
)

func TestDesktopLaunchEnvClearsInheritedRemoteBackendAuthority(t *testing.T) {
	cfg := Config{HermesRoot: filepath.Join("C:", "Hermes"), HermesHome: filepath.Join("C:", "Users", "bob", ".hermes")}
	env := desktopLaunchEnv(cfg)
	joined := strings.Join(env, "\n")
	if !strings.Contains(joined, "HERMES_DESKTOP_REMOTE_URL=") ||
		!strings.Contains(joined, "HERMES_DESKTOP_REMOTE_TOKEN=") {
		t.Fatalf("Desktop relaunch must clear inherited remote backend authority: %v", env)
	}
	if strings.Contains(joined, "HERMES_WATCHDOG_MANAGED") || strings.Contains(joined, "desktop-backend.json") {
		t.Fatalf("watchdog-owned backend state leaked into Desktop environment: %v", env)
	}
}

func TestStripInheritedDesktopRemotes(t *testing.T) {
	base := []string{
		"PATH=C:\\Windows",
		"HERMES_DESKTOP_REMOTE_URL=http://127.0.0.1:9119",
		"HERMES_DESKTOP_REMOTE_TOKEN=stale",
		"KEEP=1",
	}
	got := stripInheritedDesktopRemotes(base)
	joined := strings.Join(got, "\n")
	if strings.Contains(joined, "HERMES_DESKTOP_REMOTE_") {
		t.Fatalf("inherited Desktop remote variables survived: %v", got)
	}
	if !strings.Contains(joined, "PATH=C:\\Windows") || !strings.Contains(joined, "KEEP=1") {
		t.Fatalf("unrelated environment variables were dropped: %v", got)
	}
}
