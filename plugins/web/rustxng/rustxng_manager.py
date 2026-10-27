#!/usr/bin/env python3
"""
RustXNG helper script for Hermes.

This script helps manage a local RustXNG instance for web search.
It can start, stop, and check the status of RustXNG.

Usage:
    python rustxng_manager.py start    # Start RustXNG (via Docker or binary)
    python rustxng_manager.py stop     # Stop RustXNG
    python rustxng_manager.py status   # Check if RustXNG is running
    python rustxng_manager.py build    # Build RustXNG from source
"""

import argparse
import subprocess
import sys
import time
import requests
from pathlib import Path

RUSTXNG_DIR = Path(__file__).parent.parent.parent.parent / "plugins" / "rustxng"
DOCKER_IMAGE = "rustxng:local"
DEFAULT_PORT = 8888


def run_cmd(cmd: list, cwd: Path = None, capture: bool = True) -> subprocess.CompletedProcess:
    """Run a command and return the result."""
    return subprocess.run(cmd, cwd=cwd or RUSTXNG_DIR, capture_output=capture, text=True)


def check_running(port: int = DEFAULT_PORT) -> bool:
    """Check if RustXNG is running on the given port."""
    try:
        resp = requests.get(f"http://localhost:{port}/search?q=test&format=json", timeout=3)
        return resp.status_code == 200
    except Exception:
        return False


def start_docker(port: int = DEFAULT_PORT) -> bool:
    """Start RustXNG via Docker."""
    print(f"Starting RustXNG via Docker on port {port}...")
    
    # Check if image exists, build if not
    result = run_cmd(["docker", "images", "-q", DOCKER_IMAGE])
    if not result.stdout.strip():
        print("Building RustXNG Docker image...")
        build_result = run_cmd(["docker", "build", "-t", DOCKER_IMAGE, "."])
        if build_result.returncode != 0:
            print(f"Build failed: {build_result.stderr}")
            return False
    
    # Stop any existing container
    run_cmd(["docker", "stop", "rustxng-hermes"], capture=True)
    run_cmd(["docker", "rm", "rustxng-hermes"], capture=True)
    
    # Start new container
    result = run_cmd([
        "docker", "run", "-d",
        "--name", "rustxng-hermes",
        "-p", f"{port}:8888",
        "--restart", "unless-stopped",
        DOCKER_IMAGE
    ])
    
    if result.returncode != 0:
        print(f"Failed to start container: {result.stderr}")
        return False
    
    # Wait for startup
    for _ in range(30):
        time.sleep(1)
        if check_running(port):
            print(f"RustXNG started successfully on http://localhost:{port}")
            return True
    
    print("RustXNG failed to start within timeout")
    return False


def start_binary(port: int = DEFAULT_PORT) -> bool:
    """Start RustXNG from pre-built binary."""
    print(f"Starting RustXNG binary on port {port}...")
    
    # Look for binary
    binary_paths = [
        RUSTXNG_DIR / "target" / "release" / "rustxng",
        RUSTXNG_DIR / "target" / "release" / "rustxng.exe",
        Path.home() / ".cargo" / "bin" / "rustxng",
        Path.home() / ".cargo" / "bin" / "rustxng.exe",
    ]
    
    binary = None
    for p in binary_paths:
        if p.exists():
            binary = p
            break
    
    if not binary:
        print("RustXNG binary not found. Run 'build' first or use Docker.")
        return False
    
    # Start the binary
    env = os.environ.copy()
    env["RUSTXNG_PORT"] = str(port)
    
    # This is a background process - in practice you'd want to daemonize it
    # For now, we'll just inform the user
    print(f"Run this command to start RustXNG:")
    print(f"  {binary} --port {port}")
    print(f"Then set RUSTXNG_URL=http://localhost:{port} in your Hermes config")
    return False


def stop_docker() -> bool:
    """Stop RustXNG Docker container."""
    print("Stopping RustXNG Docker container...")
    result = run_cmd(["docker", "stop", "rustxng-hermes"])
    run_cmd(["docker", "rm", "rustxng-hermes"], capture=True)
    return result.returncode == 0


def build_rustxng() -> bool:
    """Build RustXNG from source."""
    print("Building RustXNG from source...")
    
    # Check if cargo is available
    result = run_cmd(["cargo", "--version"])
    if result.returncode != 0:
        print("Cargo not found. Install Rust first: https://rustup.rs/")
        return False
    
    # Build in release mode
    result = run_cmd(["cargo", "build", "--release"])
    if result.returncode != 0:
        print(f"Build failed: {result.stderr}")
        return False
    
    binary = RUSTXNG_DIR / "target" / "release" / "rustxng"
    if sys.platform == "win32":
        binary = binary.with_suffix(".exe")
    
    print(f"Build successful! Binary at: {binary}")
    return True


def main():
    parser = argparse.ArgumentParser(description="Manage RustXNG for Hermes")
    parser.add_argument("action", choices=["start", "stop", "status", "build", "docker-build"])
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to run on")
    parser.add_argument("--mode", choices=["docker", "binary"], default="docker", help="Run mode")
    
    args = parser.parse_args()
    
    if args.action == "start":
        if args.mode == "docker":
            success = start_docker(args.port)
        else:
            success = start_binary(args.port)
        sys.exit(0 if success else 1)
    
    elif args.action == "stop":
        success = stop_docker()
        sys.exit(0 if success else 1)
    
    elif args.action == "status":
        if check_running(args.port):
            print(f"RustXNG is running on http://localhost:{args.port}")
            sys.exit(0)
        else:
            print(f"RustXNG is NOT running on port {args.port}")
            sys.exit(1)
    
    elif args.action == "build":
        success = build_rustxng()
        sys.exit(0 if success else 1)
    
    elif args.action == "docker-build":
        print("Building Docker image...")
        result = run_cmd(["docker", "build", "-t", DOCKER_IMAGE, "."])
        sys.exit(0 if result.returncode == 0 else 1)


if __name__ == "__main__":
    import os
    main()