package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"golang.org/x/sys/windows"
)

type cycleResult struct {
	Desktop      string `json:"desktop"`
	Backend      string `json:"backend"`
	BackendPID   uint32 `json:"backendPid,omitempty"`
	BackendPort  int    `json:"backendPort,omitempty"`
	Embedding    string `json:"embedding"`
	EmbeddingPID uint32 `json:"embeddingPid,omitempty"`
}

type WatchdogState struct {
	UpdatedAt               string      `json:"updatedAt"`
	WatchdogPID             int         `json:"watchdogPid"`
	MaintenanceState        string      `json:"maintenanceState"`
	MaintenanceOwner        string      `json:"maintenanceOwner,omitempty"`
	Result                  cycleResult `json:"result"`
	ConsecutiveBackendFails int         `json:"consecutiveBackendFails"`
	PackagedExe             string      `json:"packagedExe,omitempty"`
	ListenAddr              string      `json:"listenAddr,omitempty"`
	TsnetHostname           string      `json:"tsnetHostname,omitempty"`
	TsnetEnabled            bool        `json:"tsnetEnabled"`
}

type Watchdog struct {
	cfg    Config
	logger *Logger
	back   *BackendManager

	cycleMu          sync.Mutex
	mu               sync.RWMutex
	failCount        int
	maintenanceState string
	maintenanceOwner string
	lastState        WatchdogState

	embeddingMu        sync.Mutex
	embeddingPID       int
	embeddingStartedAt time.Time
}

func NewWatchdog(cfg Config, logger *Logger) *Watchdog {
	return &Watchdog{
		cfg:    cfg,
		logger: logger,
		back:   NewBackendManager(cfg, logger),
		lastState: WatchdogState{
			WatchdogPID:   os.Getpid(),
			PackagedExe:   cfg.PackagedExe,
			ListenAddr:    cfg.ListenAddr,
			TsnetHostname: cfg.TsnetHostname,
			TsnetEnabled:  cfg.EnableTsnet && cfg.TsAuthKey != "",
		},
	}
}

func (w *Watchdog) PrewarmBackend() {
	w.cycleMu.Lock()
	defer w.cycleMu.Unlock()
	if !w.cfg.PrewarmBackend || w.maintenanceSuspended() {
		return
	}
	if _, err := w.back.EnsureHealthy(); err != nil {
		w.logger.Infof("prewarm backend: %v", err)
	}
}

func (w *Watchdog) findAnyHealthyBackend() *backendInfo {
	if child := findHealthyDesktopBackend(); child != nil {
		return child
	}
	if managed := w.back.currentHealthy(); managed != nil {
		return managed
	}
	return loadManifestBackend(w.cfg)
}

func (w *Watchdog) State() WatchdogState {
	w.mu.RLock()
	defer w.mu.RUnlock()
	return w.lastState
}

func (w *Watchdog) maintenanceSuspended() bool {
	state, active, err := maintenanceMode(w.cfg.MaintenancePath, time.Now())
	if err != nil {
		w.logger.Infof("watchdog maintenance state: %v", err)
	}
	w.mu.Lock()
	w.maintenanceState = state.State
	w.maintenanceOwner = state.Owner
	w.mu.Unlock()
	return active
}

func (w *Watchdog) saveState(result cycleResult) {
	w.mu.Lock()
	defer w.mu.Unlock()
	w.lastState = WatchdogState{
		UpdatedAt:               time.Now().Format(time.RFC3339),
		WatchdogPID:             os.Getpid(),
		MaintenanceState:        w.maintenanceState,
		MaintenanceOwner:        w.maintenanceOwner,
		Result:                  result,
		ConsecutiveBackendFails: w.failCount,
		PackagedExe:             w.cfg.PackagedExe,
		ListenAddr:              w.cfg.ListenAddr,
		TsnetHostname:           w.cfg.TsnetHostname,
		TsnetEnabled:            w.cfg.EnableTsnet && w.cfg.TsAuthKey != "",
	}
	raw, err := json.MarshalIndent(w.lastState, "", "  ")
	if err != nil {
		return
	}
	_ = os.WriteFile(w.cfg.StatePath, raw, 0o644)
}

