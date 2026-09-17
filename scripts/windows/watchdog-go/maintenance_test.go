package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func writeMaintenanceState(t *testing.T, path string, state maintenanceState) {
	t.Helper()
	raw, err := json.Marshal(state)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, raw, 0o644); err != nil {
		t.Fatal(err)
	}
}

func TestMaintenanceModeHonorsEveryLiveUpdateState(t *testing.T) {
	now := time.Date(2026, 9, 1, 12, 0, 0, 0, time.UTC)
	path := filepath.Join(t.TempDir(), "maintenance.json")
	for _, mode := range []string{"UPDATE_PREPARE", "UPSTREAM_DRAIN", "UPDATE", "RECOVERY"} {
		t.Run(mode, func(t *testing.T) {
			writeMaintenanceState(t, path, maintenanceState{
				State:          mode,
				Owner:          "hermes-update:42",
				Nonce:          "nonce",
				LeaseExpiresAt: now.Add(time.Hour).Format(time.RFC3339),
			})
			got, active, err := maintenanceMode(path, now)
			if err != nil || !active || got.State != mode {
				t.Fatalf("maintenanceMode() = (%+v, %v, %v)", got, active, err)
			}
		})
	}
}

func TestMaintenanceModeAllowsNormalAndExpiredLease(t *testing.T) {
	now := time.Date(2026, 9, 1, 12, 0, 0, 0, time.UTC)
	path := filepath.Join(t.TempDir(), "maintenance.json")
	writeMaintenanceState(t, path, maintenanceState{
		State:          maintenanceNormal,
		LeaseExpiresAt: now.Add(time.Hour).Format(time.RFC3339),
	})
	if _, active, err := maintenanceMode(path, now); err != nil || active {
		t.Fatalf("NORMAL must not suspend: active=%v err=%v", active, err)
	}
	writeMaintenanceState(t, path, maintenanceState{
		State:          "UPDATE",
		LeaseExpiresAt: now.Add(-time.Second).Format(time.RFC3339),
	})
	if _, active, err := maintenanceMode(path, now); err != nil || active {
		t.Fatalf("expired lease must not suspend: active=%v err=%v", active, err)
	}
}

func TestFreshMalformedMaintenanceStateFailsClosed(t *testing.T) {
	path := filepath.Join(t.TempDir(), "maintenance.json")
	if err := os.WriteFile(path, []byte("{"), 0o644); err != nil {
		t.Fatal(err)
	}
	got, active, err := maintenanceMode(path, time.Now())
	if err == nil || !active || got.State != maintenanceUnknown {
		t.Fatalf("fresh malformed state must suspend: (%+v, %v, %v)", got, active, err)
	}
}

func TestRunCycleDoesNotMutateProcessesDuringMaintenance(t *testing.T) {
	dir := t.TempDir()
	maintenancePath := filepath.Join(dir, "maintenance.json")
	writeMaintenanceState(t, maintenancePath, maintenanceState{
		State:          "UPDATE",
		Owner:          "hermes-update:42",
		Nonce:          "nonce-42",
		Epoch:          42,
		Timestamp:      "2026-09-06T00:00:00Z",
		LeaseExpiresAt: time.Now().Add(time.Hour).Format(time.RFC3339),
	})
	cfg := Config{
		PackagedExe:     filepath.Join(dir, "must-not-launch.exe"),
		StatePath:       filepath.Join(dir, "watchdog.state.json"),
		MaintenancePath: maintenancePath,
	}
	wd := NewWatchdog(cfg, NewLogger(filepath.Join(dir, "watchdog.log")))
	result := wd.RunCycle()
	if result.Desktop != "maintenance" || result.Backend != "maintenance" || result.Embedding != "maintenance" {
		t.Fatalf("unexpected maintenance result: %+v", result)
	}
	state := wd.State()
	if state.MaintenanceState != "UPDATE" || state.MaintenanceOwner != "hermes-update:42" ||
		state.MaintenanceNonce != "nonce-42" || state.MaintenanceEpoch != 42 ||
		state.MaintenanceTimestamp != "2026-09-06T00:00:00Z" {
		t.Fatalf("watchdog did not acknowledge maintenance owner: %+v", state)
	}
	if fileExists(cfg.PackagedExe) {
		t.Fatal("maintenance cycle launched the packaged desktop")
	}
}

func TestDesktopRecoveryRechecksRevocationImmediatelyBeforeMutation(t *testing.T) {
	dir := t.TempDir()
	exe := filepath.Join(dir, "Hermes.exe")
	if err := os.WriteFile(exe, []byte("not executable"), 0o600); err != nil {
		t.Fatal(err)
	}
	cfg := Config{PackagedExe: exe, DataDir: dir}
	logger := NewLogger(filepath.Join(dir, "watchdog.log"))
	checks := 0
	revoked := func() bool {
		checks++
		return false
	}

	if startPackagedDesktop(cfg, logger, revoked) {
		t.Fatal("revoked cold launch must not start Desktop")
	}
	if checks != 1 {
		t.Fatalf("expected one last-moment launch authority check, got %d", checks)
	}
}
