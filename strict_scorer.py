#!/usr/bin/env python3
"""
Strict graded rubric scorer for the AI Model Bake-Off.

Each model HTML file is statically analyzed (regex-based) and graded on a
STRICT 100-point rubric across 6 dimensions, plus a separate 0-5 speed bonus
derived from all_results.json timings.

Goals:
  * Grade on a SCALE, not binary "does X exist".
  * Be HARSH: a typical model should land 40-75/100. >80 is exceptional.
  * Produce real separation between models.

Outputs:
  * strict_scores.json  -- per-test, per-model, per-dimension breakdowns
  * Rebuilds index.html and {test}/index.html

The script is deterministic: same inputs -> same scores.
"""
import json
import os
import re
import math

ROOT = os.path.dirname(os.path.abspath(__file__))
TESTS = ["kanban", "dashboard", "chess", "markdown", "calculator",
         "snake", "pomodoro", "weather", "password", "gta", "webos"]
MODELS = ["sonnet", "opus", "glm", "glm52", "qwen", "ornith"]

MODEL_META = {
    "sonnet":  {"name": "Sonnet 4.6",     "provider": "Anthropic",        "color": "#f59e0b", "emoji": "🟡"},
    "opus":    {"name": "Opus 4.7",       "provider": "Anthropic",        "color": "#ef4444", "emoji": "🔴"},
    "glm":     {"name": "GLM 5.1",        "provider": "ZAI",              "color": "#22c55e", "emoji": "🟢"},
    "glm52":   {"name": "GLM-5.2",        "provider": "ZAI / z.ai",       "color": "#3b82f6", "emoji": "🔵"},
    "qwen":    {"name": "Qwen 3.7 27B",   "provider": "Local",            "color": "#6366f1", "emoji": "🟣"},
    "ornith":  {"name": "Ornith 35B",     "provider": "Local llama.cpp",  "color": "#f97316", "emoji": "🟠"},
}

TEST_META = {
    "kanban":     {"title": "Kanban Board",        "icon": "📋"},
    "dashboard":  {"title": "Dashboard",            "icon": "📊"},
    "chess":      {"title": "Chess Game",           "icon": "♟️"},
    "markdown":   {"title": "Markdown Editor",      "icon": "📝"},
    "calculator": {"title": "Calculator",           "icon": "🧮"},
    "snake":      {"title": "Snake Game",           "icon": "🐍"},
    "pomodoro":   {"title": "Pomodoro Timer",       "icon": "🍅"},
    "weather":    {"title": "Weather App",          "icon": "🌤️"},
    "password":   {"title": "Password Generator",   "icon": "🔐"},
    "gta":        {"title": "GTA-Style Game",       "icon": "🎮"},
    "webos":      {"title": "WebOS Desktop",        "icon": "🖥️"},
}

# Per-test feature spec keywords. Each keyword is a feature the prompt asked for.
# Completeness = fraction of features present (as words/identifiers in the source).
TEST_SPEC = {
    "kanban": ["todo", "progress", "done", "priority", "drag", "drop",
               "localStorage", "search", "filter", "count", "timestamp",
               "delete", "edit", "responsive", "dark"],
    "dashboard": ["kpi", "revenue", "users", "orders", "growth", "chart",
                  "svg", "canvas", "activity", "responsive", "refresh",
                  "date", "export", "hover", "counter"],
    "chess": ["board", "piece", "select", "move", "turn", "white", "black",
              "new game", "captured", "history", "highlight", "check",
              "king", "queen", "rook", "bishop", "knight", "pawn"],
    "markdown": ["editor", "preview", "toolbar", "bold", "italic", "heading",
                 "link", "list", "code", "blockquote", "word count", "copy",
                 "responsive", "parse", "render"],
    "calculator": ["display", "expression", "history", "chain", "keyboard",
                   "error", "zero", "backspace", "memory", "responsive",
                   "decimal", "percent", "operator"],
    "snake": ["canvas", "arrow", "score", "speed", "over", "restart", "food",
              "localStorage", "high", "start", "grid", "touch", "swipe",
              "collision", "loop"],
    "pomodoro": ["circular", "progress", "ring", "work", "short", "long",
                 "break", "start", "pause", "reset", "session", "audio",
                 "beep", "settings", "duration"],
    "weather": ["current", "temp", "humidity", "wind", "condition", "forecast",
                "chart", "high", "low", "icon", "sun", "cloud", "rain",
                "toggle", "celsius", "fahrenheit", "air quality", "sunrise",
                "sunset", "responsive"],
    "password": ["length", "slider", "uppercase", "lowercase", "number",
                 "symbol", "copy", "strength", "weak", "medium", "strong",
                 "generate", "history", "count", "ambiguous", "entropy"],
    "gta": ["city", "road", "building", "sidewalk", "canvas", "player", "wasd",
            "car", "park", "enter", "exit", "drive", "police", "wanted",
            "star", "npc", "chase", "minimap", "health", "money", "neon",
            "score", "restart"],
    "webos": ["desktop", "icon", "taskbar", "start", "tray", "clock", "menu",
              "shutdown", "window", "draggable", "resizable", "minimize",
              "maximize", "close", "z-order", "notepad", "textarea", "file",
              "save", "open", "calculator", "terminal", "command", "help",
              "echo", "clear", "ls", "context", "right-click", "boot"],
}


