"""Input stage: read commits from a local git repo and/or a GitHub/GitLab API.

Local mode uses `git log --pretty=format:"%h|%s|%b" <since>..<to>`.
API mode (Phase 2) fetches merged PRs via the GitHub/GitLab REST API using a
token. Python stdlib only (urllib).
"""
import json
import subprocess
import sys
import urllib.parse
import urllib.request


def read_local(repo, since, to):
    """Read commits from a local git repo. Returns list of dicts:
    {hash, subject, body}.

    Uses a NUL-separated pretty format so multi-line commit bodies are
    captured intact (a plain newline-separated format breaks on bodies that
    span multiple lines).
    """
    # %x00 = NUL separator between fields, %x1e = record separator between commits.
    # This keeps multi-line bodies from being split into bogus "commits".
    fmt = "%h%x00%s%x00%b%x1e"
    cmd = ["git", "-C", repo, "log", f"--pretty=format:{fmt}", f"{since}..{to}"]
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"git log failed: {out.stderr.strip()}")
    commits = []
    for record in out.stdout.split("\x1e"):
        record = record.strip("\n")
        if not record:
            continue
        parts = record.split("\x00", 2)
        if len(parts) < 2:
            # Malformed record; skip rather than crash.
            continue
        commits.append({
            "hash": parts[0],
            "subject": parts[1],
            "body": parts[2] if len(parts) == 3 else "",
        })
    return commits


def _api_get(url, token):
    """GET a URL with optional Bearer token. Returns parsed JSON."""
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def read_github(owner, repo, token, since=None, to=None):
    """Fetch merged PRs from GitHub REST API. Returns list of dicts:
    {hash, subject, body} (hash = PR number, subject = PR title)."""
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls?state=closed&sort=updated&direction=desc&per_page=100"
    pulls = _api_get(url, token)
    commits = []
    for pr in pulls:
        if not pr.get("merged_at"):
            continue
        commits.append({
            "hash": f"#{pr['number']}",
            "subject": pr.get("title", ""),
            "body": pr.get("body") or "",
        })
    return commits


def read_gitlab(owner, repo, token, since=None, to=None):
    """Fetch merged MRs from GitLab REST API. Returns list of dicts."""
    project = urllib.parse.quote(f"{owner}/{repo}", safe="")
    url = f"https://gitlab.com/api/v4/projects/{project}/merge_requests?state=merged&per_page=100"
    headers = {"PRIVATE-TOKEN": token} if token else {}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as resp:
        mrs = json.loads(resp.read().decode("utf-8"))
    commits = []
    for mr in mrs:
        commits.append({
            "hash": f"!{mr['iid']}",
            "subject": mr.get("title", ""),
            "body": mr.get("description") or "",
        })
    return commits


def read_commits(args):
    """Dispatch to the right input source based on args. Returns list of dicts."""
    if args.provider == "github":
        return read_github(args.repo_owner, args.repo_name, args.token, args.since, args.to)
    if args.provider == "gitlab":
        return read_gitlab(args.repo_owner, args.repo_name, args.token, args.since, args.to)
    return read_local(args.repo, args.since, args.to)