func (w *Watchdog) RunCycle() cycleResult {
	w.cycleMu.Lock()
	defer w.cycleMu.Unlock()
	if w.maintenanceSuspended() {
		res := cycleResult{Desktop: "maintenance", Backend: "maintenance", Embedding: "maintenance"}
		w.saveState(res)
		return res
	}
	embeddingStatus, embeddingPID := w.ensureEmbeddingHealthy()
	withEmbedding := func(res cycleResult) cycleResult {
		res.Embedding = embeddingStatus
		res.EmbeddingPID = embeddingPID
		return res
	}

	desktop, derr := getDesktopProcesses()
	managedReady := !w.cfg.PrewarmBackend
	if w.cfg.PrewarmBackend {
		if _, err := w.back.EnsureHealthy(); err != nil {
			w.logger.Infof("ensure managed backend: %v", err)
			managedReady = false
		} else {
			managedReady = true
		}
	}
	backend := w.findAnyHealthyBackend()

	if derr != nil || len(desktop) == 0 {
		// Avoid Hermes.exe proliferation: cold Desktop without an auth-ok
		// prewarm manifest times out at 90s and dies, then we relaunch forever.
		if w.cfg.PrewarmBackend && !managedReady {
			w.logger.Infof("Desktop DOWN — defer relaunch until managed backend auth-ok")
			res := withEmbedding(cycleResult{Desktop: "waiting_backend", Backend: "down"})
			w.saveState(res)
			return res
		}
		var skipPID uint32
		if managed := w.back.currentHealthy(); managed != nil {
			skipPID = managed.PID
		}
		stopOrphanDesktopBackends(w.logger, w.cfg, skipPID)
		w.logger.Infof("Desktop DOWN — relaunch")
		startPackagedDesktop(w.cfg, w.logger, w.back)
		w.mu.Lock()
		w.failCount = 0
		w.mu.Unlock()
		res := withEmbedding(cycleResult{Desktop: "relaunched", Backend: "pending"})
		w.saveState(res)
		return res
	}

	if backend == nil {
		w.logger.Infof("Desktop UP but backend DOWN — starting managed serve")
		if _, err := w.back.EnsureHealthy(); err != nil {
			w.logger.Infof("managed backend assist failed: %v", err)
		}
		backend = w.findAnyHealthyBackend()
	}

	if backend == nil {
		w.mu.Lock()
		w.failCount++
		fails := w.failCount
		w.mu.Unlock()
		w.logger.Infof("Desktop UP but backend still DOWN (fail=%d/%d)", fails, w.cfg.FailThreshold)
		if fails >= w.cfg.FailThreshold {
			restartPackagedDesktop(w.cfg, w.logger, w.back)
			w.mu.Lock()
			w.failCount = 0
			w.mu.Unlock()
			res := withEmbedding(cycleResult{Desktop: "restarted", Backend: "respawning"})
			w.saveState(res)
			return res
		}
		res := withEmbedding(cycleResult{Desktop: "up", Backend: "down"})
		w.saveState(res)
		return res
	}

	w.mu.Lock()
	w.failCount = 0
	w.mu.Unlock()
	w.logger.Infof("OK backend=pid:%d port:%d", backend.PID, backend.Port)
	res := withEmbedding(cycleResult{
		Desktop:     "up",
		Backend:     "up",
		BackendPID:  backend.PID,
		BackendPort: backend.Port,
	})
	w.saveState(res)
	return res
}

func (w *Watchdog) RunLoop(stop <-chan struct{}) {
	w.logger.Infof("watchdog loop interval=%ds threshold=%d exe=%s", w.cfg.IntervalSec, w.cfg.FailThreshold, w.cfg.PackagedExe)
	for {
		w.RunCycle()
		if w.cfg.Once {
			return
		}
		select {
		case <-stop:
			return
		case <-time.After(time.Duration(w.cfg.IntervalSec) * time.Second):
		}
	}
}

type lockFile struct {
	PID            int    `json:"pid"`
	ProcessCreated uint64 `json:"processCreated"`
	ExecutablePath string `json:"executablePath"`
	StartedAt      string `json:"startedAt"`
	RepoRoot       string `json:"repoRoot"`
}

type processIdentity struct {
	PID            int
	CreationTime   uint64
	ExecutablePath string
	StartedAt      time.Time
}

const legacyLockStartTolerance = 10 * time.Second

func sameExecutablePath(left, right string) bool {
	if strings.TrimSpace(left) == "" || strings.TrimSpace(right) == "" {
		return false
	}
	return strings.EqualFold(filepath.Clean(left), filepath.Clean(right))
}

func readProcessIdentity(pid int) (processIdentity, bool) {
	if pid <= 0 {
		return processIdentity{}, false
	}
	handle, err := windows.OpenProcess(windows.PROCESS_QUERY_LIMITED_INFORMATION, false, uint32(pid))
	if err != nil {
		return processIdentity{}, false
	}
	defer windows.CloseHandle(handle)

	var exitCode uint32
	if err := windows.GetExitCodeProcess(handle, &exitCode); err != nil {
		return processIdentity{}, false
	}
	const stillActiveExitCode = 259
	if exitCode != stillActiveExitCode {
		return processIdentity{}, false
	}

	var created, exited, kernel, user windows.Filetime
	if err := windows.GetProcessTimes(handle, &created, &exited, &kernel, &user); err != nil {
		return processIdentity{}, false
	}
	image := make([]uint16, 32_768)
	imageLength := uint32(len(image))
	if err := windows.QueryFullProcessImageName(handle, 0, &image[0], &imageLength); err != nil || imageLength == 0 {
		return processIdentity{}, false
	}
	creationTime := uint64(created.HighDateTime)<<32 | uint64(created.LowDateTime)

	return processIdentity{
		PID:            pid,
		CreationTime:   creationTime,
		ExecutablePath: windows.UTF16ToString(image[:imageLength]),
		StartedAt:      time.Unix(0, created.Nanoseconds()).UTC(),
	}, true
}

