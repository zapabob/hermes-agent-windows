//go:build windows

package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"time"
	"unsafe"

	"github.com/yusufpapurcu/wmi"
	"golang.org/x/sys/windows"
)

type win32Process struct {
	ProcessID      uint32
	CreationTime   uint64
	Name           string
	CommandLine    string
	ExecutablePath string
}

func isOwnedDesktopExecutable(cfg Config, executablePath string) bool {
	expected := strings.TrimSpace(cfg.PackagedExe)
	actual := strings.TrimSpace(executablePath)
	if expected == "" || actual == "" {
		return false
	}
	return strings.EqualFold(filepath.Clean(expected), filepath.Clean(actual))
}

func getDesktopProcesses(cfg Config) ([]win32Process, error) {
	snapshot, err := windows.CreateToolhelp32Snapshot(windows.TH32CS_SNAPPROCESS, 0)
	if err != nil {
		return nil, fmt.Errorf("create process snapshot: %w", err)
	}
	defer windows.CloseHandle(snapshot)

	entry := windows.ProcessEntry32{Size: uint32(unsafe.Sizeof(windows.ProcessEntry32{}))}
	if err := windows.Process32First(snapshot, &entry); err != nil {
		return nil, fmt.Errorf("read process snapshot: %w", err)
	}

	var procs []win32Process
	for {
		name := windows.UTF16ToString(entry.ExeFile[:])
		if strings.EqualFold(name, "Hermes.exe") {
			identity, ok := readProcessIdentity(int(entry.ProcessID))
			if ok && isOwnedDesktopExecutable(cfg, identity.ExecutablePath) {
				procs = append(procs, win32Process{
					ProcessID: entry.ProcessID, CreationTime: identity.CreationTime,
					Name: name, ExecutablePath: identity.ExecutablePath,
				})
			}
		}
		if err := windows.Process32Next(snapshot, &entry); err != nil {
			if err == syscall.ERROR_NO_MORE_FILES {
				break
			}
			return nil, fmt.Errorf("advance process snapshot: %w", err)
		}
	}
	return procs, nil
}

// reservedOpsPorts are stack-owned listeners — never treat as Desktop's
// ephemeral hermes serve.  In particular, the independently launched A2A Hub
// (:9123) and deterministic round-robin service (:9124) are outside the Go
// watchdog's direct supervision boundary.
var reservedOpsPorts = map[int]struct{}{
	8080: {}, 8081: {}, 8646: {}, 8765: {}, 8787: {}, 9120: {}, 9123: {}, 9124: {}, 9920: {}, 18794: {},
}

func isReservedOpsPort(port int) bool {
	_, ok := reservedOpsPorts[port]
	return ok
}

func isDesktopBackendCommandLine(cl string) bool {
	if cl == "" {
		return false
	}
	lower := strings.ToLower(cl)
	if !strings.Contains(cl, "hermes_cli.main") &&
		!strings.Contains(cl, "\\hermes.exe") &&
		!strings.Contains(cl, "Scripts\\hermes.exe") {
		return false
	}
	// Never manage gateway / harness / cron — those are stack services.
	if strings.Contains(lower, " gateway") || strings.Contains(lower, " harness") || strings.Contains(lower, " cron") {
		return false
	}
	// Explicit ops dashboard / fixed ports are not Desktop-spawned backends.
	if strings.Contains(cl, "--port 9120") || strings.Contains(cl, "--port=9120") ||
		strings.Contains(cl, "--port 8787") || strings.Contains(cl, "--port=8787") {
		return false
	}
	if strings.Contains(cl, " serve") || strings.Contains(cl, "\tserve") {
		// Prefer Desktop's ephemeral serve (--port 0). Bare "serve" still matches,
		// but find/reap skip reserved ops ports so dashboard:9120 is never claimed/killed.
		return true
	}
	if strings.Contains(cl, "dashboard") && strings.Contains(cl, "--no-open") {
		return true
	}
	return false
}

func pathWithin(candidate, root string) bool {
	if strings.TrimSpace(candidate) == "" || strings.TrimSpace(root) == "" {
		return false
	}
	candidate = filepath.Clean(candidate)
	root = filepath.Clean(root)
	rel, err := filepath.Rel(root, candidate)
	return err == nil && rel != ".." && !strings.HasPrefix(rel, ".."+string(filepath.Separator))
}

func isOwnedDesktopBackendProcess(cfg Config, proc win32Process) bool {
	if !isDesktopBackendCommandLine(proc.CommandLine) {
		return false
	}
	return pathWithin(proc.ExecutablePath, cfg.HermesRoot) || pathWithin(proc.ExecutablePath, cfg.HermesHome)
}

