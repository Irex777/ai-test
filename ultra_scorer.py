#!/usr/bin/env python3
"""
ultra_scorer.py — 1000-point multi-dimensional scoring system for AI model bake-off.

Replaces the old binary pass/fail → percentage system with a granular rubric
that actually differentiates models.

Scoring Dimensions (1000 pts total):
  A. Functional Correctness    400 pts  (weighted browser checks + console penalty)
  B. Code Architecture         200 pts  (8 sub-dimensions from static analysis)
  C. Visual Design & Polish    200 pts  (7 sub-dimensions from code + screenshot)
  D. Feature Richness          100 pts  (feature count + depth)
  E. Performance                50 pts  (load speed + code efficiency)
  F. Innovation & Detail        50 pts  (creative approach + microinteractions)

Data sources:
  - browser_results.json   (existing Playwright test results)
  - {test}/{model}.html    (source code for static analysis)
  - screenshots/*.png      (visual analysis)
  - fair_results.json      (generation timing)

Output:
  - ultra_scores.json      (detailed per-test, per-model scores)
"""

import json
import os
import re
import math
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))

MODELS = ["sonnet", "opus", "glm", "glm52", "ornith"]
TESTS = ["kanban", "dashboard", "chess", "markdown", "calculator",
         "snake", "pomodoro", "weather", "password", "gta", "webos"]

MODEL_NAMES = {
    "sonnet": "Sonnet 4.6",
    "opus":   "Opus 4.7",
    "glm":    "GLM 5.1",
    "glm52":  "GLM-5.2",
    "ornith": "Ornith 35B",
}

# ─── Browser check tier classification ────────────────────────────────────────
# Each browser check is classified as CRITICAL, IMPORTANT, or MINOR based on
# its name. This determines how many points it's worth.

CRITICAL_KEYWORDS = [
    "submit", "compute", "calculate", "render", "move", "play",
    "generate", "add task", "type", "convert", "update",
    "click", "opens", "drag", "drop", "interact",
    "timer", "countdown", "starts", "stops",
    "chess", "snake", "game", "play",
    "password", "strength", "copy",
    "weather", "data", "search",
    "preview", "render", "output",
]

MINOR_KEYWORDS = [
    "dark", "theme", "icon", "color", "responsive",
    "title bar", "close button", "menu",
    "page loads", "without error",
    "has", "exists", "visible",
]

def classify_check(name):
    """Return (tier, points) for a browser check by name."""
    name_lower = name.lower()

    # Explicit minor
    for kw in MINOR_KEYWORDS:
        if kw in name_lower:
            return ("minor", 10)

    # Critical: actual interaction/functionality
    for kw in CRITICAL_KEYWORDS:
        if kw in name_lower:
            return ("critical", 40)

    # Default: important
    return ("important", 25)


# ─── Static code analysis ─────────────────────────────────────────────────────

