package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// All values are synthetic. No model, network service, or user credential is used.
func embeddingCredentialFixture(t *testing.T) Config {
	t.Helper()
	dir := t.TempDir()
	server := filepath.Join(dir, "llama-server.exe")
	model := filepath.Join(dir, "embedding.gguf")
	for _, name := range []string{server, model} {
		if err := os.WriteFile(name, []byte("fixture"), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	return Config{
		EmbeddingEndpoint: "http://127.0.0.1:18082",
		EmbeddingServer: server,
		EmbeddingModel: model,
		EmbeddingArgsJSON: `["--embedding", "--n-gpu-layers", "99"]`,
	}
}

func embeddingEnvHas(env []string, key string) bool {
	for _, entry := range env {
		name, _, ok := strings.Cut(entry, "=")
		if ok && strings.EqualFold(name, key) {
			return true
		}
	}
	return false
}

func TestEmbeddingDoesNotInheritUnrelatedCredentials(t *testing.T) {
	keys := []string{
		"HERMES_WATCHDOG_TS_AUTHKEY", "TS_AUTHKEY", "OPENAI_API_KEY",
		"GITHUB_TOKEN", "GH_TOKEN", "ANTHROPIC_API_KEY",
		"AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
		"GOOGLE_APPLICATION_CREDENTIALS", "HERMES_DASHBOARD_SESSION_TOKEN",
		"AUXILIARY_SUMMARY_API_KEY", "_HERMES_FORCE_OPENAI_API_KEY",
		"CUSTOM_PROVIDER_SECRET", "CUSTOM_AUTHKEY", "telegram_bot_token",
	}
	for _, key := range keys {
		t.Setenv(key, "synthetic-do-not-forward")
	}
	cmd, _, err := buildEmbeddingCommand(embeddingCredentialFixture(t))
	if err != nil {
		t.Fatal(err)
	}
	if cmd.Env == nil {
		t.Fatal("nil environment would inherit the parent environment")
	}
	for _, key := range keys {
		if embeddingEnvHas(cmd.Env, key) {
			t.Errorf("unrelated credential key reached embedding child: %s", key)
		}
		if os.Getenv(key) != "synthetic-do-not-forward" {
			t.Errorf("parent environment changed: %s", key)
		}
	}
}

func TestEmbeddingPreservesLocalInferenceAndServerAuthentication(t *testing.T) {
	keep := map[string]string{
		"CUDA_VISIBLE_DEVICES": "0",
		"GGML_VK_VISIBLE_DEVICES": "0",
		"GGML_CUDA_ENABLE_UNIFIED_MEMORY": "1",
		"LLAMA_ARG_CTX_SIZE": "8192",
		"LLAMA_ARG_N_GPU_LAYERS": "99",
		"LLAMA_API_KEY": "synthetic-local-server-auth",
		"LLAMA_ARG_API_KEY_FILE": "local-server-keys.txt",
		"LLAMA_ARG_SSL_KEY_FILE": "local-server-key.pem",
		"LLAMA_ARG_SSL_CERT_FILE": "local-server-cert.pem",
	}
	for key, value := range keep {
		t.Setenv(key, value)
	}
	t.Setenv("LLAMA_ARG_CACHE_TYPE_V", "turbo3")
	cmd, _, err := buildEmbeddingCommand(embeddingCredentialFixture(t))
	if err != nil {
		t.Fatal(err)
	}
	for key, value := range keep {
		found := false
		for _, entry := range cmd.Env {
			if entry == key+"="+value {
				found = true
			}
		}
		if !found {
			t.Errorf("local inference/server setting lost: %s", key)
		}
	}
	if !embeddingEnvHas(cmd.Env, "PATH") {
		t.Error("system PATH lost")
	}
	if embeddingEnvHas(cmd.Env, "LLAMA_ARG_CACHE_TYPE_V") {
		t.Error("incompatible generation cache setting reached stock embedding server")
	}
	if !strings.Contains(strings.Join(cmd.Args, " "), "--n-gpu-layers 99") {
		t.Error("configured GPU arguments changed")
	}
}
