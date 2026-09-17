package main

import (
	"path/filepath"
	"strings"
)

func resolveWebDist(hermesRoot string) string {
	if hermesRoot == "" {
		return ""
	}
	return filepath.Join(hermesRoot, "hermes_cli", "web_dist")
}

// desktopLaunchEnv prepares only Desktop-owned startup context. The watchdog
// never injects a backend URL/token: Electron main is the sole Desktop Python
// backend lifecycle authority and decides how its local backend is created.
func desktopLaunchEnv(cfg Config) []string {
	env := []string{
		"HERMES_HOME=" + cfg.HermesHome,
		"HERMES_DESKTOP_HERMES_ROOT=" + cfg.HermesRoot,
		"HERMES_DESKTOP_CWD=" + cfg.HermesRoot,
		// Explicitly clear inherited remote overrides so a watchdog relaunch
		// cannot accidentally convert a local Desktop into remote-primary mode.
		"HERMES_DESKTOP_REMOTE_URL=",
		"HERMES_DESKTOP_REMOTE_TOKEN=",
	}
	if webDist := resolveWebDist(cfg.HermesRoot); webDist != "" {
		env = append(env, "HERMES_DESKTOP_DASHBOARD_WEB_DIST="+webDist)
	}
	return env
}

// stripInheritedDesktopRemotes drops HERMES_DESKTOP_REMOTE_* from a base env
// block so the explicit empty values appended by desktopLaunchEnv are unique.
func stripInheritedDesktopRemotes(base []string) []string {
	out := make([]string, 0, len(base))
	for _, entry := range base {
		eq := strings.IndexByte(entry, '=')
		if eq <= 0 {
			out = append(out, entry)
			continue
		}
		key := entry[:eq]
		if key == "HERMES_DESKTOP_REMOTE_URL" || key == "HERMES_DESKTOP_REMOTE_TOKEN" {
			continue
		}
		out = append(out, entry)
	}
	return out
}