def analyze_code(html_content):
    """Analyze HTML source code across 8 quality dimensions. Returns dict of scores 0-100."""

    # Extract sections
    css = ""
    js = ""
    html_body = html_content

    # Extract CSS
    style_matches = re.findall(r'<style[^>]*>(.*?)</style>', html_content, re.DOTALL | re.IGNORECASE)
    css = "\n".join(style_matches)

    # Extract JS
    script_matches = re.findall(r'<script[^>]*>(.*?)</script>', html_content, re.DOTALL | re.IGNORECASE)
    js = "\n".join(script_matches)

    total_len = len(html_content)
    css_len = len(css)
    js_len = len(js)

    # ── 1. CSS Methodology (0-100) ──
    css_score = 0
    if css_len > 100:
        css_score += 15  # Has substantial CSS
    if ":root" in css or "--" in css:  # CSS custom properties
        css_score += 20
    if "flex" in css.lower():
        css_score += 15
    if "grid" in css.lower():
        css_score += 15
    if "transition" in css.lower():
        css_score += 10
    if "transform" in css.lower():
        css_score += 10
    if "media" in css.lower() and "query" in css.lower():
        css_score += 10
    if "@keyframes" in css.lower():
        css_score += 5
    css_score = min(100, css_score)

    # ── 2. JavaScript Quality (0-100) ──
    js_score = 0
    if js_len > 200:
        js_score += 15  # Has substantial JS
    func_count = len(re.findall(r'function\s+\w+|const\s+\w+\s*=\s*\([^)]*\)\s*=>|\w+\s*=\s*function', js))
    if func_count >= 3:
        js_score += 20
    elif func_count >= 1:
        js_score += 10
    if "addEventListener" in js or "onclick" in js.lower():
        js_score += 15
    if "try" in js and "catch" in js:
        js_score += 15  # Error handling
    if "localStorage" in js or "sessionStorage" in js:
        js_score += 10  # State persistence
    if "requestAnimationFrame" in js:
        js_score += 10
    if "async" in js or "await" in js or ".then(" in js:
        js_score += 10
    if "querySelector" in js:
        js_score += 5
    js_score = min(100, js_score)

    # ── 3. Semantic HTML (0-100) ──
    sem_score = 0
    semantic_tags = ["<header", "<nav", "<main", "<section", "<article",
                     "<aside", "<footer", "<figure", "<details", "<summary"]
    for tag in semantic_tags:
        if tag in html_body.lower():
            sem_score += 15
    if 'role=' in html_body.lower():
        sem_score += 15
    if '<form' in html_body.lower():
        sem_score += 10
    sem_score = min(100, sem_score)

    # ── 4. Accessibility (0-100) ──
    a11y_score = 0
    if 'aria-label' in html_body.lower():
        a11y_score += 25
    if 'aria-' in html_body.lower():
        a11y_score += 15
    if 'alt=' in html_body.lower():
        a11y_score += 15
    if 'tabindex' in html_body.lower():
        a11y_score += 15
    if '<label' in html_body.lower():
        a11y_score += 15
    if 'title=' in html_body.lower():
        a11y_score += 15
    a11y_score = min(100, a11y_score)

    # ── 5. Code Organization (0-100) ──
    org_score = 0
    comment_count = len(re.findall(r'<!--.*?-->|/\*.*?\*/|//.*$', html_content, re.MULTILINE | re.DOTALL))
    if comment_count >= 5:
        org_score += 25
    elif comment_count >= 1:
        org_score += 10
    # Indentation consistency (check for 2 or 4 space indent)
    indent_lines = re.findall(r'^(\s+)\S', html_content, re.MULTILINE)
    if indent_lines:
        indent_sizes = [len(i) for i in indent_lines]
        if len(set(indent_sizes)) > 1:
            org_score += 20  # Has structure
    # Class naming consistency
    class_names = re.findall(r'class="([^"]+)"', html_content)
    if class_names:
        has_consistent_naming = any("-" in c or "_" in c or re.match(r'^[a-z][a-zA-Z0-9]*$', c) for c in class_names[:10])
        if has_consistent_naming:
            org_score += 25
    # No inline styles everywhere (inline style ratio)
    inline_styles = len(re.findall(r'style="[^"]*"', html_content))
    total_tags = len(re.findall(r'<\w+', html_body))
    if total_tags > 0 and inline_styles / total_tags < 0.3:
        org_score += 30
    elif total_tags > 0 and inline_styles / total_tags < 0.5:
        org_score += 15
    org_score = min(100, org_score)

    # ── 6. File Efficiency (0-100) ──
    # Reward apps that are feature-rich but not bloated
    # Ideal range: 5KB - 80KB
    size_kb = total_len / 1024
    if size_kb < 1:
        eff_score = 10  # Too small = probably incomplete
    elif size_kb < 5:
        eff_score = 60
    elif size_kb <= 80:
        eff_score = 100
    elif size_kb <= 120:
        eff_score = 80
    elif size_kb <= 200:
        eff_score = 60
    else:
        eff_score = 30  # Bloated

    # ── 7. Modern Features (0-100) ──
    modern_score = 0
    if "const " in js or "let " in js:
        modern_score += 20  # ES6+
    if "=>" in js:
        modern_score += 15  # Arrow functions
    if "template" in js.lower() or "${" in js:
        modern_score += 15  # Template literals
    if "classList" in js:
        modern_score += 15  # Modern DOM API
    if "Map(" in js or "Set(" in js:
        modern_score += 10
    if "..." in js and "spread" not in js.lower():  # Spread operator heuristic
        modern_score += 10
    if "fetch(" in js:
        modern_score += 15
    modern_score = min(100, modern_score)

    # ── 8. Self-Contained (0-100) ──
    self_score = 100
    # Penalize external dependencies
    external = len(re.findall(r'(?:src|href)="https?://', html_content))
    external += len(re.findall(r'@import\s+url\(["\']?https?://', css))
    if external > 0:
        self_score = max(0, 100 - external * 25)

    return {
        "css_methodology": css_score,
        "js_quality": js_score,
        "semantic_html": sem_score,
        "accessibility": a11y_score,
        "code_organization": org_score,
        "file_efficiency": eff_score,
        "modern_features": modern_score,
        "self_contained": self_score,
        "metrics": {
            "total_kb": round(size_kb, 1),
            "css_kb": round(css_len / 1024, 1),
            "js_kb": round(js_len / 1024, 1),
            "functions": func_count,
            "comments": comment_count,
            "inline_style_ratio": round(inline_styles / max(1, total_tags), 2),
        }
    }


