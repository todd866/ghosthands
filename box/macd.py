#!/usr/bin/env python3
"""GhostMirror: the ghostbox control API on a real Mac, so ghosthands can drive a real computer
(its own GPU, its own signed-in Google Chrome) with the same jobs and agent as the container.

Same HTTP API as box/boxd.py (status, screenshot, move, click, type, key, scroll, navigate, url),
so `run.py --target box --box-url http://127.0.0.1:8790` drives it unchanged.

  eyes      screencapture of the main display (JPEG)
  hands     CoreGraphics events (ctypes, no extra packages): curved, eased pointer paths, per-key
            typing rhythm, like box/boxd.py
  navigate  Google Chrome's AppleScript interface (set URL of the active tab): no keystrokes to
            intercept, no autocomplete, and no automation flag for pages (navigator.webdriver stays
            false; AppleScript is not a DevTools connection)
  logins    none of its own: the signed-in Chrome's password manager fills logins on their sites

macOS asks once (the owner, on the Mac) for Screen Recording and Accessibility for the app that
runs this (GhostMirror.app), and for permission to control Google Chrome.

Input is confined to the page: keys, typing and clicks only while Google Chrome is frontmost,
clicks only inside its page area, and only the key chords a web page needs (no Spotlight, app
switching, address bar or DevTools), so a page cannot steer the agent into the rest of the Mac.

Listens on 127.0.0.1 only; BOX_TOKEN required (as boxd). Reach it from another Mac over ssh -L.
"""
import ctypes
import ctypes.util
import hmac
import json
import math
import os
import random
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

TOKEN = os.environ.get("BOX_TOKEN", "")
PORT = int(os.environ.get("BOX_PORT", "47811"))
if len(TOKEN) < 16:
    sys.exit("macd: BOX_TOKEN (16+ chars) is required")

# ---------------------------------------------------------------- CoreGraphics via ctypes

_cg = ctypes.cdll.LoadLibrary(ctypes.util.find_library("ApplicationServices"))
_cf = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreFoundation"))


class CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


class CGSize(ctypes.Structure):
    _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]


class CGRect(ctypes.Structure):
    _fields_ = [("origin", CGPoint), ("size", CGSize)]


_cg.CGMainDisplayID.restype = ctypes.c_uint32
_cg.CGDisplayBounds.restype = CGRect
_cg.CGDisplayBounds.argtypes = [ctypes.c_uint32]
_cg.CGEventCreate.restype = ctypes.c_void_p
_cg.CGEventCreate.argtypes = [ctypes.c_void_p]
_cg.CGEventGetLocation.restype = CGPoint
_cg.CGEventGetLocation.argtypes = [ctypes.c_void_p]
_cg.CGEventCreateMouseEvent.restype = ctypes.c_void_p
_cg.CGEventCreateMouseEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint32, CGPoint, ctypes.c_uint32]
_cg.CGEventCreateKeyboardEvent.restype = ctypes.c_void_p
_cg.CGEventCreateKeyboardEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_bool]
_cg.CGEventKeyboardSetUnicodeString.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p]
_cg.CGEventSetFlags.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
_cg.CGEventSetIntegerValueField.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int64]
_cg.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
_cg.CGEventCreateScrollWheelEvent2.restype = ctypes.c_void_p
_cg.CGEventCreateScrollWheelEvent2.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                                                ctypes.c_int32, ctypes.c_int32, ctypes.c_int32]
_cf.CFRelease.argtypes = [ctypes.c_void_p]

HID = 0                      # kCGHIDEventTap: events enter where hardware events do
MOVED, LDOWN, LUP, RDOWN, RUP, LDRAG = 5, 1, 2, 3, 4, 6
CLICK_STATE = 1              # kCGMouseEventClickState
F_SHIFT, F_CTRL, F_ALT, F_CMD = 0x20000, 0x40000, 0x80000, 0x100000

_lock = threading.Lock()


def screen_points():
    b = _cg.CGDisplayBounds(_cg.CGMainDisplayID())
    return int(b.size.width), int(b.size.height)


def pointer():
    e = _cg.CGEventCreate(None)
    p = _cg.CGEventGetLocation(e)
    _cf.CFRelease(e)
    return p.x, p.y


def _post_mouse(kind, x, y, button=0, clicks=None):
    e = _cg.CGEventCreateMouseEvent(None, kind, CGPoint(x, y), button)
    if clicks:
        _cg.CGEventSetIntegerValueField(e, CLICK_STATE, clicks)
    _cg.CGEventPost(HID, e)
    _cf.CFRelease(e)


def _rand(a, b):
    return random.uniform(a, b)


