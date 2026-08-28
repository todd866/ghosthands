"""The autonomous loop: capture -> plan (brain) -> ground (eyes) -> act (hands) -> repeat.
Logs every step (jsonl + a screenshot per step) and pauses at money checkpoints."""
import os, json, time, shutil, subprocess
from urllib.parse import urlsplit
from .eyes import Eyes
from .config import Config

def safari_navigate(url):
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("navigate requires a full http(s) URL")
    script = """on run argv
tell application "Safari" to set URL of front document to item 1 of argv
end run"""
    subprocess.run(["osascript", "-e", script, url], check=True)

class Agent:
    def __init__(self, planner, grounder, hands, eyes=None, run_dir=None, browser_nav=True):
        self.planner = planner
        self.grounder = grounder
        self.hands = hands
        self.eyes = eyes or Eyes()
        self.browser_nav = browser_nav
        self.run_dir = run_dir or os.path.join(
            Config.runs_dir, "run-%s-%d" % (time.strftime("%Y%m%d-%H%M%S"), os.getpid())
        )
        os.makedirs(self.run_dir, mode=0o700, exist_ok=True)
        os.chmod(self.run_dir, 0o700)
        self.log_path = os.path.join(self.run_dir, "log.jsonl")
        self.history = []
        self.step = 0

    def _log(self, kind, summary, extra=None):
        obj = {"t": time.strftime("%H:%M:%S"), "step": self.step, "kind": kind, "summary": summary}
        if extra:
            obj.update(extra)
        with open(self.log_path, "a") as f:
            f.write(json.dumps(obj) + "\n")
        print("[%s] step %d %s: %s" % (obj["t"], self.step, kind, summary), flush=True)

    def run(self, goal, guide, max_steps=20):
        self._log("start", goal.strip().splitlines()[0][:100])
        for _ in range(max_steps):
            if self._abort_requested():
                self._log("abort", "ABORT flag found before next step")
                return "aborted"
            self.step += 1
            frame = self.eyes.capture()
            w, h = self.eyes.dims(frame)
            shutil.copyfile(frame, os.path.join(self.run_dir, "step%03d.jpg" % self.step))
            try:
                plan, raw = self.planner.decide(goal, guide, frame, self.history, (w, h))
            except Exception as e:
                self._log("planner_error", str(e)); return "planner_error"
            act = plan.get("action", "")
            self._log("plan", "%s | %s" % (act, (plan.get("observation") or "")[:90]),
                      {"plan": plan})
            if act == "done":
                self._log("done", plan.get("reasoning", "")); return "done"
            if act == "verify_stop":
                if self._checkpoint(plan.get("reason", "")) == "abort":
                    return "aborted"
                self.history.append("[human reviewed checkpoint and approved -> continue]")
                continue
            try:
                if self._abort_requested():
                    self._log("abort", "ABORT flag found before action")
                    return "aborted"
                self._execute(plan, (w, h), frame)
            except Exception as e:
                self._log("exec_error", "%s: %s" % (act, e))
                try:
                    self.hands.release_all()
                except Exception as release_error:
                    self._log("release_error", str(release_error))
                self.history.append("%s FAILED: %s" % (act, e))
                continue
            self.history.append(self._hist(plan))
        self._log("max_steps", "reached %d steps" % max_steps)
        return "max_steps"

    def _abort_requested(self):
        return os.path.exists(os.path.join(self.run_dir, "ABORT"))

    def _checkpoint(self, reason):
        cp = os.path.join(self.run_dir, "CHECKPOINT_step%03d.txt" % self.step)
        open(cp, "w").write(reason + "\n")
        self._log("checkpoint", "PAUSED for human review: " + reason)
        cont = os.path.join(self.run_dir, "CONTINUE")
        abrt = os.path.join(self.run_dir, "ABORT")
        while True:
            if os.path.exists(cont):
                os.remove(cont); self._log("resume", "human approved continue"); return "continue"
            if os.path.exists(abrt):
                os.remove(abrt); self._log("abort", "human aborted"); return "abort"
            time.sleep(2.0)

    def _hist(self, plan):
        a = plan.get("action", "")
        d = plan.get("target") or plan.get("text") or plan.get("keys") or plan.get("url") or ""
        return ("%s: %s" % (a, d))[:130]

    def _execute(self, plan, dims, frame):
        w, h = dims
        a = plan.get("action", "")
        if a in ("click", "double_click"):
            desc = plan.get("target", "")
            x, y, frac, raw = self.grounder.locate(frame, desc, dims)
            self._log("ground", "%s -> %d,%d (%.3f,%.3f)" % (desc[:50], x, y, frac[0], frac[1]))
            if self._abort_requested():
                raise RuntimeError("ABORT flag found after grounding")
            self.hands.move(frac[0], frac[1]); time.sleep(0.18)
            self.hands.click()
            if a == "double_click":
                time.sleep(0.09); self.hands.click()
        elif a == "type":
            self.hands.type(plan.get("text", ""))
        elif a == "key":
            self.hands.key(plan.get("keys", ""))
        elif a == "scroll":
            amt = abs(int(plan.get("amount", 5)))
            if plan.get("direction") == "down":
                amt = -amt
            self.hands.scroll(amt)
        elif a == "navigate":
            if self.browser_nav:
                safari_navigate(plan.get("url", "")); time.sleep(2.2)
            else:
                raise RuntimeError("navigate disabled")
        elif a == "wait":
            time.sleep(float(plan.get("seconds", 1.5)))
        else:
            raise RuntimeError("unknown action %r" % a)
