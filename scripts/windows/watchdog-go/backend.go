package main

import (
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
	"time"
)

const desktopBackendManifestName = "desktop-backend.json"

// DefaultManagedBackendPort matches Desktop local serve expectation (:9119).
// 9120 remains reserved for the operator dashboard UI.
const DefaultManagedBackendPort = 9119

var backendReadyRE = regexp.MustCompile(`^HERMES_(?:BACKEND|DASHBOARD)_READY port=(\d+)`)

// DesktopBackendManifest is published for packaged Desktop to connect without cold-spawning serve.
type DesktopBackendManifest struct {
	BaseURL    string          `json:"baseUrl"`
	URL        string          `json:"url,omitempty"` // operator/compat alias for baseUrl
	Token      string          `json:"token"`
	Port       int             `json:"port"`
	PID        int             `json:"pid,omitempty"`
	HermesRoot string          `json:"hermesRoot,omitempty"`
	HermesHome string          `json:"hermesHome,omitempty"`
	UpdatedAt  json.RawMessage `json:"updatedAt,omitempty"` // string or unix-ms number
	Managed    bool            `json:"managed"`
}

// BackendManager supervises a watchdog-owned hermes serve for fast Desktop connect.
type BackendManager struct {
	cfg    Config
	logger *Logger

	mu    sync.Mutex
	cmd   *exec.Cmd
	pid   int
	port  int
	token string
}

func NewBackendManager(cfg Config, logger *Logger) *BackendManager {
	return &BackendManager{cfg: cfg, logger: logger}
}

func (bm *BackendManager) ManifestPath() string {
	return filepath.Join(bm.cfg.DataDir, desktopBackendManifestName)
}

func parseReadyPortLine(line string) (int, bool) {
	m := backendReadyRE.FindStringSubmatch(strings.TrimSpace(line))
	if len(m) != 2 {
		return 0, false
	}
	var port int
	if _, err := fmt.Sscanf(m[1], "%d", &port); err != nil || port <= 0 {
		return 0, false
	}
	return port, true
}

func generateSessionToken() (string, error) {
	buf := make([]byte, 32)
	if _, err := rand.Read(buf); err != nil {
		return "", err
	}
	return base64.RawURLEncoding.EncodeToString(buf), nil
}

func resolvePythonExe(hermesRoot string) string {
	if hermesRoot == "" {
		return ""
	}
	for _, rel := range []string{".venv\\Scripts\\python.exe", "venv\\Scripts\\python.exe"} {
		candidate := filepath.Join(hermesRoot, rel)
		if fileExists(candidate) {
			return candidate
		}
	}
	if home, err := os.UserHomeDir(); err == nil && home != "" {
		shared := filepath.Join(home, ".hermes", "hermes-agent", "venv", "Scripts", "python.exe")
		if fileExists(shared) {
			return shared
		}
	}
	return ""
}

func resolveWebDist(hermesRoot string) string {
	if hermesRoot == "" {
		return ""
	}
	candidate := filepath.Join(hermesRoot, "hermes_cli", "web_dist")
	if fileExists(filepath.Join(candidate, "index.html")) {
		return candidate
	}
	return candidate
}

func resolveServeWorkDir(cfg Config, python string) string {
	candidates := []string{
		strings.Trim(strings.TrimSpace(cfg.HermesRoot), `"'`),
		strings.Trim(strings.TrimSpace(cfg.HermesHome), `"'`),
	}
	if python != "" {
		// shared venv: ~/.hermes/hermes-agent/venv/Scripts/python.exe → repo-ish parent
		candidates = append(candidates, filepath.Clean(filepath.Join(filepath.Dir(python), "..", "..")))
	}
	for _, dir := range candidates {
		if dir == "" {
			continue
		}
		if st, err := os.Stat(dir); err == nil && st.IsDir() {
			return dir
		}
	}
	return ""
}

