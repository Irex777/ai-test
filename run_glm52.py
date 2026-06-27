#!/usr/bin/env python3
"""Generate 11 HTML apps via GLM-5.2 z.ai API sequentially."""
import json
import os
import re
import subprocess
import sys

BASE = "/Volumes/Data/Projects/ai-test"
API = "https://api.z.ai/api/coding/paas/v4/chat/completions"
AUTH = "Bearer dd81e938e2df410b98166ec367a1becd.vpOKxZkcT26ScAA2"
MODEL = "glm-5.2"
MAX_TOKENS = 16384
TEMPERATURE = 0.7
TIMEOUT = 120

TESTS = [
    "kanban", "dashboard", "chess", "markdown", "calculator",
    "snake", "pomodoro", "weather", "password", "gta", "webos",
]


def strip_fences(text: str) -> str:
    """Strip markdown code fences and leading non-HTML text."""
    text = text.strip()
    # Strip ```html ... ``` or ``` ... ``` fences
    if text.startswith("```"):
        # remove first fence line
        lines = text.splitlines()
        # drop leading fence
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        # drop trailing fence
        while lines and lines[-1].strip() == "```":
            lines.pop()
        text = "\n".join(lines).strip()
    # If there's leading prose before <!DOCTYPE or <html, trim to first tag
    m = re.search(r"(<!DOCTYPE|<html)", text, re.IGNORECASE)
    if m:
        text = text[m.start():]
    # Trim trailing text after </html>
    m2 = re.search(r"</html>\s*$", text, re.IGNORECASE)
    if not m2:
        # find last </html> anywhere
        idx = text.lower().rfind("</html>")
        if idx != -1:
            text = text[: idx + len("</html>")]
    return text.strip() + "\n"


def run_one(test: str, prompt: str) -> bool:
    out_path = os.path.join(BASE, test, "glm52.html")
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": MAX_TOKENS,
        "temperature": TEMPERATURE,
        "stream": False,
    }
    cmd = [
        "curl", "-s", API,
        "-H", "Content-Type: application/json",
        "-H", f"Authorization: {AUTH}",
        "-d", json.dumps(payload),
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=TIMEOUT
        )
    except subprocess.TimeoutExpired:
        print(f"{test}: TIMEOUT after {TIMEOUT}s")
        return False

    raw = proc.stdout
    if not raw.strip():
        print(f"{test}: EMPTY RESPONSE (stderr={proc.stderr[:200]})")
        return False

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        print(f"{test}: JSON PARSE FAILED (first 200={raw[:200]})")
        return False

    # Check API error
    if "error" in data:
        print(f"{test}: API ERROR: {data['error']}")
        return False

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        print(f"{test}: NO CONTENT (keys={list(data.keys())})")
        return False

    if not content or not content.strip():
        print(f"{test}: EMPTY CONTENT")
        # Print finish reason for diagnostics
        try:
            fr = data["choices"][0].get("finish_reason")
            usage = data.get("usage", {})
            print(f"  finish_reason={fr} usage={usage}")
        except Exception:
            pass
        return False

    html = strip_fences(content)
    if not html or "<" not in html:
        print(f"{test}: NO HTML AFTER STRIP (len={len(html)})")
        return False

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    size = os.path.getsize(out_path)
    print(f"{test}: OK {size} bytes -> {out_path}")
    # Diagnostic: finish reason + usage
    try:
        fr = data["choices"][0].get("finish_reason")
        usage = data.get("usage", {})
        print(f"  finish_reason={fr} usage={usage}")
    except Exception:
        pass
    return True


def main():
    with open(os.path.join(BASE, "prompts.json"), encoding="utf-8") as f:
        prompts = json.load(f)

    results = {}
    for test in TESTS:
        prompt = prompts.get(test)
        if not prompt:
            print(f"{test}: NO PROMPT FOUND, skipping")
            results[test] = False
            continue
        ok = run_one(test, prompt)
        results[test] = ok
        sys.stdout.flush()

    print("\n=== SUMMARY ===")
    ok_count = sum(1 for v in results.values() if v)
    print(f"{ok_count}/{len(TESTS)} succeeded")
    for test in TESTS:
        status = "OK" if results[test] else "FAIL"
        print(f"  {test}: {status}")
    return 0 if ok_count == len(TESTS) else 1


if __name__ == "__main__":
    sys.exit(main())
