"""Write stage: turn logical changes into plain-language release notes via Ollama.

Uses the local Ollama HTTP API (http://localhost:11434/api/generate) with
qwen2.5:7b. Python stdlib only (urllib).
"""
import json
import urllib.request

OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "qwen2.5:7b"

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


def ollama_generate(prompt, model=DEFAULT_MODEL, url=OLLAMA_URL, timeout=180):
    """Call the local Ollama generate API. Returns the full response text."""
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.4},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data.get("response", "").strip()


def write_release_note(change, ollama_generate=ollama_generate, model=DEFAULT_MODEL):
    """Write a release note for one logical change. Returns the note text."""
    commits = ", ".join(change.get("commits", []))
    prompt = WRITE_PROMPT.format(
        title=change.get("title", ""),
        summary=change.get("summary", ""),
        commits=commits or change.get("summary", ""),
    )
    return ollama_generate(prompt, model)