func getDesktopBackendCandidates(cfg Config) ([]win32Process, error) {
	type result struct {
		procs []win32Process
		err   error
	}
	ch := make(chan result, 1)
	go func() {
		var all []win32Process
		// Full Win32_Process+CommandLine can hang when a process is wedged.
		err := wmi.Query("SELECT ProcessId, Name, CommandLine, ExecutablePath FROM Win32_Process", &all)
		if err != nil {
			ch <- result{nil, err}
			return
		}
		out := make([]win32Process, 0, 4)
		for _, p := range all {
			if isOwnedDesktopBackendProcess(cfg, p) {
				out = append(out, p)
			}
		}
		ch <- result{out, nil}
	}()
	select {
	case r := <-ch:
		return r.procs, r.err
	case <-time.After(8 * time.Second):
		return nil, fmt.Errorf("WMI process scan timed out after 8s")
	}
}

func netstatTCPOutput(timeout time.Duration) ([]byte, error) {
	if timeout <= 0 {
		timeout = 8 * time.Second
	}
	cmd := exec.Command("netstat", "-ano", "-p", "tcp")
	type result struct {
		b   []byte
		err error
	}
	ch := make(chan result, 1)
	go func() {
		b, err := cmd.CombinedOutput()
		ch <- result{b, err}
	}()
	select {
	case r := <-ch:
		return r.b, r.err
	case <-time.After(timeout):
		if cmd.Process != nil {
			_ = cmd.Process.Kill()
		}
		return nil, fmt.Errorf("netstat timed out after %s", timeout)
	}
}

func listeningPIDsOnPort(port int) []uint32 {
	if port <= 0 {
		return nil
	}
	out, err := netstatTCPOutput(8 * time.Second)
	if err != nil {
		return nil
	}
	needle := fmt.Sprintf(":%d", port)
	seen := map[uint32]struct{}{}
	var pids []uint32
	for _, line := range strings.Split(string(out), "\n") {
		line = strings.TrimSpace(line)
		if !strings.Contains(line, "LISTENING") || !strings.Contains(line, needle) {
			continue
		}
		fields := strings.Fields(line)
		if len(fields) < 5 {
			continue
		}
		hostPort := fields[1]
		idx := strings.LastIndex(hostPort, ":")
		if idx < 0 {
			continue
		}
		p, convErr := strconv.Atoi(hostPort[idx+1:])
		if convErr != nil || p != port {
			continue
		}
		pid64, convErr := strconv.ParseUint(fields[len(fields)-1], 10, 32)
		if convErr != nil || pid64 == 0 {
			continue
		}
		pid := uint32(pid64)
		if _, ok := seen[pid]; ok {
			continue
		}
		seen[pid] = struct{}{}
		pids = append(pids, pid)
	}
	return pids
}

func getListeningPorts(pid uint32) ([]int, error) {
	out, err := netstatTCPOutput(8 * time.Second)
	if err != nil {
		return nil, err
	}
	ports := make([]int, 0, 2)
	target := fmt.Sprintf("%d", pid)
	for _, line := range strings.Split(string(out), "\n") {
		line = strings.TrimSpace(line)
		if !strings.Contains(line, "LISTENING") {
			continue
		}
		fields := strings.Fields(line)
		if len(fields) < 5 || fields[len(fields)-1] != target {
			continue
		}
		hostPort := fields[1]
		idx := strings.LastIndex(hostPort, ":")
		if idx < 0 {
			continue
		}
		portStr := hostPort[idx+1:]
		port, convErr := strconv.Atoi(portStr)
		if convErr == nil && port > 0 {
			ports = appendUniqueInt(ports, port)
		}
	}
	return ports, nil
}

func appendUniqueInt(list []int, v int) []int {
	for _, existing := range list {
		if existing == v {
			return list
		}
	}
	return append(list, v)
}

func testBackendStatus(port int) bool {
	client := &http.Client{Timeout: 2 * time.Second}
	resp, err := client.Get(fmt.Sprintf("http://127.0.0.1:%d/api/status", port))
	if err != nil {
		return false
	}
	defer resp.Body.Close()
	return resp.StatusCode == http.StatusOK
}

// testBackendAuth verifies the session token unlocks a gated API.
// /api/status is public, so LISTEN+status-OK can still be token-drift.
// Matches Desktop electron/watchdog-backend.ts: Authorization Bearer +
// X-Hermes-Session-Token (post-7/20 gate accepts Bearer).
func testBackendAuth(port int, token string) bool {
	if port <= 0 || strings.TrimSpace(token) == "" {
		return false
	}
	tok := strings.TrimSpace(token)
	client := &http.Client{Timeout: 3 * time.Second}
	req, err := http.NewRequest(http.MethodGet, fmt.Sprintf("http://127.0.0.1:%d/api/sessions", port), nil)
	if err != nil {
		return false
	}
	req.Header.Set("Authorization", "Bearer "+tok)
	req.Header.Set("X-Hermes-Session-Token", tok)
	resp, err := client.Do(req)
	if err != nil {
		return false
	}
	defer resp.Body.Close()
	return resp.StatusCode == http.StatusOK
}