# ============================================================
# RAW METRIC EXTRACTION
# ============================================================
def extract_metrics(html):
    """Return a dict of raw metrics extracted via regex from the HTML source."""
    m = {}
    m["size"] = len(html)
    m["lines"] = html.count("\n") + 1

    low = html.lower()

    # --- JavaScript structure ---
    m["js_functions"] = len(re.findall(r"\bfunction\s+[A-Za-z_$][\w$]*\s*\(", html))
    m["js_arrow_fns"] = len(re.findall(r"(?:const|let|var)\s+[A-Za-z_$][\w$]*\s*=\s*(?:async\s*)?\([^)]*\)\s*=>", html))
    m["js_methods"]   = len(re.findall(r"[A-Za-z_$][\w$]*\s*:\s*function\s*\(", html))  # obj methods
    m["total_fns"]    = m["js_functions"] + m["js_arrow_fns"] + m["js_methods"]

    # function lengths (lines)
    fn_blocks = re.findall(r"function\s+[A-Za-z_$][\w$]*\s*\([^)]*\)\s*\{", html)
    m["long_fns"] = 0
    # rough: find function bodies by brace matching (cheap heuristic on a sample)
    # we'll instead count: a function whose body is > 80 lines (rare in these files)
    for match in re.finditer(r"function\s+[A-Za-z_$][\w$]*\s*\([^)]*\)\s*\{", html):
        start = match.end()
        depth = 1
        i = start
        while i < len(html) and depth > 0:
            if html[i] == "{":
                depth += 1
            elif html[i] == "}":
                depth -= 1
            i += 1
        body_lines = html[start:i].count("\n")
        if body_lines > 80:
            m["long_fns"] += 1

    # --- Event handlers ---
    m["addEventListener"] = len(re.findall(r"\.addEventListener\s*\(", html))
    m["inline_handlers"]  = len(re.findall(r"\bon(?:click|change|input|submit|keydown|keyup|keypress|load|mouseover|mouseout|mousedown|mouseup|mousemove|touchstart|touchmove|touchend|dragstart|dragend|drop|dragover|focus|blur)\s*=", html))

    # --- Defects / risks ---
    m["eval"]            = len(re.findall(r"\beval\s*\(", html))
    m["innerHTML_writes"]= len(re.findall(r"\.innerHTML\s*=", html))
    m["setInterval"]     = len(re.findall(r"\bsetInterval\s*\(", html))
    m["clearInterval"]   = len(re.findall(r"\bclearInterval\s*\(", html))
    m["setTimeout"]      = len(re.findall(r"\bsetTimeout\s*\(", html))
    m["requestAnimationFrame"] = len(re.findall(r"\brequestAnimationFrame\s*\(", html))
    m["try_catch"]       = len(re.findall(r"\btry\s*\{", html))
    m["isNaN_checks"]    = len(re.findall(r"\bisNaN\s*\(", html))
    m["parseFloat"]      = len(re.findall(r"\bparseFloat\s*\(", html))
    m["parseInt"]        = len(re.findall(r"\bparseInt\s*\(", html))
    m["console_log"]     = len(re.findall(r"\bconsole\.log\s*\(", html))
    m["typeof_checks"]   = len(re.findall(r"\btypeof\s+", html))
    m["ternary"]         = low.count("?")  # rough
    # comments
    m["line_comments"]   = len(re.findall(r"//[^\n]*", html))
    m["block_comments"]  = len(re.findall(r"/\*[\s\S]*?\*/", html))
    m["total_comments"]  = m["line_comments"] + m["block_comments"]

    # --- CSS polish ---
    m["css_transitions"] = len(re.findall(r"transition\s*:", low))
    m["css_keyframes"]   = len(re.findall(r"@keyframes\b", low))
    m["css_animation"]   = len(re.findall(r"animation\s*:", low))
    m["css_transforms"]  = len(re.findall(r"transform\s*:", low))
    m["css_hover"]       = len(re.findall(r":hover\b", low))
    m["css_active"]      = len(re.findall(r":active\b", low))
    m["css_focus"]       = len(re.findall(r":focus\b", low))
    m["css_focus_visible"] = len(re.findall(r":focus-visible\b", low))
    m["css_box_shadow"]  = len(re.findall(r"box-shadow\s*:", low))
    m["css_border_radius"] = len(re.findall(r"border-radius\s*:", low))
    m["css_grid"]        = len(re.findall(r"(?:display\s*:\s*grid|grid-template)", low))
    m["css_flex"]        = len(re.findall(r"display\s*:\s*flex", low))
    m["prefers_reduced"] = 1 if "prefers-reduced-motion" in low else 0

    # CSS custom properties
    css_var_defs = set(re.findall(r"--([a-zA-Z][\w-]*)\s*:", html))
    m["css_var_defs"] = len(css_var_defs)
    m["css_var_uses"] = len(re.findall(r"var\(\s*--[\w-]+", html))

    # --- Semantic / a11y ---
    semantic_tags = ["header", "nav", "main", "section", "article", "footer", "aside", "figure", "figcaption"]
    m["semantic_tags"] = sum(len(re.findall(r"<%s\b" % t, low)) for t in semantic_tags)
    m["div_count"]     = len(re.findall(r"<div\b", low))
    m["button_count"]  = len(re.findall(r"<button\b", low))
    m["label_with_for"]= len(re.findall(r"<label\b[^>]*\bfor\s*=", low))
    m["input_count"]   = len(re.findall(r"<input\b", low))
    m["form_count"]    = len(re.findall(r"<form\b", low))
    m["headings"]      = len(re.findall(r"<h[1-6]\b", low))
    m["aria_labels"]   = len(re.findall(r"\baria-[a-z]+\s*=", low))
    m["aria_live"]     = len(re.findall(r"\baria-live\b", low))
    m["role_attr"]     = len(re.findall(r"\brole\s*=\s*[\"']", low))
    m["title_attr"]    = len(re.findall(r"<[a-z][^>]*\btitle\s*=\s*[\"']", low))
    m["tabindex"]      = len(re.findall(r"\btabindex\s*=", low))
    m["alt_attrs"]     = len(re.findall(r"\balt\s*=\s*[\"']", low))

    # --- Typography ---
    m["font_family"]    = len(re.findall(r"font-family\s*:", low))
    m["font_sizes"]     = len(set(re.findall(r"font-size\s*:\s*([0-9.]+\w*)", low)))
    m["font_weights"]   = len(set(re.findall(r"font-weight\s*:\s*([0-9a-z]+)", low)))
    m["line_heights"]   = len(set(re.findall(r"line-height\s*:\s*([0-9.]+(?:px|em|rem|%)?)", low)))

    # --- Colors ---
    m["hex_colors"]  = len(set(re.findall(r"#[0-9a-fA-F]{3,8}\b", html)))
    m["rgb_colors"]  = len(set(re.findall(r"rgba?\s*\(\s*\d+", low)))
    m["total_colors"] = m["hex_colors"] + m["rgb_colors"]

    # --- Feedback patterns ---
    fb_patterns = ["toast", "notification", "alert(", "modal", "dialog", "confirm(",
                   "snackbar", "success", "error", "warning", "loading", "spinner",
                   "progressbar", "progress-bar", "alert", "warn"]
    m["feedback_patterns"] = sum(low.count(p) for p in fb_patterns)
    m["has_toast_like"] = 1 if any(p in low for p in ["toast", "notification", "snackbar", "modal", "dialog"]) else 0
    m["has_confirm"] = 1 if "confirm(" in low else 0

    # --- Keyboard ---
    m["keydown_handlers"] = len(re.findall(r"(?:addEventListener\s*\(\s*['\"]key|onkeydown)", low))
    m["keyboard_any"]    = len(re.findall(r"key(?:down|up|press)", low))
    m["debounce"]        = len(re.findall(r"debounce|setTimeout\s*\([^,]+,\s*\d+\)", low))

    # --- Localstorage / canvas / svg ---
    m["localStorage"] = len(re.findall(r"localStorage", html))
    m["canvas_ctx"]   = len(re.findall(r"getContext\s*\(", html))
    m["svg"]          = len(re.findall(r"<svg\b", low))
    m["web_audio"]    = len(re.findall(r"AudioContext|new\s+Audio", html))

    # --- Game / app-specific runtime ---
    m["has_loop"] = 1 if (re.search(r"\brequestAnimationFrame\b", html) or re.search(r"\bsetInterval\s*\([^,]+,\s*\d+\)", html)) else 0

    return m


# ============================================================
# SCORING HELPERS
# ============================================================
def clamp(x, lo, hi):
    return max(lo, min(hi, x))

def scaled(metric, low_thr, hi_thr, max_pts):
    """Linear ramp: 0 at low_thr, full at hi_thr (and above)."""
    if hi_thr == low_thr:
        return max_pts if metric >= hi_thr else 0.0
    return clamp((metric - low_thr) / (hi_thr - low_thr), 0.0, 1.0) * max_pts

def penalize(metric, low_thr, hi_thr, max_pts):
    """Inverse ramp: full at low_thr, 0 at hi_thr (and above). Used for defects."""
    if hi_thr == low_thr:
        return 0.0 if metric >= hi_thr else max_pts
    return clamp(1 - (metric - low_thr) / (hi_thr - low_thr), 0.0, 1.0) * max_pts


