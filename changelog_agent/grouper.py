"""Extract stage: group commits into logical changes.

Two passes:
1. Deterministic bucketing by conventional-commit prefix (feat/fix/perf/...).
2. LLM pass (qwen2.5:7b) that reads the bucketed commits and produces a
   structured grouping: [{category, title, summary, commits: [hashes]}].
   It merges related commits and drops internal noise (CI, typo fixes, WIP).
"""
import json
import re

# conventional-commit prefix -> customer-facing category
PREFIX_CATEGORY = {
    "feat": "Features",
    "feature": "Features",
    "fix": "Fixes",
    "bugfix": "Fixes",
    "hotfix": "Fixes",
    "perf": "Improvements",
    "performance": "Improvements",
    "refactor": "Improvements",
    "refactoring": "Improvements",
    "improve": "Improvements",
    "improvement": "Improvements",
    "docs": "Chores",
    "documentation": "Chores",
    "chore": "Chores",
    "test": "Chores",
    "build": "Chores",
    "ci": "Chores",
    "style": "Chores",
}

# subjects that are internal noise and should be dropped
NOISE_PATTERNS = [
    re.compile(r"^chore:\s*(bump|update|upgrade).*(version|dependency|node)", re.I),
    re.compile(r"^ci:", re.I),
    re.compile(r"^test:", re.I),
    re.compile(r"^docs:", re.I),
    re.compile(r"wip", re.I),
    re.compile(r"typo", re.I),
    re.compile(r"^merge ", re.I),
    re.compile(r"^revert ", re.I),
]


def _category_for(subject):
    """Return (category, prefix) for a conventional-commit subject, or (None, None)."""
    m = re.match(r"^([a-z]+)(\([^)]*\))?:", subject.strip())
    if not m:
        return None, None
    prefix = m.group(1).lower()
    return PREFIX_CATEGORY.get(prefix), prefix


def deterministic_bucket(commits):
    """Bucket commits by conventional-commit prefix. Returns dict:
    {category: [commit, ...]} plus 'Uncategorized' for the rest."""
    buckets = {}
    for c in commits:
        category, _ = _category_for(c["subject"])
        if category is None:
            category = "Uncategorized"
        buckets.setdefault(category, []).append(c)
    return buckets


def drop_noise(commits):
    """Filter out internal-noise commits (CI, version bumps, WIP, typos)."""
    kept = []
    for c in commits:
        subj = c["subject"]
        if any(p.search(subj) for p in NOISE_PATTERNS):
            continue
        kept.append(c)
    return kept


def _ollama_grouping_prompt(buckets):
    """Build the LLM grouping prompt from deterministic buckets."""
    lines = []
    for category, commits in buckets.items():
        lines.append(f"[{category}]")
        for c in commits:
            lines.append(f"  {c['hash']} {c['subject']}")
    return (
        "You are a release-note editor. Group the following commits into 3-5 "
        "logical, customer-meaningful changes. Merge related commits (e.g. "
        "'fix login' + 'fix login redirect' -> one 'Fixed login issues' change). "
        "Drop internal noise (CI tweaks, typo fixes, WIP, version bumps).\n\n"
        "COMMITS:\n" + "\n".join(lines) +
        "\n\nReturn ONLY a JSON array, no prose, of objects with keys: "
        "category (one of: Features, Fixes, Improvements, Chores), "
        "title (short customer-facing title), summary (1-2 sentence summary), "
        "commits (array of commit hashes).\n"
    )


def parse_grouping_json(text):
    """Parse the model's JSON array response, tolerating markdown fences."""
    text = text.strip()
    # strip ```json ... ``` fences if present
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    # find the first [ ... ] block
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON array found in model response")
    return json.loads(text[start:end + 1])


def llm_group(commits, ollama_generate, model="qwen2.5:7b"):
    """LLM pass: group commits into logical changes. Falls back to deterministic
    bucketing if the model fails or returns unusable JSON."""
    buckets = deterministic_bucket(commits)
    prompt = _ollama_grouping_prompt(buckets)
    try:
        raw = ollama_generate(prompt, model)
        changes = parse_grouping_json(raw)
        # validate shape
        if not isinstance(changes, list):
            raise ValueError("not a list")
        cleaned = []
        for ch in changes:
            if not isinstance(ch, dict):
                continue
            cleaned.append({
                "category": ch.get("category", "Improvements"),
                "title": ch.get("title", "").strip(),
                "summary": ch.get("summary", "").strip(),
                "commits": [str(h) for h in ch.get("commits", [])],
            })
        if cleaned:
            return cleaned
    except Exception:
        pass
    # Fallback: deterministic grouping
    return deterministic_group(commits)


def deterministic_group(commits):
    """Fallback grouping: one logical change per category, no LLM."""
    commits = drop_noise(commits)
    buckets = deterministic_bucket(commits)
    changes = []
    for category in ("Features", "Fixes", "Improvements", "Chores"):
        group = buckets.get(category, [])
        if not group:
            continue
        title = category
        summary = "; ".join(c["subject"] for c in group)
        changes.append({
            "category": category,
            "title": title,
            "summary": summary,
            "commits": [c["hash"] for c in group],
        })
    return changes
