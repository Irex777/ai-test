#!/usr/bin/env python3
"""
browser_tests.py — Real headless-Chromium functional testing of AI-generated HTML apps.

For each (test, model) it loads {test}/{model}.html in a real headless Chromium browser
and exercises actual functionality: clicking buttons, typing text, playing games,
submitting forms. This differentiates models by whether their apps actually WORK, not
by how the source code looks.

Output:
  /tmp/ai-test/browser_results.json   — per (test,model) detailed scores
  /tmp/ai-test/screenshots/*.png      — a screenshot of each app after testing
  stdout                              — per-file progress + per-model summary
"""

import os
import re
import json
import time
import traceback
from playwright.sync_api import sync_playwright

ROOT = "/tmp/ai-test"
SHOTS = os.path.join(ROOT, "screenshots")
MODELS = ["sonnet", "opus", "glm", "glm52", "ornith"]
TESTS = ["kanban", "dashboard", "chess", "markdown", "calculator",
         "snake", "pomodoro", "weather", "password", "gta", "webos"]

os.makedirs(SHOTS, exist_ok=True)


# --------------------------------------------------------------------------- #
# Generic helpers
# --------------------------------------------------------------------------- #
def check(name, fn):
    """Run a check; one failure never propagates. Returns a result dict."""
    try:
        return {"name": name, "pass": bool(fn()), "error": None}
    except Exception as e:  # noqa: BLE001
        return {"name": name, "pass": False, "error": str(e)[:120]}


def ev(page, js, arg=None):
    """page.evaluate wrapper that tolerates no-arg JS."""
    if arg is None:
        return page.evaluate(js)
    return page.evaluate(js, arg)


def sel_contains(keywords):
    """Build a CSS selector that matches class/id *containing* any keyword (case-insensitive)."""
    parts = []
    for kw in keywords:
        for attr in ("class", "id"):
            parts.append(f'[{attr}*="{kw}" i]')
    return ",".join(parts)


def count_attr(page, keywords):
    sel = sel_contains(keywords)
    try:
        return len(page.query_selector_all(sel))
    except Exception:
        return 0


def has_any_text(page, texts):
    body = ev(page, "() => (document.body.innerText||'').toLowerCase()")
    return any(t.lower() in body for t in texts)


def read_value(page, keywords):
    """Read first non-empty text/value from an element whose class/id matches a keyword."""
    sel = sel_contains(keywords)
    try:
        els = page.query_selector_all(sel)
    except Exception:
        els = []
    for el in els:
        try:
            tag = el.evaluate("e => (e.tagName||'').toLowerCase()")
            if tag in ("input", "textarea"):
                v = el.get_attribute("value") or ""
                if v.strip():
                    return v.strip()
            t = el.inner_text()
            if t and t.strip():
                return t.strip()
        except Exception:
            continue
    return ""


def is_dark(page):
    """True if the body / html background is dark (low luminance)."""
    return bool(ev(page, r"""() => {
        const el = document.body || document.documentElement;
        const bg = window.getComputedStyle(el).backgroundColor;
        const m = bg.match(/\d+/g);
        if (!m || m.length < 3) {
            // fall back to background-color of html
            const bg2 = window.getComputedStyle(document.documentElement).backgroundColor;
            const m2 = bg2.match(/\d+/g);
            if (!m2 || m2.length < 3) return false;
            const [r,g,b] = m2.map(Number);
            return (r*0.299 + g*0.587 + b*0.114) < 128;
        }
        const [r,g,b] = m.map(Number);
        return (r*0.299 + g*0.587 + b*0.114) < 128;
    }"""))


def canvas_content(page, sel="canvas"):
    """True if a canvas has visibly drawn (non-transparent / non-black or non-blank) pixels."""
    return bool(ev(page, r"""(sel) => {
        const c = document.querySelector(sel);
        if (!c) return false;
        const ctx = c.getContext ? c.getContext('2d') : null;
        if (!ctx) return false;
        const w = Math.max(1, c.width), h = Math.max(1, c.height);
        try {
            const d = ctx.getImageData(0, 0, w, h).data;
            let n = 0;
            for (let i = 0; i < d.length; i += 4) {
                if (d[i] !== 0 || d[i+1] !== 0 || d[i+2] !== 0 || d[i+3] !== 0) {
                    n++;
                    if (n > 12) return true;
                }
            }
            return n > 0;
        } catch (e) { return false; }
    }""", sel))


def canvas_density(page, sel="canvas"):
    """Fraction (0..1) of non-transparent pixels on a canvas, for richer-content checks."""
    return ev(page, r"""(sel) => {
        const c = document.querySelector(sel);
        if (!c) return 0;
        const ctx = c.getContext ? c.getContext('2d') : null;
        if (!ctx) return 0;
        const w = Math.max(1, c.width), h = Math.max(1, c.height);
        try {
            const d = ctx.getImageData(0, 0, w, h).data;
            let n = 0, total = 0;
            for (let i = 0; i < d.length; i += 4) {
                total++;
                if (d[i] !== 0 || d[i+1] !== 0 || d[i+2] !== 0 || d[i+3] !== 0) n++;
            }
            return total ? n / total : 0;
        } catch (e) { return 0; }
    }""", sel)


def click_el(handle, timeout=5000):
    """Click a JSHandle/ElementHandle, falling back to force-click."""
    el = handle.as_element() if hasattr(handle, "as_element") else handle
    if not el:
        return False
    try:
        el.click(timeout=timeout)
        return True
    except Exception:
        try:
            el.click(force=True, timeout=timeout)
            return True
        except Exception:
            return False