# ─── Visual design analysis (from code, not screenshots) ──────────────────────

def analyze_visual_design(html_content):
    """Analyze visual design quality from CSS properties. Returns scores 0-100."""

    css = "\n".join(re.findall(r'<style[^>]*>(.*?)</style>', html_content, re.DOTALL | re.IGNORECASE))
    css_lower = css.lower()

    # ── 1. Color Sophistication (0-100) ──
    color_score = 0
    # Count unique colors used
    colors = set(re.findall(r'#[0-9a-fA-F]{3,8}\b|rgba?\([^)]+\)|hsla?\([^)]+\)', css))
    if len(colors) >= 5:
        color_score += 30
    elif len(colors) >= 3:
        color_score += 20
    elif len(colors) >= 1:
        color_score += 10
    # CSS custom properties for theming
    if ":root" in css and "--" in css:
        color_score += 25
    # Gradient usage
    if "gradient" in css_lower:
        color_score += 20
    # Box shadow (depth)
    if "box-shadow" in css_lower:
        color_score += 15
    # Filter effects
    if "filter:" in css_lower or "backdrop-filter" in css_lower:
        color_score += 10
    color_score = min(100, color_score)

    # ── 2. Typography (0-100) ──
    typo_score = 0
    if "font-family" in css_lower:
        typo_score += 25
    if "font-size" in css_lower:
        # Check for size hierarchy
        sizes = re.findall(r'font-size:\s*(\d+(?:\.\d+)?)', css)
        if len(set(sizes)) >= 3:
            typo_score += 25
        elif len(set(sizes)) >= 1:
            typo_score += 10
    if "font-weight" in css_lower:
        typo_score += 20
    if "line-height" in css_lower:
        typo_score += 15
    if "letter-spacing" in css_lower or "text-transform" in css_lower:
        typo_score += 15
    typo_score = min(100, typo_score)

    # ── 3. Spacing & Layout (0-100) ──
    space_score = 0
    if "padding" in css_lower:
        space_score += 25
    if "margin" in css_lower:
        space_score += 25
    if "gap:" in css_lower:
        space_score += 20  # Flexbox/Grid gap
    if "border-radius" in css_lower:
        space_score += 15
    if "max-width" in css_lower:
        space_score += 15
    space_score = min(100, space_score)

    # ── 4. Animations & Transitions (0-100) ──
    anim_score = 0
    if "transition" in css_lower:
        transition_count = css_lower.count("transition")
        anim_score += min(30, transition_count * 10)
    if "@keyframes" in css_lower:
        keyframe_count = css_lower.count("@keyframes")
        anim_score += min(30, keyframe_count * 15)
    if "animation" in css_lower:
        anim_score += 20
    if "transform" in css_lower:
        anim_score += 20
    anim_score = min(100, anim_score)

    # ── 5. Interactive Feedback (0-100) ──
    interact_score = 0
    if ":hover" in css_lower:
        interact_score += 30
    if ":active" in css_lower:
        interact_score += 20
    if ":focus" in css_lower:
        interact_score += 20
    if ":focus-visible" in css_lower:
        interact_score += 15
    if "cursor:" in css_lower:
        interact_score += 15
    interact_score = min(100, interact_score)

    # ── 6. Responsive Design (0-100) ──
    resp_score = 0
    media_queries = len(re.findall(r'@media[^{]+\{', css))
    if media_queries >= 3:
        resp_score += 40
    elif media_queries >= 1:
        resp_score += 25
    if "flex" in css_lower and "wrap" in css_lower:
        resp_score += 20
    if "clamp(" in css_lower or "min(" in css_lower or "max(" in css_lower:
        resp_score += 20
    if "vw" in css_lower or "vh" in css_lower or "vmin" in css_lower:
        resp_score += 20
    resp_score = min(100, resp_score)

    # ── 7. Component Polish (0-100) ──
    polish_score = 0
    if "box-shadow" in css_lower:
        polish_score += 20
    if "border-radius" in css_lower:
        polish_score += 15
    if "backdrop-filter" in css_lower or "filter:" in css_lower:
        polish_score += 20
    if "opacity" in css_lower:
        polish_score += 10
    if "z-index" in css_lower:
        polish_score += 15  # Layering system
    if "overflow" in css_lower:
        polish_score += 10
    if "object-fit" in css_lower:
        polish_score += 10
    polish_score = min(100, polish_score)

    return {
        "color_sophistication": color_score,
        "typography": typo_score,
        "spacing_layout": space_score,
        "animations": anim_score,
        "interactive_feedback": interact_score,
        "responsive": resp_score,
        "component_polish": polish_score,
    }