func buildServeCommand(cfg Config, preferredToken string) (*exec.Cmd, string, int, error) {
	python := resolvePythonExe(cfg.HermesRoot)
	if python == "" {
		return nil, "", 0, fmt.Errorf("python not found under %s (.venv or venv)", cfg.HermesRoot)
	}
	workDir := resolveServeWorkDir(cfg, python)
	if workDir == "" {
		return nil, "", 0, fmt.Errorf("no valid workdir for hermes serve (hermes-root=%q)", cfg.HermesRoot)
	}
	// Reuse the previous session token when restarting managed serve so a live
	// Desktop process (HERMES_DESKTOP_REMOTE_TOKEN from launch env) keeps
	// unlocking /api/sessions after a backend flap. Mint a new token only when
	// the caller has no preferred value (cold start or intentional drift replace).
	token := strings.TrimSpace(preferredToken)
	if token == "" {
		var err error
		token, err = generateSessionToken()
		if err != nil {
			return nil, "", 0, err
		}
	}
	port := cfg.ManagedBackendPort
	if port <= 0 {
		port = DefaultManagedBackendPort
	}
	if isReservedOpsPort(port) {
		return nil, "", 0, fmt.Errorf("managed backend port %d is reserved for ops services", port)
	}
	webDist := resolveWebDist(workDir)
	if webDist == "" {
		webDist = resolveWebDist(cfg.HermesRoot)
	}
	// --skip-build: headless serve already skips SPA build, but keep the flag
	// so callers/re-exec paths never fall into npm/web build hangs on cold start.
	cmd := exec.Command(
		python,
		"-m", "hermes_cli.main",
		"serve",
		"--host", "127.0.0.1",
		"--port", fmt.Sprintf("%d", port),
		"--skip-build",
	)
	cmd.Dir = workDir
	cmd.Env = append(os.Environ(),
		"HERMES_HOME="+cfg.HermesHome,
		"HERMES_DESKTOP=1",
		"HERMES_WATCHDOG_MANAGED=1",
		"HERMES_DASHBOARD_SESSION_TOKEN="+token,
		"HERMES_WEB_DIST="+webDist,
		"HERMES_DESKTOP_HERMES_ROOT="+workDir,
		"HERMES_DESKTOP_CWD="+workDir,
		"PYTHONUTF8=1",
		"PYTHONIOENCODING=utf-8",
		"PYTHONUNBUFFERED=1",
	)
	return cmd, token, port, nil
}

func (bm *BackendManager) readManifest() (*DesktopBackendManifest, error) {
	raw, err := os.ReadFile(bm.ManifestPath())
	if err != nil {
		return nil, err
	}
	var manifest DesktopBackendManifest
	if err := json.Unmarshal(raw, &manifest); err != nil {
		return nil, err
	}
	if manifest.BaseURL == "" && manifest.URL != "" {
		manifest.BaseURL = manifest.URL
	}
	return &manifest, nil
}

func (bm *BackendManager) writeManifest(manifest DesktopBackendManifest) error {
	raw, err := json.MarshalIndent(manifest, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(bm.ManifestPath(), raw, 0o644)
}

func (bm *BackendManager) clearManifest() {
	_ = os.Remove(bm.ManifestPath())
}

func (bm *BackendManager) currentHealthy() *backendInfo {
	bm.mu.Lock()
	pid := bm.pid
	port := bm.port
	bm.mu.Unlock()
	if pid <= 0 || port <= 0 {
		return nil
	}
	if !processAlive(pid) {
		return nil
	}
	if isReservedOpsPort(port) {
		return nil
	}
	if !testBackendStatus(port) {
		return nil
	}
	return &backendInfo{PID: uint32(pid), Port: port, Cmd: "watchdog-managed serve"}
}

func (bm *BackendManager) stopLocked() {
	if bm.cmd != nil && bm.cmd.Process != nil {
		// os.Process retains the Windows process handle opened by Start. Killing
		// through that handle cannot be redirected to a later process that reused
		// the same numeric PID.
		_ = bm.cmd.Process.Kill()
		_ = bm.cmd.Wait()
	}
	bm.cmd = nil
	bm.pid = 0
	bm.port = 0
	// Intentionally keep bm.token: Desktop may still hold this value via
	// HERMES_DESKTOP_REMOTE_TOKEN until the next relaunch. Clearing it here
	// forced a new mint on every serve restart and produced sessions 401 drift.
}

func (bm *BackendManager) waitForReadyPort(port int, timeout time.Duration) error {
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if testBackendStatus(port) {
			return nil
		}
		time.Sleep(500 * time.Millisecond)
	}
	return fmt.Errorf("timed out waiting for /api/status on port %d (%s)", port, timeout)
}