def find_and_click(page, texts, timeout=5000):
    """Find a visible clickable element whose label matches one of `texts` (exact preferred) and click it."""
    if isinstance(texts, str):
        texts = [texts]
    for t in texts:
        handle = page.evaluate_handle(r"""(t) => {
            const want = t.toLowerCase();
            const sels = 'button, [role=button], a, .btn, .button, input[type=button], input[type=submit], [onclick], summary, [class*=btn i]';
            const cands = Array.from(document.querySelectorAll(sels));
            // 1) exact label
            for (const el of cands) {
                const txt = (el.innerText || el.textContent || el.value || '').trim().toLowerCase();
                if (txt && txt === want) {
                    const r = el.getBoundingClientRect();
                    if (r.width > 0 && r.height > 0) return el;
                }
            }
            // 2) contains label (skip very generic single chars handled later)
            for (const el of cands) {
                const txt = (el.innerText || el.textContent || el.value || '').trim().toLowerCase();
                if (txt && txt.includes(want)) {
                    const r = el.getBoundingClientRect();
                    if (r.width > 0 && r.height > 0) return el;
                }
            }
            // 3) title/aria-label match
            for (const el of cands) {
                const al = (el.getAttribute('aria-label') || el.getAttribute('title') || '').trim().toLowerCase();
                if (al && al.includes(want)) {
                    const r = el.getBoundingClientRect();
                    if (r.width > 0 && r.height > 0) return el;
                }
            }
            return null;
        }""", t)
        if click_el(handle, timeout):
            return True
    return False


def find_and_fill(page, text, prefer_keywords=None):
    """Find a text input/textarea and fill it.

    When `prefer_keywords` is given, inputs whose id/class/placeholder/aria-label
    contains one of those keywords are preferred over a generic first match — this
    matters for apps where the first visible input is a search box rather than the
    intended field (e.g. a kanban's task-title input hidden inside an add-task modal).
    Returns True on success.
    """
    handle = page.evaluate_handle(r"""(kw) => {
        const sels = 'textarea, input[type=text], input:not([type]), input[type=search], [contenteditable=true]';
        const cands = Array.from(document.querySelectorAll(sels));
        const vis = cands.filter(el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; });
        const sig = (el) => (((el.id||'') + ' ' + (el.className||'') + ' ' +
                              (el.placeholder||'') + ' ' + (el.getAttribute('aria-label')||'')).toLowerCase());
        const scored = (el) => (kw && kw.length) ? (kw.some(k => sig(el).includes(k)) ? 1 : 0) : 0;
        // 1) visible + keyword match
        if (kw && kw.length) {
            const hit = vis.filter(el => scored(el));
            if (hit.length) return hit[0];
        }
        // 2) any visible input
        if (vis.length) return vis[0];
        // 3) hidden keyword match (modal may need opening first)
        if (kw && kw.length) {
            const hit = cands.filter(el => scored(el));
            if (hit.length) return hit[0];
        }
        return cands[0] || null;
    }""", prefer_keywords or [])
    el = handle.as_element() if handle else None
    if not el:
        return False
    try:
        tag = el.evaluate("e => (e.tagName||'').toLowerCase()")
        if tag in ("input", "textarea"):
            el.fill(text)
        else:  # contenteditable
            el.click()
            page.keyboard.press("Control+a")
            page.keyboard.press("Delete")
            page.keyboard.type(text)
        return True
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# Per-test functional check suites
# --------------------------------------------------------------------------- #
def test_kanban(page, errors):
    c = [check("Page loads without JS errors", lambda: len(errors) == 0)]

    def cols():
        return ev(page, r"""() => {
            const sels = '[class*=column i],[class*=board i],[class*=lane i],[class*=list i],[id*=column i],[id*=board i],[id*=lane i]';
            const els = document.querySelectorAll(sels);
            if (els.length >= 3) return true;
            // a board container with >=3 children counts too
            const b = document.querySelector('[class*=board i],[id*=board i]');
            return !!(b && b.children.length >= 3);
        }""")
    c.append(check("Board/columns visible (>=3)", cols))

    def add_input_exists():
        return bool(page.query_selector(
            "input[type=text], input:not([type]), input[type=search], textarea, [contenteditable=true]"))
    c.append(check("Add-task input/area exists", add_input_exists))

    def add_task():
        # Many kanban apps open a modal/form when you click "Add Task", with the
        # title input hidden until then. Open it, fill the title field by keyword,
        # then submit.
        find_and_click(page, ["add task", "new task", "create task", "add", "new", "+"])
        page.wait_for_timeout(700)
        if not find_and_fill(page, "Test Task XYZ",
                             prefer_keywords=["task", "title", "name", "subject", "todo", "add", "new"]):
            return False
        page.wait_for_timeout(300)
        if not find_and_click(page, ["save task", "save", "add task", "add", "create", "submit", "confirm", "ok"]):
            page.keyboard.press("Enter")
        page.wait_for_timeout(800)
        return "test task xyz".lower() in ev(
            page, "() => (document.body.innerText||'').toLowerCase()")
    c.append(check("Type 'Test Task' and submit it", add_task))

    def task_appears():
        return "test task xyz".lower() in ev(
            page, "() => (document.body.innerText||'').toLowerCase()")
    c.append(check("Added task text appears in DOM", task_appears))

    def ls_used():
        try:
            data = ev(page, "() => { try { return JSON.stringify(window.localStorage); } catch(e){ return ''; } }")
            return bool(data) and data.strip() not in ("{}", "")
        except Exception:
            return False
    c.append(check("localStorage stores board data", ls_used))

    def priority():
        return (count_attr(page, ["priority"]) >= 1
                or has_any_text(page, ["high", "medium", "low", "urgent", "p1", "p2", "p3"]))
    c.append(check("Priority controls exist", priority))

    def del_btn():
        return (count_attr(page, ["delete", "remove", "close", "trash"]) >= 1
                or has_any_text(page, ["delete", "remove", "×", "✕", "clear"]))
    c.append(check("Delete control on tasks", del_btn))

    c.append(check("Dark theme", lambda: is_dark(page)))

    def count_disp():
        return (count_attr(page, ["count", "total", "counter", "badge", "stat"]) >= 1
                or bool(re.search(r"\d+\s*(tasks?|cards?|items?)", ev(
                    page, "() => (document.body.innerText||'')").lower())))
    c.append(check("Task count display exists", count_disp))
    return c