// waitManagedPortCleared is deliberately observational. A port number alone is
// never authority to terminate its owner; an unrelated process may legitimately
// hold the configured port. Callers may stop an in-memory child they launched,
// then use this helper to prove the port became free.
func waitManagedPortCleared(port int, timeout time.Duration, logger *Logger) bool {
	if port <= 0 {
		return true
	}
	if timeout <= 0 {
		timeout = 15 * time.Second
	}
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if testBackendStatus(port) {
			time.Sleep(400 * time.Millisecond)
			continue
		}
		if len(listeningPIDsOnPort(port)) == 0 {
			return true
		}
		time.Sleep(400 * time.Millisecond)
	}
	cleared := !testBackendStatus(port) && len(listeningPIDsOnPort(port)) == 0
	if !cleared && logger != nil {
		logger.Infof("managed port %d still occupied after clear wait (%s)", port, timeout)
	}
	return cleared
}

type backendInfo struct {
	PID  uint32 `json:"pid"`
	Port int    `json:"port"`
	Cmd  string `json:"cmd,omitempty"`
}

func findHealthyDesktopBackend(cfg Config) *backendInfo {
	candidates, err := getDesktopBackendCandidates(cfg)
	if err != nil {
		return nil
	}
	for _, proc := range candidates {
		ports, perr := getListeningPorts(proc.ProcessID)
		if perr != nil {
			continue
		}
		for _, port := range ports {
			if isReservedOpsPort(port) {
				continue
			}
			if testBackendStatus(port) {
				return &backendInfo{
					PID:  proc.ProcessID,
					Port: port,
					Cmd:  proc.CommandLine,
				}
			}
		}
	}
	return nil
}

func stopProcessTreeIfIdentityMatches(expected win32Process, logger *Logger) bool {
	// Keep the queried kernel handle through termination. Resolving the numeric
	// PID again after validation can target a foreign process if the original
	// exits and Windows reuses the number.
	handle, err := windows.OpenProcess(
		windows.PROCESS_QUERY_LIMITED_INFORMATION|windows.PROCESS_TERMINATE|windows.SYNCHRONIZE,
		false,
		expected.ProcessID,
	)
	if err != nil {
		if logger != nil {
			logger.Infof("refusing Desktop stop pid=%d: cannot open exact process handle", expected.ProcessID)
		}
		return false
	}
	defer windows.CloseHandle(handle)

	identity, ok := readProcessIdentityFromHandle(handle, int(expected.ProcessID))
	if !ok || identity.CreationTime != expected.CreationTime ||
		!sameExecutablePath(identity.ExecutablePath, expected.ExecutablePath) {
		if logger != nil {
			logger.Infof("refusing Desktop stop pid=%d: process identity changed", expected.ProcessID)
		}
		return false
	}
	if err := windows.TerminateProcess(handle, 1); err != nil {
		if logger != nil {
			logger.Infof("Desktop stop pid=%d failed on exact process handle: %v", expected.ProcessID, err)
		}
		return false
	}
	_, _ = windows.WaitForSingleObject(handle, 5_000)
	return true
}

func stopAllDesktopProcessTrees(logger *Logger, cfg Config) {
	desktop, err := getDesktopProcesses(cfg)
	if err != nil {
		logger.Infof("enumerate Hermes.exe for tree-kill: %v", err)
	}
	seen := make(map[uint32]struct{}, len(desktop))
	for _, p := range desktop {
		if _, ok := seen[p.ProcessID]; ok {
			continue
		}
		seen[p.ProcessID] = struct{}{}
		logger.Infof("stopping exact owned Hermes.exe process pid=%d", p.ProcessID)
		stopProcessTreeIfIdentityMatches(p, logger)
	}
}

func stopOrphanDesktopBackends(logger *Logger, cfg Config, skipPIDs ...uint32) int {
	// Process name, path, command line, and listening port establish only that a
	// process resembles a Desktop backend. They do not prove that this watchdog
	// launched it. Preserve every candidate and let the watchdog stop only the
	// exact child handle held by BackendManager.
	if logger != nil {
		logger.Infof("orphan backend reap skipped: no watchdog-owned child identity")
	}
	return 0
}

func readLaunchManifest(cfg Config, bm *BackendManager) *DesktopBackendManifest {
	if bm != nil {
		if manifest, err := bm.readManifest(); err == nil && manifest != nil {
			return manifest
		}
	}
	path := filepath.Join(cfg.DataDir, desktopBackendManifestName)
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil
	}
	var manifest DesktopBackendManifest
	if json.Unmarshal(raw, &manifest) != nil {
		return nil
	}
	if manifest.BaseURL == "" || manifest.Token == "" {
		return nil
	}
	return &manifest
}

