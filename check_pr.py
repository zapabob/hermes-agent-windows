import subprocess, json, sys, os

# Get list of open PRs by zapabob
cmd = ["gh", "pr", "list", "--author", "zapabob", "--state", "open", "--limit", "100", "--json", "number,url"]
result = subprocess.run(cmd, capture_output=True, text=True)
if result.returncode != 0:
    print(f"Error listing PRs: {result.stderr}", file=sys.stderr)
    sys.exit(1)
try:
    prs = json.loads(result.stdout)
except json.JSONDecodeError as e:
    print(f"Failed to parse JSON: {e}", file=sys.stderr)
    sys.exit(1)

if not prs:
    print("[SILENT]")
    sys.exit(0)

unresolved = []
for pr in prs:
    num = pr["number"]
    url = pr["url"]
    # extract owner/repo from url: https://github.com/owner/repo/pull/num
    # remove trailing slash if any
    url = url.rstrip("/")
    # split by '/'
    parts = url.split("/")
    # parts: ['https:', '', 'github.com', 'owner', 'repo', 'pull', 'num']
    if len(parts) < 7:
        continue
    owner = parts[3]
    repo = parts[4]
    full_repo = f"{owner}/{repo}"
    # get reviewThreads
    view_cmd = ["gh", "pr", "view", str(num), "--repo", full_repo, "--json", "reviewThreads"]
    view_result = subprocess.run(view_cmd, capture_output=True, text=True)
    if view_result.returncode != 0:
        # if error, treat as no unresolved? but we can skip
        continue
    try:
        data = json.loads(view_result.stdout)
    except json.JSONDecodeError:
        continue
    threads = data.get("reviewThreads", [])
    has_unresolved = any(not t.get("isResolved", True) for t in threads)
    if has_unresolved:
        unresolved.append((full_repo, num))

if not unresolved:
    print("[SILENT]")
else:
    print("未解決のレビューコメントがあるPR:")
    for repo, num in unresolved:
        print(f"- {repo} PR #{num}")
