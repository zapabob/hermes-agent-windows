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
	ProcessID   uint32
	Name        string
	CommandLine string
}

func getDesktopProcesses() ([]win32Process, error) {
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
			procs = append(procs, win32Process{ProcessID: entry.ProcessID, Name: name})
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

func getDesktopBackendCandidates() ([]win32Process, error) {
	type result struct {
		procs []win32Process
		err   error
	}
	ch := make(chan result, 1)
	go func() {
		var all []win32Process
		// Full Win32_Process+CommandLine can hang when a process is wedged.
		err := wmi.Query("SELECT ProcessId, Name, CommandLine FROM Win32_Process", &all)
		if err != nil {
			ch <- result{nil, err}
			return
		}
		out := make([]win32Process, 0, 4)
		for _, p := range all {
			if isDesktopBackendCommandLine(p.CommandLine) {
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

// stopListenersOnPort kills process trees holding LocalPort==port.
// waitManagedPortCleared kills listeners and waits until /api/status is gone
// so a replacement serve is not racing a wedged occupant (token-drift loops).
func waitManagedPortCleared(port int, timeout time.Duration, logger *Logger) bool {
	if port <= 0 {
		return true
	}
	if timeout <= 0 {
		timeout = 15 * time.Second
	}
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		_ = stopListenersOnPort(port, logger)
		time.Sleep(400 * time.Millisecond)
		if testBackendStatus(port) {
			continue
		}
		if len(listeningPIDsOnPort(port)) == 0 {
			return true
		}
	}
	cleared := !testBackendStatus(port) && len(listeningPIDsOnPort(port)) == 0
	if !cleared && logger != nil {
		logger.Infof("managed port %d still occupied after clear wait (%s)", port, timeout)
	}
	return cleared
}

func stopListenersOnPort(port int, logger *Logger) int {
	if port <= 0 {
		return 0
	}
	n := 0
	seen := map[uint32]struct{}{}
	candidates, err := getDesktopBackendCandidates()
	if err != nil && logger != nil {
		logger.Infof("WMI backend candidate scan failed: %v; falling back to netstat", err)
	}
	for _, proc := range candidates {
		if _, ok := seen[proc.ProcessID]; ok {
			continue
		}
		ports, perr := getListeningPorts(proc.ProcessID)
		if perr != nil {
			continue
		}
		holds := false
		for _, p := range ports {
			if p == port {
				holds = true
				break
			}
		}
		if !holds {
			continue
		}
		seen[proc.ProcessID] = struct{}{}
		if logger != nil {
			logger.Infof("killing token-drift backend pid=%d on port %d", proc.ProcessID, port)
		}
		stopProcessPID(proc.ProcessID)
		n++
	}
	// WMI full-scan can time out while a wedged occupant still holds the port.
	for _, pid := range listeningPIDsOnPort(port) {
		if _, ok := seen[pid]; ok {
			continue
		}
		seen[pid] = struct{}{}
		if logger != nil {
			logger.Infof("killing netstat listener pid=%d on port %d", pid, port)
		}
		stopProcessPID(pid)
		n++
	}
	return n
}

type backendInfo struct {
	PID  uint32 `json:"pid"`
	Port int    `json:"port"`
	Cmd  string `json:"cmd,omitempty"`
}

func findHealthyDesktopBackend() *backendInfo {
	candidates, err := getDesktopBackendCandidates()
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

func stopProcessPID(pid uint32) {
	// /T reaps the process tree. Plain /F leaves Electron grandchildren and
	// desktop-spawned hermes serve orphans (before-quit never runs on force kill).
	// Bound taskkill: a wedged target can hang the watchdog probe loop forever.
	cmd := exec.Command("taskkill", "/PID", fmt.Sprintf("%d", pid), "/T", "/F")
	if err := cmd.Start(); err != nil {
		return
	}
	done := make(chan error, 1)
	go func() { done <- cmd.Wait() }()
	select {
	case <-done:
		return
	case <-time.After(5 * time.Second):
		_ = cmd.Process.Kill()
	}
}

func stopAllDesktopProcessTrees(logger *Logger) {
	desktop, err := getDesktopProcesses()
	if err != nil {
		logger.Infof("enumerate Hermes.exe for tree-kill: %v", err)
	}
	seen := make(map[uint32]struct{}, len(desktop))
	for _, p := range desktop {
		if _, ok := seen[p.ProcessID]; ok {
			continue
		}
		seen[p.ProcessID] = struct{}{}
		logger.Infof("tree-killing Hermes.exe pid=%d", p.ProcessID)
		stopProcessPID(p.ProcessID)
	}
	// Catch any helper that WMI missed under the packaged image name.
	_ = exec.Command("taskkill", "/IM", "Hermes.exe", "/T", "/F").Run()
}

func stopOrphanDesktopBackends(logger *Logger, cfg Config, skipPIDs ...uint32) int {
	desktop, err := getDesktopProcesses()
	if err == nil && len(desktop) > 0 {
		return 0
	}
	skipPort := cfg.ManagedBackendPort
	if skipPort <= 0 {
		skipPort = DefaultManagedBackendPort
	}
	// If the managed serve is healthy, never reap backend candidates.
	// Candidates often include a non-listening python/hermes wrapper; taskkill
	// /T on that wrapper kills the child that still holds :9119 and produces
	// the Desktop↔backend flap (ECONNRESET → Desktop DOWN → relaunch loop).
	if testBackendStatus(skipPort) {
		if logger != nil {
			logger.Infof("skip orphan reap; managed port %d is healthy", skipPort)
		}
		return 0
	}
	skip := make(map[uint32]struct{}, len(skipPIDs)+4)
	for _, pid := range skipPIDs {
		if pid > 0 {
			skip[pid] = struct{}{}
		}
	}
	for _, pid := range listeningPIDsOnPort(skipPort) {
		skip[pid] = struct{}{}
	}
	candidates, err := getDesktopBackendCandidates()
	if err != nil {
		return 0
	}
	n := 0
	for _, proc := range candidates {
		if _, keep := skip[proc.ProcessID]; keep {
			logger.Infof("skip reap pid=%d (managed backend)", proc.ProcessID)
			continue
		}
		ports, perr := getListeningPorts(proc.ProcessID)
		if perr != nil || len(ports) == 0 {
			logger.Infof("skip reap pid=%d (listening ports unknown)", proc.ProcessID)
			continue
		}
		skipProc := false
		for _, port := range ports {
			if port == skipPort {
				logger.Infof("skip reap pid=%d (managed port %d)", proc.ProcessID, port)
				skipProc = true
				break
			}
			if isReservedOpsPort(port) {
				logger.Infof("skip reap pid=%d (ops port %d)", proc.ProcessID, port)
				skipProc = true
				break
			}
		}
		if skipProc {
			continue
		}
		logger.Infof("reaping orphan backend pid=%d", proc.ProcessID)
		stopProcessPID(proc.ProcessID)
		n++
	}
	return n
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

func startPackagedDesktop(cfg Config, logger *Logger, bm *BackendManager) bool {
	if !fileExists(cfg.PackagedExe) {
		logger.Infof("Hermes.exe missing at %s", cfg.PackagedExe)
		return false
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

func restartPackagedDesktop(cfg Config, logger *Logger, bm *BackendManager) bool {
	logger.Infof("restarting Desktop (force backend respawn)")
	stopAllDesktopProcessTrees(logger)
	time.Sleep(2 * time.Second)
	var skipPID uint32
	if bm != nil {
		if managed := bm.currentHealthy(); managed != nil {
			skipPID = managed.PID
		}
	}
	// Desktop is gone — reap leftover ephemeral serves (managed :9119 is skipped).
	stopOrphanDesktopBackends(logger, cfg, skipPID)
	time.Sleep(1 * time.Second)
	if bm != nil {
		if _, err := bm.EnsureHealthy(); err != nil {
			logger.Infof("pre-restart managed backend: %v", err)
		}
	}
	return startPackagedDesktop(cfg, logger, bm)
}