def test_dashboard(page, errors):
    c = [check("Page loads without JS errors", lambda: len(errors) == 0)]

    def cards():
        return count_attr(page, ["card", "kpi", "stat", "metric", "tile"]) >= 2
    c.append(check("KPI/stat cards exist (>=2)", cards))

    def numeric():
        txt = ev(page, "() => (document.body.innerText||'')")
        return bool(re.search(r"[$€£¥]|\d{2,}|\d+\s*%|\d+\s*k", txt))
    c.append(check("KPI cards show numeric content", numeric))

    def chart_el():
        return bool(page.query_selector("canvas, svg"))
    c.append(check("Chart element exists (canvas/svg)", chart_el))

    def chart_drawn():
        if page.query_selector("canvas"):
            return canvas_content(page, "canvas")
        return ev(page, r"""() => {
            const s = document.querySelector('svg');
            if (!s) return false;
            return s.querySelectorAll('path,rect,circle,line,polygon,polyline,ellipse,text,g,area').length > 1;
        }""")
    c.append(check("Chart has drawn content", chart_drawn))

    def feed():
        return ev(page, r"""() => {
            const lists = document.querySelectorAll('[class*=activity i],[class*=feed i],[class*=list i],[class*=recent i],[class*=transaction i],ul,tbody');
            for (const l of lists) {
                if (l.children.length >= 3) return true;
            }
            return false;
        }""")
    c.append(check("Activity feed/list with >=3 items", feed))

    c.append(check("Dark theme", lambda: is_dark(page)))

    def export_btn():
        return (find_and_click(page, ["export", "download", "csv", "pdf", "save"])
                or count_attr(page, ["export", "download"]) >= 1
                or has_any_text(page, ["export", "download"]))
    c.append(check("Export/download control exists", export_btn))

    def date_filter():
        return (count_attr(page, ["date", "filter", "search", "period", "range"]) >= 1
                or bool(page.query_selector("input[type=date], input[type=search], select")))
    c.append(check("Date/filter element exists", date_filter))

    def hover_effect():
        return ev(page, r"""() => {
            const cards = document.querySelectorAll('[class*=card i],[class*=stat i],[class*=kpi i],[class*=metric i],[class*=tile i]');
            for (const el of cards) {
                const cs = window.getComputedStyle(el);
                if (cs.transition && cs.transition !== 'all 0s ease 0s' && cs.transitionDelay.indexOf('0s') === 0 && cs.transition !== '') return true;
                if ((cs.transitionDuration && cs.transitionDuration !== '0s') ||
                    (cs.transform && cs.transform !== 'none') ||
                    (cs.boxShadow && cs.boxShadow !== 'none')) return true;
            }
            return false;
        }""")
    c.append(check("Cards have hover/transition styling", hover_effect))
    return c


def test_chess(page, errors):
    c = [check("Page loads without JS errors", lambda: len(errors) == 0)]

    def grid():
        return ev(page, r"""() => {
            const sq = document.querySelectorAll('[class*=square i],[class*=cell i],[class*=tile i],[class*=rank i],[class*=file i]');
            if (sq.length >= 32) return true;
            const tr = document.querySelectorAll('table tr,.board tr');
            if (tr.length >= 8) return true;
            if (document.querySelector('canvas')) return true;
            const b = document.querySelector('[class*=board i],[id*=board i]');
            return !!(b && b.children.length >= 32);
        }""")
    c.append(check("8x8 grid / 64 cells exist", grid))

    def pieces():
        return ev(page, r"""() => {
            const pc = '♔♕♖♗♘♙♚♛♜♝♞♟';
            const text = document.body.innerText || '';
            if ([...text].some(ch => pc.includes(ch))) return true;
            if (document.querySelectorAll('img[class*=piece i],img[src*=piece i],[class*=piece i]').length > 0) return true;
            const sq = document.querySelectorAll('[class*=square i],[class*=cell i],[class*=tile i]');
            let n = 0;
            for (const s of sq) { if ((s.innerText||'').trim()) n++; }
            return n >= 4;
        }""")
    c.append(check("Chess pieces visible", pieces))

    def click_feedback():
        before = ev(page, "() => (document.body.innerHTML||'').length")
        handle = page.evaluate_handle(r"""() => {
            const pc = '♔♕♖♗♘♙♚♛♜♝♞♟';
            const cands = Array.from(document.querySelectorAll(
              '[class*=piece i],[class*=square i],[class*=cell i],[class*=tile i],img[src*=piece i]'));
            for (const el of cands) {
                const t = el.innerText || '';
                if ([...t].some(ch => pc.includes(ch))) return el;
            }
            for (const el of cands) {
                const r = el.getBoundingClientRect();
                if (r.width > 0 && r.height > 0) return el;
            }
            return cands[0] || null;
        }""")
        if not click_el(handle):
            return False
        page.wait_for_timeout(500)
        after = ev(page, "() => (document.body.innerHTML||'').length")
        highlights = count_attr(page, ["highlight", "valid", "possible", "selected", "move", "hint"])
        return (after != before) or highlights > 0
    c.append(check("Clicking a piece gives visual feedback", click_feedback))

    def turn():
        return has_any_text(page, ["turn", "white", "black", "to move", "your move"])
    c.append(check("Turn indicator exists", turn))

    def new_game():
        return (count_attr(page, ["new", "reset", "restart"]) >= 1
                or has_any_text(page, ["new game", "reset", "restart", "new", "play again"]))
    c.append(check("New Game control exists", new_game))

    def captured():
        return (count_attr(page, ["captured", "taken", "graveyard", "dead"]) >= 1
                or has_any_text(page, ["captured", "taken pieces"]))
    c.append(check("Captured-pieces display exists", captured))

    def history():
        return (count_attr(page, ["history", "moves", "log", "notation", "movelist"]) >= 1
                or has_any_text(page, ["move history", "moves:", "history"]))
    c.append(check("Move-history area exists", history))

    c.append(check("Dark theme", lambda: is_dark(page)))

    def rendered():
        return ev(page, r"""() => {
            const b = document.querySelector('[class*=board i],[id*=board i],canvas,table');
            if (!b) return false;
            const r = b.getBoundingClientRect();
            return r.width > 100 && r.height > 100;
        }""")
    c.append(check("Board is properly rendered (non-zero size)", rendered))
    return c