// currentProcessSessionID returns the Windows session that hosts this process.
// Session 0 is the non-interactive services session (S4U boot tasks land here).
func currentProcessSessionID() (uint32, error) {
	var sessionID uint32
	err := windows.ProcessIdToSessionId(uint32(os.Getpid()), &sessionID)
	return sessionID, err
}

func isNonInteractiveSession() bool {
	sessionID, err := currentProcessSessionID()
	return err == nil && sessionID == 0
}

const desktopLogonTaskName = "HermesDesktopAutoStart"

// startDesktopInInteractiveSession asks the logon-registered Desktop task to
// run in the user's interactive session. Direct CreateProcess from Session 0
// either fails silently or produces a window the console user never sees.
func startDesktopInInteractiveSession(logger *Logger) bool {
	cmd := exec.Command("schtasks.exe", "/Run", "/TN", desktopLogonTaskName)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	out, err := cmd.CombinedOutput()
	trimmed := strings.TrimSpace(string(out))
	if err != nil {
		if logger != nil {
			logger.Infof("Session 0 Desktop relaunch via %s failed: %v (%s)", desktopLogonTaskName, err, trimmed)
		}
		return false
	}
	if logger != nil {
		logger.Infof("requested interactive Desktop launch via scheduled task %s", desktopLogonTaskName)
	}
	return true
}

func startPackagedDesktop(cfg Config, logger *Logger, bm *BackendManager, mutationAllowed func() bool) bool {
	if !fileExists(cfg.PackagedExe) {
		logger.Infof("Hermes.exe missing at %s", cfg.PackagedExe)
		return false
	}
	if mutationAllowed != nil && !mutationAllowed() {
		logger.Infof("Desktop launch revoked by maintenance fence")
		return false
	}
	// S4U boot tasks host the watchdog in Session 0. Never CreateProcess a GUI
	// Desktop there — kill+skip left the console without Hermes.exe and burned
	// the recovery budget. Prefer the Interactive logon task instead.
	if isNonInteractiveSession() {
		logger.Infof("watchdog is running in Session 0 (non-interactive); launching Desktop via %s (Desktop belongs in user session)", desktopLogonTaskName)
		return startDesktopInInteractiveSession(logger)
	}
	work := filepath.Dir(cfg.PackagedExe)
	cmd := exec.Command(cfg.PackagedExe)
	cmd.Dir = work
	manifest := readLaunchManifest(cfg, bm)
	cmd.Env = append(stripInheritedDesktopRemotes(os.Environ()), desktopLaunchEnv(cfg, manifest)...)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	if err := cmd.Start(); err != nil {
		logger.Infof("failed to launch Desktop: %v", err)
		return false
	}
	if manifest != nil {
		logger.Infof("launched %s (prewarmed backend %s)", cfg.PackagedExe, manifest.BaseURL)
	} else {
		logger.Infof("launched %s", cfg.PackagedExe)
	}
	return true
}

func restartPackagedDesktop(cfg Config, logger *Logger, bm *BackendManager, mutationAllowed func() bool) bool {
	if mutationAllowed != nil && !mutationAllowed() {
		logger.Infof("Desktop restart revoked before stop")
		return false
	}
	// Session 0 can terminate interactive Hermes.exe but cannot put a visible
	// window back. Refusing the stop avoids "Desktop mysteriously dies".
	if isNonInteractiveSession() {
		logger.Infof("Session 0: refusing Desktop kill; recovering managed backend only")
		if bm != nil {
			if _, err := bm.EnsureHealthy(); err != nil {
				logger.Infof("Session 0 backend recovery: %v", err)
			}
		}
		return false
	}
	logger.Infof("restarting Desktop (force backend respawn)")
	stopAllDesktopProcessTrees(logger, cfg)
	time.Sleep(2 * time.Second)
	if mutationAllowed != nil && !mutationAllowed() {
		logger.Infof("Desktop restart revoked after stop")
		return false
	}
	var skipPID uint32
	if bm != nil {
		if managed := bm.currentHealthy(); managed != nil {
			skipPID = managed.PID
		}
	}
	// Desktop is gone — reap leftover ephemeral serves (managed :9119 is skipped).
	stopOrphanDesktopBackends(logger, cfg, skipPID)
	time.Sleep(1 * time.Second)
	if mutationAllowed != nil && !mutationAllowed() {
		logger.Infof("Desktop restart revoked before backend recovery")
		return false
	}
	if bm != nil {
		if _, err := bm.EnsureHealthy(); err != nil {
			logger.Infof("pre-restart managed backend: %v", err)
		}
	}
	return startPackagedDesktop(cfg, logger, bm, mutationAllowed)
}