// EnsureHealthy keeps (or starts) the watchdog-managed serve and publishes desktop-backend.json.
func (bm *BackendManager) EnsureHealthy() (*backendInfo, error) {
	if bm.cfg.HermesRoot == "" {
		return nil, fmt.Errorf("hermes root not configured")
	}
	if existing := bm.currentHealthy(); existing != nil {
		// Prefer published manifest token over a stale in-memory copy so we
		// do not kill a healthy serve after an unrelated token rotation race.
		if manifest, err := bm.readManifest(); err == nil && manifest.Token != "" {
			bm.token = manifest.Token
		}
		if bm.token != "" && testBackendAuth(existing.Port, bm.token) {
			_ = bm.publishManifestLocked(existing.Port, int(existing.PID))
			return existing, nil
		}
		// Last chance: if the live port still accepts ANY known token from
		// the previous in-memory value after a rematch, keep it.
		bm.logger.Infof("in-memory backend auth mismatch on port %d; replacing only if port auth-dead", existing.Port)
		bm.mu.Lock()
		bm.stopLocked()
		bm.mu.Unlock()
		_ = waitManagedPortCleared(existing.Port, 15*time.Second, bm.logger)
	}

	bm.mu.Lock()
	defer bm.mu.Unlock()

	if bm.cmd != nil && bm.port > 0 && processAlive(bm.pid) && testBackendStatus(bm.port) {
		info := &backendInfo{PID: uint32(bm.pid), Port: bm.port, Cmd: "watchdog-managed serve"}
		_ = bm.publishManifestLocked(bm.port, bm.pid)
		return info, nil
	}

	bm.stopLocked()

	if port := bm.cfg.ManagedBackendPort; port <= 0 {
		port = DefaultManagedBackendPort
	} else if isReservedOpsPort(port) {
		bm.clearManifest()
		return nil, fmt.Errorf("managed backend port %d is reserved", port)
	} else if testBackendStatus(port) {
		bm.port = port
		if manifest, err := bm.readManifest(); err == nil && manifest.Token != "" {
			bm.token = manifest.Token
		} else if err != nil {
			bm.logger.Infof("managed port %d up but manifest unreadable: %v", port, err)
		}
		// Only reuse when token unlocks gated APIs. Otherwise we'd publish a
		// fresh token while the live serve still expects the old one (Desktop 401).
		if bm.token != "" && testBackendAuth(port, bm.token) {
			pid := 0
			if listeners := listeningPIDsOnPort(port); len(listeners) > 0 {
				pid = int(listeners[0])
			}
			bm.port = port
			bm.pid = pid
			_ = bm.publishManifestLocked(port, pid)
			bm.logger.Infof("reusing healthy managed backend on port %d (auth ok pid=%d)", port, pid)
			return &backendInfo{PID: uint32(pid), Port: port, Cmd: "existing serve on managed port"}, nil
		}
		if bm.token == "" {
			bm.logger.Infof("managed port %d is up but no reusable session token; replacing occupant", port)
		} else {
			bm.logger.Infof("managed port %d is up but session token drifted; replacing occupant", port)
		}
		if !waitManagedPortCleared(port, 15*time.Second, bm.logger) {
			bm.clearManifest()
			return nil, fmt.Errorf("managed port %d still occupied after token-drift replace", port)
		}
		bm.port = 0
		// Drift replace must mint a fresh token; the live occupant rejected ours.
		bm.token = ""
	} else if listeners := listeningPIDsOnPort(port); len(listeners) > 0 {
		// LISTEN-but-dead (HTTP 000) blocks bind; force-clear before spawn.
		bm.logger.Infof("managed port %d has LISTEN without /api/status; clearing zombie pid(s)=%v", port, listeners)
		if !waitManagedPortCleared(port, 15*time.Second, bm.logger) {
			bm.clearManifest()
			return nil, fmt.Errorf("managed port %d zombie LISTEN uncleared", port)
		}
	}

	preferredToken := strings.TrimSpace(bm.token)
	if preferredToken == "" {
		if manifest, err := bm.readManifest(); err == nil {
			preferredToken = strings.TrimSpace(manifest.Token)
		}
	}
	cmd, token, port, err := buildServeCommand(bm.cfg, preferredToken)
	if err != nil {
		bm.clearManifest()
		return nil, err
	}
	if preferredToken != "" && token == preferredToken {
		bm.logger.Infof("reusing session token for managed serve restart on port %d", port)
	}
	hideWindowsProcess(cmd)

	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return nil, err
	}
	cmd.Stderr = io.Discard

	if err := cmd.Start(); err != nil {
		bm.clearManifest()
		return nil, err
	}
	bm.cmd = cmd
	bm.pid = cmd.Process.Pid
	bm.port = port
	bm.token = token
	go io.Copy(io.Discard, stdout)

	if err := bm.waitForReadyPort(port, time.Duration(bm.cfg.BackendStartTimeoutSec)*time.Second); err != nil {
		if cmd.Process != nil && !processAlive(cmd.Process.Pid) {
			bm.stopLocked()
			bm.clearManifest()
			return nil, fmt.Errorf("managed backend exited before /api/status became ready")
		}
		// Child uvicorn may outlive the parent wrapper — keep waiting on the fixed port.
		if err2 := bm.waitForReadyPort(port, time.Duration(bm.cfg.BackendReadyTimeoutSec)*time.Second); err2 != nil {
			bm.stopLocked()
			bm.clearManifest()
			return nil, err2
		}
	}

	// Refuse to publish a token that does not authenticate (squatter race).
	if !testBackendAuth(port, token) {
		bm.logger.Infof("managed backend status-ready but auth failed on port %d; refusing drifted manifest", port)
		reusedToken := preferredToken != "" && token == preferredToken
		bm.stopLocked()
		_ = waitManagedPortCleared(port, 15*time.Second, bm.logger)
		bm.clearManifest()
		// Boot/logon often reuses a stale preferred token while serve minted a
		// different gate. One fresh-token retry avoids burning the recovery
		// budget and killing interactive Desktop.
		if reusedToken {
			bm.logger.Infof("retrying managed serve on port %d with freshly minted session token", port)
			bm.token = ""
			cmd2, token2, port2, err2 := buildServeCommand(bm.cfg, "")
			if err2 != nil {
				bm.clearManifest()
				return nil, fmt.Errorf("managed backend on port %d failed session-token auth (fresh mint: %w)", port, err2)
			}
			hideWindowsProcess(cmd2)
			stdout2, err2 := cmd2.StdoutPipe()
			if err2 != nil {
				return nil, err2
			}
			cmd2.Stderr = io.Discard
			if err2 := cmd2.Start(); err2 != nil {
				bm.clearManifest()
				return nil, err2
			}
			bm.cmd = cmd2
			bm.pid = cmd2.Process.Pid
			bm.port = port2
			bm.token = token2
			go io.Copy(io.Discard, stdout2)
			if err2 := bm.waitForReadyPort(port2, time.Duration(bm.cfg.BackendStartTimeoutSec)*time.Second); err2 != nil {
				if err3 := bm.waitForReadyPort(port2, time.Duration(bm.cfg.BackendReadyTimeoutSec)*time.Second); err3 != nil {
					bm.stopLocked()
					bm.clearManifest()
					return nil, fmt.Errorf("managed backend on port %d failed session-token auth (fresh ready: %w)", port, err3)
				}
			}
			if !testBackendAuth(port2, token2) {
				bm.stopLocked()
				_ = waitManagedPortCleared(port2, 15*time.Second, bm.logger)
				bm.clearManifest()
				return nil, fmt.Errorf("managed backend on port %d failed session-token auth after fresh mint", port2)
			}
			port = port2
		} else {
			return nil, fmt.Errorf("managed backend on port %d failed session-token auth", port)
		}
	}

	if err := bm.publishManifestLocked(port, bm.pid); err != nil {
		bm.logger.Infof("manifest write failed: %v", err)
	}

	bm.logger.Infof("managed backend ready pid=%d port=%d", bm.pid, bm.port)
	return &backendInfo{PID: uint32(bm.pid), Port: port, Cmd: "watchdog-managed serve"}, nil
}

