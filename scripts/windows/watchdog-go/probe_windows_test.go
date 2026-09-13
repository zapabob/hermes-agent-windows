//go:build windows

package main

import (
	"net"
	"net/http"
	"testing"
	"time"
)

func startProbeServer(t *testing.T, handler http.Handler) (port int, closeFn func()) {
	t.Helper()
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	srv := &http.Server{Handler: handler}
	go func() { _ = srv.Serve(ln) }()
	port = ln.Addr().(*net.TCPAddr).Port
	return port, func() {
		_ = srv.Close()
		_ = ln.Close()
	}
}

func TestProbeBackendStatusClassifiesTimeout(t *testing.T) {
	port, closeFn := startProbeServer(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		time.Sleep(800 * time.Millisecond)
		w.WriteHeader(http.StatusOK)
	}))
	defer closeFn()

	res := probeBackendStatus(port, 100*time.Millisecond)
	if res.Kind != ProbeTimeout {
		t.Fatalf("kind=%s want timeout (err=%v)", res.Kind, res.Err)
	}
}

func TestProbeBackendStatusClassifiesHTTP500(t *testing.T) {
	port, closeFn := startProbeServer(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
	}))
	defer closeFn()

	res := probeBackendStatus(port, time.Second)
	if res.Kind != ProbeHTTPError || res.StatusCode != 500 {
		t.Fatalf("kind=%s code=%d want http_error/500", res.Kind, res.StatusCode)
	}
}

func TestProbeBackendStatusClassifiesOK(t *testing.T) {
	port, closeFn := startProbeServer(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))
	defer closeFn()

	res := probeBackendStatus(port, time.Second)
	if !res.OK() {
		t.Fatalf("kind=%s want ok", res.Kind)
	}
}

func TestProbeBackendStatusClassifiesTransportError(t *testing.T) {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	port := ln.Addr().(*net.TCPAddr).Port
	_ = ln.Close()

	res := probeBackendStatus(port, 200*time.Millisecond)
	if res.Kind != ProbeTransportError {
		t.Fatalf("kind=%s want transport_error (err=%v)", res.Kind, res.Err)
	}
}

func TestProbeBackendAuthClassifiesUnauthorized(t *testing.T) {
	port, closeFn := startProbeServer(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusUnauthorized)
	}))
	defer closeFn()

	res := probeBackendAuth(port, "tok", time.Second)
	if !res.DefinitiveAuthFailure() {
		t.Fatalf("kind=%s want unauthorized", res.Kind)
	}
}

func TestProbeBackendAuthClassifiesTimeoutSeparatelyFromUnauthorized(t *testing.T) {
	port, closeFn := startProbeServer(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		time.Sleep(800 * time.Millisecond)
		w.WriteHeader(http.StatusUnauthorized)
	}))
	defer closeFn()

	res := probeBackendAuth(port, "tok", 100*time.Millisecond)
	if res.Kind != ProbeTimeout {
		t.Fatalf("kind=%s want timeout (not unauthorized)", res.Kind)
	}
	if res.DefinitiveAuthFailure() {
		t.Fatal("timeout must not be definitive auth failure")
	}
}
