#!/usr/bin/env python3
"""
Fair generation: 5 models x 11 tests = 55 single-shot generations.

Identical parameters for every model:
  max_tokens   = 16384
  temperature  = 0.7
  prompt       = taken verbatim from prompts.json

No retries. A failure is recorded honestly as a failure.

Three parallel streams (so a slow reasoning model never blocks a fast one):
  Stream A "claude" : sonnet + opus  -> 2 concurrent workers (Claude CLI)
  Stream B "zai"    : glm + glm52    -> 1 sequential worker (avoid ZAI rate limits)
  Stream C "ornith" : ornith         -> 1 sequential worker (single GPU)

Within a stream, jobs run in test order. Output -> {test}/{model}.html.
Results -> fair_results.json (time, size, success, error).
"""
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

ROOT = "/tmp/ai-test"
TESTS = ["kanban", "dashboard", "chess", "markdown", "calculator",
         "snake", "pomodoro", "weather", "password", "gta", "webos"]

# ---- API endpoints / credentials ----
ZAI_API = "https://api.z.ai/api/coding/paas/v4/chat/completions"
ZAI_AUTH = "Authorization: Bearer dd81e938e2df410b98166ec367a1becd.vpOKxZkcT26ScAA2"
ORNITH_URL = "http://100.78.81.11:8080/v1/chat/completions"
ORNITH_MODEL = "ornith-1.0-35b-Q4_K_M.gguf"

# Claude CLI model ids
CLAUDE_ID = {"sonnet": "claude-sonnet-4-20250514",
             "opus":   "claude-opus-4-20250514"}
# ZAI model ids
ZAI_ID = {"glm":   "glm-5",
          "glm52": "glm-5.2"}

MAX_TOKENS = 16384
TEMPERATURE = 0.7
TIMEOUT = 600  # generous, identical window for every model

PRINT_LOCK = Lock()


def log(msg):
    with PRINT_LOCK:
        print(msg, flush=True)


# ------------------------------------------------------------------
# Fence / prose stripping (reused from run_glm52.py, made robust)
# ------------------------------------------------------------------
def strip_fences(text):
    if not text:
        return ""
    text = text.strip()
    # strip ```html ... ``` or ``` ... ``` fences
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        while lines and lines[-1].strip() == "```":
            lines.pop()
        text = "\n".join(lines).strip()
    # trim leading prose before first <!DOCTYPE or <html
    m = re.search(r"(<!DOCTYPE|<html)", text, re.IGNORECASE)
    if m:
        text = text[m.start():]
    # trim trailing text after last </html>
    idx = text.lower().rfind("</html>")
    if idx != -1:
        text = text[: idx + len("</html>")]
    return text.strip() + "\n"