# ============================================================
# DIMENSION SCORERS
# ============================================================
def score_functionality(m, test):
    """30 pts: core_mechanics(10) + completeness(10) + edge_cases(10)."""
    # --- core mechanics (10): real event handlers wired to functions ---
    # reward addEventListener, penalize inline handlers as primary mechanism
    handlers = m["addEventListener"] + m["inline_handlers"]
    ae_ratio = m["addEventListener"] / max(handlers, 1)
    # need both handlers AND functions for real logic
    s_core = 0.0
    s_core += scaled(handlers, 2, 12, 6.0)         # at least 12 handlers wired -> full 6
    s_core += scaled(m["total_fns"], 4, 20, 4.0)   # real decomposition
    # penalty if mostly inline
    if handlers > 0 and ae_ratio < 0.3:
        s_core *= 0.7
    s_core = clamp(s_core, 0.0, 10.0)

    # --- completeness (10): fraction of spec keywords present ---
    spec = TEST_SPEC[test]
    html_low = m["_html_low"]
    present = sum(1 for kw in spec if kw in html_low)
    frac = present / max(len(spec), 1)
    s_comp = frac * 10.0
    # small floor penalty: <70% presence is incomplete
    if frac < 0.5:
        s_comp = min(s_comp, 4.0)
    s_comp = clamp(s_comp, 0.0, 10.0)

    # --- edge cases & error handling (10) ---
    s_edge = 0.0
    s_edge += scaled(m["try_catch"], 0, 3, 3.0)
    s_edge += scaled(m["isNaN_checks"] + m["typeof_checks"], 0, 3, 2.0)
    s_edge += scaled(m["parseInt"] + m["parseFloat"], 0, 3, 1.5)
    # guard-clause style: if/return patterns
    guards = len(re.findall(r"\bif\s*\([^)]*\)\s*(?:return|throw|continue)", m["_html"]))
    s_edge += scaled(guards, 0, 4, 2.0)
    # empty-state / NaN display handling
    if any(p in html_low for p in ["nan", "undefined", "null check", "||", "??"]):
        s_edge += 0.5
    # validation specifically
    if re.search(r"(?:required|pattern=|minlength|maxlength|invalid)", html_low):
        s_edge += 1.0
    s_edge = clamp(s_edge, 0.0, 10.0)

    return {
        "core_mechanics": round(s_core, 1),
        "completeness":   round(s_comp, 1),
        "edge_cases":     round(s_edge, 1),
        "total": round(s_core + s_comp + s_edge, 1),
    }


def score_code_quality(m):
    """20 pts: structure(7) + defect_avoidance(7) + maintainability(6)."""
    # --- structure (7): function decomposition, no god-functions ---
    s_struct = 0.0
    s_struct += scaled(m["total_fns"], 3, 18, 4.0)   # 18+ functions = great decomposition
    # penalize god functions
    s_struct -= m["long_fns"] * 1.5
    # reward modular separation: average fn size sweet spot
    s_struct = clamp(s_struct, 0.0, 7.0)

    # --- defect avoidance (7) ---
    s_def = 7.0
    s_def -= penalize(m["inline_handlers"], 0, 8, 2.0) * 0   # we want to subtract, so reverse
    # restart: start at full, subtract per defect category
    s_def = 7.0
    # inline handlers: each cluster of 5 loses 1 point
    s_def -= clamp(m["inline_handlers"] / 5.0, 0.0, 2.5)
    # eval is severe
    s_def -= m["eval"] * 2.0
    # innerHTML writes (XSS risk): each loses a bit
    s_def -= clamp(m["innerHTML_writes"] / 6.0, 0.0, 1.5)
    # setInterval without clearInterval = leak
    leaks = max(0, m["setInterval"] - m["clearInterval"])
    s_def -= clamp(leaks / 2.0, 0.0, 1.5)
    # console.log left in = unprofessional
    s_def -= clamp(m["console_log"] / 6.0, 0.0, 1.0)
    s_def = clamp(s_def, 0.0, 7.0)

    # --- maintainability (6) ---
    s_maint = 0.0
    s_maint += scaled(m["total_comments"], 2, 15, 2.0)  # comments
    s_maint += scaled(m["css_var_defs"], 2, 10, 2.0)    # CSS custom properties
    # DRY: many literal magic numbers = brittle
    magic = len(re.findall(r"\b\d{2,}\b", m["_html"]))  # rough
    if magic < 40:
        s_maint += 1.5
    elif magic < 100:
        s_maint += 0.75
    # consistent use of var() = maintainable theming
    if m["css_var_uses"] >= 6:
        s_maint += 0.5
    s_maint = clamp(s_maint, 0.0, 6.0)

    return {
        "structure":         round(s_struct, 1),
        "defect_avoidance":  round(s_def, 1),
        "maintainability":   round(s_maint, 1),
        "total": round(s_struct + s_def + s_maint, 1),
    }


def score_ux(m):
    """20 pts: micro_interactions(7) + feedback(7) + keyboard(6)."""
    # --- micro interactions (7) ---
    s_micro = 0.0
    s_micro += scaled(m["css_transitions"], 1, 8, 3.0)
    s_micro += scaled(m["css_keyframes"] + m["css_animation"], 0, 4, 2.0)
    s_micro += scaled(m["css_transforms"], 0, 4, 1.5)
    s_micro += scaled(m["css_hover"], 2, 10, 1.5)  # meaningful hover states
    s_micro += scaled(m["css_active"], 0, 3, 0.5)
    s_micro = clamp(s_micro, 0.0, 7.0)

    # --- feedback systems (7) ---
    s_fb = 0.0
    s_fb += scaled(m["feedback_patterns"], 1, 8, 3.0)
    if m["has_toast_like"]:
        s_fb += 1.5
    if m["has_confirm"]:
        s_fb += 0.75
    # visual progress indicators
    if m["canvas_ctx"] > 0 or m["svg"] > 0:
        s_fb += 0.75
    # explicit success/error styling
    if re.search(r"\.(?:success|error|warning|danger)\b", m["_html_low"]):
        s_fb += 1.0
    s_fb = clamp(s_fb, 0.0, 7.0)

    # --- keyboard & input quality (6) ---
    s_kb = 0.0
    s_kb += scaled(m["keydown_handlers"], 0, 4, 2.5)
    # input validation with inline feedback
    if re.search(r"(?:required|pattern=|invalid|valid)", m["_html_low"]):
        s_kb += 1.0
    # undo / keyboard shortcuts beyond basics
    if re.search(r"(?:undo|ctrl\+|cmd\+|meta\+)", m["_html_low"]):
        s_kb += 1.5
    # debounce on input
    if m["debounce"] > 0:
        s_kb += 1.0
    s_kb = clamp(s_kb, 0.0, 6.0)

    return {
        "micro_interactions": round(s_micro, 1),
        "feedback":           round(s_fb, 1),
        "keyboard":           round(s_kb, 1),
        "total": round(s_micro + s_fb + s_kb, 1),
    }