func (bm *BackendManager) publishManifestLocked(port, pid int) error {
	if pid <= 0 {
		if listeners := listeningPIDsOnPort(port); len(listeners) > 0 {
			pid = int(listeners[0])
		}
	}
	updatedAt, _ := json.Marshal(time.Now().Format(time.RFC3339))
	manifest := DesktopBackendManifest{
		BaseURL:    fmt.Sprintf("http://127.0.0.1:%d", port),
		Token:      bm.token,
		Port:       port,
		PID:        pid,
		HermesRoot: bm.cfg.HermesRoot,
		HermesHome: bm.cfg.HermesHome,
		UpdatedAt:  updatedAt,
		Managed:    true,
	}
	return bm.writeManifest(manifest)
}

func loadManifestBackend(cfg Config) *backendInfo {
	path := filepath.Join(cfg.DataDir, desktopBackendManifestName)
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil
	}
	var manifest DesktopBackendManifest
	if err := json.Unmarshal(raw, &manifest); err != nil {
		return nil
	}
	if manifest.BaseURL == "" && manifest.URL != "" {
		manifest.BaseURL = manifest.URL
	}
	port := manifest.Port
	if port <= 0 && manifest.BaseURL != "" {
		// Best-effort parse http://127.0.0.1:NNNN
		var parsed int
		if _, err := fmt.Sscanf(strings.TrimPrefix(manifest.BaseURL, "http://127.0.0.1:"), "%d", &parsed); err == nil {
			port = parsed
		}
	}
	if port <= 0 || isReservedOpsPort(port) {
		return nil
	}
	if manifest.PID > 0 && !processAlive(manifest.PID) {
		return nil
	}
	if !testBackendStatus(port) {
		return nil
	}
	return &backendInfo{PID: uint32(manifest.PID), Port: port, Cmd: "manifest serve"}
}