# ─── Feature richness analysis ────────────────────────────────────────────────

def analyze_features(html_content, test_name):
    """Count implemented features and bonus features. Returns 0-100."""

    js = "\n".join(re.findall(r'<script[^>]*>(.*?)</script>', html_content, re.DOTALL | re.IGNORECASE))
    js_lower = js.lower()
    html_lower = html_content.lower()

    # Feature indicators by test type
    feature_checks = {
        "kanban": [
            ("Multiple columns", "column" in html_lower or "board" in html_lower),
            ("Add task", "add" in js_lower and "task" in js_lower),
            ("Drag & drop", "drag" in js_lower or "draggable" in html_lower),
            ("Delete task", "delete" in js_lower or "remove" in js_lower),
            ("Edit task", "edit" in js_lower and "contenteditable" not in html_lower),
            ("Task counter", "count" in js_lower or "length" in js_lower),
            ("Color labels", "label" in html_lower or "tag" in html_lower),
            ("Local storage", "localstorage" in js_lower),
            ("Priority levels", "priority" in html_lower or "urgent" in html_lower),
            ("Due dates", "date" in html_lower),
        ],
        "dashboard": [
            ("Charts/visualizations", "chart" in html_lower or "canvas" in html_lower or "svg" in html_lower),
            ("Stat cards", "stat" in html_lower or "metric" in html_lower or "card" in html_lower),
            ("Navigation", "nav" in html_lower or "sidebar" in html_lower),
            ("Data tables", "<table" in html_lower or "grid" in html_lower),
            ("Filters", "filter" in js_lower),
            ("Dark mode", "dark" in html_lower or "theme" in html_lower),
            ("Search", "search" in html_lower),
            ("Notifications", "notif" in html_lower or "alert" in html_lower),
            ("Export", "export" in html_lower or "download" in html_lower),
            ("Real-time updates", "interval" in js_lower or "setInterval" in js_lower),
        ],
        "chess": [
            ("8x8 board", "8" in js_lower),
            ("Piece movement", "move" in js_lower),
            ("Turn system", "turn" in js_lower or "white" in js_lower),
            ("Move validation", "valid" in js_lower or "legal" in js_lower),
            ("Check detection", "check" in js_lower),
            ("Piece capture", "capture" in js_lower),
            ("Move history", "history" in js_lower or "log" in html_lower),
            ("Highlight squares", "highlight" in js_lower or "select" in js_lower),
            ("Undo move", "undo" in js_lower),
            ("FEN notation", "fen" in js_lower),
        ],
        "snake": [
            ("Grid system", "grid" in js_lower or "cell" in js_lower),
            ("Snake movement", "direction" in js_lower or "move" in js_lower),
            ("Food/growth", "food" in js_lower or "apple" in js_lower or "grow" in js_lower),
            ("Score tracking", "score" in js_lower),
            ("Game over", "game" in js_lower and ("over" in js_lower or "end" in js_lower)),
            ("Speed control", "speed" in js_lower or "level" in js_lower),
            ("High score", "high" in js_lower or "best" in js_lower),
            ("Pause", "pause" in js_lower),
            ("Restart", "restart" in js_lower or "reset" in js_lower or "new game" in html_lower),
            ("Wall collision", "wall" in js_lower or "collision" in js_lower or "boundary" in js_lower),
        ],
        "calculator": [
            ("Number buttons", "0" in html_lower and "1" in html_lower),
            ("Operators", "+" in html_lower and "-" in html_lower),
            ("Display", "display" in html_lower or "result" in html_lower or "screen" in html_lower),
            ("Decimal support", "." in js_lower or "decimal" in js_lower),
            ("Clear/AC", "clear" in js_lower or "ac" in html_lower),
            ("Keyboard support", "keydown" in js_lower or "keypress" in js_lower),
            ("Backspace", "backspace" in js_lower or "delete" in js_lower),
            ("History", "history" in js_lower),
            ("Percentage", "%" in html_lower or "percent" in js_lower),
            ("Memory functions", "memory" in js_lower or "m+" in html_lower),
        ],
        "markdown": [
            ("Editor textarea", "textarea" in html_lower),
            ("Live preview", "preview" in html_lower),
            ("Markdown parsing", "replace" in js_lower or "markdown" in js_lower or "parse" in js_lower),
            ("Headings", "h1" in js_lower or "heading" in js_lower or "#" in js_lower),
            ("Bold/italic", "bold" in js_lower or "italic" in js_lower or "*" in js_lower),
            ("Links", "link" in js_lower or "href" in js_lower),
            ("Lists", "list" in js_lower or "ul" in js_lower),
            ("Code blocks", "code" in js_lower),
            ("Word count", "count" in js_lower or "length" in js_lower),
            ("Export", "export" in js_lower or "download" in js_lower or "save" in js_lower),
        ],
        "pomodoro": [
            ("Timer display", "timer" in html_lower or "countdown" in html_lower or "time" in html_lower),
            ("Start/pause", "start" in js_lower and "pause" in js_lower),
            ("Reset", "reset" in js_lower),
            ("Work/break modes", "work" in js_lower and "break" in js_lower),
            ("Session count", "session" in js_lower or "count" in js_lower),
            ("Audio alert", "audio" in html_lower or "sound" in js_lower or "beep" in js_lower),
            ("Visual progress", "progress" in html_lower or "circle" in html_lower or "ring" in html_lower),
            ("Settings", "setting" in html_lower or "config" in html_lower),
            ("Notifications", "notif" in js_lower),
            ("Task tracking", "task" in html_lower),
        ],
        "weather": [
            ("City search", "search" in html_lower or "city" in html_lower or "input" in html_lower),
            ("Temperature display", "temp" in html_lower or "degree" in html_lower or "°" in html_content),
            ("Weather icons", "icon" in html_lower or "emoji" in html_content or "svg" in html_lower),
            ("Forecast", "forecast" in html_lower or "day" in html_lower),
            ("Humidity", "humidity" in html_lower or "moisture" in html_lower),
            ("Wind", "wind" in html_lower),
            ("Multiple cities", "city" in html_lower),
            ("Dynamic background", "background" in js_lower),
            ("Time display", "time" in html_lower or "date" in html_lower),
            ("Temperature units", "celsius" in html_lower or "fahrenheit" in html_lower or "°c" in html_content.lower()),
        ],
        "password": [
            ("Generate button", "generate" in html_lower),
            ("Password display", "password" in html_lower),
            ("Length control", "length" in html_lower or "slider" in html_lower or "range" in html_lower),
            ("Character types", "uppercase" in html_lower or "lowercase" in html_lower),
            ("Numbers", "number" in html_lower or "0123456789" in js),
            ("Symbols", "symbol" in html_lower or "special" in html_lower or "!@#$" in js),
            ("Copy button", "copy" in html_lower),
            ("Strength meter", "strength" in html_lower),
            ("Exclude similar", "similar" in html_lower or "exclude" in html_lower),
            ("Multiple passwords", "batch" in html_lower or "multiple" in html_lower),
        ],
        "gta": [
            ("Player character", "player" in js_lower),
            ("Movement controls", "keydown" in js_lower or "arrow" in js_lower or "wasd" in js_lower),
            ("Map/world", "map" in js_lower or "world" in js_lower or "canvas" in html_lower),
            ("Collision", "collision" in js_lower or "collide" in js_lower),
            ("NPCs/enemies", "npc" in js_lower or "enemy" in js_lower or "ped" in js_lower),
            ("Score/money", "score" in js_lower or "money" in js_lower or "cash" in js_lower),
            ("Health", "health" in js_lower or "life" in js_lower),
            ("Weapons", "weapon" in js_lower or "gun" in js_lower or "shoot" in js_lower),
            ("Vehicles", "car" in js_lower or "vehicle" in js_lower or "drive" in js_lower),
            ("Mini-map", "minimap" in js_lower or "radar" in js_lower),
        ],
        "webos": [
            ("Desktop", "desktop" in html_lower),
            ("Taskbar/dock", "taskbar" in html_lower or "dock" in html_lower or "bar" in html_lower),
            ("Window management", "window" in js_lower),
            ("Multiple apps", "app" in html_lower),
            ("Clock", "clock" in js_lower or "time" in js_lower),
            ("Start menu", "start" in html_lower or "menu" in html_lower),
            ("Window drag", "drag" in js_lower),
            ("Close/minimize", "close" in js_lower or "minimize" in js_lower),
            ("Notepad app", "notepad" in html_lower or "text" in html_lower),
            ("File system", "file" in js_lower or "folder" in html_lower),
        ],
    }

    checks = feature_checks.get(test_name, [])
    implemented = sum(1 for _, ok in checks if ok)
    total = len(checks)

    base_score = (implemented / total * 60) if total else 0

    # Bonus features (beyond spec)
    bonus = 0
    # Dark mode
    if "dark" in html_lower or "theme" in html_lower:
        bonus += 10
    # Animations
    if "@keyframes" in html_lower:
        bonus += 10
    # Responsive
    if "@media" in html_lower:
        bonus += 10
    # Keyboard shortcuts
    if "keydown" in js_lower or "keyup" in js_lower or "keypress" in js_lower:
        bonus += 10
    bonus = min(40, bonus)

    return {
        "core_features": round(base_score, 1),
        "bonus_features": bonus,
        "feature_count": f"{implemented}/{total}",
        "total_score": min(100, base_score + bonus),
    }