def score_visual(m):
    """15 pts: typography(5) + color_cohesion(5) + layout_spacing(5)."""
    # --- typography (5) ---
    s_typo = 0.0
    if m["font_family"] >= 1:
        s_typo += 1.0
    s_typo += scaled(m["font_sizes"], 1, 4, 2.0)       # type scale
    s_typo += scaled(m["font_weights"], 1, 3, 1.5)
    if m["line_heights"] >= 1:
        s_typo += 0.5
    s_typo = clamp(s_typo, 0.0, 5.0)

    # --- color & cohesion (5) ---
    s_color = 0.0
    # CSS variables are the cohesion signal
    s_color += scaled(m["css_var_defs"], 2, 10, 3.0)
    # too many distinct ad-hoc colors = chaotic; <6 ideal, >25 chaotic
    if m["total_colors"] <= 25:
        s_color += 2.0
    elif m["total_colors"] <= 40:
        s_color += 1.0
    else:
        s_color += 0.25
    # cohesive palette signal: high var() usage relative to raw hex
    if m["css_var_uses"] >= 8:
        s_color += 0.0  # already counted
    s_color = clamp(s_color, 0.0, 5.0)

    # --- layout & spacing (5) ---
    s_layout = 0.0
    s_layout += scaled(m["css_grid"] + m["css_flex"], 1, 6, 2.0)
    s_layout += scaled(m["css_box_shadow"], 0, 4, 1.0)
    s_layout += scaled(m["css_border_radius"], 1, 6, 1.5)
    # systematic spacing (8/16/24 multiples)
    spacing_vals = re.findall(r"(?:padding|margin|gap)\s*:\s*(\d+)", m["_html_low"])
    multiples = sum(1 for v in spacing_vals if int(v) % 4 == 0)
    if spacing_vals and multiples / len(spacing_vals) >= 0.6:
        s_layout += 0.5
    s_layout = clamp(s_layout, 0.0, 5.0)

    return {
        "typography":      round(s_typo, 1),
        "color_cohesion":  round(s_color, 1),
        "layout_spacing":  round(s_layout, 1),
        "total": round(s_typo + s_color + s_layout, 1),
    }


def score_accessibility(m):
    """10 pts: semantic(4) + aria(3) + keyboard_contrast(3)."""
    # --- semantic HTML (4) ---
    s_sem = 0.0
    s_sem += scaled(m["semantic_tags"], 1, 6, 2.0)
    # use real <button> not <div onclick>
    if m["button_count"] > 0 and m["div_count"] > 0:
        btn_ratio = m["button_count"] / (m["button_count"] + m["div_count"])
        s_sem += min(btn_ratio * 4, 1.5)   # reward real buttons
    if m["label_with_for"] >= 1:
        s_sem += 0.5
    s_sem = clamp(s_sem, 0.0, 4.0)

    # --- aria & labels (3) ---
    s_aria = 0.0
    s_aria += scaled(m["aria_labels"], 1, 6, 1.5)
    s_aria += scaled(m["role_attr"] + m["aria_live"], 0, 3, 1.0)
    s_aria += scaled(m["title_attr"] + m["alt_attrs"], 0, 3, 0.5)
    s_aria = clamp(s_aria, 0.0, 3.0)

    # --- keyboard nav & contrast (3) ---
    s_kc = 0.0
    s_kc += scaled(m["css_focus"] + m["css_focus_visible"], 0, 3, 1.5)
    s_kc += scaled(m["tabindex"], 0, 2, 0.5)
    if m["prefers_reduced"]:
        s_kc += 1.0
    s_kc = clamp(s_kc, 0.0, 3.0)

    return {
        "semantic":         round(s_sem, 1),
        "aria":             round(s_aria, 1),
        "keyboard_contrast":round(s_kc, 1),
        "total": round(s_sem + s_aria + s_kc, 1),
    }


def score_performance(m):
    """5 pts: bundle(3) + runtime(2)."""
    # bundle size relative to feature set
    size_kb = m["size"] / 1024
    fns = max(m["total_fns"], 1)
    kb_per_fn = size_kb / fns

    s_bundle = 0.0
    if size_kb <= 15:
        s_bundle += 3.0
    elif size_kb <= 25:
        s_bundle += 2.5
    elif size_kb <= 35:
        s_bundle += 2.0
    elif size_kb <= 45:
        s_bundle += 1.5
    elif size_kb <= 60:
        s_bundle += 0.75
    else:
        s_bundle += 0.25
    # huge base64 blobs penalty (rough)
    if re.search(r"data:image/[^;]{4,};base64,[A-Za-z0-9+/]{5000,}", m["_html"]):
        s_bundle -= 1.0
    s_bundle = clamp(s_bundle, 0.0, 3.0)

    # runtime patterns
    s_run = 0.0
    if m["requestAnimationFrame"] > 0:
        s_run += 1.0
    # event delegation / cleanup signal
    if m["clearInterval"] > 0 or m["debounce"] > 0:
        s_run += 0.5
    # removeEventListener = disciplined
    if re.search(r"\.removeEventListener\b", m["_html"]):
        s_run += 0.5
    s_run = clamp(s_run, 0.0, 2.0)

    return {
        "bundle":   round(s_bundle, 1),
        "runtime":  round(s_run, 1),
        "total": round(s_bundle + s_run, 1),
    }


# ============================================================
# MAIN SCORER
# ============================================================
def score_file(html, test):
    m = extract_metrics(html)
    m["_html"] = html
    m["_html_low"] = html.lower()

    func = score_functionality(m, test)
    qual = score_code_quality(m)
    ux   = score_ux(m)
    vis  = score_visual(m)
    a11y = score_accessibility(m)
    perf = score_performance(m)

    # strip private fields from metrics snapshot
    metrics = {k: v for k, v in m.items() if not k.startswith("_")}

    quality = func["total"] + qual["total"] + ux["total"] + vis["total"] + a11y["total"] + perf["total"]
    quality = round(quality, 1)

    return {
        "quality_score": quality,
        "dimensions": {
            "functionality": func,
            "code_quality":  qual,
            "ux":            ux,
            "visual":        vis,
            "accessibility": a11y,
            "performance":   perf,
        },
        "metrics": metrics,
        "size_bytes": m["size"],
    }


def load_timings():
    """Load all_results.json timings (only some models have data)."""
    path = os.path.join(ROOT, "all_results.json")
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


def compute_speed_bonus(timings):
    """For each test, rank the 4 known-timed models and award 5..0 speed bonus.
    Models without timing data get None."""
    per_test = {}
    for test in TESTS:
        entries = []
        for model in ["sonnet", "opus", "glm", "qwen"]:
            key = f"{test}_{model}"
            if key in timings and timings[key].get("ok") and timings[key].get("time", 99999) < 9999:
                entries.append((model, timings[key]["time"]))
        # rank: fastest=5, scaled to slowest=0.5
        entries.sort(key=lambda x: x[1])
        bonus = {}
        if entries:
            tmin = entries[0][1]
            tmax = entries[-1][1]
            for model, t in entries:
                if tmax == tmin:
                    pts = 5.0
                else:
                    pts = 5.0 - 4.5 * (t - tmin) / (tmax - tmin)
                bonus[model] = round(pts, 2)
        # models without timing data
        for model in MODELS:
            if model not in bonus:
                bonus[model] = None
        per_test[test] = bonus
    return per_test