def test_markdown(page, errors):
    c = [check("Page loads without JS errors", lambda: len(errors) == 0)]

    def editor():
        return bool(page.query_selector(
            "textarea, [contenteditable=true], [class*=editor i], [id*=editor i]"))
    c.append(check("Editor textarea/contenteditable exists", editor))

    def preview():
        return bool(page.query_selector(
            "[class*=preview i], [id*=preview i], [class*=output i], [class*=result i]"))
    c.append(check("Preview area exists", preview))

    def toolbar():
        return ev(page, r"""() => {
            const btns = Array.from(document.querySelectorAll('button,[role=button],.btn,[class*=btn i]'));
            let n = 0;
            for (const b of btns) {
                const t = (b.innerText||b.title||b.getAttribute('aria-label')||'').toLowerCase();
                if (/bold|italic|heading|link|strike|quote|list|code|image|h[1-6]/.test(t) || /<b>|<i>|B$|I$/.test((b.innerText||''))) n++;
            }
            return n >= 3;
        }""")
    c.append(check("Toolbar with >=3 formatting buttons", toolbar))

    def h1():
        if not find_and_fill(page, "# Hello"):
            return False
        page.wait_for_timeout(600)
        return ev(page, r"""() => {
            const p = document.querySelector('[class*=preview i],[id*=preview i],[class*=output i],[class*=result i]') || document.body;
            return !!(p.querySelector('h1') || /<h1/i.test(p.innerHTML) || /hello/i.test(p.innerText||''));
        }""")
    c.append(check("Typing '# Hello' renders an <h1>", h1))

    def bold():
        if not find_and_fill(page, "**bold**"):
            return False
        page.wait_for_timeout(600)
        return ev(page, r"""() => {
            const p = document.querySelector('[class*=preview i],[id*=preview i],[class*=output i],[class*=result i]') || document.body;
            return !!(p.querySelector('strong,b') || /<(strong|b)[>\s]/i.test(p.innerHTML));
        }""")
    c.append(check("Typing '**bold**' renders <strong>/<b>", bold))

    def wordcount():
        return (count_attr(page, ["word", "count", "char", "stats"]) >= 1
                or has_any_text(page, ["words", "characters", "chars"]))
    c.append(check("Word-count display exists", wordcount))

    def copy_btn():
        return (count_attr(page, ["copy"]) >= 1
                or has_any_text(page, ["copy", "clipboard"]))
    c.append(check("Copy button exists", copy_btn))

    c.append(check("Dark theme", lambda: is_dark(page)))

    def split_pane():
        return ev(page, r"""() => {
            const ed = document.querySelector('textarea,[contenteditable=true],[class*=editor i],[id*=editor i]');
            const pv = document.querySelector('[class*=preview i],[id*=preview i],[class*=output i]');
            if (!ed || !pv) return false;
            const a = ed.getBoundingClientRect();
            const b = pv.getBoundingClientRect();
            const side = Math.abs(a.left - b.left) > 80 || Math.abs(a.right - b.right) > 80;
            const stacked = Math.abs(a.top - b.top) > 80;
            return side || stacked;
        }""")
    c.append(check("Split-pane layout (editor + preview)", split_pane))
    return c