# ─── Main scoring ─────────────────────────────────────────────────────────────

def score_all():
    # Load browser results
    browser = {}
    if os.path.exists(os.path.join(HERE, "browser_results.json")):
        browser = json.load(open(os.path.join(HERE, "browser_results.json")))

    # Load generation timing
    gen_times = {}
    if os.path.exists(os.path.join(HERE, "fair_results.json")):
        fair = json.load(open(os.path.join(HERE, "fair_results.json")))
        for r in fair.get("results", []):
            gen_times[(r["test"], r["model"])] = r.get("time_seconds", 0)
    # Also check generation logs for timing
    if os.path.exists(os.path.join(HERE, "generation_log2.txt")):
        import re as re2
        with open(os.path.join(HERE, "generation_log2.txt")) as f:
            for line in f:
                m = re2.match(r'\[(\w+)/(\w+)\]\s+(?:DONE|FAILED)\s+[\d.]+(?:KB|s)', line.strip())
                if m:
                    pass  # Already have times from fair_results

    results = {}

    for test in TESTS:
        results[test] = {}

        # Gather timing for speed normalization
        ok_times = {}
        for model in MODELS:
            html_path = os.path.join(HERE, test, f"{model}.html")
            if os.path.exists(html_path) and os.path.getsize(html_path) > 500:
                t = gen_times.get((test, model), 0)
                if t > 0:
                    ok_times[model] = t

        for model in MODELS:
            html_path = os.path.join(HERE, test, f"{model}.html")

            # Check if file exists
            if not os.path.exists(html_path) or os.path.getsize(html_path) < 500:
                results[test][model] = {
                    "total": 0,
                    "status": "FAILED",
                    "dimensions": {},
                    "error": "generation failed or file missing",
                }
                continue

            with open(html_path, encoding="utf-8", errors="replace") as f:
                html_content = f.read()

            # ── A. FUNCTIONAL CORRECTNESS (400 pts) ──
            bk = f"{test}_{model}"
            bentry = browser.get(bk, {})
            checks = bentry.get("checks", [])
            console_errors = bentry.get("console_errors", [])

            # Classify and weight checks
            critical_pts = 0
            critical_max = 0
            important_pts = 0
            important_max = 0
            minor_pts = 0
            minor_max = 0

            for chk in checks:
                tier, pts = classify_check(chk["name"])
                if tier == "critical":
                    critical_max += pts
                    if chk["pass"]:
                        critical_pts += pts
                elif tier == "important":
                    important_max += pts
                    if chk["pass"]:
                        important_pts += pts
                else:
                    minor_max += pts
                    if chk["pass"]:
                        minor_pts += pts

            # Weighted functional score (out of 400)
            # Critical: up to 200 pts, Important: up to 130 pts, Minor: up to 70 pts
            func_critical = (critical_pts / critical_max * 200) if critical_max else 0
            func_important = (important_pts / important_max * 130) if important_max else 0
            func_minor = (minor_pts / minor_max * 70) if minor_max else 0
            func_raw = func_critical + func_important + func_minor

            # Console error penalty
            console_penalty = min(30, len(console_errors) * 5)
            func_score = max(0, func_raw - console_penalty)

            # ── B. CODE ARCHITECTURE (200 pts) ──
            code = analyze_code(html_content)
            code_dims = [
                code["css_methodology"],
                code["js_quality"],
                code["semantic_html"],
                code["accessibility"],
                code["code_organization"],
                code["file_efficiency"],
                code["modern_features"],
                code["self_contained"],
            ]
            code_score = sum(code_dims) / len(code_dims) * 2  # Average * 2 = 200 max

            # ── C. VISUAL DESIGN & POLISH (200 pts) ──
            visual = analyze_visual_design(html_content)
            visual_dims = [
                visual["color_sophistication"],
                visual["typography"],
                visual["spacing_layout"],
                visual["animations"],
                visual["interactive_feedback"],
                visual["responsive"],
                visual["component_polish"],
            ]
            visual_score = sum(visual_dims) / len(visual_dims) * 2  # Average * 2 ≈ 200 max

            # ── D. FEATURE RICHNESS (100 pts) ──
            features = analyze_features(html_content, test)
            feature_score = features["total_score"]

            # ── E. PERFORMANCE (50 pts) ──
            load_ms = bentry.get("load_time_ms", 0)
            if load_ms > 0:
                # Faster = more points. <500ms = 30pts, >5000ms = 5pts
                perf_load = max(5, min(30, 30 - (load_ms - 500) / 200))
            else:
                perf_load = 15

            # Code efficiency bonus
            size_kb = code["metrics"]["total_kb"]
            if size_kb < 10:
                perf_code = 10
            elif size_kb < 30:
                perf_code = 20
            elif size_kb < 60:
                perf_code = 15
            elif size_kb < 100:
                perf_code = 10
            else:
                perf_code = 5

            perf_score = perf_load + perf_code  # Out of 50

            # ── F. INNOVATION & DETAIL (50 pts) ──
            # Creative patterns
            innov = 0
            js = "\n".join(re.findall(r'<script[^>]*>(.*?)</script>', html_content, re.DOTALL | re.IGNORECASE))
            # Confetti/effects
            if "confetti" in js.lower() or "particle" in js.lower() or "sparkle" in js.lower():
                innov += 10
            # Sound effects
            if "audio" in html_content.lower() or "AudioContext" in js or "oscillator" in js.lower():
                innov += 10
            # Keyboard shortcuts beyond basic
            if js.lower().count("keydown") >= 3 or js.lower().count("keyup") >= 3:
                innov += 10
            # Loading states
            if "loading" in html_content.lower() or "spinner" in html_content.lower() or "skeleton" in html_content.lower():
                innov += 5
            # Toast/notification system
            if "toast" in html_content.lower() or "notification" in html_content.lower() or "snackbar" in html_content.lower():
                innov += 10
            # Easter eggs / extra polish
            if "easter" in js.lower() or "secret" in js.lower():
                innov += 5
            innov = min(50, innov)

            # ── TOTAL ──
            total = round(func_score + code_score + visual_score + feature_score + perf_score + innov)

            results[test][model] = {
                "total": total,
                "status": "OK",
                "dimensions": {
                    "functional": round(func_score),
                    "code": round(code_score),
                    "visual": round(visual_score),
                    "features": round(feature_score),
                    "performance": round(perf_score),
                    "innovation": round(innov),
                },
                "details": {
                    "browser_checks": {
                        "critical": f"{critical_pts}/{critical_max}",
                        "important": f"{important_pts}/{important_max}",
                        "minor": f"{minor_pts}/{minor_max}",
                    },
                    "console_errors": len(console_errors),
                    "code_quality": code,
                    "visual_design": visual,
                    "features": features,
                    "load_time_ms": load_ms,
                    "file_size_kb": code["metrics"]["total_kb"],
                }
            }

    return results