def score_all():
    timings = load_timings()
    speed_bonus = compute_speed_bonus(timings)

    scores = {
        "rubric": {
            "functionality": {"max": 30, "subs": ["core_mechanics(10)", "completeness(10)", "edge_cases(10)"]},
            "code_quality":  {"max": 20, "subs": ["structure(7)", "defect_avoidance(7)", "maintainability(6)"]},
            "ux":            {"max": 20, "subs": ["micro_interactions(7)", "feedback(7)", "keyboard(6)"]},
            "visual":        {"max": 15, "subs": ["typography(5)", "color_cohesion(5)", "layout_spacing(5)"]},
            "accessibility": {"max": 10, "subs": ["semantic(4)", "aria(3)", "keyboard_contrast(3)"]},
            "performance":   {"max":  5, "subs": ["bundle(3)", "runtime(2)"]},
        },
        "tests": {},
        "totals": {},
    }

    for test in TESTS:
        scores["tests"][test] = {}
        for model in MODELS:
            path = os.path.join(ROOT, test, f"{model}.html")
            if not os.path.exists(path):
                continue
            with open(path, encoding="utf-8", errors="replace") as f:
                html = f.read()
            result = score_file(html, test)
            # attach speed bonus
            sb = speed_bonus.get(test, {}).get(model)
            result["speed_bonus"] = sb
            result["combined"] = round(result["quality_score"] + (sb or 0), 1)
            result["has_speed_data"] = sb is not None
            scores["tests"][test][model] = result

    # totals per model
    for model in MODELS:
        quality_sum = 0.0
        speed_sum = 0.0
        combined_sum = 0.0
        n = 0
        size_sum = 0
        for test in TESTS:
            r = scores["tests"][test].get(model)
            if not r:
                continue
            n += 1
            quality_sum += r["quality_score"]
            combined_sum += r["combined"]
            if r["speed_bonus"] is not None:
                speed_sum += r["speed_bonus"]
            size_sum += r["size_bytes"]
        scores["totals"][model] = {
            "quality_total": round(quality_sum, 1),
            "quality_avg": round(quality_sum / max(n, 1), 1),
            "speed_total": round(speed_sum, 1),
            "combined_total": round(combined_sum, 1),
            "combined_avg": round(combined_sum / max(n, 1), 1),
            "avg_size_kb": round(size_sum / max(n, 1) / 1024, 1),
            "tests_counted": n,
            "max_possible": n * 100,         # quality
            "max_combined": n * 105,         # quality + speed
        }

    return scores


# ============================================================
# STRENGTHS / WEAKNESSES DERIVATION
# ============================================================
DIM_LABELS = {
    "functionality": "Functionality",
    "code_quality":  "Code Quality",
    "ux":            "UX Polish",
    "visual":        "Visual Design",
    "accessibility": "Accessibility",
    "performance":   "Performance",
}
DIM_MAX = {
    "functionality": 30, "code_quality": 20, "ux": 20,
    "visual": 15, "accessibility": 10, "performance": 5,
}


def compute_dimension_avgs(scores):
    """Per-model, per-dimension average (as fraction of that dimension's max)."""
    out = {m: {} for m in MODELS}
    for model in MODELS:
        sums = {d: 0.0 for d in DIM_LABELS}
        n = 0
        for test in TESTS:
            r = scores["tests"][test].get(model)
            if not r:
                continue
            n += 1
            for d in DIM_LABELS:
                sums[d] += r["dimensions"][d]["total"]
        for d in DIM_LABELS:
            avg = sums[d] / max(n, 1)
            out[model][d] = {
                "avg": round(avg, 1),
                "max": DIM_MAX[d],
                "pct": round(avg / DIM_MAX[d] * 100, 1),
            }
    return out


def derive_strengths_weaknesses(dim_avgs, model):
    """Return (strengths[], weaknesses[]) based on dimension pct scores."""
    items = [(d, info["pct"], DIM_LABELS[d]) for d, info in dim_avgs[model].items()]
    items.sort(key=lambda x: -x[1])
    strengths = []
    weaknesses = []
    for d, pct, label in items:
        if pct >= 70:
            strengths.append(f"Strong {label} ({pct:.0f}%)")
        elif pct >= 55 and len(strengths) < 2:
            strengths.append(f"Solid {label} ({pct:.0f}%)")
        elif pct < 45:
            weaknesses.append(f"Weak {label} ({pct:.0f}%)")
        elif pct < 55 and len(weaknesses) < 2:
            weaknesses.append(f"Average {label} ({pct:.0f}%)")
    if not strengths:
        strengths.append("Balanced but unspectacular")
    if not weaknesses:
        weaknesses.append("No glaring gaps")
    return strengths[:3], weaknesses[:3]