# ------------------------------------------------------------------
# Model callers  ->  (content, error)
# ------------------------------------------------------------------
def call_claude(cli_model, prompt):
    cmd = ["claude", "-p", "--model", cli_model]
    try:
        proc = subprocess.run(cmd, input=prompt, capture_output=True,
                              text=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return None, f"TIMEOUT after {TIMEOUT}s"
    except Exception as e:
        return None, f"subprocess error: {e}"
    if proc.returncode != 0:
        return None, f"claude exit {proc.returncode}: {proc.stderr.strip()[:200]}"
    out = proc.stdout
    if not out or not out.strip():
        return None, f"empty stdout (stderr {proc.stderr.strip()[:150]})"
    return out, None


def _http_json_api(url, payload, auth_header, label):
    """Shared POST-with-curl for ZAI + ornith (OpenAI-style JSON)."""
    headers = ["-H", "Content-Type: application/json"]
    if auth_header:
        headers += ["-H", auth_header]
    cmd = ["curl", "-s", "--max-time", str(TIMEOUT), url] + headers + \
          ["-d", json.dumps(payload)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=TIMEOUT + 30)
    except subprocess.TimeoutExpired:
        return None, f"TIMEOUT after {TIMEOUT}s"
    except Exception as e:
        return None, f"subprocess error: {e}"
    raw = proc.stdout
    if not raw or not raw.strip():
        return None, f"empty response (stderr {proc.stderr.strip()[:150]})"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None, f"JSON parse fail: {raw[:200]}"
    if isinstance(data, dict) and "error" in data:
        return None, f"API error: {str(data['error'])[:200]}"
    try:
        content = data["choices"][0]["message"]["content"]
        fr = data["choices"][0].get("finish_reason")
        usage = data.get("usage", {})
    except (KeyError, IndexError, TypeError):
        return None, f"no content field: {raw[:200]}"
    if not content or not str(content).strip():
        return None, f"empty content (finish={fr} usage={usage})"
    return str(content), None


def call_zai(zai_model, prompt):
    payload = {"model": zai_model,
               "messages": [{"role": "user", "content": prompt}],
               "max_tokens": MAX_TOKENS,
               "temperature": TEMPERATURE,
               "stream": False,
               "thinking": {"type": "disabled"}}
    return _http_json_api(ZAI_API, payload, ZAI_AUTH, zai_model)


def call_ornith(prompt):
    payload = {"model": ORNITH_MODEL,
               "messages": [{"role": "user", "content": prompt}],
               "max_tokens": MAX_TOKENS,
               "temperature": TEMPERATURE,
               "stream": False}
    return _http_json_api(ORNITH_URL, payload, None, "ornith")


# ------------------------------------------------------------------
# Single job
# ------------------------------------------------------------------
def run_one(model, test, prompt, caller):
    label = f"[{model}/{test}]"
    log(f"{label} starting...")
    t0 = time.time()
    content, err = caller(prompt)
    elapsed = time.time() - t0
    if err:
        log(f"{label} FAILED {elapsed:.0f}s - {err}")
        return {"model": model, "test": test, "success": False,
                "error": err, "time_seconds": round(elapsed, 2),
                "output_size_bytes": 0}
    html = strip_fences(content)
    if not html or "<" not in html:
        msg = "no HTML after strip"
        log(f"{label} FAILED {elapsed:.0f}s - {msg}")
        return {"model": model, "test": test, "success": False,
                "error": msg, "time_seconds": round(elapsed, 2),
                "output_size_bytes": len(html or "")}
    os.makedirs(os.path.join(ROOT, test), exist_ok=True)
    out_path = os.path.join(ROOT, test, f"{model}.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    size = os.path.getsize(out_path)
    log(f"{label} DONE {size//1024}KB {elapsed:.0f}s")
    return {"model": model, "test": test, "success": True,
            "error": None, "time_seconds": round(elapsed, 2),
            "output_size_bytes": size}


# ------------------------------------------------------------------
# Streams
# ------------------------------------------------------------------
def claude_stream(jobs, prompts):
    """sonnet + opus, 2 concurrent workers."""
    out = []
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="claude") as ex:
        futs = {}
        for (model, test) in jobs:
            caller = (lambda m: (lambda p: call_claude(CLAUDE_ID[m], p)))(model)
            futs[ex.submit(run_one, model, test, prompts[test], caller)] = (model, test)
        for fut in as_completed(futs):
            out.append(fut.result())
    return out


def zai_stream(jobs, prompts):
    """glm + glm52, strictly sequential (rate limits)."""
    out = []
    for (model, test) in jobs:
        caller = (lambda m: (lambda p: call_zai(ZAI_ID[m], p)))(model)
        out.append(run_one(model, test, prompts[test], caller))
    return out


def ornith_stream(jobs, prompts):
    """ornith, strictly sequential (single GPU)."""
    out = []
    for (model, test) in jobs:
        out.append(run_one(model, test, prompts[test], call_ornith))
    return out


def main():
    with open(os.path.join(ROOT, "prompts.json"), encoding="utf-8") as f:
        prompts = json.load(f)

    claude_jobs = [(m, t) for m in ("sonnet", "opus") for t in TESTS]
    zai_jobs    = [(m, t) for m in ("glm", "glm52") for t in TESTS]
    ornith_jobs = [("ornith", t) for t in TESTS]

    log(f"=== FAIR GENERATION: 55 jobs across 3 streams (timeout {TIMEOUT}s, "
        f"max_tokens {MAX_TOKENS}, temp {TEMPERATURE}) ===")

    all_results = []
    with ThreadPoolExecutor(max_workers=3, thread_name_prefix="stream") as ex:
        fc = ex.submit(claude_stream, claude_jobs, prompts)
        fz = ex.submit(zai_stream, zai_jobs, prompts)
        fo = ex.submit(ornith_stream, ornith_jobs, prompts)
        for fut in as_completed([fc, fz, fo]):
            all_results.extend(fut.result())

    # sort + persist
    order = {m: i for i, m in enumerate(["sonnet", "opus", "glm", "glm52", "ornith"])}
    torder = {t: i for i, t in enumerate(TESTS)}
    all_results.sort(key=lambda r: (torder.get(r["test"], 99), order.get(r["model"], 99)))

    with open(os.path.join(ROOT, "fair_results.json"), "w") as f:
        json.dump({"params": {"max_tokens": MAX_TOKENS,
                              "temperature": TEMPERATURE,
                              "timeout": TIMEOUT,
                              "shots": 1,
                              "retries": 0},
                   "results": all_results}, f, indent=2)

    ok = sum(1 for r in all_results if r["success"])
    log(f"\n=== GENERATION COMPLETE: {ok}/{len(all_results)} succeeded ===")
    for r in all_results:
        status = "OK " if r["success"] else "FAIL"
        extra = f"{r['output_size_bytes']//1024}KB" if r["success"] else r["error"][:40]
        log(f"  {status} {r['model']:<7} {r['test']:<11} {r['time_seconds']:>6.1f}s  {extra}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
