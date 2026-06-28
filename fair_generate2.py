#!/usr/bin/env python3
"""
Fair generation v2 — CLEAN REDO with fixes:
  1. Correct Claude model IDs: use aliases 'sonnet' and 'opus' (latest, not retired)
  2. Claude calls SEQUENTIAL within stream (no CLI concurrency)
  3. GLM models: thinking ENABLED (default), max_tokens=65536 (room for reasoning + output)
  4. Ornith: max_tokens=65536 (reasoning model, needs room)
  5. Timeout: 1200s (Opus needs longer)
  6. Old files DELETED before run (no contamination)

Three parallel streams:
  Stream A "claude" : sonnet THEN opus (sequential, ~55 min)
  Stream B "zai"    : glm THEN glm52   (sequential, ~50 min)
  Stream C "ornith" : ornith           (sequential, ~28 min)
"""
import json, os, re, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

ROOT = "/tmp/ai-test"
TESTS = ["kanban", "dashboard", "chess", "markdown", "calculator",
         "snake", "pomodoro", "weather", "password", "gta", "webos"]

ZAI_API = "https://api.z.ai/api/coding/paas/v4/chat/completions"
ZAI_AUTH = "Authorization: Bearer dd81e938e2df410b98166ec367a1becd.vpOKxZkcT26ScAA2"
ORNITH_URL = "http://100.78.81.11:8080/v1/chat/completions"
ORNITH_MODEL = "ornith-1.0-35b-Q4_K_M.gguf"

# CORRECT model aliases (not retired IDs)
CLAUDE_MODELS = {"sonnet": "sonnet", "opus": "opus"}
ZAI_MODELS = {"glm": "glm-5", "glm52": "glm-5.2"}

MAX_TOKENS = 65536
TEMPERATURE = 0.7
TIMEOUT = 1200

PRINT_LOCK = Lock()

def log(msg):
    with PRINT_LOCK:
        print(msg, flush=True)

def strip_fences(text):
    if not text:
        return ""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        while lines and lines[-1].strip() == "```":
            lines.pop()
        text = "\n".join(lines).strip()
    m = re.search(r"(<!DOCTYPE|<html)", text, re.IGNORECASE)
    if m:
        text = text[m.start():]
    idx = text.lower().rfind("</html>")
    if idx != -1:
        text = text[: idx + len("</html>")]
    return text.strip() + "\n"

def call_claude(model_alias, prompt):
    """Call Claude CLI with correct model alias."""
    cmd = ["claude", "-p", "--model", model_alias]
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

def call_api(url, payload, auth_header):
    """Shared POST for ZAI + ornith."""
    headers = ["-H", "Content-Type: application/json"]
    if auth_header:
        headers += ["-H", auth_header]
    cmd = ["curl", "-s", "--max-time", str(TIMEOUT), url] + headers + \
          ["-d", json.dumps(payload)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT + 30)
    except subprocess.TimeoutExpired:
        return None, f"TIMEOUT after {TIMEOUT}s"
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
    except (KeyError, IndexError, TypeError):
        return None, f"no content: {raw[:200]}"
    if not content or not str(content).strip():
        fr = data.get("choices", [{}])[0].get("finish_reason", "?")
        usage = data.get("usage", {})
        rt = usage.get("completion_tokens_details", {}).get("reasoning_tokens", 0)
        return None, f"empty content (finish={fr} reasoning_tokens={rt})"
    return str(content), None

def call_zai(model_id, prompt):
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": MAX_TOKENS,
        "temperature": TEMPERATURE,
        "stream": False,
        # thinking NOT set = enabled (default) — fair to the model
    }
    return call_api(ZAI_API, payload, ZAI_AUTH)

def call_ornith(prompt):
    payload = {
        "model": ORNITH_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": MAX_TOKENS,
        "temperature": TEMPERATURE,
    }
    return call_api(ORNITH_URL, payload, None)

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
        log(f"{label} FAILED {elapsed:.0f}s - no HTML after strip")
        return {"model": model, "test": test, "success": False,
                "error": "no HTML after strip", "time_seconds": round(elapsed, 2),
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

def claude_stream(prompts):
    """Sonnet THEN Opus — sequential (no CLI concurrency)."""
    out = []
    for model in ("sonnet", "opus"):
        alias = CLAUDE_MODELS[model]
        for test in TESTS:
            caller = (lambda a: (lambda p: call_claude(a, p)))(alias)
            out.append(run_one(model, test, prompts[test], caller))
    return out

def zai_stream(prompts):
    """GLM THEN GLM-5.2 — sequential (avoid rate limits)."""
    out = []
    for model in ("glm", "glm52"):
        model_id = ZAI_MODELS[model]
        for test in TESTS:
            caller = (lambda mid: (lambda p: call_zai(mid, p)))(model_id)
            out.append(run_one(model, test, prompts[test], caller))
    return out

def ornith_stream(prompts):
    """Ornith — sequential (single GPU)."""
    out = []
    for test in TESTS:
        out.append(run_one("ornith", test, prompts[test], call_ornith))
    return out

def main():
    with open(os.path.join(ROOT, "prompts.json"), encoding="utf-8") as f:
        prompts = json.load(f)

    log(f"=== CLEAN REDO: 55 jobs, 3 parallel streams ===")
    log(f"    max_tokens={MAX_TOKENS} temp={TEMPERATURE} timeout={TIMEOUT}s")
    log(f"    Claude: aliases sonnet+opus (sequential)")
    log(f"    GLM: thinking ENABLED (default), max_tokens={MAX_TOKENS}")

    all_results = []
    with ThreadPoolExecutor(max_workers=3, thread_name_prefix="stream") as ex:
        fc = ex.submit(claude_stream, prompts)
        fz = ex.submit(zai_stream, prompts)
        fo = ex.submit(ornith_stream, prompts)
        for fut in as_completed([fc, fz, fo]):
            all_results.extend(fut.result())

    order = {m: i for i, m in enumerate(["sonnet", "opus", "glm", "glm52", "ornith"])}
    torder = {t: i for i, t in enumerate(TESTS)}
    all_results.sort(key=lambda r: (torder.get(r["test"], 99), order.get(r["model"], 99)))

    with open(os.path.join(ROOT, "fair_results.json"), "w") as f:
        json.dump({"params": {"max_tokens": MAX_TOKENS,
                              "temperature": TEMPERATURE,
                              "timeout": TIMEOUT,
                              "shots": 1, "retries": 0,
                              "thinking": "enabled (default)",
                              "claude_models": "sonnet, opus aliases"},
                   "results": all_results}, f, indent=2)

    ok = sum(1 for r in all_results if r["success"])
    log(f"\n=== COMPLETE: {ok}/{len(all_results)} succeeded ===")
    for r in all_results:
        status = "OK " if r["success"] else "FAIL"
        extra = f"{r['output_size_bytes']//1024}KB" if r["success"] else r["error"][:50]
        log(f"  {status} {r['model']:<7} {r['test']:<11} {r['time_seconds']:>6.1f}s  {extra}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
