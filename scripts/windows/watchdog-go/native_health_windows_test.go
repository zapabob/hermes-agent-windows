//go:build windows

package main

import (
	"fmt"
	"net"
	"net/http"
	"sync/atomic"
	"testing"
	"time"
)

// Temporary event-loop stall: listener alive, /api/status delayed 30s.
// Expect: owned PID unchanged, no stopLocked, health=DEGRADED.
func TestNativeStallStatusDoesNotKillOwnedBackend(t *testing.T) {
	if testing.Short() {
		t.Skip("native stall takes >30s")
	}
	var stall atomic.Bool
	stall.Store(true)
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	port := ln.Addr().(*net.TCPAddr).Port
	mux := http.NewServeMux()
	mux.HandleFunc("/api/status", func(w http.ResponseWriter, r *http.Request) {
		if stall.Load() {
			time.Sleep(35 * time.Second)
		}
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"ok":true}`))
	})
	mux.HandleFunc("/api/sessions", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`[]`))
	})
	srv := &http.Server{Handler: mux}
	go func() { _ = srv.Serve(ln) }()
	defer func() { _ = srv.Close() }()

	dir := t.TempDir()
	cfg := Config{
		HermesRoot:                  dir,
		DataDir:                     dir,
		ManagedBackendPort:          port,
		BackendSoftFailThreshold:    3,
		BackendUnresponsiveGraceSec: 120,
		BackendStatusTimeoutMs:      500,
		BackendAuthTimeoutMs:        500,
	}
	bm := NewBackendManager(cfg, NewLogger(dir+"\\w.log"))
	// Adopt the test server as "owned" without a real Python child.
	bm.pid = 1 // placeholder; processAlive hooked
	bm.port = port
	bm.token = "native-stall-token"
	bm.probeHooks = backendProbeFns{
		processAlive: func(int) bool { return true },
		status:       probeBackendStatus,
		auth:         probeBackendAuth,
		now:          time.Now,
		sleep:        time.Sleep,
	}
	bm.resetStopCount()

	start := time.Now()
	info, err := bm.EnsureHealthy()
	elapsed := time.Since(start)
	if err != nil {
		t.Fatal(err)
	}
	if info == nil || int(info.PID) != bm.pid {
		t.Fatalf("pid changed: %+v", info)
	}
	if bm.stopInvoked() {
		t.Fatal("stopLocked during stall")
	}
	if bm.token != "native-stall-token" {
		t.Fatal("token rotated during stall")
	}
	state, _, _, _, _, _ := bm.HealthSnapshot()
	if state != BackendDegraded {
		t.Fatalf("health=%s want degraded", state)
	}
	if elapsed > 5*time.Second {
		// probe timeout should be ~500ms, not wait for handler sleep
		t.Logf("probe returned in %s (expected ~status timeout)", elapsed)
	}
	stall.Store(false)
	// Recovery before grace
	info2, err := bm.EnsureHealthy()
	if err != nil {
		t.Fatal(err)
	}
	if info2.PID != info.PID {
		t.Fatal("pid changed after recovery")
	}
	state, fails, _, _, _, _ := bm.HealthSnapshot()
	if state != BackendHealthy {
		t.Fatalf("after recovery health=%s fails=%d", state, fails)
	}
	if fails != 0 {
		t.Fatalf("softFailures not reset: %d", fails)
	}
}

func TestNativeHangPastGraceRestartsOnce(t *testing.T) {
	if testing.Short() {
		t.Skip("grace test uses shortened config, not full 120s")
	}
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	port := ln.Addr().(*net.TCPAddr).Port
	mux := http.NewServeMux()
	mux.HandleFunc("/api/status", func(w http.ResponseWriter, r *http.Request) {
		time.Sleep(2 * time.Second)
		w.WriteHeader(http.StatusOK)
	})
	mux.HandleFunc("/api/sessions", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = fmt.Fprint(w, "[]")
	})
	srv := &http.Server{Handler: mux}
	go func() { _ = srv.Serve(ln) }()
	defer func() { _ = srv.Close() }()

	dir := t.TempDir()
	cfg := Config{
		HermesRoot:                  dir,
		DataDir:                     dir,
		ManagedBackendPort:          port,
		BackendSoftFailThreshold:    2,
		BackendUnresponsiveGraceSec: 1,
		BackendStatusTimeoutMs:      100,
		BackendAuthTimeoutMs:        100,
	}
	bm := NewBackendManager(cfg, NewLogger(dir+"\\hang.log"))
	bm.pid = 42
	bm.port = port
	bm.token = "hang-token"
	clock := time.Now()
	bm.probeHooks = backendProbeFns{
		processAlive: func(int) bool { return true },
		status:       probeBackendStatus,
		auth:         probeBackendAuth,
		now:          func() time.Time { return clock },
		sleep:        func(time.Duration) {},
	}
	bm.resetStopCount()
	_, _ = bm.EnsureHealthy() // fail 1 degraded
	clock = clock.Add(2 * time.Second)
	_, _ = bm.EnsureHealthy() // fail 2 + grace → unresponsive → stop
	if !bm.stopInvoked() {
		t.Fatal("expected controlled restart after grace")
	}
	if bm.TokenRotationPending() {
		t.Fatal("hang restart must not arm token rotation when token unchanged")
	}
}
