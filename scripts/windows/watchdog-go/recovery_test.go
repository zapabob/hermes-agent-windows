package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestWriteRecoveryStateReplacesWholeDocument(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "recovery.json")
	if err := os.WriteFile(path, make([]byte, 128), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := writeRecoveryState(path, recoveryState{LastAction: "backend_start"}); err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var state recoveryState
	if err := json.Unmarshal(raw, &state); err != nil {
		t.Fatalf("replacement is not valid JSON: %v", err)
	}
	if state.LastAction != "backend_start" || state.UpdatedAt == "" {
		t.Fatalf("unexpected replacement state: %+v", state)
	}
	if matches, err := filepath.Glob(filepath.Join(dir, ".recovery-budget-*.tmp")); err != nil || len(matches) != 0 {
		t.Fatalf("temporary recovery files remain: matches=%v err=%v", matches, err)
	}
}

func TestRecoveryBackoffAndBudgetPersistAcrossWatchdogRestart(t *testing.T) {
	path := filepath.Join(t.TempDir(), "recovery.json")
	now := time.Date(2026, 9, 6, 1, 0, 0, 0, time.UTC)

	state, allowed, _, err := reserveRecovery(path, "desktop_relaunch", now)
	if err != nil || !allowed || state.Consecutive != 1 {
		t.Fatalf("first reserve = (%+v, %v, %v)", state, allowed, err)
	}
	if _, allowed, wait, err := reserveRecovery(path, "desktop_relaunch", now.Add(time.Second)); err != nil || allowed || wait <= 0 {
		t.Fatalf("backoff was not retained: allowed=%v wait=%v err=%v", allowed, wait, err)
	}

	for _, offset := range []time.Duration{30 * time.Second, 90 * time.Second} {
		if _, allowed, _, err := reserveRecovery(path, "desktop_relaunch", now.Add(offset)); err != nil || !allowed {
			t.Fatalf("reserve at %v: allowed=%v err=%v", offset, allowed, err)
		}
	}
	if _, allowed, wait, err := reserveRecovery(path, "desktop_relaunch", now.Add(3*time.Minute)); err != nil || allowed || wait != recoveryCircuitBreak {
		t.Fatalf("budget circuit = allowed=%v wait=%v err=%v", allowed, wait, err)
	}
	if state, err := readRecoveryState(path, now.Add(3*time.Minute)); err != nil || parseRecoveryTime(state.CircuitOpenUntil).IsZero() {
		t.Fatalf("circuit did not persist: state=%+v err=%v", state, err)
	}
}

func TestHealthyResetClearsBackoffButKeepsRollingBudget(t *testing.T) {
	path := filepath.Join(t.TempDir(), "recovery.json")
	now := time.Date(2026, 9, 6, 1, 0, 0, 0, time.UTC)
	if _, allowed, _, err := reserveRecovery(path, "backend_start", now); err != nil || !allowed {
		t.Fatal(err)
	}
	state, err := markRecoveryHealthy(path, now.Add(time.Second))
	if err != nil || state.Consecutive != 0 || state.NextAllowedAt != "" || len(state.Events) != 1 {
		t.Fatalf("healthy reset = %+v err=%v", state, err)
	}
	if _, allowed, _, err := reserveRecovery(path, "backend_start", now.Add(2*time.Second)); err != nil || !allowed {
		t.Fatalf("healthy state should clear backoff: allowed=%v err=%v", allowed, err)
	}
}

func TestMalformedRecoveryStateHealsToEmpty(t *testing.T) {
	path := filepath.Join(t.TempDir(), "recovery.json")
	// PowerShell Set-Content -Encoding utf8 prefixes U+FEFF; also cover truncated JSON.
	if err := os.WriteFile(path, append([]byte{0xEF, 0xBB, 0xBF}, '{'), 0o600); err != nil {
		t.Fatal(err)
	}
	state, allowed, _, err := reserveRecovery(path, "desktop_relaunch", time.Now())
	if err != nil || !allowed {
		t.Fatalf("corrupt/BOM budget must heal to empty allow: allowed=%v err=%v state=%+v", allowed, err, state)
	}
}