def test_calculator(page, errors):
    c = [check("Page loads without JS errors", lambda: len(errors) == 0)]

    def display():
        return read_value(page, ["display", "screen", "result", "output"]) != "" or \
            count_attr(page, ["display", "screen", "result"]) >= 1
    c.append(check("Display element exists", display))

    def digits():
        return ev(page, r"""() => {
            const els = Array.from(document.querySelectorAll('button,[role=button],.btn,.key,[class*=key i],td,div'));
            const set = new Set();
            for (const el of els) { const t = (el.innerText||'').trim(); if (/^[0-9]$/.test(t)) set.add(t); }
            return set.size >= 8;
        }""")
    c.append(check("Number buttons 0-9 exist", digits))

    def operators():
        return ev(page, r"""() => {
            const els = Array.from(document.querySelectorAll('button,[role=button],.btn,.key,[class*=key i],td,div'));
            const ops = new Set();
            for (const el of els) {
                const t = (el.innerText||'').trim();
                if (['+','-','×','÷','*','/','x','X'].includes(t)) ops.add(t);
            }
            return ops.size >= 3;
        }""")
    c.append(check("Operator buttons (+,-,*,/) exist", operators))

    def compute():
        for t in ["AC", "C", "CE", "Clear", "clr"]:
            if find_and_click(page, t):
                break
        page.wait_for_timeout(200)
        find_and_click(page, "5"); page.wait_for_timeout(150)
        find_and_click(page, ["+"]); page.wait_for_timeout(150)
        find_and_click(page, "3"); page.wait_for_timeout(150)
        find_and_click(page, ["=", "equals"]); page.wait_for_timeout(400)
        disp = read_value(page, ["display", "screen", "result", "output"])
        disp = re.sub(r"[^\d.]", "", disp)
        try:
            return abs(float(disp) - 8.0) < 0.001
        except Exception:
            return False
    c.append(check("5 + 3 = yields 8", compute))

    def clear_btn():
        return (count_attr(page, ["clear", "reset", "ac"]) >= 1
                or has_any_text(page, ["ac", "clear", "c", "ce", "reset"]))
    c.append(check("Clear/AC button exists", clear_btn))

    def decimal():
        return ev(page, r"""() => {
            const els = Array.from(document.querySelectorAll('button,[role=button],.btn,.key,[class*=key i]'));
            for (const el of els) if ((el.innerText||'').trim() === '.') return true;
            return false;
        }""")
    c.append(check("Decimal-point button exists", decimal))

    def keyboard():
        try:
            page.click("body")
        except Exception:
            pass
        page.keyboard.type("5+3=")
        page.wait_for_timeout(300)
        disp = read_value(page, ["display", "screen", "result", "output"])
        ok = "8" in disp
        if not ok:
            page.keyboard.press("Enter")
            page.wait_for_timeout(300)
            disp = read_value(page, ["display", "screen", "result", "output"])
            ok = "8" in disp
        return ok
    c.append(check("Keyboard support (type 5+3=)", keyboard))

    def div_zero():
        for t in ["AC", "C", "CE", "Clear"]:
            if find_and_click(page, t):
                break
        page.wait_for_timeout(200)
        find_and_click(page, "5"); page.wait_for_timeout(120)
        find_and_click(page, ["÷", "/", "*"]); page.wait_for_timeout(120)
        find_and_click(page, "0"); page.wait_for_timeout(120)
        find_and_click(page, ["=", "equals"]); page.wait_for_timeout(400)
        disp = read_value(page, ["display", "screen", "result", "output"]).lower()
        return any(k in disp for k in ["error", "inf", "nan", "∞", "infinity", "cannot"])
    c.append(check("Divide-by-zero shows error (not crash)", div_zero))

    c.append(check("Dark theme", lambda: is_dark(page)))
    return c


def test_snake(page, errors):
    c = [check("Page loads without JS errors", lambda: len(errors) == 0)]

    def canvas():
        return bool(page.query_selector("canvas"))
    c.append(check("Canvas element exists", canvas))

    def canvas_drawn():
        return canvas_content(page, "canvas")
    c.append(check("Canvas has drawn content", canvas_drawn))

    def score():
        return (count_attr(page, ["score"]) >= 1
                or has_any_text(page, ["score"]))
    c.append(check("Score display exists", score))

    def arrows():
        before = errors[:] if False else None
        for k in ["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"]:
            try:
                page.keyboard.press(k)
            except Exception:
                return False
            page.wait_for_timeout(80)
        return True
    c.append(check("Arrow-key handler works (no crash)", arrows))

    def start():
        return (count_attr(page, ["start", "restart", "play"]) >= 1
                or has_any_text(page, ["start", "play", "restart", "press", "game over", "space"]))
    c.append(check("Start/restart control or start screen exists", start))

    def bounds():
        return ev(page, r"""() => {
            const cv = document.querySelector('canvas');
            if (cv) { const r = cv.getBoundingClientRect(); return r.width > 100 && r.height > 100; }
            const area = document.querySelector('[class*=board i],[class*=game i],[class*=area i],[id*=game i]');
            if (area) { const r = area.getBoundingClientRect(); return r.width > 100 && r.height > 100; }
            return false;
        }""")
    c.append(check("Game area has visible boundaries", bounds))

    c.append(check("Dark theme", lambda: is_dark(page)))

    def food():
        # press arrows, then check canvas still has content (food/snake redrawn) and density
        for k in ["ArrowUp", "ArrowRight"]:
            try:
                page.keyboard.press(k)
            except Exception:
                pass
            page.wait_for_timeout(120)
        d = canvas_density(page, "canvas")
        return d > 0.0 and canvas_content(page, "canvas")
    c.append(check("Food/snake present after key press", food))

    def ls_high():
        try:
            data = ev(page, "() => { try { return JSON.stringify(window.localStorage); } catch(e){ return ''; } }")
            if data and data.strip() not in ("{}", ""):
                return True
        except Exception:
            pass
        # fallback: code/UI references high score
        return has_any_text(page, ["high score", "highscore", "best"])
    c.append(check("localStorage for high score", ls_high))
    return c


def test_pomodoro(page, errors):
    c = [check("Page loads without JS errors", lambda: len(errors) == 0)]

    def timer_text():
        t = read_value(page, ["timer", "time", "clock", "display", "countdown"])
        return bool(re.search(r"\d{1,2}:\d{2}|^\d{1,3}$|\d+\s*s", t))
    c.append(check("Timer display shows time", timer_text))

    def start_btn():
        return (count_attr(page, ["start", "pause", "play", "control"]) >= 1
                or has_any_text(page, ["start", "pause", "play", "begin", "▶"]))
    c.append(check("Start/Pause button exists", start_btn))

    def progress():
        return bool(page.query_selector("svg circle, svg, canvas"))
    c.append(check("Circular progress (svg/canvas)", progress))

    def modes():
        return (count_attr(page, ["mode", "work", "break", "short", "long"]) >= 1
                or has_any_text(page, ["work", "short break", "long break", "focus", "25", "5", "15"]))
    c.append(check("Mode buttons exist (Work/Break)", modes))

    def decrement():
        before = read_value(page, ["timer", "time", "clock", "display", "countdown"])

        def to_sec(s):
            s2 = re.sub(r"[^\d:]", "", s)
            parts = [p for p in s2.split(":") if p != ""]
            try:
                nums = [int(p) for p in parts]
                if len(nums) == 2:
                    return nums[0] * 60 + nums[1]
                if len(nums) == 1:
                    return nums[0]
            except Exception:
                return None
            return None

        b = to_sec(before)
        find_and_click(page, ["start", "begin", "play", "▶", "resume"])
        page.wait_for_timeout(2500)
        after = read_value(page, ["timer", "time", "clock", "display", "countdown"])
        a = to_sec(after)
        if b is not None and a is not None:
            return a < b
        return before != after
    c.append(check("Start -> timer decrements after 2s", decrement))

    def session():
        return (count_attr(page, ["session", "count", "cycle", "pomodoro"]) >= 1
                or has_any_text(page, ["session", "cycle", "completed", "round"]))
    c.append(check("Session counter exists", session))

    def settings():
        return (count_attr(page, ["setting", "config", "option", "duration", "customize"]) >= 1
                or has_any_text(page, ["settings", "customize", "duration", "minutes"]))
    c.append(check("Settings/customization controls exist", settings))

    c.append(check("Dark theme", lambda: is_dark(page)))

    def audio():
        return ev(page, r"""() => {
            return !!(window.AudioContext || window.webkitAudioContext || document.querySelector('audio'));
        }""")
    c.append(check("Web Audio API / audio element referenced", audio))
    return c


