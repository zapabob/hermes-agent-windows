//go:build windows

package main

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"strings"
	"time"
)

// ProbeKind classifies HTTP health/auth outcomes. Timeout must never be
// conflated with authentication failure or process death.
type ProbeKind int

const (
	ProbeOK ProbeKind = iota
	ProbeTimeout
	ProbeUnauthorized
	ProbeHTTPError
	ProbeTransportError
)

func (k ProbeKind) String() string {
	switch k {
	case ProbeOK:
		return "ok"
	case ProbeTimeout:
		return "timeout"
	case ProbeUnauthorized:
		return "unauthorized"
	case ProbeHTTPError:
		return "http_error"
	case ProbeTransportError:
		return "transport_error"
	default:
		return "unknown"
	}
}

// ProbeResult is the classified outcome of one backend HTTP probe.
type ProbeResult struct {
	Kind       ProbeKind
	StatusCode int
	Latency    time.Duration
	Err        error
}

func (r ProbeResult) OK() bool {
	return r.Kind == ProbeOK
}

func (r ProbeResult) DefinitiveAuthFailure() bool {
	return r.Kind == ProbeUnauthorized
}

func (r ProbeResult) SoftFailure() bool {
	switch r.Kind {
	case ProbeTimeout, ProbeTransportError, ProbeHTTPError:
		return true
	default:
		return false
	}
}

func classifyHTTPProbe(err error, statusCode int, latency time.Duration) ProbeResult {
	res := ProbeResult{Latency: latency, StatusCode: statusCode, Err: err}
	if err != nil {
		if errors.Is(err, context.DeadlineExceeded) || isTimeoutErr(err) {
			res.Kind = ProbeTimeout
			return res
		}
		res.Kind = ProbeTransportError
		return res
	}
	switch {
	case statusCode == http.StatusOK:
		res.Kind = ProbeOK
	case statusCode == http.StatusUnauthorized || statusCode == http.StatusForbidden:
		res.Kind = ProbeUnauthorized
	default:
		res.Kind = ProbeHTTPError
	}
	return res
}

func isTimeoutErr(err error) bool {
	if err == nil {
		return false
	}
	var ne net.Error
	if errors.As(err, &ne) && ne.Timeout() {
		return true
	}
	msg := strings.ToLower(err.Error())
	return strings.Contains(msg, "timeout") || strings.Contains(msg, "deadline exceeded")
}

func probeBackendStatus(port int, timeout time.Duration) ProbeResult {
	if port <= 0 {
		return ProbeResult{Kind: ProbeTransportError, Err: fmt.Errorf("invalid port")}
	}
	if timeout <= 0 {
		timeout = 2 * time.Second
	}
	client := &http.Client{Timeout: timeout}
	start := time.Now()
	resp, err := client.Get(fmt.Sprintf("http://127.0.0.1:%d/api/status", port))
	latency := time.Since(start)
	if err != nil {
		return classifyHTTPProbe(err, 0, latency)
	}
	defer resp.Body.Close()
	_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, 4096))
	return classifyHTTPProbe(nil, resp.StatusCode, latency)
}

func probeBackendAuth(port int, token string, timeout time.Duration) ProbeResult {
	if port <= 0 || strings.TrimSpace(token) == "" {
		return ProbeResult{Kind: ProbeTransportError, Err: fmt.Errorf("missing port or token")}
	}
	if timeout <= 0 {
		timeout = 3 * time.Second
	}
	tok := strings.TrimSpace(token)
	client := &http.Client{Timeout: timeout}
	req, err := http.NewRequest(http.MethodGet, fmt.Sprintf("http://127.0.0.1:%d/api/sessions", port), nil)
	if err != nil {
		return ProbeResult{Kind: ProbeTransportError, Err: err}
	}
	req.Header.Set("Authorization", "Bearer "+tok)
	req.Header.Set("X-Hermes-Session-Token", tok)
	start := time.Now()
	resp, err := client.Do(req)
	latency := time.Since(start)
	if err != nil {
		return classifyHTTPProbe(err, 0, latency)
	}
	defer resp.Body.Close()
	_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, 4096))
	return classifyHTTPProbe(nil, resp.StatusCode, latency)
}

// Boolean wrappers retained for read-only backend observation probes.
func testBackendStatus(port int) bool {
	return probeBackendStatus(port, 2*time.Second).OK()
}

func testBackendAuth(port int, token string) bool {
	return probeBackendAuth(port, token, 3*time.Second).OK()
}
