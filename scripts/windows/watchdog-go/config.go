package main

import (
	"os"
	"path/filepath"
	"strings"
)

// Config holds runtime paths and secrets loaded from flags/env.
// This binary is intentionally outside Hermes tool/plugin discovery.
type Config struct {
	IntervalSec              int
	FailThreshold            int
	Once                     bool
	PrewarmBackend           bool
	BackendStartTimeoutSec   int
	BackendReadyTimeoutSec   int
	ManagedBackendPort       int
	EmbeddingEnabled         bool
	EmbeddingEndpoint        string
	EmbeddingServer          string
	EmbeddingModel           string
	EmbeddingArgsJSON        string
	EmbeddingStartTimeoutSec int
	ListenAddr               string
	TsnetHostname            string
	EnableTsnet              bool
	HermesRoot               string
	HermesHome               string
	PackagedExe              string
	DataDir                  string
	LogPath                  string
	LockPath                 string
	StatePath                string
	MaintenancePath          string
	TsAuthKey                string
}

func defaultHermesHome() string {
	if v := strings.TrimSpace(os.Getenv("HERMES_HOME")); v != "" {
		return v
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return ""
	}
	return filepath.Join(home, ".hermes")
}

func defaultDataDir() string {
	if v := strings.TrimSpace(os.Getenv("HERMES_WATCHDOG_DATA")); v != "" {
		return v
	}
	local := os.Getenv("LOCALAPPDATA")
	if local == "" {
		return filepath.Join(defaultHermesHome(), "watchdog-go")
	}
	return filepath.Join(local, "HermesWatchdog")
}

func defaultPackagedExe(repoRoot string) string {
	if repoRoot != "" {
		candidate := filepath.Join(repoRoot, "apps", "desktop", "release", "win-unpacked", "Hermes.exe")
		if fileExists(candidate) {
			return candidate
		}
	}
	local := os.Getenv("LOCALAPPDATA")
	if local != "" {
		candidate := filepath.Join(local, "hermes", "hermes-agent", "apps", "desktop", "release", "win-unpacked", "Hermes.exe")
		if fileExists(candidate) {
			return candidate
		}
	}
	if local != "" {
		return filepath.Join(local, "hermes", "hermes-agent", "apps", "desktop", "release", "win-unpacked", "Hermes.exe")
	}
	return ""
}

func loadTsAuthKey() string {
	for _, key := range []string{"HERMES_WATCHDOG_TS_AUTHKEY", "TS_AUTHKEY"} {
		if v := strings.TrimSpace(os.Getenv(key)); v != "" {
			return v
		}
	}
	return ""
}

func fileExists(path string) bool {
	if path == "" {
		return false
	}
	_, err := os.Stat(path)
	return err == nil
}

func ensureDir(path string) error {
	return os.MkdirAll(path, 0o755)
}