def test_weather(page, errors):
    c = [check("Page loads without JS errors", lambda: len(errors) == 0)]

    def temp():
        txt = ev(page, "() => (document.body.innerText||'')")
        return bool(re.search(r"-?\d+\s*°|-?\d+\s*(c|f)|temp", txt, re.I))
    c.append(check("Current temperature displayed", temp))

    def humidity_wind():
        txt = ev(page, "() => (document.body.innerText||'').toLowerCase()")
        return ("humidity" in txt) or ("wind" in txt) or ("%" in txt and "km" in txt) or ("mph" in txt)
    c.append(check("Humidity/wind info displayed", humidity_wind))

    def forecast():
        return ev(page, r"""() => {
            const els = document.querySelectorAll('[class*=forecast i],[class*=day i],[class*=card i],[class*=hour i],[class*=daily i]');
            if (els.length >= 3) return true;
            // table rows
            const rows = document.querySelectorAll('table tr, tbody tr');
            return rows.length >= 3;
        }""")
    c.append(check("Forecast row with >=3 items", forecast))

    def chart():
        return bool(page.query_selector("canvas, svg"))
    c.append(check("Temperature chart (svg/canvas)", chart))

    def toggle():
        return (count_attr(page, ["toggle", "unit", "switch"]) >= 1
                or has_any_text(page, ["°c", "°f", "celsius", "fahrenheit", "c/f", "°c / °f"]))
    c.append(check("C/F toggle button exists", toggle))

    def toggle_works():
        before = read_value(page, ["temp", "temperature", "degree"])
        before_body = ev(page, "() => (document.body.innerText||'')")
        clicked = find_and_click(page, ["°f", "°c", "fahrenheit", "celsius", "°c / °f", "c/f", "toggle", "switch", "unit"])
        page.wait_for_timeout(900)
        after = read_value(page, ["temp", "temperature", "degree"])
        after_body = ev(page, "() => (document.body.innerText||'')")
        return clicked and (before != after or before_body != after_body)
    c.append(check("Toggle changes temperature value", toggle_works))

    def icon():
        return ev(page, r"""() => {
            const text = document.body.innerText || '';
            const emojis = '☀☁⛅🌤🌧⛈🌩❄🌫🌪🌊🌞🌡';
            if ([...text].some(ch => emojis.includes(ch))) return true;
            return document.querySelectorAll('svg,img[class*=icon i],[class*=icon i],[class*=weather i]').length > 0;
        }""")
    c.append(check("Weather condition icon/visual", icon))

    c.append(check("Dark theme", lambda: is_dark(page)))

    def sun_times():
        return (has_any_text(page, ["sunrise", "sunset", "dawn", "dusk"])
                or count_attr(page, ["sunrise", "sunset", "sun"]) >= 1)
    c.append(check("Sunrise/sunset times displayed", sun_times))
    return c


def test_password(page, errors):
    c = [check("Page loads without JS errors", lambda: len(errors) == 0)]

    def slider():
        return bool(page.query_selector("input[type=range], input[type=number], [class*=slider i], [class*=length i]"))
    c.append(check("Password length slider/range exists", slider))

    def toggles():
        return ev(page, r"""() => {
            const boxes = document.querySelectorAll('input[type=checkbox],input[type=radio],[role=checkbox],[role=switch]');
            if (boxes.length >= 2) return true;
            const t = (document.body.innerText||'').toLowerCase();
            const kws = ['upper','lower','number','symbol','special','digit','character'];
            return kws.filter(k => t.includes(k)).length >= 2;
        }""")
    c.append(check("Character-type toggles exist", toggles))

    def gen_btn():
        return (count_attr(page, ["generate", "gen"]) >= 1
                or has_any_text(page, ["generate", "create", "new password", "regenerate", "roll"]))
    c.append(check("Generate button exists", gen_btn))

    def gen_works():
        find_and_click(page, ["generate", "create", "new password", "regenerate", "new", "roll", "▶", "🎲"])
        page.wait_for_timeout(700)
        pw = read_value(page, ["password", "output", "result", "generated", "pw", "field"])
        return len(pw) >= 8
    c.append(check("Generate produces password >=8 chars", gen_works))

    def strength():
        return (count_attr(page, ["strength", "meter", "weak", "strong", "bar"]) >= 1
                or has_any_text(page, ["strength", "weak", "strong", "medium", "fair", "password strength"]))
    c.append(check("Strength meter/indicator exists", strength))

    def copy_btn():
        return (count_attr(page, ["copy"]) >= 1
                or has_any_text(page, ["copy", "clipboard"]))
    c.append(check("Copy button exists", copy_btn))

    def history():
        return (count_attr(page, ["history", "previous", "past", "saved"]) >= 1
                or has_any_text(page, ["history", "previous", "saved passwords"]))
    c.append(check("Password history area exists", history))

    def char_count():
        return (count_attr(page, ["count", "length", "chars", "size"]) >= 1
                or has_any_text(page, ["characters", "length", "chars"]))
    c.append(check("Character count display", char_count))

    c.append(check("Dark theme", lambda: is_dark(page)))
    return c