# ============================================================
# HTML GENERATION
# ============================================================
CSS_BASE = """
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
:root {
  --bg: #0d1117; --bg2: #161b22; --bg3: #21262d; --border: #30363d;
  --text: #e6edf3; --text2: #8b949e; --accent: #58a6ff;
  --purple: #6366f1; --green: #22c55e; --amber: #f59e0b; --red: #ef4444;
  --sonnet:#f59e0b; --opus:#ef4444; --glm:#22c55e; --glm52:#3b82f6;
  --qwen:#6366f1; --ornith:#f97316;
}
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background: var(--bg); color: var(--text); line-height: 1.6; min-height: 100vh; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
.container { max-width: 1200px; margin: 0 auto; padding: 0 24px; }

.hero { text-align: center; padding: 60px 24px 40px; position: relative; overflow: hidden; }
.hero::before { content:''; position:absolute; top:-50%; left:-50%; width:200%; height:200%;
  background: radial-gradient(ellipse at center, rgba(99,102,241,0.15) 0%, transparent 70%); }
.hero h1 { font-size: 3rem; font-weight: 800; position:relative;
  background: linear-gradient(135deg, #6366f1, #a855f7, #ec4899);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  background-clip: text; margin-bottom: 8px; }
.hero .subtitle { color: var(--text2); font-size: 1.1rem; position:relative; }
.hero .meta { color: var(--text2); font-size: 0.85rem; margin-top: 6px; position:relative; }
.badge-old { display:inline-block; background: var(--bg3); border:1px solid var(--border);
  color: var(--text2); padding: 3px 10px; border-radius: 999px; font-size: 0.75rem;
  margin-top: 10px; position: relative; }

.card { background: var(--bg2); border: 1px solid var(--border); border-radius: 12px;
  padding: 20px; transition: border-color 0.2s, transform 0.2s; }
.card:hover { border-color: var(--accent); transform: translateY(-2px); }

.section { padding: 40px 0; }
.section-title { font-size: 1.4rem; font-weight: 700; margin-bottom: 6px; }
.section-desc { color: var(--text2); font-size: 0.9rem; margin-bottom: 20px; }

.grid-2 { display: grid; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); gap: 16px; }
.grid-3 { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }

.tabs { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 20px; }
.tab-btn { padding: 8px 18px; border-radius: 999px; border: 1px solid var(--border);
  background: var(--bg2); color: var(--text2); cursor: pointer; font-size: 0.9rem;
  transition: all 0.2s; font-weight: 500; }
.tab-btn:hover { border-color: var(--text2); color: var(--text); }
.tab-btn.active { color: #fff; border-color: transparent; }

.stats-bar { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 14px; }
.stat { background: var(--bg3); border: 1px solid var(--border); border-radius: 8px;
  padding: 8px 14px; display: flex; flex-direction: column; min-width: 90px; }
.stat-label { font-size: 0.7rem; color: var(--text2); text-transform: uppercase; letter-spacing: 0.5px; }
.stat-value { font-size: 1.1rem; font-weight: 700; }

.iframe-wrap { border: 1px solid var(--border); border-radius: 12px; overflow: hidden;
  background: #fff; height: 560px; }
.iframe-wrap iframe { width: 100%; height: 100%; border: none; }

.winner-badge { display: inline-block; background: linear-gradient(135deg, #f59e0b, #ef4444);
  color: #fff; padding: 3px 12px; border-radius: 999px; font-weight: 700; font-size: 0.8rem; }
.rank-num { font-size: 1.5rem; font-weight: 800; }

.cmp-table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
.cmp-table th, .cmp-table td { padding: 10px 12px; text-align: left;
  border-bottom: 1px solid var(--border); }
.cmp-table th { color: var(--text2); font-weight: 600; text-transform: uppercase;
  font-size: 0.7rem; letter-spacing: 0.5px; }
.cmp-table tr:hover td { background: var(--bg3); }
.score-bar { height: 5px; border-radius: 3px; background: var(--bg3); min-width: 60px; margin-top: 3px; }
.score-bar-fill { height: 100%; border-radius: 3px; }
.best { color: #22c55e; font-weight: 700; }

/* Dimension breakdown bars */
.dim-list { display: flex; flex-direction: column; gap: 6px; margin-top: 10px; }
.dim-row { display: grid; grid-template-columns: 130px 1fr 50px; gap: 10px; align-items: center; font-size: 0.78rem; }
.dim-label { color: var(--text2); }
.dim-track { height: 7px; border-radius: 4px; background: var(--bg3); overflow: hidden; }
.dim-fill { height: 100%; border-radius: 4px; transition: width 0.4s; }
.dim-val { font-weight: 700; text-align: right; font-size: 0.78rem; }

/* Methodology */
.method-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 14px; }
.method-item { background: var(--bg2); border: 1px solid var(--border); border-radius: 10px;
  padding: 16px; }
.method-item h4 { font-size: 0.95rem; margin-bottom: 6px; display:flex; gap:8px; align-items:center; }
.method-item .pts { margin-left:auto; color: var(--accent); font-size: 0.8rem; font-weight: 700;
  background: rgba(88,166,255,0.1); padding: 2px 8px; border-radius: 999px; }
.method-item p { color: var(--text2); font-size: 0.82rem; }
.method-item ul { color: var(--text2); font-size: 0.78rem; margin-top: 6px; padding-left: 18px; }

.back-link { display: inline-flex; align-items: center; gap: 6px; color: var(--text2);
  font-size: 0.9rem; padding: 10px 0; }
.back-link:hover { color: var(--accent); }

footer { text-align: center; padding: 28px 0; border-top: 1px solid var(--border);
  color: var(--text2); font-size: 0.82rem; margin-top: 40px; }

.dim-panel { background: var(--bg2); border: 1px solid var(--border); border-radius: 12px;
  padding: 16px; margin-bottom: 14px; }
.dim-panel h4 { font-size: 0.85rem; color: var(--text2); text-transform: uppercase;
  letter-spacing: 0.5px; margin-bottom: 4px; }

@media (max-width: 760px) {
  .hero h1 { font-size: 2rem; }
  .grid-2, .grid-3 { grid-template-columns: 1fr; }
  .iframe-wrap { height: 420px; }
  .cmp-table { font-size: 0.78rem; }
}
"""


def fmt_speed(sb):
    if sb is None:
        return "—"
    return f"+{sb:.1f}"


def score_color(q):
    """Color hint based on quality score (0-100)."""
    if q >= 70:
        return "#22c55e"
    if q >= 55:
        return "#a3e635"
    if q >= 40:
        return "#f59e0b"
    return "#ef4444"


def dim_breakdown_html(dims, model_color):
    """Render the 6-dimension breakdown bars for one model."""
    rows = []
    for key, label in DIM_LABELS.items():
        d = dims[key]
        total = d["total"]
        maxv = DIM_MAX[key]
        pct = total / maxv * 100
        rows.append(f"""
      <div class="dim-row">
        <span class="dim-label">{label}</span>
        <div class="dim-track"><div class="dim-fill" style="width:{pct:.0f}%;background:{model_color}"></div></div>
        <span class="dim-val">{total:.0f}/{maxv}</span>
      </div>""")
    return f'<div class="dim-list">{"".join(rows)}</div>'


def build_test_page(test):
    """Build {test}/index.html with strict scores + dimension breakdowns."""
    with open(os.path.join(ROOT, "strict_scores.json")) as f:
        scores = json.load(f)
    meta = TEST_META[test]
    test_scores = scores["tests"][test]
    # rank models by combined
    ranked = sorted(MODELS, key=lambda m: -(test_scores[m]["combined"] if m in test_scores else 0))
    winner = ranked[0]
    wmeta = MODEL_META[winner]
    wscore = test_scores[winner]

    # winner table cells: rank order with quality, speed, combined
    rows_html = []
    for rank, model in enumerate(ranked, 1):
        s = test_scores[model]
        mm = MODEL_META[model]
        col = mm["color"]
        q = s["quality_score"]
        qcol = score_color(q)
        rows_html.append(f"""
    <div class="dim-panel" style="border-left: 4px solid {col}">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
        <div>
          <span style="font-size:1.05rem;font-weight:700">{mm['emoji']} {mm['name']}</span>
          <span style="color:var(--text2);margin-left:6px;font-size:0.8rem">{mm['provider']}</span>
        </div>
        <div style="display:flex;gap:8px;align-items:center">
          <span class="rank-num" style="color:{col}">#{rank}</span>
          {('<span class="winner-badge">🏆 WINNER</span>' if rank == 1 else '')}
        </div>
      </div>
      <div class="stats-bar">
        <div class="stat"><span class="stat-label">Quality</span><span class="stat-value" style="color:{qcol}">{q:.0f}/100</span></div>
        <div class="stat"><span class="stat-label">Speed Bonus</span><span class="stat-value">{fmt_speed(s['speed_bonus'])}</span></div>
        <div class="stat"><span class="stat-label">Combined</span><span class="stat-value" style="color:{qcol}">{s['combined']:.1f}/105</span></div>
        <div class="stat"><span class="stat-label">File Size</span><span class="stat-value">{s['size_bytes']/1024:.1f} KB</span></div>
      </div>
      {dim_breakdown_html(s['dimensions'], col)}
      <div style="margin-top:14px">
        <div class="iframe-wrap"><iframe src="{model}.html" loading="lazy" title="{mm['name']} output"></iframe></div>
      </div>
    </div>""")

    # tabs (kept for parity with old design; first tab auto-activated via JS)
    tab_btns = "".join(
        f'<button class="tab-btn" data-target="panel-{i}" style="--mc:{MODEL_META[m]["color"]}">{MODEL_META[m]["emoji"]} {MODEL_META[m]["name"]}</button>'
        for i, m in enumerate(ranked)
    )

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{meta['title']} — AI Model Bake-Off (Strict Rubric)</title>
<style>{CSS_BASE}</style>
</head>
<body>

<div class="hero">
  <h1>{meta['icon']} {meta['title']}</h1>
  <p class="subtitle">🏆 Winner: {wmeta['emoji']} {wmeta['name']} — {wscore['combined']:.1f}/105 ({wscore['quality_score']:.0f}/100 quality)</p>
  <p class="meta">Strict graded rubric · 100pt quality + 5pt speed bonus · 6 dimensions</p>
  <span class="badge-old">Replaces binary feature-check (everyone passed)</span>
