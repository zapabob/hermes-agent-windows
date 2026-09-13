package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"time"
)

const (
	recoveryWindow       = 10 * time.Minute
	recoveryBudget       = 3
	recoveryBaseBackoff  = 30 * time.Second
	recoveryMaxBackoff   = 5 * time.Minute
	recoveryCircuitBreak = 15 * time.Minute
)

type recoveryState struct {
	Events           []string `json:"events,omitempty"`
	Consecutive      int      `json:"consecutive"`
	NextAllowedAt    string   `json:"nextAllowedAt,omitempty"`
	CircuitOpenUntil string   `json:"circuitOpenUntil,omitempty"`
	LastAction       string   `json:"lastAction,omitempty"`
	UpdatedAt        string   `json:"updatedAt"`
}

func parseRecoveryTime(value string) time.Time {
	parsed, err := time.Parse(time.RFC3339Nano, value)
	if err != nil {
		return time.Time{}
	}
	return parsed
}

func readRecoveryState(path string, now time.Time) (recoveryState, error) {
	if path == "" {
		return recoveryState{}, fmt.Errorf("recovery state path is empty")
	}
	raw, err := os.ReadFile(path)
	if os.IsNotExist(err) {
		return recoveryState{}, nil
	}
	if err != nil {
		return recoveryState{}, err
	}
	// UTF-8 BOM (e.g. PowerShell Set-Content -Encoding utf8) and partial
	// writes must not permanently deny all recovery — treat as empty and
	// let the next successful reserve rewrite a clean document.
	raw = bytes.TrimPrefix(raw, []byte{0xEF, 0xBB, 0xBF})
	raw = bytes.TrimSpace(raw)
	if len(raw) == 0 {
		return recoveryState{}, nil
	}
	var state recoveryState
	if err := json.Unmarshal(raw, &state); err != nil {
		return recoveryState{}, nil
	}
	cutoff := now.Add(-recoveryWindow)
	kept := state.Events[:0]
	for _, rawEvent := range state.Events {
		if event := parseRecoveryTime(rawEvent); !event.IsZero() && !event.Before(cutoff) && !event.After(now.Add(time.Minute)) {
			kept = append(kept, event.Format(time.RFC3339Nano))
		}
	}
	state.Events = kept
	return state, nil
}

func writeRecoveryState(path string, state recoveryState) error {
	state.UpdatedAt = time.Now().UTC().Format(time.RFC3339Nano)
	raw, err := json.MarshalIndent(state, "", "  ")
	if err != nil {
		return err
	}
	if path == "" {
		return fmt.Errorf("recovery state path is empty")
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return err
	}
	// Never truncate the live state file in place. A terminated watchdog or a
	// concurrent reader during os.WriteFile can leave a zero-filled/partial JSON
	// document, which disables the recovery budget and blocks all future starts.
	tmp, err := os.CreateTemp(filepath.Dir(path), ".recovery-budget-*.tmp")
	if err != nil {
		return err
	}
	tmpPath := tmp.Name()
	defer func() {
		_ = os.Remove(tmpPath)
	}()
	if err := tmp.Chmod(0o600); err != nil {
		_ = tmp.Close()
		return err
	}
	if _, err := tmp.Write(raw); err != nil {
		_ = tmp.Close()
		return err
	}
	if err := tmp.Sync(); err != nil {
		_ = tmp.Close()
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	if err := os.Rename(tmpPath, path); err != nil {
		return fmt.Errorf("replace recovery state: %w", err)
	}
	return nil
}

func reserveRecovery(path, action string, now time.Time) (recoveryState, bool, time.Duration, error) {
	state, err := readRecoveryState(path, now)
	if err != nil {
		return state, false, recoveryCircuitBreak, err
	}
	if until := parseRecoveryTime(state.CircuitOpenUntil); until.After(now) {
		return state, false, until.Sub(now), nil
	}
	if len(state.Events) >= recoveryBudget {
		until := now.Add(recoveryCircuitBreak)
		state.CircuitOpenUntil = until.Format(time.RFC3339Nano)
		state.NextAllowedAt = state.CircuitOpenUntil
		if err := writeRecoveryState(path, state); err != nil {
			return state, false, recoveryCircuitBreak, err
		}
		return state, false, recoveryCircuitBreak, nil
	}
	if next := parseRecoveryTime(state.NextAllowedAt); next.After(now) {
		return state, false, next.Sub(now), nil
	}

	state.Events = append(state.Events, now.Format(time.RFC3339Nano))
	state.Consecutive++
	backoff := recoveryBaseBackoff << min(state.Consecutive-1, 4)
	if backoff > recoveryMaxBackoff {
		backoff = recoveryMaxBackoff
	}
	state.NextAllowedAt = now.Add(backoff).Format(time.RFC3339Nano)
	state.CircuitOpenUntil = ""
	state.LastAction = action
	if err := writeRecoveryState(path, state); err != nil {
		return state, false, recoveryCircuitBreak, err
	}
	return state, true, 0, nil
}

func markRecoveryHealthy(path string, now time.Time) (recoveryState, error) {
	state, err := readRecoveryState(path, now)
	if err != nil {
		return state, err
	}
	state.Consecutive = 0
	state.NextAllowedAt = ""
	state.CircuitOpenUntil = ""
	state.LastAction = "healthy"
	return state, writeRecoveryState(path, state)
}
