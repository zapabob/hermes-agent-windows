package main

import (
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"
)

const defaultEmbeddingStartTimeoutSec = 180

var embeddingCredentialName = regexp.MustCompile(`(?i)(^|_)(API_KEY|ACCESS_KEY|AUTHKEY|AUTH|CREDENTIALS?|PASSWORD|PRIVATE_KEY|SECRET|TOKEN|KEY)(_|$)`)

// embeddingChildEnv is deliberately local to the embedding spawn boundary.
// Preserve GPU/OS/runtime settings and the server's own inbound authentication,
// but never pass unrelated provider, developer, or watchdog credentials. This
// does not change the environment of the parent, Desktop, or Electron-owned backend.
func embeddingChildEnv(base []string) []string {
	out := make([]string, 0, len(base)) // non-nil: empty must not mean inherit
	for _, entry := range base {
		key, _, _ := strings.Cut(entry, "=")
		upper := strings.ToUpper(key)
		if upper == "LLAMA_ARG_CACHE_TYPE_V" {
			// Stock embedding llama-server cannot use the generation turbo cache.
			continue
		}
		switch upper {
		case "LLAMA_API_KEY", "LLAMA_ARG_API_KEY_FILE", "LLAMA_ARG_SSL_KEY_FILE":
			// These configure this server's own access control, not a provider.
			out = append(out, entry)
			continue
		}
		if strings.HasPrefix(upper, "_HERMES_FORCE_") || embeddingCredentialName.MatchString(key) {
			continue
		}
		out = append(out, entry)
	}
	return out
}

// buildEmbeddingCommand accepts only the operator's configured local endpoint.
// Model download and generic command parsing are deliberately out of scope.
func buildEmbeddingCommand(cfg Config) (*exec.Cmd, string, error) {
	endpoint, host, port, err := parseEmbeddingEndpoint(cfg.EmbeddingEndpoint)
	if err != nil {
		return nil, "", err
	}
	if strings.TrimSpace(cfg.EmbeddingServer) == "" || !fileExists(cfg.EmbeddingServer) {
		return nil, "", fmt.Errorf("embedding server executable is missing")
	}
	if strings.TrimSpace(cfg.EmbeddingModel) == "" || !fileExists(cfg.EmbeddingModel) {
		return nil, "", fmt.Errorf("embedding GGUF is missing")
	}
	extra, err := parseEmbeddingArgs(cfg.EmbeddingArgsJSON)
	if err != nil {
		return nil, "", err
	}
	args := []string{
		"--model", cfg.EmbeddingModel,
		"--host", host,
		"--port", strconv.Itoa(port),
	}
	args = append(args, extra...)
	cmd := exec.Command(cfg.EmbeddingServer, args...)
	cmd.Dir = filepath.Dir(cfg.EmbeddingServer)
	cmd.Env = embeddingChildEnv(os.Environ())
	return cmd, endpoint, nil
}

func parseEmbeddingEndpoint(raw string) (string, string, int, error) {
	value := strings.TrimSpace(raw)
	parsed, err := url.Parse(value)
	if err != nil || parsed == nil {
		return "", "", 0, fmt.Errorf("embedding endpoint must be an absolute HTTP URL")
	}
	if parsed.Scheme != "http" || parsed.Host == "" || parsed.User != nil ||
		(parsed.Path != "" && parsed.Path != "/") || parsed.RawQuery != "" || parsed.Fragment != "" {
		return "", "", 0, fmt.Errorf("embedding endpoint must be an absolute loopback HTTP URL")
	}
	host := parsed.Hostname()
	if !isLoopbackHost(host) {
		return "", "", 0, fmt.Errorf("embedding endpoint must be loopback")
	}
	port, err := strconv.Atoi(parsed.Port())
	if err != nil || port <= 0 || port > 65535 {
		return "", "", 0, fmt.Errorf("embedding endpoint must include a valid port")
	}
	return strings.TrimRight(parsed.String(), "/"), host, port, nil
}

func isLoopbackHost(host string) bool {
	if strings.EqualFold(strings.TrimSpace(host), "localhost") {
		return true
	}
	parsed := net.ParseIP(host)
	return parsed != nil && parsed.IsLoopback()
}