def human_move(tx, ty):
    """Cubic Bezier with a sideways bow, smoothstep easing, Fitts-like duration, ~120 Hz, an
    occasional overshoot-and-correct on long moves (the same model as box/boxd.py)."""
    W, H = screen_points()
    tx = max(0, min(W - 1, float(tx))); ty = max(0, min(H - 1, float(ty)))
    sx, sy = pointer()
    dist = math.hypot(tx - sx, ty - sy)
    if dist < 2:
        _post_mouse(MOVED, tx, ty); return
    dur = min(1.1, 0.12 + 0.11 * math.log2(1 + dist / 9.0)) * _rand(0.85, 1.2)
    nx, ny = -(ty - sy) / dist, (tx - sx) / dist
    bow = dist * _rand(-0.18, 0.18)
    c1 = (sx + (tx - sx) * _rand(0.2, 0.4) + nx * bow, sy + (ty - sy) * _rand(0.2, 0.4) + ny * bow)
    c2 = (sx + (tx - sx) * _rand(0.6, 0.85) + nx * bow * 0.5, sy + (ty - sy) * _rand(0.6, 0.85) + ny * bow * 0.5)
    overshoot = dist > 150 and random.random() < 0.35
    ex, ey = tx, ty
    if overshoot:
        k = _rand(0.02, 0.05); ex, ey = tx + (tx - sx) * k, ty + (ty - sy) * k
    steps = max(8, int(dur * 120))
    t0 = time.monotonic()
    for i in range(1, steps + 1):
        u = i / steps; u = u * u * (3 - 2 * u)
        a, b, c, d = (1 - u) ** 3, 3 * (1 - u) ** 2 * u, 3 * (1 - u) * u ** 2, u ** 3
        _post_mouse(MOVED, a * sx + b * c1[0] + c * c2[0] + d * ex, a * sy + b * c1[1] + c * c2[1] + d * ey)
        lag = t0 + dur * i / steps - time.monotonic()
        if lag > 0:
            time.sleep(lag)
    if overshoot:
        time.sleep(_rand(0.04, 0.09))
        for i in range(1, 7):
            u = i / 6; _post_mouse(MOVED, ex + (tx - ex) * u, ey + (ty - ey) * u); time.sleep(0.012)
    _post_mouse(MOVED, tx, ty)


def click(button="left", double=False):
    x, y = pointer()
    down, up, b = (RDOWN, RUP, 1) if button == "right" else (LDOWN, LUP, 0)
    for n in range(2 if double else 1):
        _post_mouse(down, x, y, b, n + 1); time.sleep(_rand(0.05, 0.12))
        _post_mouse(up, x, y, b, n + 1)
        if double and n == 0:
            time.sleep(_rand(0.07, 0.13))


def scroll(amount):
    """+ = page down, in wheel notches (lines)."""
    n = int(amount)
    for _ in range(min(abs(n), 40)):
        e = _cg.CGEventCreateScrollWheelEvent2(None, 1, 1, -3 if n > 0 else 3, 0, 0)  # kCGScrollEventUnitLine
        _cg.CGEventPost(HID, e); _cf.CFRelease(e)
        time.sleep(_rand(0.03, 0.09))


# macOS virtual key codes (ANSI layout) for named keys and chords
_KC = {"a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9, "b": 11, "q": 12,
       "w": 13, "e": 14, "r": 15, "y": 16, "t": 17, "1": 18, "2": 19, "3": 20, "4": 21, "6": 22, "5": 23,
       "=": 24, "9": 25, "7": 26, "-": 27, "8": 28, "0": 29, "]": 30, "o": 31, "u": 32, "[": 33, "i": 34,
       "p": 35, "l": 37, "j": 38, "'": 39, "k": 40, ";": 41, "\\": 42, ",": 43, "/": 44, "n": 45, "m": 46,
       ".": 47, "`": 50, "return": 36, "enter": 36, "tab": 48, "space": 49, "delete": 51, "backspace": 51,
       "escape": 53, "esc": 53, "forwarddelete": 117, "del": 117, "home": 115, "end": 119,
       "pageup": 116, "pgup": 116, "pagedown": 121, "pgdn": 121, "left": 123, "right": 124, "down": 125,
       "up": 126, "arrow-left": 123, "arrow-right": 124, "arrow-down": 125, "arrow-up": 126,
       "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97, "f7": 98, "f8": 100, "f9": 101,
       "f10": 109, "f11": 103, "f12": 111}
_MOD = {"cmd": F_CMD, "command": F_CMD, "meta": F_CMD, "super": F_CMD, "ctrl": F_CTRL, "control": F_CTRL,
        "alt": F_ALT, "option": F_ALT, "shift": F_SHIFT}


