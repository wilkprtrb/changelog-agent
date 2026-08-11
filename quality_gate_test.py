#!/usr/bin/env python3
"""
QUALITY GATE — day-1 test of qwen2.5:7b release-note writing quality.

Feeds a sample of real commits to the local Ollama model and prints the
release notes it produces, so Guilliman can judge whether the model writes
good, plain-language, customer-facing notes.

Run:  python3 quality_gate_test.py [--repo /path/to/repo] [--model qwen2.5:7b]
"""
import argparse
import json
import subprocess
import sys
import urllib.request

OLLAMA_URL = "http://localhost:11434/api/generate"

WRITE_PROMPT = """You are a technical writer for a SaaS product. Write a customer-facing release note
in plain English. The audience is a non-technical user of the product.

CHANGE: {title} — {summary}
SUPPORTING COMMITS: {commits}

Write 2-4 sentences explaining what changed and WHY it matters to the user.
RULES:
- Plain language. No jargon, no internal ticket numbers, no "refactored", no "fixed a bug in X module".
- Lead with the user benefit, not the implementation.
- If it's a fix, say what was broken and what now works.
- If it's a feature, say what the user can now do.
- Do NOT invent features or claims not supported by the commits.
- Do NOT mention AI or that this was generated.
"""


def get_commits(repo, since="HEAD~10", to="HEAD"):
    """Read commits from a local git repo."""
    cmd = ["git", "-C", repo, "log", "--pretty=format:%h|%s|%b", f"{since}..{to}"]
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0:
        print(f"git error: {out.stderr}", file=sys.stderr)
        sys.exit(1)
    commits = []
    for line in out.stdout.strip().splitlines():
        if not line:
            continue
        parts = line.split("|", 2)
        if len(parts) == 3:
            commits.append({"hash": parts[0], "subject": parts[1], "body": parts[2]})
        else:
            commits.append({"hash": parts[0], "subject": parts[1], "body": ""})
    return commits


def ollama_generate(prompt, model="qwen2.5:7b", timeout=180):
    """Call the local Ollama generate API. Returns full text."""
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.4},
    }
    req = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data.get("response", "").strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="/tmp/qg-test")
    ap.add_argument("--model", default="qwen2.5:7b")
    ap.add_argument("--since", default="HEAD~9")
    ap.add_argument("--to", default="HEAD")
    args = ap.parse_args()

    commits = get_commits(args.repo, args.since, args.to)
    print(f"=== QUALITY GATE: model={args.model} repo={args.repo} ===")
    print(f"Read {len(commits)} commits.\n")

    # Group deterministically by conventional-commit prefix for the test.
    groups = {"feat": [], "fix": [], "perf": [], "refactor": [], "docs": [], "chore": []}
    for c in commits:
        subj = c["subject"].lower()
        matched = False
        for prefix in groups:
            if subj.startswith(prefix + ":"):
                groups[prefix].append(c)
                matched = True
                break
        if not matched:
            groups.setdefault("other", []).append(c)

    # Build a few logical changes for the test.
    test_changes = []
    if groups["feat"]:
        test_changes.append({
            "title": "New features",
            "summary": "Added login with OAuth, dark mode, and CSV report export.",
            "commits": ", ".join(c["subject"] for c in groups["feat"]),
        })
    if groups["fix"]:
        test_changes.append({
            "title": "Bug fixes",
            "summary": "Fixed login redirect loop, timezone display, and empty settings state.",
            "commits": ", ".join(c["subject"] for c in groups["fix"]),
        })
    if groups["perf"]:
        test_changes.append({
            "title": "Performance",
            "summary": "Faster dashboard loading via query caching.",
            "commits": ", ".join(c["subject"] for c in groups["perf"]),
        })

    print("=== MODEL OUTPUT (raw) ===\n")
    results = []
    for change in test_changes:
        prompt = WRITE_PROMPT.format(
            title=change["title"],
            summary=change["summary"],
            commits=change["commits"],
        )
        print(f"--- CHANGE: {change['title']} ---")
        print(f"Commits: {change['commits']}\n")
        try:
            note = ollama_generate(prompt, args.model)
            print(note)
            print()
            results.append({"title": change["title"], "note": note})
        except Exception as e:
            print(f"ERROR calling Ollama: {e}", file=sys.stderr)
            sys.exit(1)

    with open("QUALITY-GATE-RAW.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\n=== Raw output saved to QUALITY-GATE-RAW.json ===")


if __name__ == "__main__":
    main()
