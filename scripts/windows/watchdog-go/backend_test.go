package main

import (
	"fmt"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestParseReadyPortLine(t *testing.T) {
	cases := []struct {
		line string
		want int
		ok   bool
	}{
		{"HERMES_BACKEND_READY port=43210", 43210, true},
		{"HERMES_DASHBOARD_READY port=9123", 9123, true},
		{"noise", 0, false},
		{"HERMES_BACKEND_READY port=0", 0, false},
	}
	for _, tc := range cases {
		got, ok := parseReadyPortLine(tc.line)
		if ok != tc.ok || got != tc.want {
			t.Fatalf("line %q => (%d,%v) want (%d,%v)", tc.line, got, ok, tc.want, tc.ok)
		}
	}
}

func TestBuildServeCommandIncludesSkipBuild(t *testing.T) {
	dir := t.TempDir()
	venvPy := filepath.Join(dir, ".venv", "Scripts")
	if err := os.MkdirAll(venvPy, 0o755); err != nil {
		t.Fatal(err)
	}
	pyPath := filepath.Join(venvPy, "python.exe")
	if err := os.WriteFile(pyPath, []byte("stub"), 0o644); err != nil {
		t.Fatal(err)
	}
	cfg := Config{
		HermesRoot:         dir,
		HermesHome:         dir,
		ManagedBackendPort: DefaultManagedBackendPort,
	}
	cmd, token, port, err := buildServeCommand(cfg, "")
	if err != nil {
		t.Fatal(err)
	}
	if token == "" || port != DefaultManagedBackendPort {
		t.Fatalf("unexpected token/port: %q %d", token, port)
	}
	joined := strings.Join(cmd.Args, " ")
	if !strings.Contains(joined, "serve") || !strings.Contains(joined, "--skip-build") {
		t.Fatalf("expected serve --skip-build in args, got %v", cmd.Args)
	}
	reused, reusedToken, _, err := buildServeCommand(cfg, "stable-session-token")
	if err != nil {
		t.Fatal(err)
	}
	if reusedToken != "stable-session-token" {
		t.Fatalf("expected preferred token reuse, got %q", reusedToken)
	}
	envJoined := strings.Join(reused.Env, ";")
	if !strings.Contains(envJoined, "HERMES_DASHBOARD_SESSION_TOKEN=stable-session-token") {
		t.Fatalf("preferred token missing from serve env: %q", envJoined)
	}
}

func TestResolvePythonExe(t *testing.T) {
	dir := t.TempDir()
	venvPy := filepath.Join(dir, ".venv", "Scripts")
	if err := os.MkdirAll(venvPy, 0o755); err != nil {
		t.Fatal(err)
	}
	pyPath := filepath.Join(venvPy, "python.exe")
	if err := os.WriteFile(pyPath, []byte("stub"), 0o644); err != nil {
		t.Fatal(err)
	}
	got := resolvePythonExe(dir)
	if got != pyPath {
		t.Fatalf("expected %q got %q", pyPath, got)
	}
}

func TestDesktopLaunchEnvClearsLoopbackManagedRemote(t *testing.T) {
	cfg := Config{
		HermesRoot: `C:\repo`,
		HermesHome: `C:\Users\u\.hermes`,
	}
	manifest := &DesktopBackendManifest{
		BaseURL: "http://127.0.0.1:54321",
		Token:   "tok",
	}
	env := desktopLaunchEnv(cfg, manifest)
	joined := stringsJoinEnv(env)
	for _, want := range []string{
		"HERMES_DESKTOP_HERMES_ROOT=C:\\repo",
		"HERMES_DESKTOP_REMOTE_URL=",
		"HERMES_DESKTOP_REMOTE_TOKEN=",
	} {
		if !containsSubstr(joined, want) {
			t.Fatalf("missing %q in %q", want, joined)
		}
	}
	if containsSubstr(joined, "HERMES_DESKTOP_REMOTE_URL=http://127.0.0.1:54321") {
		t.Fatalf("loopback managed serve must not inject REMOTE_URL: %q", joined)
	}
	if containsSubstr(joined, "HERMES_DESKTOP_REMOTE_TOKEN=tok") {
		t.Fatalf("loopback managed serve must not inject REMOTE_TOKEN: %q", joined)
	}
}

func TestDesktopLaunchEnvSetsNonLoopbackManagedRemote(t *testing.T) {
	cfg := Config{
		HermesRoot: `C:\repo`,
		HermesHome: `C:\Users\u\.hermes`,
	}
	manifest := &DesktopBackendManifest{
		BaseURL: "http://10.0.0.8:9119",
		Token:   "tok",
	}
	env := desktopLaunchEnv(cfg, manifest)
	joined := stringsJoinEnv(env)
	for _, want := range []string{
		"HERMES_DESKTOP_REMOTE_URL=http://10.0.0.8:9119",
		"HERMES_DESKTOP_REMOTE_TOKEN=tok",
		"HERMES_DESKTOP_HERMES_ROOT=C:\\repo",
	} {
		if !containsSubstr(joined, want) {
			t.Fatalf("missing %q in %q", want, joined)
		}
	}
}

func TestDesktopLaunchEnvClearsIncompleteRemotes(t *testing.T) {
	cfg := Config{HermesHome: "C:\\h", HermesRoot: "C:\\repo"}
	env := desktopLaunchEnv(cfg, nil)
	joined := stringsJoinEnv(env)
	if !containsSubstr(joined, "HERMES_DESKTOP_REMOTE_URL=") || !containsSubstr(joined, "HERMES_DESKTOP_REMOTE_TOKEN=") {
		t.Fatalf("expected explicit empty remotes, got %q", joined)
	}
	if containsSubstr(joined, "HERMES_DESKTOP_REMOTE_URL=http") {
		t.Fatalf("nil manifest must not inject remote URL: %q", joined)
	}
	env2 := desktopLaunchEnv(cfg, &DesktopBackendManifest{BaseURL: "http://127.0.0.1:9119", Token: ""})
	joined2 := stringsJoinEnv(env2)
	if containsSubstr(joined2, "HERMES_DESKTOP_REMOTE_URL=http://127.0.0.1:9119") {
		t.Fatalf("URL-only manifest must clear, not set URL: %q", joined2)
	}
}

func TestStripInheritedDesktopRemotes(t *testing.T) {
	base := []string{
		"PATH=C:\\Windows",
		"HERMES_DESKTOP_REMOTE_URL=http://stale:9118",
		"HERMES_DESKTOP_REMOTE_TOKEN=old",
		"FOO=bar",
	}
	got := stripInheritedDesktopRemotes(base)
	joined := stringsJoinEnv(got)
	if containsSubstr(joined, "HERMES_DESKTOP_REMOTE_URL=") || containsSubstr(joined, "HERMES_DESKTOP_REMOTE_TOKEN=") {
		t.Fatalf("strip must drop remotes, got %q", joined)
	}
	if !containsSubstr(joined, "PATH=C:\\Windows") || !containsSubstr(joined, "FOO=bar") {
		t.Fatalf("strip must keep unrelated env, got %q", joined)
	}
}

func stringsJoinEnv(env []string) string {
	out := ""
	for _, e := range env {
		out += e + ";"
	}
	return out
}

func containsSubstr(haystack, needle string) bool {
	return len(needle) == 0 || (len(haystack) >= len(needle) && indexOf(haystack, needle) >= 0)
}

func indexOf(s, sub string) int {
	for i := 0; i+len(sub) <= len(s); i++ {
		if s[i:i+len(sub)] == sub {
			return i
		}
	}
	return -1
}

func TestBackendManagerWriteReadManifest(t *testing.T) {
	dir := t.TempDir()
	cfg := Config{
		DataDir:    dir,
		HermesRoot: dir,
		HermesHome: dir,
	}
	logger := NewLogger(filepath.Join(dir, "test.log"))
	bm := NewBackendManager(cfg, logger)
	bm.mu.Lock()
	bm.token = "abc"
	bm.mu.Unlock()
	if err := bm.publishManifestLocked(12345, 999); err != nil {
		t.Fatal(err)
	}
	got, err := bm.readManifest()
	if err != nil {
		t.Fatal(err)
	}
	if got.Port != 12345 || got.Token != "abc" || !got.Managed {
		t.Fatalf("unexpected manifest: %+v", got)
	}
}

func TestTokenRotationArmedOnRemintNotFirstPublish(t *testing.T) {
	dir := t.TempDir()
	bm := NewBackendManager(Config{DataDir: dir, HermesRoot: dir, HermesHome: dir}, NewLogger(filepath.Join(dir, "t.log")))
	bm.token = "tok-a"
	if err := bm.publishManifestLocked(9119, 1); err != nil {
		t.Fatal(err)
	}
	if bm.TokenRotationPending() {
		t.Fatal("first publish must not arm token rotation")
	}
	bm.token = "tok-a"
	if err := bm.publishManifestLocked(9119, 1); err != nil {
		t.Fatal(err)
	}
	if bm.TokenRotationPending() {
		t.Fatal("same-token republish must not arm rotation")
	}
	bm.token = "tok-b"
	if err := bm.publishManifestLocked(9119, 2); err != nil {
		t.Fatal(err)
	}
	if !bm.TokenRotationPending() {
		t.Fatal("token remint must arm Desktop restart")
	}
	if !bm.ConsumeTokenRotation() {
		t.Fatal("ConsumeTokenRotation should return true once")
	}
	if bm.TokenRotationPending() || bm.ConsumeTokenRotation() {
		t.Fatal("rotation flag must clear after consume")
	}
}

func TestWaitManagedPortClearedEmptyPort(t *testing.T) {
	if !waitManagedPortCleared(0, time.Second, nil) {
		t.Fatal("port 0 should be treated as cleared")
	}
}

func TestWaitManagedPortClearedPreservesForeignListener(t *testing.T) {
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	server := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusServiceUnavailable)
	})}
	defer server.Close()
	go func() { _ = server.Serve(listener) }()
	port := listener.Addr().(*net.TCPAddr).Port

	if waitManagedPortCleared(port, 150*time.Millisecond, nil) {
		t.Fatal("foreign listener must remain occupied")
	}
	resp, err := http.Get(fmt.Sprintf("http://127.0.0.1:%d/", port))
	if err != nil {
		t.Fatalf("foreign listener was terminated: %v", err)
	}
	resp.Body.Close()
}

func TestReadManifestToleratesNumericUpdatedAtAndURLAlias(t *testing.T) {
	dir := t.TempDir()
	bm := NewBackendManager(Config{DataDir: dir}, NewLogger(filepath.Join(dir, "t.log")))
	raw := []byte(`{"url":"http://127.0.0.1:9119","token":"tok","port":9119,"updatedAt":1784904830048}`)
	if err := os.WriteFile(bm.ManifestPath(), raw, 0o644); err != nil {
		t.Fatal(err)
	}
	got, err := bm.readManifest()
	if err != nil {
		t.Fatalf("read: %v", err)
	}
	if got.Token != "tok" || got.BaseURL != "http://127.0.0.1:9119" || got.Port != 9119 {
		t.Fatalf("unexpected: %+v", got)
	}
}