func parseEmbeddingArgs(raw string) ([]string, error) {
	var args []string
	if err := json.Unmarshal([]byte(strings.TrimSpace(raw)), &args); err != nil {
		return nil, fmt.Errorf("embedding args must be a JSON string array")
	}
	hasEmbeddingMode := false
	for _, arg := range args {
		value := strings.TrimSpace(arg)
		if value == "" {
			return nil, fmt.Errorf("embedding args must not contain an empty value")
		}
		lower := strings.ToLower(value)
		if lower == "--model" || lower == "-m" || lower == "--host" || lower == "--port" ||
			strings.HasPrefix(lower, "--model=") || strings.HasPrefix(lower, "--host=") || strings.HasPrefix(lower, "--port=") {
			return nil, fmt.Errorf("embedding args must not override model, host, or port")
		}
		if lower == "--embedding" {
			hasEmbeddingMode = true
		}
	}
	if !hasEmbeddingMode {
		return nil, fmt.Errorf("embedding args must include --embedding")
	}
	return args, nil
}

func embeddingEndpointHealthy(endpoint string) bool {
	client := http.Client{Timeout: 2 * time.Second}
	response, err := client.Get(endpoint + "/health")
	if err != nil {
		return false
	}
	defer response.Body.Close()
	return response.StatusCode >= http.StatusOK && response.StatusCode < http.StatusMultipleChoices
}

func (w *Watchdog) ensureEmbeddingHealthy() (string, uint32) {
	if !w.cfg.EmbeddingEnabled {
		return "disabled", 0
	}
	if w.maintenanceSuspended() {
		return "maintenance", 0
	}
	endpoint, _, port, err := parseEmbeddingEndpoint(w.cfg.EmbeddingEndpoint)
	if err != nil {
		w.logger.Infof("embedding configuration: %v", err)
		return "misconfigured", 0
	}
	if embeddingEndpointHealthy(endpoint) {
		return "up", firstListenerPID(port)
	}
	cmd, _, err := buildEmbeddingCommand(w.cfg)
	if err != nil {
		w.logger.Infof("embedding configuration: %v", err)
		return "misconfigured", 0
	}

	w.embeddingMu.Lock()
	defer w.embeddingMu.Unlock()
	if w.maintenanceSuspended() {
		return "maintenance", 0
	}
	if embeddingEndpointHealthy(endpoint) {
		return "up", firstListenerPID(port)
	}
	if w.embeddingPID > 0 && processAlive(w.embeddingPID) {
		if time.Since(w.embeddingStartedAt) < embeddingStartTimeout(w.cfg) {
			return "starting", uint32(w.embeddingPID)
		}
		w.logger.Infof("embedding server pid=%d exceeded startup timeout; restarting owned process", w.embeddingPID)
		if w.embeddingProcess != nil {
			_ = w.embeddingProcess.Kill()
			_, _ = w.embeddingProcess.Wait()
		}
		w.embeddingPID = 0
		w.embeddingProcess = nil
		w.embeddingStartedAt = time.Time{}
	}
	if listeners := listeningPIDsOnPort(port); len(listeners) > 0 {
		w.logger.Infof("embedding endpoint %s is unhealthy on unowned pid(s)=%v; preserving occupant", endpoint, listeners)
		return "port_occupied", listeners[0]
	}

	hideWindowsProcess(cmd)
	cmd.Stdout = io.Discard
	cmd.Stderr = io.Discard
	if err := cmd.Start(); err != nil {
		w.logger.Infof("embedding server start failed: %v", err)
		return "start_failed", 0
	}
	w.embeddingPID = cmd.Process.Pid
	w.embeddingProcess = cmd.Process
	w.embeddingStartedAt = time.Now()
	w.logger.Infof("embedding server starting pid=%d endpoint=%s", w.embeddingPID, endpoint)
	return "starting", uint32(w.embeddingPID)
}

func embeddingStartTimeout(cfg Config) time.Duration {
	seconds := cfg.EmbeddingStartTimeoutSec
	if seconds <= 0 {
		seconds = defaultEmbeddingStartTimeoutSec
	}
	return time.Duration(seconds) * time.Second
}

func firstListenerPID(port int) uint32 {
	if listeners := listeningPIDsOnPort(port); len(listeners) > 0 {
		return listeners[0]
	}
	return 0
}
