#!/usr/bin/env python3
"""Compile ALL generation results into fair_results.json with correct parsing."""
import json, os, re

ROOT = "/tmp/ai-test"
tests = ["kanban", "dashboard", "chess", "markdown", "calculator",
         "snake", "pomodoro", "weather", "password", "gta", "webos"]
models = ["sonnet", "opus", "glm", "glm52", "ornith"]

all_results = {}

# 1. Parse generation_log.txt (Claude + Ornith + old GLM failures)
with open(os.path.join(ROOT, "generation_log.txt"), "rb") as f:
    raw = f.read().replace(b"\x00", b"").decode("utf-8", errors="replace")

for line in raw.split("\n"):
    line = line.strip()
    # DONE format: [model/test] DONE 23KB 120s
    m = re.match(r"\[(\w+)/(\w+)\]\s+DONE\s+(\d+)KB\s+(\d+)s", line)
    if m:
        model, test, kb, secs = m.groups()
        key = f"{test}_{model}"
        if key not in all_results:
            all_results[key] = {
                "model": model, "test": test, "success": True,
                "time_seconds": float(secs), "output_size_bytes": int(kb)*1024,
                "error": None
            }
        continue
    # FAILED format: [model/test] FAILED 96s - error msg
    m = re.match(r"\[(\w+)/(\w+)\]\s+FAILED\s+(\d+)s\s*-\s*(.*)", line)
    if m:
        model, test, secs, err = m.groups()
        key = f"{test}_{model}"
        if key not in all_results or not all_results[key]["success"]:
            all_results[key] = {
                "model": model, "test": test, "success": False,
                "time_seconds": float(secs), "output_size_bytes": 0,
                "error": err[:100]
            }

# 2. GLM results from glm_results.json (OVERRIDES old failures)
glm_path = os.path.join(ROOT, "glm_results.json")
if os.path.exists(glm_path):
    with open(glm_path) as f:
        for r in json.load(f):
            key = f"{r['test']}_{r['model']}"
            all_results[key] = r

# 3. Opus extra results
opus_path = os.path.join(ROOT, "opus_extra_results.json")
if os.path.exists(opus_path):
    with open(opus_path) as f:
        for r in json.load(f):
            key = f"{r['test']}_{r['model']}"
            all_results[key] = r

# Print summary
print("=== FULL GENERATION RESULTS ===\n")
for model in models:
    succ = []
    fail = []
    for test in tests:
        key = f"{test}_{model}"
        r = all_results.get(key, {})
        if r.get("success"):
            succ.append(test)
        else:
            fail.append(test)
    print(f"  {model:8s}: {len(succ)}/11 succeeded")
    if fail:
        print(f"           FAILED: {', '.join(fail)}")

total_ok = sum(1 for r in all_results.values() if r.get("success"))
print(f"\n  TOTAL: {total_ok}/{len(tests)*len(models)}")

# Save
output = {
    "params": {
        "max_tokens": 16384,
        "temperature": 0.7,
        "timeout_seconds": 600,
        "shots": 1,
        "retries": 0,
        "glm_thinking": "disabled",
        "note": "All models given identical prompt from prompts.json, one shot each, no retries. GLM models had thinking disabled to prevent reasoning tokens from consuming output budget. Opus/Sonnet via Claude CLI, GLM via ZAI API, Ornith via local llama.cpp."
    },
    "results": list(all_results.values())
}

with open(os.path.join(ROOT, "fair_results.json"), "w") as f:
    json.dump(output, f, indent=2)
print(f"\nSaved {len(all_results)} entries to fair_results.json")
