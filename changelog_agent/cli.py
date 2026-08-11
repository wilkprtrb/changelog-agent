"""CLI entry point for the Changelog Agent.

Orchestrates: read commits -> group -> write release notes -> output to drafts/.

The human review gate is non-negotiable: output goes to drafts/ (or output/ if
--publish is passed explicitly). It never auto-publishes.

Usage:
  python3 -m changelog_agent --repo /path/to/repo --since v1.2.0 --to HEAD
  python3 -m changelog_agent --provider github --token $GH_TOKEN \
      --repo-owner owner --repo-name name --since v1.2.0
"""
import argparse
import datetime
import json
import os
import sys

from . import __version__
from .git_reader import read_commits
from .grouper import llm_group, deterministic_group
from .writer import ollama_generate, write_release_note, DEFAULT_MODEL
from .output import write_outputs


def _repo_name(args):
    if args.provider in ("github", "gitlab"):
        return f"{args.repo_owner}/{args.repo_name}"
    return os.path.basename(os.path.abspath(args.repo))


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="changelog-agent",
        description="Turn git commits into plain-language, customer-facing release notes.",
    )
    ap.add_argument("--version", action="version", version=f"changelog-agent {__version__}")

    # input source
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--repo", help="path to a local git repo")
    src.add_argument("--provider", choices=["github", "gitlab"],
                     help="fetch from GitHub/GitLab API instead of local git")

    ap.add_argument("--repo-owner", help="owner/org for API mode")
    ap.add_argument("--repo-name", help="repo name for API mode")
    ap.add_argument("--token", help="GitHub/GitLab API token (or set GH_TOKEN/GITLAB_TOKEN)")

    ap.add_argument("--since", default="HEAD~20", help="start ref (default HEAD~20)")
    ap.add_argument("--to", default="HEAD", help="end ref (default HEAD)")

    ap.add_argument("--model", default=DEFAULT_MODEL, help="Ollama model (default qwen2.5:7b)")
    ap.add_argument("--version-tag", default=None, help="version label for the changelog (default: auto)")
    ap.add_argument("--date", default=None, help="date for the changelog (default: today)")
    ap.add_argument("--no-llm", action="store_true",
                    help="skip LLM grouping; use deterministic bucketing only")
    ap.add_argument("--publish", action="store_true",
                    help="write to output/ instead of drafts/ (human review gate override)")
    ap.add_argument("--drafts-dir", default=None, help="override drafts directory")
    ap.add_argument("--output-dir", default=None, help="override output directory")

    args = ap.parse_args(argv)

    if not args.repo and not args.provider:
        ap.error("must provide --repo or --provider")

    # token resolution
    if args.provider and not args.token:
        args.token = os.environ.get("GH_TOKEN") or os.environ.get("GITLAB_TOKEN")

    # ---- Stage 1: read commits ----
    print(f"[1/4] Reading commits...")
    try:
        commits = read_commits(args)
    except Exception as e:
        print(f"ERROR reading commits: {e}", file=sys.stderr)
        return 1
    if not commits:
        print("No commits found in range. Nothing to do.")
        return 0
    print(f"      Read {len(commits)} commits.")

    # ---- Stage 2: group ----
    print("[2/4] Grouping commits into logical changes...")
    if args.no_llm:
        changes = deterministic_group(commits)
    else:
        changes = llm_group(commits, ollama_generate, args.model)
    print(f"      Grouped into {len(changes)} logical changes.")

    # ---- Stage 3: write release notes ----
    print(f"[3/4] Writing release notes with {args.model}...")
    for i, ch in enumerate(changes, 1):
        try:
            note = write_release_note(ch, ollama_generate, args.model)
            ch["note"] = note
            print(f"      [{i}/{len(changes)}] {ch.get('title', ch.get('category'))}")
        except Exception as e:
            print(f"      [{i}/{len(changes)}] WARNING: could not write note ({e}); using summary.")
            ch["note"] = ""

    # ---- Stage 4: output ----
    version = args.version_tag or _auto_version(args)
    date = args.date or datetime.date.today().isoformat()
    repo_name = _repo_name(args)

    if args.publish:
        out_dir = args.output_dir or os.path.join(os.getcwd(), "output")
        print(f"[4/4] Writing to {out_dir} (--publish)...")
    else:
        out_dir = args.drafts_dir or os.path.join(os.getcwd(), "drafts")
        print(f"[4/4] Writing draft to {out_dir} for human review...")

    md_path, json_path = write_outputs(changes, version, date, out_dir, repo_name)
    print(f"      CHANGELOG.md  -> {md_path}")
    print(f"      changelog.json -> {json_path}")
    print("\nDraft written for review. Guilliman must approve before publishing.")
    print("Re-run with --publish to move to output/ once approved.")
    return 0


def _auto_version(args):
    """Best-effort version label: use the --to ref if it looks like a tag."""
    to = args.to
    if to and to != "HEAD":
        return to
    return "unreleased"


if __name__ == "__main__":
    sys.exit(main())
