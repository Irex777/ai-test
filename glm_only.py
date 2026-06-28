#!/usr/bin/env python3
"""Regenerate ONLY GLM models (glm + glm52) with thinking disabled."""
import json, os, sys, time
sys.path.insert(0, "/tmp/ai-test")
from fair_generate import call_zai, strip_fences, TESTS, ZAI_ID

ROOT = "/tmp/ai-test"
results = []

for model in ("glm", "glm52"):
    for test in TESTS:
        label = f"[{model}/{test}]"
        print(f"{label} starting...", flush=True)
        with open(os.path.join(ROOT, "prompts.json")) as f:
            prompt = json.load(f)[test]
        t0 = time.time()
        content, err = call_zai(ZAI_ID[model], prompt)
        elapsed = time.time() - t0
        if err:
            print(f"{label} FAILED {elapsed:.0f}s - {err}", flush=True)
            results.append({"model": model, "test": test, "success": False,
                          "error": err, "time_seconds": round(elapsed, 2), "output_size_bytes": 0})
            continue
        html = strip_fences(content)
        if not html or "<" not in html:
            print(f"{label} FAILED {elapsed:.0f}s - no HTML", flush=True)
            results.append({"model": model, "test": test, "success": False,
                          "error": "no HTML after strip", "time_seconds": round(elapsed, 2),
                          "output_size_bytes": len(html or "")})
            continue
        out_path = os.path.join(ROOT, test, f"{model}.html")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html)
        size = os.path.getsize(out_path)
        print(f"{label} DONE {size//1024}KB {elapsed:.0f}s", flush=True)
        results.append({"model": model, "test": test, "success": True,
                       "error": None, "time_seconds": round(elapsed, 2),
                       "output_size_bytes": size})

ok = sum(1 for r in results if r["success"])
print(f"\n=== GLM GENERATION COMPLETE: {ok}/{len(results)} succeeded ===")
for r in results:
    status = "OK " if r["success"] else "FAIL"
    extra = f"{r['output_size_bytes']//1024}KB" if r["success"] else r["error"][:50]
    print(f"  {status} {r['model']:<7} {r['test']:<11} {r['time_seconds']:>6.1f}s  {extra}")

# Save results
with open(os.path.join(ROOT, "glm_results.json"), "w") as f:
    json.dump(results, f, indent=2)
