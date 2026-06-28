#!/usr/bin/env python3
"""
ZAI-only regeneration (glm + glm52), 22 single-shot jobs.

Why this exists: the FIRST fair_generate.py run hit a script bug — the ZAI
auth header was missing its "Authorization: " prefix, so every glm/glm52 call
failed with "Authentication parameter not received" BEFORE reaching the model.
Those 22 calls never constituted a real shot at the model, so this pass gives
glm and glm52 their actual one shot each (still no retries). Claude + Ornith
were unaffected and are left as-is.

Writes results to zai_results.json for later merge into fair_results.json.
"""
import importlib.util
import json
import os

spec = importlib.util.spec_from_file_location("fg", os.path.join("/tmp/ai-test", "fair_generate.py"))
fg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fg)

ROOT = "/tmp/ai-test"
TESTS = fg.TESTS


def run_zai_model(model):
    out = []
    for test in TESTS:
        prompt = json.load(open(os.path.join(ROOT, "prompts.json")))[test]
        caller = (lambda m: (lambda p: fg.call_zai(fg.ZAI_ID[m], p)))(model)
        out.append(fg.run_one(model, test, prompt, caller))
    return out


def main():
    fg.log("=== ZAI-ONLY PASS (glm + glm52, fixed auth) ===")
    results = run_zai_model("glm") + run_zai_model("glm52")
    with open(os.path.join(ROOT, "zai_results.json"), "w") as f:
        json.dump({"results": results}, f, indent=2)
    ok = sum(1 for r in results if r["success"])
    fg.log(f"=== ZAI PASS DONE: {ok}/{len(results)} succeeded ===")
    for r in results:
        status = "OK " if r["success"] else "FAIL"
        extra = f"{r['output_size_bytes']//1024}KB" if r["success"] else r["error"][:40]
        fg.log(f"  {status} {r['model']:<7} {r['test']:<11} {r['time_seconds']:>6.1f}s  {extra}")


if __name__ == "__main__":
    main()
