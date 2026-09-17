//go:build windows

package main

import (
	"fmt"
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
	// Never classify gateway / harness / cron as Desktop backend observations.
	if strings.Contains(lower, " gateway") || strings.Contains(lower, " harness") || strings.Contains(lower, " cron") {
		return false
	}
	// Explicit ops dashboard / fixed ports are not Desktop backend observations.
	if strings.Contains(cl, "--port 9120") || strings.Contains(cl, "--port=9120") ||
		strings.Contains(cl, "--port 8787") || strings.Contains(cl, "--port=8787") {
		return false
	}
	if strings.Contains(cl, " serve") || strings.Contains(cl, "\tserve") {
		// Prefer Desktop's ephemeral serve (--port 0). Bare "serve" still matches,
		// while reserved ops ports are excluded from observation.
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

func startPackagedDesktop(cfg Config, logger *Logger, mutationAllowed func() bool) bool {
	if !fileExists(cfg.PackagedExe) {
		logger.Infof("Hermes.exe missing at %s", cfg.PackagedExe)
		return false
	}
	if mutationAllowed != nil && !mutationAllowed() {
		logger.Infof("Desktop launch revoked by maintenance fence")
		return false
	}
	// S4U boot tasks host the watchdog in Session 0. Never CreateProcess a GUI
	// Desktop there; delegate the launch into the interactive user session.
	if isNonInteractiveSession() {
		logger.Infof("watchdog is running in Session 0 (non-interactive); launching Desktop via %s", desktopLogonTaskName)
		return startDesktopInInteractiveSession(logger)
	}
	work := filepath.Dir(cfg.PackagedExe)
	cmd := exec.Command(cfg.PackagedExe)
	cmd.Dir = work
	cmd.Env = append(stripInheritedDesktopRemotes(os.Environ()), desktopLaunchEnv(cfg)...)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	if err := cmd.Start(); err != nil {
		logger.Infof("failed to launch Desktop: %v", err)
		return false
	}
	logger.Infof("launched %s; Electron main owns its backend lifecycle", cfg.PackagedExe)
	return true
}