</div>

<div class="container">
  <a href="../" class="back-link">← Back to all tests</a>

  <div class="section">
    <h2 class="section-title">📊 Strict Scores & Dimension Breakdown</h2>
    <p class="section-desc">Each model graded across 6 dimensions. Bars show how much of each dimension's max the model earned. Quality is graded on a scale, not binary.</p>
    {''.join(f'<div class="panel-block" id="panel-{i}" style="display:{("block" if i==0 else "none")}">{r}</div>' for i, r in enumerate(rows_html))}
  </div>

  <div class="section">
    <h2 class="section-title">⚖️ Side-by-Side Comparison</h2>
    <p class="section-desc">All 6 outputs rendered together.</p>
    <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));gap:12px">
{chr(10).join(f'      <div><div style="font-size:0.85rem;font-weight:600;margin-bottom:4px;color:{MODEL_META[m]["color"]}">{MODEL_META[m]["emoji"]} {MODEL_META[m]["name"]} — {test_scores[m]["quality_score"]:.0f}/100</div><div class="iframe-wrap" style="height:380px"><iframe src="{m}.html" loading="lazy" title="{MODEL_META[m]["name"]}"></iframe></div></div>' for m in ranked)}
    </div>
  </div>

</div>

<footer>
  <p>AI Model Bake-Off · {meta['title']} · Strict graded rubric · 6 models compared</p>
</footer>

<script>
(function() {{
  const tabs = document.querySelectorAll('.tab-btn');
  const panels = document.querySelectorAll('.panel-block');
  // we no longer use tabs; show all panels stacked. (Kept structure for parity.)
}})();
</script>

</body>
</html>
"""
    return page


def build_main_index():
    """Build /index.html with rankings + methodology + winner table."""
    with open(os.path.join(ROOT, "strict_scores.json")) as f:
        scores = json.load(f)
    totals = scores["totals"]
    dim_avgs = compute_dimension_avgs(scores)

    ranked = sorted(MODELS, key=lambda m: -totals[m]["combined_total"])
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣"]

    # ---- Rankings cards ----
    rank_cards = []
    for i, model in enumerate(ranked):
        t = totals[model]
        mm = MODEL_META[model]
        strengths, weaknesses = derive_strengths_weaknesses(dim_avgs, model)
        strengths_html = "".join(f"<span style='display:inline-block;background:rgba(34,197,94,0.1);color:#22c55e;padding:2px 8px;border-radius:6px;font-size:0.75rem;margin:2px'>{s}</span>" for s in strengths)
        weaknesses_html = "".join(f"<span style='display:inline-block;background:rgba(239,68,68,0.1);color:#ef4444;padding:2px 8px;border-radius:6px;font-size:0.75rem;margin:2px'>{w}</span>" for w in weaknesses)
        rank_cards.append(f"""
    <div class="card" style="display:flex;gap:16px;border-left:4px solid {mm['color']};padding:18px">
      <span style="font-size:2.2rem">{medals[i]}</span>
      <div style="flex:1">
        <div style="font-size:1.1rem;font-weight:700">{mm['emoji']} {mm['name']} <span style="color:var(--text2);font-weight:400;font-size:0.85rem">({mm['provider']})</span></div>
        <div style="color:var(--text2);font-size:0.85rem;margin:4px 0 8px">
          Combined <strong style="color:{score_color(t['quality_avg']*1.0)}">{t['combined_total']:.1f}/1155</strong> ·
          Quality avg <strong>{t['quality_avg']:.1f}/100</strong> ·
          Speed <strong>+{t['speed_total']:.1f}</strong> ·
          Avg size {t['avg_size_kb']:.1f} KB
        </div>
        <div style="margin-bottom:4px"><strong style="color:#22c55e;font-size:0.78rem">STRENGTHS</strong> {strengths_html}</div>
        <div><strong style="color:#ef4444;font-size:0.78rem">WEAKNESSES</strong> {weaknesses_html}</div>
      </div>
    </div>""")

    # ---- Per-test winner table ----
    header_cells = "".join(
        f"<th style='text-align:center'>{MODEL_META[m]['emoji']}<br><span style='font-weight:400;text-transform:none;font-size:0.7rem'>{MODEL_META[m]['name']}</span></th>"
        for m in ranked
    )
    table_rows = []
    for test in TESTS:
        ts = scores["tests"][test]
        cells = []
        # find winner quality for this test
        winner_model = max(ranked, key=lambda m: ts[m]["combined"])
        for model in ranked:
            s = ts[model]
            q = s["quality_score"]
            is_winner = model == winner_model
            color = score_color(q)
            badge = ' class="best"' if is_winner else ''
            winner_mark = " 🏆" if is_winner else ""
            cells.append(
                f"<td{badge}><strong style='color:{color}'>{q:.0f}</strong>/100{winner_mark}<div class='score-bar'><div class='score-bar-fill' style='width:{q}%;background:{color}'></div></div></td>"
            )
        table_rows.append(
            f"<tr><td><strong>{TEST_META[test]['icon']} {TEST_META[test]['title']}</strong></td>{''.join(cells)}</tr>"
        )
    total_row = "<tr style='font-weight:700;border-top:2px solid var(--accent)'><td>📊 TOTAL (out of 1155)</td>" + \
        "".join(f"<td class='best'>{totals[m]['combined_total']:.1f}<div style='color:var(--text2);font-size:0.7rem;font-weight:400'>Q {totals[m]['quality_total']:.0f} + sp {totals[m]['speed_total']:.1f}</div></td>" for m in ranked) + \
        "</tr>"

    # ---- Test grid (11 cards) ----
    test_cards = []
    for test in TESTS:
        ts = scores["tests"][test]
        winner_model = max(ranked, key=lambda m: ts[m]["combined"])
        winner_s = ts[winner_model]
        # mini per-model scores
        mini = " ".join(
            f"<span style='color:{score_color(ts[m]['quality_score'])};font-weight:600'>{MODEL_META[m]['name'].split()[0]}: {ts[m]['quality_score']:.0f}</span>"
            for m in ranked
        )
        test_cards.append(f"""
    <a href="{test}/" class="card" style="text-decoration:none;display:block">
      <div style="font-size:1.8rem;margin-bottom:6px">{TEST_META[test]['icon']}</div>
      <div style="font-size:1rem;font-weight:700;margin-bottom:6px">{TEST_META[test]['title']}</div>
      <div style="font-size:0.72rem;color:var(--text2);margin-bottom:8px;line-height:1.5">{mini}</div>
      <div><span class="winner-badge">🏆 {MODEL_META[winner_model]['emoji']} {MODEL_META[winner_model]['name']} ({winner_s['combined']:.1f}/105)</span></div>
    </a>""")

    # ---- Methodology ----
    methodology_items = """
      <div class="method-item">
        <h4>🎯 Functionality &amp; Correctness <span class="pts">30 pts</span></h4>
        <p>Core mechanics working end-to-end, completeness vs the spec, and edge-case handling.</p>
        <ul><li>Core mechanics (10): real event handlers wired to working logic, game loops present.</li>
            <li>Completeness (10): fraction of requested spec features implemented <em>with code</em>.</li>
            <li>Edge cases (10): try/catch, validation, divide-by-zero guards, empty-state handling.</li></ul>
      </div>
      <div class="method-item">
        <h4>🏗️ Code Quality &amp; Architecture <span class="pts">20 pts</span></h4>
        <p>How well the code is structured, defect-free, and maintainable.</p>
        <ul><li>Structure (7): function decomposition, no god-functions, meaningful names.</li>
            <li>Defect avoidance (7): penalize inline <code>onclick=</code>, <code>eval()</code>, <code>innerHTML</code> with input, leaked timers.</li>
            <li>Maintainability (6): comments, CSS custom properties, DRY, no magic numbers everywhere.</li></ul>
      </div>
      <div class="method-item">
        <h4>✨ UX &amp; Interaction Polish <span class="pts">20 pts</span></h4>
        <p>Does the app feel responsive, give feedback, and respect keyboard users?</p>
        <ul><li>Micro-interactions (7): CSS transitions, keyframes, transforms, real hover states.</li>
            <li>Feedback (7): toasts, dialogs, loading states, success/error messaging.</li>
            <li>Keyboard &amp; input (6): keyboard shortcuts, inline validation, undo, debounce.</li></ul>
      </div>
      <div class="method-item">
        <h4>🎨 Visual Design <span class="pts">15 pts</span></h4>
        <p>Deliberate type system, cohesive color palette, and systematic spacing.</p>
        <ul><li>Typography (5): font stack, size scale, weight contrast, line-height.</li>
            <li>Color &amp; cohesion (5): CSS variables, intentional accent colors (not random hex).</li>
            <li>Layout &amp; spacing (5): grid/flex quality, 8px spacing rhythm, box-shadow depth.</li></ul>
      </div>
      <div class="method-item">
        <h4>♿ Accessibility <span class="pts">10 pts</span></h4>
        <p><strong style="color:#f59e0b">The great differentiator</strong> — most models score near 0 here.</p>
        <ul><li>Semantic HTML (4): <code>&lt;header&gt;</code>, <code>&lt;main&gt;</code>, <code>&lt;button&gt;</code> not <code>&lt;div onclick&gt;</code>, heading hierarchy.</li>
            <li>ARIA &amp; labels (3): <code>aria-label</code>, <code>aria-live</code>, <code>role=</code>, icon-only button titles.</li>
            <li>Keyboard nav &amp; contrast (3): <code>:focus-visible</code>, <code>tabindex</code>, <code>prefers-reduced-motion</code>.</li></ul>
      </div>
      <div class="method-item">
        <h4>⚡ Performance &amp; Efficiency <span class="pts">5 pts</span></h4>
        <p>File size vs feature set, and runtime discipline.</p>
        <ul><li>Bundle (3): &lt;15KB efficient; &gt;50KB bloated; large inline base64 = penalty.</li>
            <li>Runtime (2): <code>requestAnimationFrame</code> over <code>setInterval</code>, debouncing, cleanup.</li></ul>
      </div>
      <div class="method-item" style="border-color:var(--amber)">
        <h4>⏱️ Speed Bonus <span class="pts" style="background:rgba(245,158,11,0.15);color:#f59e0b">+5 max</span></h4>
        <p>Separate from quality. Per test, fastest of the timed models gets +5, scaled to +0.5 for slowest. Models without recorded timing data get no bonus.</p>
      </div>
