#!/usr/bin/env python3
"""Resume GLM-5.2 generation for missing tests."""
import json, os, time, requests, sys

ZAI_API = "https://api.z.ai/api/coding/paas/v4/chat/completions"
ZAI_AUTH = "Bearer dd81e938e2df410b98166ec367a1becd.vpOKxZkcT26ScAA2"
MODEL = "glm-5.2"

tests = ['kanban','dashboard','chess','markdown','calculator','snake','pomodoro','weather','password','gta','webos']
missing = []
for t in tests:
    path = f'{t}/glm52.html'
    if not os.path.exists(path) or os.path.getsize(path) < 1000:
        missing.append(t)

print(f"GLM-5.2 resume: {len(missing)} tests needed: {missing}", flush=True)
prompts = json.load(open('prompts.json'))

for t in missing:
    prompt = prompts.get(t, "")
    if not prompt:
        print(f"[glm52/{t}] SKIP - no prompt", flush=True)
        continue

    print(f"[glm52/{t}] starting...", flush=True)
    t0 = time.time()
    try:
        resp = requests.post(ZAI_API, headers={
            "Authorization": ZAI_AUTH,
            "Content-Type": "application/json"
        }, json={
            "model": MODEL,
            "messages": [
                {"role": "system", "content": "You are an expert web developer. Generate a complete, single-file HTML application. Output ONLY the HTML code, no explanations, no markdown fences. The file must be completely self-contained with no external dependencies, CDNs, or imports."},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 65536,
            "temperature": 0.7,
            "thinking": {"type": "enabled", "thinking_budget": 32768}
        }, timeout=1200)
        
        elapsed = time.time() - t0
        if resp.status_code != 200:
            print(f"[glm52/{t}] FAILED {elapsed:.0f}s - HTTP {resp.status_code}: {resp.text[:200]}", flush=True)
            continue
            
        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        reasoning = data.get("choices", [{}])[0].get("message", {}).get("reasoning_content", "")
        
        if not content or len(content.strip()) < 500:
            print(f"[glm52/{t}] FAILED {elapsed:.0f}s - empty/short response ({len(content)} chars, {len(reasoning)} reasoning)", flush=True)
            continue
            
        # Strip markdown fences if present
        if content.strip().startswith("```"):
            lines = content.strip().split("\n")
            content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        
        outpath = f'{t}/glm52.html'
        os.makedirs(t, exist_ok=True)
        with open(outpath, 'w') as f:
            f.write(content)
        
        kb = len(content) / 1024
        print(f"[glm52/{t}] DONE {kb:.0f}KB {elapsed:.0f}s ({len(reasoning)} reasoning chars)", flush=True)
        
    except requests.exceptions.Timeout:
        print(f"[glm52/{t}] FAILED - TIMEOUT after {time.time()-t0:.0f}s", flush=True)
    except Exception as e:
        print(f"[glm52/{t}] FAILED - {type(e).__name__}: {e}", flush=True)

print("=== GLM-5.2 resume complete ===", flush=True)