def test_gta(page, errors):
    c = [check("Page loads without JS errors", lambda: len(errors) == 0)]

    def canvas():
        return bool(page.query_selector("canvas"))
    c.append(check("Canvas element exists", canvas))

    def canvas_drawn():
        return canvas_content(page, "canvas")
    c.append(check("Canvas has drawn content (city map)", canvas_drawn))

    def density():
        return canvas_density(page, "canvas") > 0.004
    c.append(check("Map is richly populated", density))

    def player():
        return (count_attr(page, ["player", "character", "hero"]) >= 1
                or canvas_density(page, "canvas") > 0.002)
    c.append(check("Player character representation exists", player))

    def wasd():
        for code in ["w", "a", "s", "d"]:
            try:
                page.keyboard.press(code)
            except Exception:
                return False
            page.wait_for_timeout(90)
        page.wait_for_timeout(200)
        return True
    c.append(check("WASD movement: no crash", wasd))

    def health():
        return (count_attr(page, ["health", "hp", "life"]) >= 1
                or has_any_text(page, ["health", "hp", "life"]))
    c.append(check("Health bar/display exists", health))

    def money():
        return (count_attr(page, ["money", "cash", "score", "scoreboard"]) >= 1
                or has_any_text(page, ["money", "cash", "$", "score", "wanted"]))
    c.append(check("Score/money display exists", money))

    def minimap():
        return ev(page, r"""() => {
            const maps = document.querySelectorAll('canvas,[class*=minimap i],[class*=mini-map i],[id*=minimap i],[class*=radar i]');
            for (const m of maps) {
                const r = m.getBoundingClientRect();
                if (r.width > 0 && r.width < 320 && r.height > 0) {
                    // small element in a corner => minimap candidate
                    if ((m.className && /mini|radar/i.test(m.className)) || m.id && /mini|radar/i.test(m.id)) return true;
                }
            }
            // >=2 canvases => one is likely a minimap
            return document.querySelectorAll('canvas').length >= 2;
        }""")
    c.append(check("Minimap exists", minimap))

    def vehicles():
        return (has_any_text(page, ["car", "vehicle", "drive"])
                or canvas_density(page, "canvas") > 0.006)
    c.append(check("Cars/vehicles visible on map", vehicles))

    def npcs():
        return (has_any_text(page, ["pedestrian", "npc", "ped", "civilian", "citizen"])
                or canvas_density(page, "canvas") > 0.006)
    c.append(check("NPC/pedestrian elements exist", npcs))

    def wanted():
        return (has_any_text(page, ["wanted", "police", "cop", "star", "busted", "wanted level"])
                or count_attr(page, ["wanted", "police", "star"]) >= 1)
    c.append(check("Wanted level / police system referenced", wanted))

    c.append(check("Dark theme / neon aesthetic", lambda: is_dark(page)))
    return c


def test_webos(page, errors):
    c = [check("Page loads without JS errors", lambda: len(errors) == 0)]

    def desktop():
        return count_attr(page, ["desktop", "screen", "workspace", "root", "main"]) >= 1
    c.append(check("Desktop area exists", desktop))

    def icons():
        return ev(page, r"""() => {
            const ic = document.querySelectorAll('[class*=icon i],[id*=icon i],[data-app],.app-icon,.app,button[onclick],div[onclick]');
            return ic.length >= 4;
        }""")
    c.append(check("Desktop icons exist (>=4)", icons))

    def taskbar():
        return count_attr(page, ["taskbar", "task-bar", "bar", "dock", "panel"]) >= 1
    c.append(check("Taskbar exists", taskbar))

    def start_btn():
        return (count_attr(page, ["start", "menu-btn", "launcher"]) >= 1
                or has_any_text(page, ["start", "menu", "apps", "≡", "☰"]))
    c.append(check("Start button exists", start_btn))

    def clock():
        return ev(page, r"""() => {
            const txt = document.body.innerText || '';
            return /\b\d{1,2}:\d{2}\b/.test(txt);
        }""")
    c.append(check("Clock/time display exists", clock))

    def open_window():
        before = ev(page, r"""() => document.querySelectorAll(
            '[class*=window i],[class*=dialog i],[class*=app-window i],[class*=panel i],[role=dialog]').length""")
        # click the first desktop icon
        handle = page.evaluate_handle(r"""() => {
            const ic = Array.from(document.querySelectorAll(
              '[class*=icon i],[id*=icon i],[data-app],.app-icon,[class*=app i],button[onclick],div[onclick],li'));
            for (const el of ic) { const r = el.getBoundingClientRect(); if (r.width>0 && r.height>0 && r.width<400) return el; }
            return ic[0] || null;
        }""")
        clicked = click_el(handle)
        page.wait_for_timeout(900)
        after = ev(page, r"""() => document.querySelectorAll(
            '[class*=window i],[class*=dialog i],[class*=app-window i],[class*=panel i],[role=dialog]').length""")
        return clicked and (after > before)
    c.append(check("Clicking an icon opens a window", open_window))

    def title_bar():
        return count_attr(page, ["title-bar", "titlebar", "title", "header", "window-header"]) >= 1
    c.append(check("Window has a title bar", title_bar))

    def close_btn():
        return (count_attr(page, ["close", "x-btn"]) >= 1
                or has_any_text(page, ["×", "✕", "close", "x"]))
    c.append(check("Window has close button", close_btn))

    def start_menu():
        before = ev(page, r"""() => document.querySelectorAll(
            '[class*=menu i],[class*=start-menu i],[role=menu]').length""")
        find_and_click(page, ["start", "menu", "apps", "≡", "☰"])
        page.wait_for_timeout(700)
        after = ev(page, r"""() => document.querySelectorAll(
            '[class*=menu i],[class*=start-menu i],[role=menu]').length""")
        return after > before
    c.append(check("Start menu appears when Start clicked", start_menu))

    def app_notepad():
        # try to open notepad
        find_and_click(page, ["notepad", "notes", "text", "editor"])
        page.wait_for_timeout(700)
        return bool(page.query_selector("textarea, [contenteditable=true]"))
    c.append(check("Notepad app has textarea (if opened)", app_notepad))

    def app_terminal():
        find_and_click(page, ["terminal", "console", "cmd", "shell"])
        page.wait_for_timeout(700)
        return ev(page, r"""() => {
            const inp = document.querySelectorAll('input[type=text],input:not([type]),textarea');
            const out = document.querySelectorAll('[class*=output i],[class*=console i],[class*=terminal i],[class*=log i]');
            return inp.length >= 1 && out.length >= 1;
        }""")
    c.append(check("Terminal app has input+output (if opened)", app_terminal))

    def app_calc():
        find_and_click(page, ["calculator", "calc"])
        page.wait_for_timeout(700)
        return ev(page, r"""() => {
            const els = Array.from(document.querySelectorAll('button,[role=button],.btn,[class*=key i]'));
            const set = new Set();
            for (const el of els) { const t = (el.innerText||'').trim(); if (/^[0-9]$/.test(t)) set.add(t); }
            return set.size >= 4;
        }""")
    c.append(check("Calculator app has number buttons (if opened)", app_calc))

    c.append(check("Dark theme", lambda: is_dark(page)))
    return c