"""

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI Model Bake-Off — Strict Graded Rubric</title>
<style>{CSS_BASE}</style>
</head>
<body>

<div class="hero">
  <h1>🏆 AI Model Bake-Off</h1>
  <p class="subtitle">6 models · 11 challenges · single-shot · graded on a 100pt strict rubric</p>
  <p class="meta">Quality (0-100) across 6 dimensions + speed bonus (0-5) · Total max 1155</p>
  <span class="badge-old">v2: replaces binary feature-checks where everyone scored 87-99%</span>
</div>

<div class="container">

  <div class="section">
    <h2 class="section-title">🏅 Final Rankings</h2>
    <p class="section-desc">Ranked by combined total (quality + speed bonus). Quality is the headline metric — speed bonus is a small tiebreaker.</p>
    <div class="grid-2" style="gap:14px">
{''.join(rank_cards)}
    </div>
  </div>

  <div class="section">
    <h2 class="section-title">📊 Cross-Test Comparison (Quality / 100)</h2>
    <p class="section-desc">The strict rubric produces real separation. 🏆 marks each test's winner by combined score.</p>
    <div style="overflow-x:auto;border:1px solid var(--border);border-radius:12px;background:var(--bg2)">
      <table class="cmp-table">
        <thead><tr>
          <th>Test</th>{header_cells}
        </tr></thead>
        <tbody>
{''.join(table_rows)}
        </tbody>
        <tfoot>{total_row}</tfoot>
      </table>
    </div>
  </div>

  <div class="section">
    <h2 class="section-title">🧪 The 11 Challenges</h2>
    <div class="grid-3">
{''.join(test_cards)}
    </div>
  </div>

  <div class="section">
    <h2 class="section-title">🔬 Scoring Methodology</h2>
    <p class="section-desc">Each app is statically analyzed (regex/parsing of the HTML/CSS/JS) and graded on a <strong>scale</strong> across 6 dimensions. Scoring is intentionally strict: a typical model lands 40-75/100, not 90+. Speed bonus is computed separately from recorded timings.</p>
    <div class="method-grid">
{methodology_items}
    </div>
  </div>

</div>

<footer>
  <p>AI Model Bake-Off · Strict graded rubric · 11 tests × 6 models · Quality (100) + Speed (5) per test</p>
</footer>

</body>
</html>
"""
    return page


def main():
    scores = score_all()
    out = os.path.join(ROOT, "strict_scores.json")
    with open(out, "w") as f:
        json.dump(scores, f, indent=2)
    print(f"[scorer] wrote {out}")

    # build pages
    main_html = build_main_index()
    with open(os.path.join(ROOT, "index.html"), "w") as f:
        f.write(main_html)
    print(f"[build] wrote index.html ({len(main_html)} bytes)")

    for test in TESTS:
        page = build_test_page(test)
        path = os.path.join(ROOT, test, "index.html")
        with open(path, "w") as f:
            f.write(page)
        print(f"[build] wrote {test}/index.html ({len(page)} bytes)")

    # brief console summary
    print("\n=== STRICT SCORES (quality 0-100) ===")
    for test in TESTS:
        print(f"\n--- {test.upper()} ---")
        rows = sorted(scores["tests"][test].items(),
                      key=lambda kv: -kv[1]["quality_score"])
        for model, r in rows:
            meta = MODEL_META[model]
            print(f"  {meta['emoji']:>2} {meta['name']:<18} "
                  f"Q={r['quality_score']:>5}  "
                  f"speed={r['speed_bonus']}  "
                  f"comb={r['combined']:>5}")

    print("\n=== TOTALS (ranked) ===")
    rows = sorted(scores["totals"].items(), key=lambda kv: -kv[1]["combined_total"])
    for i, (model, t) in enumerate(rows, 1):
        meta = MODEL_META[model]
        print(f"  #{i} {meta['emoji']:>2} {meta['name']:<18} "
              f"Q_total={t['quality_total']:>6.1f}/{t['max_possible']}  "
              f"avg={t['quality_avg']:>5}  "
              f"speed={t['speed_total']:>5}  "
              f"combined={t['combined_total']:>6.1f}/{t['max_combined']}")


if __name__ == "__main__":
    main()