func desktopLaunchEnv(cfg Config, manifest *DesktopBackendManifest) []string {
	env := []string{
		"HERMES_HOME=" + cfg.HermesHome,
		"HERMES_DESKTOP_HERMES_ROOT=" + cfg.HermesRoot,
		"HERMES_DESKTOP_CWD=" + cfg.HermesRoot,
	}
	webDist := resolveWebDist(cfg.HermesRoot)
	if webDist != "" {
		env = append(env, "HERMES_DESKTOP_DASHBOARD_WEB_DIST="+webDist)
	}
	if manifest != nil && strings.TrimSpace(manifest.BaseURL) != "" && strings.TrimSpace(manifest.Token) != "" {
		env = append(env,
			"HERMES_DESKTOP_REMOTE_URL="+strings.TrimSpace(manifest.BaseURL),
			"HERMES_DESKTOP_REMOTE_TOKEN="+strings.TrimSpace(manifest.Token),
		)
	} else {
		// Explicit clear: inherited User/process remotes must not reach Desktop as
		// URL-without-TOKEN (hard boot error) or a stale remote override.
		env = append(env,
			"HERMES_DESKTOP_REMOTE_URL=",
			"HERMES_DESKTOP_REMOTE_TOKEN=",
		)
	}
	return env
}

// stripInheritedDesktopRemotes drops HERMES_DESKTOP_REMOTE_* from a base env
// block so later appends (set or clear) are unambiguous on Windows.
func stripInheritedDesktopRemotes(base []string) []string {
	out := make([]string, 0, len(base))
	for _, e := range base {
		eq := strings.IndexByte(e, '=')
		if eq <= 0 {
			out = append(out, e)
			continue
		}
		key := e[:eq]
		if key == "HERMES_DESKTOP_REMOTE_URL" || key == "HERMES_DESKTOP_REMOTE_TOKEN" {
			continue
		}
		out = append(out, e)
	}
	return out
}