func lockMatchesProcess(lock lockFile, identity processIdentity) bool {
	if lock.PID <= 0 || lock.PID != identity.PID || !sameExecutablePath(lock.ExecutablePath, identity.ExecutablePath) {
		return false
	}
	if lock.ProcessCreated != 0 {
		return lock.ProcessCreated == identity.CreationTime
	}
	startedAt, err := time.Parse(time.RFC3339Nano, lock.StartedAt)
	if err != nil || identity.StartedAt.IsZero() {
		return false
	}
	delta := startedAt.Sub(identity.StartedAt)
	if delta < 0 {
		delta = -delta
	}
	return delta <= legacyLockStartTolerance
}

func writeLockExclusive(lockPath string, lock lockFile) error {
	raw, err := json.MarshalIndent(lock, "", "  ")
	if err != nil {
		return err
	}
	file, err := os.OpenFile(lockPath, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o600)
	if err != nil {
		return err
	}
	written := false
	defer func() {
		_ = file.Close()
		if !written {
			_ = os.Remove(lockPath)
		}
	}()
	if _, err := file.Write(raw); err != nil {
		return err
	}
	if err := file.Sync(); err != nil {
		return err
	}
	if err := file.Close(); err != nil {
		return err
	}
	written = true
	return nil
}

func acquireLock(lockPath, repoRoot string, logger *Logger) (func(), bool) {
	self, ok := readProcessIdentity(os.Getpid())
	if !ok {
		logger.Infof("cannot establish watchdog process identity — refusing lock acquisition")
		return nil, false
	}
	lf := lockFile{
		PID:            self.PID,
		ProcessCreated: self.CreationTime,
		ExecutablePath: self.ExecutablePath,
		StartedAt:      self.StartedAt.Format(time.RFC3339Nano),
		RepoRoot:       repoRoot,
	}
	acquired := false
	for attempt := 0; attempt < 3; attempt++ {
		if err := writeLockExclusive(lockPath, lf); err == nil {
			acquired = true
			break
		} else if !os.IsExist(err) {
			logger.Infof("failed to create lock: %v", err)
			return nil, false
		}

		raw, err := os.ReadFile(lockPath)
		if err != nil {
			logger.Infof("failed to inspect existing lock: %v", err)
			return nil, false
		}
		var existing lockFile
		if err := json.Unmarshal(raw, &existing); err != nil {
			if info, statErr := os.Stat(lockPath); statErr == nil && time.Since(info.ModTime()) < time.Second && attempt < 2 {
				time.Sleep(25 * time.Millisecond)
				continue
			}
		} else if existing.PID > 0 {
			if actual, alive := readProcessIdentity(existing.PID); alive {
				candidate := existing
				if candidate.ExecutablePath == "" && sameExecutablePath(actual.ExecutablePath, self.ExecutablePath) {
					candidate.ExecutablePath = self.ExecutablePath
				}
				if lockMatchesProcess(candidate, actual) {
					logger.Infof("another watchdog holds %s (pid=%d) — exiting", lockPath, existing.PID)
					return nil, false
				}
				if sameExecutablePath(actual.ExecutablePath, self.ExecutablePath) {
					logger.Infof("live watchdog identity conflicts with %s (pid=%d) — refusing a second owner", lockPath, existing.PID)
					return nil, false
				}
			}
		}
		if err := os.Remove(lockPath); err != nil && !os.IsNotExist(err) {
			logger.Infof("failed to remove stale lock: %v", err)
			return nil, false
		}
		if attempt == 2 {
			logger.Infof("lock acquisition raced repeatedly — refusing startup")
			return nil, false
		}
	}
	if !acquired {
		logger.Infof("failed to establish exclusive lock ownership")
		return nil, false
	}
	release := func() {
		raw, err := os.ReadFile(lockPath)
		if err != nil {
			return
		}
		var existing lockFile
		if json.Unmarshal(raw, &existing) == nil && lockMatchesProcess(existing, self) {
			_ = os.Remove(lockPath)
		}
	}
	return release, true
}

func processAlive(pid int) bool {
	_, ok := readProcessIdentity(pid)
	return ok
}
