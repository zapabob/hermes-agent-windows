//go:build windows

// Test-owned native Git proxy. No network, services, or production resources.
package main

import (
    "crypto/sha256"
    "encoding/json"
    "errors"
    "fmt"
    "io"
    "net"
    "os"
    "os/exec"
    "path/filepath"
    "strconv"
    "strings"
    "syscall"
    "time"
)

func main() {
    args := os.Args[1:]
    binary, err := os.Executable()
    if err == nil { err = publishLaunch(binary, os.Args) }
    if err != nil {
        fmt.Fprintln(os.Stderr, "owned launch registration failed:", err)
        os.Exit(126)
    }
    if err := publishTimeoutOwner(); err != nil {
        fmt.Fprintln(os.Stderr, "owned timeout registration failed:", err)
        os.Exit(126)
    }
    if os.Getenv("S06_FAKE_GH") == "1" && len(args)>0 && (args[0]=="auth" || args[0]=="pr") {
        binary, err := os.Executable()
        if err != nil || os.Getenv("GH_TOKEN") != "OWNED_FAKE_GH_TOKEN" ||
           os.Getenv("GH_PROMPT_DISABLED") != "1" || os.Getenv("GIT_TERMINAL_PROMPT") != "0" ||
           !strings.EqualFold(strings.Split(os.Getenv("PATH"), string(os.PathListSeparator))[0], filepath.Dir(binary)) {
            os.Exit(91)
        }
        if os.Getenv("S06_FAKE_GH_FAIL") == "1" { os.Exit(1) }
        if len(args)>0 && args[0] == "auth" { os.Stdout.WriteString("OWNED_GH_AUTH\n"); return }
        if len(args)>0 && args[0] == "pr" { os.Stdout.WriteString(`{"url":"https://example.invalid/owned","state":"OPEN","number":42}`); return }
        os.Exit(92)
    }
    if len(args) == 2 && args[0] == "--owned-wait-descendant" {
        depth, err := strconv.Atoi(args[1])
        if err != nil || depth < 0 || depth > 1 { os.Exit(126) }
        if err := waitOwnedTree(depth); err != nil {
            fmt.Fprintln(os.Stderr, err)
            os.Exit(126)
        }
        return
    }
    status := false
    for _, arg := range args {
        if arg == "auth" && os.Getenv("S06_SHIM_HANG_GH") == "1" {
            if err := waitOwnedTree(2); err != nil {
                fmt.Fprintln(os.Stderr, err)
                os.Exit(126)
            }
            return
        }
        if arg == "diff" && os.Getenv("S06_SHIM_OUTPUT_LIMIT") == "1" {
            chunk := make([]byte, 65536)
            for i := range chunk { chunk[i] = 'x' }
            for i := 0; i < 32; i++ {
                if _, err := os.Stdout.Write(chunk); err != nil { os.Exit(126) }
                time.Sleep(100 * time.Millisecond)
            }
            if err := os.WriteFile(os.Getenv("S06_OUTPUT_COMPLETE_MARKER"), []byte("OWNED_OUTPUT_COMPLETED"), 0600); err != nil { os.Exit(126) }
            return
        }
        if arg == "status" { status = true }
        if arg == "fetch" && os.Getenv("S06_SHIM_HANG_FETCH") == "1" {
            if err := waitOwnedTree(2); err != nil {
                fmt.Fprintln(os.Stderr, err)
                os.Exit(126)
            }
            return
        }
    }
    if !status {
        if delay, err := strconv.Atoi(os.Getenv("S06_SHIM_DELAY_CONFIG")); err == nil && delay > 0 {
            time.Sleep(time.Duration(delay) * time.Millisecond)
        }
    }
    if status {
        eof := make(chan bool, 1)
        go func() { _, err := io.ReadAll(os.Stdin); eof <- err == nil }()
        select {
        case closed := <-eof:
            if !closed { os.Exit(124) }
        case <-time.After(750 * time.Millisecond):
            if err := os.WriteFile(os.Getenv("S06_STDIN_MARKER"), []byte("OWNED_STDIN_NOT_CLOSED"), 0600); err != nil { os.Exit(126) }
            os.Stderr.WriteString("Owned Git stdin did not reach EOF\n")
            os.Exit(125)
        }
        if marker := os.Getenv("S06_OPERATION_MARKER"); marker != "" {
            if err := os.WriteFile(marker, []byte("OWNED_STATUS_OPERATION_EXECUTED"), 0600); err != nil { os.Exit(126) }
        }
    }
    realGit := os.Getenv("S06_REAL_GIT")
    if realGit != os.Getenv("S06_GIT") {
        fmt.Fprintln(os.Stderr, "real Git differs from the bound fixture executable")
        os.Exit(126)
    }
    if err := publishLaunch(realGit, append([]string{realGit}, args...)); err != nil {
        fmt.Fprintln(os.Stderr, err)
        os.Exit(126)
    }
    var aliases []string
    if err := json.Unmarshal([]byte(os.Getenv("S06_GIT_ALIASES")), &aliases); err != nil { os.Exit(126) }
    for _, alias := range aliases {
        // The Git launcher can retain its original argv[0] in the worker.
        // Both variants bind the complete argv and the same frozen worker exe.
        if err := publishLaunch(alias, append([]string{realGit}, args...)); err != nil { os.Exit(126) }
        if err := publishLaunch(alias, append([]string{alias}, args...)); err != nil { os.Exit(126) }
        if err := publishLaunch(alias, append([]string{filepath.Base(alias)}, args...)); err != nil { os.Exit(126) }
    }
    command := exec.Command(realGit, args...)
    command.Stdin = os.Stdin
    command.Stdout = os.Stdout
    command.Stderr = os.Stderr
    command.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags:0x08000000}
    if err := command.Run(); err != nil {
        if exit, ok := err.(*exec.ExitError); ok { os.Exit(exit.ExitCode()) }
        os.Stderr.WriteString(err.Error())
        os.Exit(127)
    }
}