def main():
    scores = score_all()

    # Save
    out_path = os.path.join(HERE, "ultra_scores.json")
    with open(out_path, "w") as f:
        json.dump(scores, f, indent=2)
    print(f"Scores written to {out_path}")

    # Print summary
    print("\n" + "=" * 80)
    print("ULTRA SCORES (1000-point scale)")
    print("=" * 80)

    # Per-model totals
    model_totals = {m: {"total": 0, "count": 0, "tests": {}} for m in MODELS}
    for test in TESTS:
        for model in MODELS:
            entry = scores[test].get(model, {})
            t = entry.get("total", 0)
            model_totals[model]["total"] += t
            model_totals[model]["count"] += 1
            model_totals[model]["tests"][test] = t

    print(f"\n{'Rank':<6} {'Model':<16} {'Total':>8} {'Avg/Test':>10} {'Tests':>7}")
    print("-" * 55)

    ranked = sorted(MODELS, key=lambda m: model_totals[m]["total"], reverse=True)
    for rank, model in enumerate(ranked, 1):
        total = model_totals[model]["total"]
        count = model_totals[model]["count"]
        avg = total / count if count else 0
        name = MODEL_NAMES.get(model, model)
        print(f"  {rank}.   {name:<16} {total:>6}  {avg:>8.0f}  {count:>5}/11")

    # Per-test breakdown
    print(f"\n{'Test':<14} | ", end="")
    for m in ranked:
        print(f"{MODEL_NAMES[m][:7]:>8}", end=" | ")
    print()
    print("-" * (14 + 12 * len(ranked)))

    for test in TESTS:
        print(f"{test:<14} | ", end="")
        for m in ranked:
            s = scores[test].get(m, {}).get("total", 0)
            print(f"{s:>8}", end=" | ")
        print()

    # Per-test winners
    print("\nTest Winners:")
    for test in TESTS:
        test_scores = [(m, scores[test].get(m, {}).get("total", 0)) for m in MODELS]
        test_scores.sort(key=lambda x: x[1], reverse=True)
        winner = test_scores[0]
        name = MODEL_NAMES.get(winner[0], winner[0])
        print(f"  {test:<14} → {name} ({winner[1]} pts)")


if __name__ == "__main__":
    main()
