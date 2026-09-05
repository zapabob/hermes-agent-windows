package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestMutatingRoutesAreNotRegistered(t *testing.T) {
	cfg := Config{}
	wd := NewWatchdog(cfg, NewLogger(t.TempDir()+"/test.log"))
	srv := NewHTTPServer(wd)
	for _, path := range []string{
		"/api/v1/pause",
		"/api/v1/resume",
		"/api/v1/cycle",
		"/api/v1/stop",
		"/api/v1/restart",
		"/api/v1/force-restart",
	} {
		req := httptest.NewRequest(http.MethodPost, path, nil)
		req.Header.Set("Authorization", "Bearer secret-token")
		req.Header.Set("X-Admin-Token", "secret-token")
		w := httptest.NewRecorder()
		srv.Handler().ServeHTTP(w, req)
		if w.Code != http.StatusNotFound {
			t.Fatalf("%s must not be registered; got %d body=%s", path, w.Code, w.Body.String())
		}
	}
}

func TestStatusJSON(t *testing.T) {
	cfg := Config{ListenAddr: "127.0.0.1:9920"}
	wd := NewWatchdog(cfg, NewLogger(t.TempDir()+"/test.log"))
	srv := NewHTTPServer(wd)
	req := httptest.NewRequest("GET", "/api/status", nil)
	w := httptest.NewRecorder()
	srv.handleStatus(w, req)
	if w.Code != 200 {
		t.Fatalf("expected 200, got %d", w.Code)
	}
	var state WatchdogState
	if err := json.Unmarshal(w.Body.Bytes(), &state); err != nil {
		t.Fatal(err)
	}
	if state.ListenAddr != cfg.ListenAddr {
		t.Fatalf("unexpected listen addr %q", state.ListenAddr)
	}
}

func TestIsDesktopBackendCommandLine(t *testing.T) {
	cases := []struct {
		cl   string
		want bool
	}{
		{"python -m hermes_cli.main serve", true},
		{"python -m hermes_cli.main serve --host 127.0.0.1 --port 0", true},
		{"python -m hermes_cli.main serve --port 9120", false},
		{"python -m hermes_cli.main dashboard --no-open", true},
		{"python -m hermes_cli.main gateway start", false},
		{"python -m hermes_cli.main harness start", false},
		{"", false},
	}
	for _, tc := range cases {
		if got := isDesktopBackendCommandLine(tc.cl); got != tc.want {
			t.Fatalf("cmd %q => %v want %v", tc.cl, got, tc.want)
		}
	}
}

func TestIsReservedOpsPort(t *testing.T) {
	for _, port := range []int{8787, 9120, 9123, 9124} {
		if !isReservedOpsPort(port) {
			t.Fatalf("expected stack-owned port %d to be excluded from watchdog management", port)
		}
	}
	if isReservedOpsPort(54321) {
		t.Fatal("ephemeral port must not be reserved")
	}
}