func publishLaunch(executable string, command []string) error {
    cwd, err := os.Getwd()
    if err != nil { return err }
    runtime, err := timeoutOwnerRoot()
    if err != nil { return err }
    // Product config probes omit Popen(cwd) and inherit the bound Python
    // runtime root. Final Git operations and tree children use the exact repo.
    if !strings.EqualFold(filepath.Clean(cwd), filepath.Join(os.Getenv("S06_OPERATION_ROOT"), "owned spaced repo")) &&
       !strings.EqualFold(filepath.Clean(cwd), runtime) {
        return errors.New("owned Git cwd differs from its registered runtime/repository")
    }
    return publishLaunchAt(executable, command, cwd)
}

// Observe the existing product owner's timeout command; never execute it here.
// Targets are this shim's PID only, with the two bound owner's exact arg orders.
func publishTimeoutOwner() error {
    runtime, err := timeoutOwnerRoot()
    if err != nil { return err }
    executable := os.Getenv("S06_TASKKILL")
    pid := strconv.Itoa(os.Getpid())
    for _, command := range [][]string{
        {"taskkill", "/F", "/T", "/PID", pid},
        {"taskkill", "/T", "/F", "/PID", pid},
    } {
        if err := publishLaunchAt(executable, command, runtime); err != nil { return err }
    }
    return nil
}

func timeoutOwnerRoot() (string, error) {
    root, operation := os.Getenv("S06_SOURCE_ROOT"), os.Getenv("S06_OPERATION_ROOT")
    runtime := filepath.Clean(os.Getenv("S06_RUNTIME_ROOT"))
    if !filepath.IsAbs(root) || !filepath.IsAbs(runtime) ||
       !(strings.EqualFold(runtime, root) ||
         strings.EqualFold(runtime, filepath.Join(operation, "missing-static-controls owned runtime")) ||
         strings.EqualFold(runtime, filepath.Join(operation, "changed-static-controls owned runtime"))) {
        return "", errors.New("unknown timeout owner cwd")
    }
    return runtime, nil
}

func publishLaunchAt(executable string, command []string, cwd string) error {
    operation := os.Getenv("S06_OPERATION_ROOT")
    identity := os.Getenv("S06_OPERATION_ID")
    if !filepath.IsAbs(operation) || identity == "" || !filepath.IsAbs(executable) || len(command) == 0 {
        return errors.New("incomplete owned launch authority")
    }
    executable, err := filepath.EvalSymlinks(executable)
    if err != nil { return err }
    var bindings map[string]string
    if err := json.Unmarshal([]byte(os.Getenv("S06_EXECUTABLE_BINDINGS")), &bindings); err != nil { return err }
    content, err := os.ReadFile(executable)
    if err != nil { return err }
    digest := fmt.Sprintf("%x", sha256.Sum256(content))
    if bindings[strings.ToLower(executable)] != digest { return errors.New("owned executable hash mismatch") }
    record, err := json.Marshal(map[string]interface{}{
        "operation":operation, "id":identity, "exe":executable, "sha256":digest,
        "cwd":cwd, "cmd":command,
    })
    if err != nil { return err }
    directory := filepath.Join(operation, "owned launch registry")
    file, err := os.CreateTemp(directory, "owned-launch-*.partial")
    if err != nil { return err }
    temporary := file.Name()
    if _, err := file.Write(record); err != nil { file.Close(); return err }
    if err := file.Close(); err != nil { return err }
    return os.Rename(temporary, strings.TrimSuffix(temporary, ".partial")+".json")
}

func waitOwnedTree(depth int) (result error) {
    directory := os.Getenv("S06_SHIM_TREE_MARKERS")
    if directory == "" || !filepath.IsAbs(directory) {
        return errors.New("owned tree marker directory must be absolute")
    }
    if err := os.MkdirAll(directory, 0700); err != nil { return err }
    listener, err := net.Listen("tcp", "127.0.0.1:0")
    if err != nil { return err }
    defer func() { result = errors.Join(result, listener.Close()) }()
    cwd, err := os.Getwd()
    if err != nil { return err }
    record, err := json.Marshal(map[string]interface{}{
        "pid":os.Getpid(), "parent":os.Getppid(), "cwd":cwd,
        "port":listener.Addr().(*net.TCPAddr).Port, "depth":depth,
    })
    if err != nil { return err }
    final := filepath.Join(directory,strconv.Itoa(os.Getpid())+".json")
    if err := os.WriteFile(final+".partial",record,0600); err != nil { return err }
    if err := os.Rename(final+".partial",final); err != nil { return err }
    // Publish ownership before spawning: every live descendant has a marked ancestor.
    var child *exec.Cmd
    if depth > 0 {
        binary, err := os.Executable()
        if err != nil { return err }
        child = exec.Command(binary, "--owned-wait-descendant", strconv.Itoa(depth-1))
        child.Stdin, child.Stdout, child.Stderr = os.Stdin, os.Stdout, os.Stderr
        child.SysProcAttr = &syscall.SysProcAttr{HideWindow:true, CreationFlags:0x08000000}
        if err := publishLaunch(binary, child.Args); err != nil { return err }
        if err := child.Start(); err != nil { return err }
    }
    time.Sleep(90*time.Second)
    // Descendants finish their own cleanup before this ancestor exits.
    if child != nil {
        if err := child.Wait(); err != nil {
            return fmt.Errorf("wait for owned child: %w", err)
        }
    }
    return nil
}