def _key_event(code, down, flags=0):
    e = _cg.CGEventCreateKeyboardEvent(None, code, down)
    _cg.CGEventSetFlags(e, flags)
    _cg.CGEventPost(HID, e); _cf.CFRelease(e)


def key(keys):
    parts = [p.strip().lower() for p in (keys if isinstance(keys, (list, tuple)) else str(keys).replace(",", "+").split("+")) if p.strip()]
    flags = 0
    for p in parts[:-1]:
        if p not in _MOD:
            raise ValueError("unknown modifier %r" % p)
        flags |= _MOD[p]
    k = parts[-1] if parts else ""
    if k in _MOD:
        return
    if k not in _KC:
        raise ValueError("unknown key %r" % k)
    _key_event(_KC[k], True, flags); time.sleep(_rand(0.04, 0.09)); _key_event(_KC[k], False, flags)


def _type_char(ch):
    units = ch.encode("utf-16-le")
    arr = (ctypes.c_uint16 * (len(units) // 2)).from_buffer_copy(units)
    for down in (True, False):
        e = _cg.CGEventCreateKeyboardEvent(None, 0, down)
        _cg.CGEventKeyboardSetUnicodeString(e, len(arr), arr)
        _cg.CGEventPost(HID, e); _cf.CFRelease(e)
        if down:
            time.sleep(_rand(0.02, 0.06))


def type_text(text):
    for ch in text:
        _type_char(ch)
        time.sleep(_rand(0.035, 0.11) + (_rand(0.08, 0.25) if ch in " .,@/" else 0))


# ---------------------------------------------------------------- confinement
# On a real Mac the keyboard and mouse reach the owner's whole account, not a container. A page
# that talks the planner into "press cmd+space, type Terminal, ..." must get nowhere, so input is
# confined in code: only while Google Chrome is the frontmost app, clicks only inside its page
# area, and only key chords a person uses on a web page.

CHROME_BUNDLE = "com.google.Chrome"
TOOLBAR_PT = int(os.environ.get("MACD_TOOLBAR_PT", "90"))     # tab strip + toolbar, in points

# chords allowed on a page (modifier set, key); everything else is refused
_ALLOWED_CHORDS = {
    (frozenset(), k) for k in ("return", "enter", "tab", "escape", "esc", "delete", "backspace",
                                "forwarddelete", "del", "space", "up", "down", "left", "right",
                                "arrow-up", "arrow-down", "arrow-left", "arrow-right", "home", "end",
                                "pageup", "pagedown", "pgup", "pgdn")
} | {(frozenset({"shift"}), k) for k in ("tab", "return", "up", "down", "left", "right", "home", "end")} \
  | {(frozenset({"cmd"}), k) for k in ("a", "c", "v", "x", "z", "f", "left", "right", "up", "down")} \
  | {(frozenset({"cmd", "shift"}), "z"), (frozenset({"alt"}), "left"), (frozenset({"alt"}), "right"),
     (frozenset({"alt"}), "delete"), (frozenset({"alt"}), "backspace")}
_CANON = {"command": "cmd", "meta": "cmd", "super": "cmd", "control": "ctrl", "option": "alt"}


def frontmost_bundle():
    """Bundle id of the frontmost app, from lsappinfo (needs no permission)."""
    asn = subprocess.run(["lsappinfo", "front"], capture_output=True, text=True, timeout=5).stdout.strip()
    out = subprocess.run(["lsappinfo", "info", "-only", "bundleid", asn],
                         capture_output=True, text=True, timeout=5).stdout
    import re
    m = re.search(r'(?:bundleID|"CFBundleIdentifier")\s*=\s*"([^"]*)"', out)
    return m.group(1) if m else ""


def require_chrome():
    b = frontmost_bundle()
    if b != CHROME_BUNDLE:
        raise PermissionError("refused: input goes only to Google Chrome; the front app is %s" % (b or "?"))


def chrome_page_rect():
    """Chrome's front window content area (points): its bounds minus the tab strip and toolbar."""
    out = _osascript(['tell application "Google Chrome" to get bounds of front window'])
    l, t, r, b = [int(v) for v in out.replace(" ", "").split(",")]
    return l, t + TOOLBAR_PT, r, b


def require_in_page(x, y):
    l, t, r, b = chrome_page_rect()
    if not (l <= x < r and t <= y < b):
        raise PermissionError("refused: (%d,%d) is outside Chrome's page area" % (x, y))


def check_chord(keys):
    parts = [p.strip().lower() for p in (keys if isinstance(keys, (list, tuple)) else str(keys).replace(",", "+").split("+")) if p.strip()]
    mods = frozenset(_CANON.get(p, p) for p in parts[:-1])
    k = parts[-1] if parts else ""
    if (mods, k) not in _ALLOWED_CHORDS:
        raise PermissionError("refused: %r is not a key a page needs" % "+".join(parts))


# ---------------------------------------------------------------- Chrome (AppleScript)

def _osascript(lines, *args):
    argv = ["osascript"]
    for l in lines:
        argv += ["-e", l]
    r = subprocess.run(argv + list(args), capture_output=True, text=True, timeout=20)
    if r.returncode != 0:
        raise RuntimeError("Chrome control failed: %s" % r.stderr.strip()[:200])
    return r.stdout.strip()


def check_url(url):
    u = str(url).strip()
    if any(ord(c) < 32 for c in u) or urlparse(u).scheme not in ("http", "https") or not urlparse(u).hostname:
        raise PermissionError("refused: navigate takes an http(s) address, got %r" % u[:80])
    return u


def navigate(url):
    _osascript(["on run argv", 'tell application "Google Chrome"',
                "if (count of windows) = 0 then make new window",
                "set URL of active tab of front window to item 1 of argv", "end tell", "end run"],
               check_url(url))


def current_url():
    return _osascript(['tell application "Google Chrome" to get URL of active tab of front window'])


# ---------------------------------------------------------------- screen

def screenshot():
    fd, path = tempfile.mkstemp(suffix=".jpg"); os.close(fd)
    try:
        r = subprocess.run(["screencapture", "-x", "-m", "-t", "jpg", path], capture_output=True, timeout=20)
        if r.returncode != 0 or os.path.getsize(path) < 2000:
            raise RuntimeError("screen capture failed (Screen Recording not granted, or the display is asleep)")
        # Retina pixels -> points, so a grounded fraction maps straight to a point
        w, h = screen_points()
        subprocess.run(["sips", "-z", str(h), str(w), path], capture_output=True, timeout=20)
        with open(path, "rb") as f:
            return f.read(), w, h
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


# ---------------------------------------------------------------- http (as boxd)

class Handler(BaseHTTPRequestHandler):
    server_version = "ghostmirror/1"

    def log_message(self, fmt, *a):
        sys.stderr.write("macd %s\n" % (fmt % a))

    def _reply(self, code, body, ctype="application/json", headers=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, str(v))
        self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            w, h = screen_points()
            return self._reply(200, {"ok": True, "width": w, "height": h})
        self._reply(404, {"error": "POST /action"})

    def do_POST(self):
        if self.headers.get("Origin") or not (self.headers.get("Content-Type") or "").startswith("application/json"):
            return self._reply(403, {"error": "API clients only"})
        if not hmac.compare_digest(self.headers.get("X-Box-Token") or "", TOKEN):
            return self._reply(401, {"error": "bad token"})
        if self.path != "/action":
            return self._reply(404, {"error": "POST /action"})
        try:
            req = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            verb = req.get("verb")
            with _lock:
                if verb == "status":
                    w, h = screen_points(); x, y = pointer()
                    return self._reply(200, {"width": w, "height": h, "x": int(x), "y": int(y)})
                if verb == "screenshot":
                    data, w, h = screenshot()
                    return self._reply(200, data, "image/jpeg", {"X-Width": w, "X-Height": h})
                if verb == "vault":
                    return self._reply(200, {"logins": []})     # the Mac's own Chrome fills logins
                if verb == "downloads":
                    return self._reply(200, {"done": [], "pending": []})
                if verb == "url":
                    return self._reply(200, {"url": current_url()})
                if verb in ("move", "click", "type", "key", "scroll"):
                    require_chrome()
                if verb == "move":
                    human_move(req["x"], req["y"])
                elif verb == "click":
                    if "x" in req and "y" in req:
                        require_in_page(req["x"], req["y"])
                        human_move(req["x"], req["y"]); time.sleep(_rand(0.04, 0.12))
                    x, y = pointer()
                    require_in_page(x, y)
                    click(req.get("button", "left"), bool(req.get("double")))
                elif verb == "type":
                    type_text(str(req.get("text", "")))
                elif verb == "key":
                    check_chord(req.get("keys", ""))
                    key(req.get("keys", ""))
                elif verb == "scroll":
                    x, y = pointer()
                    require_in_page(x, y)
                    scroll(req.get("amount", 0))
                elif verb == "navigate":
                    navigate(req.get("url", ""))
                else:
                    return self._reply(400, {"error": "unknown verb %r" % verb})
            self._reply(200, {"ok": True})
        except PermissionError as e:
            self._reply(403, {"error": str(e)})
        except Exception as e:
            self._reply(500, {"error": "%s: %s" % (type(e).__name__, str(e)[:300])})


if __name__ == "__main__":
    print("macd on 127.0.0.1:%d, screen %dx%d points" % ((PORT,) + screen_points()), flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