TEST_FUNCS = {
    "kanban": test_kanban,
    "dashboard": test_dashboard,
    "chess": test_chess,
    "markdown": test_markdown,
    "calculator": test_calculator,
    "snake": test_snake,
    "pomodoro": test_pomodoro,
    "weather": test_weather,
    "password": test_password,
    "gta": test_gta,
    "webos": test_webos,
}


# --------------------------------------------------------------------------- #
# Page loading + main loop
# --------------------------------------------------------------------------- #
def load_page(browser, html_path):
    errors = []
    context = browser.new_context(viewport={"width": 1280, "height": 800})
    page = context.new_page()
    page.set_default_timeout(8000)
    page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
    page.on("pageerror", lambda err: errors.append(str(err)[:200]))
    start = time.time()
    page.goto(f"file://{html_path}", wait_until="domcontentloaded", timeout=10000)
    page.wait_for_timeout(2000)
    load_ms = int((time.time() - start) * 1000)
    return page, context, errors, load_ms


def main():
    results = {}
    print("=" * 70)
    print("Browser functional tests (headless Chromium)")
    print("=" * 70)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for test in TESTS:
            for model in MODELS:
                key = f"{test}_{model}"
                html_path = os.path.join(ROOT, test, f"{model}.html")

                if not os.path.exists(html_path) or os.path.getsize(html_path) < 100:
                    results[key] = {
                        "score": 0, "passed": 0, "total": 0,
                        "checks": [], "console_errors": [],
                        "error": "file missing or too small",
                    }
                    print(f"[{test}/{model}]  file missing — score 0")
                    continue

                try:
                    page, context, errors, load_ms = load_page(browser, html_path)
                except Exception as e:  # noqa: BLE001
                    results[key] = {
                        "score": 0, "passed": 0, "total": 0,
                        "checks": [], "console_errors": [],
                        "load_time_ms": 0,
                        "error": f"load failed: {str(e)[:120]}",
                    }
                    print(f"[{test}/{model}]  LOAD FAILED — score 0")
                    continue

                try:
                    checks = TEST_FUNCS[test](page, errors)
                except Exception as e:  # noqa: BLE001
                    checks = [{"name": "test suite", "pass": False,
                               "error": f"suite crashed: {str(e)[:120]}"}]

                # screenshot
                try:
                    page.screenshot(path=os.path.join(SHOTS, f"{test}_{model}.png"))
                except Exception:
                    pass

                passed = sum(1 for c in checks if c["pass"])
                total = len(checks)
                score = round(passed / total * 100) if total else 0

                results[key] = {
                    "score": score,
                    "passed": passed,
                    "total": total,
                    "checks": checks,
                    "console_errors": errors[:10],
                    "load_time_ms": load_ms,
                }
                print(f"[{test}/{model}]  {passed}/{total} checks passed  ->  {score}%")

                try:
                    context.close()
                except Exception:
                    pass

        browser.close()

    # save JSON
    out_path = os.path.join(ROOT, "browser_results.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults written to {out_path}")
    print(f"Screenshots in {SHOTS}/")

    # per-model summary
    print("\n" + "=" * 70)
    print("PER-MODEL AVERAGE SCORE")
    print("=" * 70)
    model_scores = {m: [] for m in MODELS}
    for key, r in results.items():
        model = key.rsplit("_", 1)[-1]
        if model in model_scores and r.get("total", 0) > 0:
            model_scores[model].append(r["score"])
    for m in MODELS:
        scores = model_scores[m]
        if scores:
            avg = sum(scores) / len(scores)
            print(f"  {m:8s}  avg {avg:5.1f}%  (over {len(scores)} apps)")
        else:
            print(f"  {m:8s}  no results")

    overall = [r["score"] for r in results.values() if r.get("total", 0) > 0]
    if overall:
        print(f"  {'OVERALL':8s}  avg {sum(overall)/len(overall):5.1f}%  (over {len(overall)} apps)")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise
