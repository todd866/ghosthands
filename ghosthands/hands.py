"""Hands: inject mouse/keyboard input through an RP2040 USB-HID board.

This is DOM-independent and works with native apps as well as browsers. Hardware HID does not
guarantee that automated behaviour is undetectable. DryRunHands only logs actions.
"""
import json, secrets, time
try:
    import serial
    from serial.tools import list_ports
except ImportError:
    serial = None
    list_ports = None
from .config import Config

_BOARD_WORDS = ("circuitpython", "rp2040", "qt py", "xiao", "adafruit", "seeed", "raspberry")
_BOARD_VIDS = {0x239A, 0x2E8A}  # Adafruit/CircuitPython and Raspberry Pi


def serial_ports():
    """Return the serial devices pyserial can currently see."""
    if list_ports is None:
        raise RuntimeError("pyserial not installed (pip install pyserial)")
    return list(list_ports.comports())


def _port_score(port):
    device = (getattr(port, "device", "") or "").lower()
    metadata = " ".join(str(getattr(port, name, "") or "") for name in
                        ("description", "manufacturer", "product")).lower()
    score = 0
    if "/cu.usbmodem" in device or "/tty.usbmodem" in device:
        score += 30
    elif "/ttyacm" in device or device.startswith("com"):
        score += 20
    if any(word in metadata for word in _BOARD_WORDS):
        score += 100
    if getattr(port, "vid", None) in _BOARD_VIDS:
        score += 50
    return score


def discover_pico_port(ports=None, explicit_port=None):
    """Find exactly one healthy ghosthands firmware port, or fail clearly."""
    available = list(serial_ports() if ports is None else ports)
    requested = explicit_port or Config.pico_port
    if requested:
        candidates = [requested]
    else:
        candidates = []
    ranked = sorted(((_port_score(port), getattr(port, "device", ""), port)
                     for port in available), reverse=True, key=lambda item: (item[0], item[1]))
    # A device name alone is not enough: only probe ports with a matching USB vendor
    # or descriptive metadata, so unrelated modems are never sent commands.
    ranked = [item for item in ranked if item[0] >= 50 and item[1]]
    if not requested:
        candidates = [item[1] for item in ranked]
    if not candidates:
        seen = ", ".join(getattr(port, "device", "?") for port in available) or "none"
        raise RuntimeError(
            "no CircuitPython/RP2040 serial port found (ports seen: %s). "
            "Connect the board or set GH_PICO_PORT explicitly." % seen
        )

    healthy = []
    failures = []
    for device in candidates:
        try:
            reply = PicoHands(device).ping()
            if reply.get("pong") is True and reply.get("kbd") is True and reply.get("abs_mouse") is True:
                healthy.append(device)
            else:
                failures.append("%s: incomplete HID (%s)" % (device, reply))
        except Exception as exc:
            failures.append("%s: %s" % (device, exc))
    if len(healthy) == 1:
        return healthy[0]
    if len(healthy) > 1:
        raise RuntimeError(
            "multiple healthy ghosthands boards found: %s. Set GH_PICO_PORT or use --port."
            % ", ".join(healthy)
        )
    raise RuntimeError("no healthy ghosthands firmware responded (%s)" % "; ".join(failures))

class Hands:
    def move(self, x01, y01): raise NotImplementedError
    def click(self, button="left"): raise NotImplementedError
    def type(self, text): raise NotImplementedError
    def key(self, keys): raise NotImplementedError
    def scroll(self, amount): raise NotImplementedError
    def release_all(self): raise NotImplementedError

class PicoHands(Hands):
    """One JSON command per line over USB CDC serial; one ack per command."""
    def __init__(self, port=None):
        if serial is None:
            raise RuntimeError("pyserial not installed (pip install pyserial)")
        self.port = port or discover_pico_port()

    def _send(self, cmd):
        request = dict(cmd)
        request_id = secrets.token_hex(8)
        request["id"] = request_id
        p = serial.Serial(self.port, 115200, timeout=0.8, write_timeout=1.0)
        try:
            p.dtr = True
            time.sleep(0.12)
            p.reset_input_buffer()
            p.write((json.dumps(request) + "\n").encode())
            p.flush()
            # typing needs per-char time or chars drop; clicks/keys are quick
            # Firmware can pause up to 0.54s per character (typing jitter plus a
            # word pause), so size the deadline to the documented worst case.
            deadline_seconds = 2.0 + 0.6 * len(str(request.get("type", ""))) if "type" in request else 1.5
            deadline = time.monotonic() + deadline_seconds
            while time.monotonic() < deadline:
                line = p.readline().decode("utf-8", "ignore").strip()
                if not line.startswith("{"):
                    continue
                try:
                    reply = json.loads(line)
                except ValueError:
                    continue
                # The console CDC may echo the request; accept only a real ack.
                if reply.get("id") != request_id or "ok" not in reply:
                    continue
                if reply.get("ok") is not True:
                    raise RuntimeError("board rejected command: %s" % reply.get("err", reply))
                return reply
        finally:
            p.close()
        raise RuntimeError("board did not acknowledge command on %s" % self.port)

    def move(self, x01, y01):
        px = round(max(0.0, min(1.0, x01)) * 32767)
        py = round(max(0.0, min(1.0, y01)) * 32767)
        return self._send({"move": {"x": px, "y": py}})

    def click(self, button="left"):
        return self._send({"click": button})

    def type(self, text):
        # chunk long strings (<=18 chars) -- the HID stack drops chars on long bursts
        last = ""
        for i in range(0, len(text), 18):
            chunk = text[i:i+18]
            last = self._send({"type": chunk})
            if last.get("chars") != len(chunk):
                raise RuntimeError("board typed %s of %s requested characters" % (
                    last.get("chars"), len(chunk)
                ))
            time.sleep(0.15)
        return last

    def key(self, keys):
        if isinstance(keys, str):
            keys = keys.replace("+", ",")
            keys = keys.split(",") if "," in keys else keys
        return self._send({"key": keys})

    def scroll(self, amount):
        return self._send({"scroll": amount})

    def ping(self):
        return self._send({"ping": 1})

    def release_all(self):
        return self._send({"release_all": 1})

class DryRunHands(Hands):
    def move(self, x01, y01): print("  [dry] move %.3f,%.3f" % (x01, y01)); return "dry"
    def click(self, button="left"): print("  [dry] click %s" % button); return "dry"
    def type(self, text): print("  [dry] type %r" % text); return "dry"
    def key(self, keys): print("  [dry] key %s" % keys); return "dry"
    def scroll(self, amount): print("  [dry] scroll %s" % amount); return "dry"
    def release_all(self): return "dry"

def make_hands(backend=None, port=None):
    backend = backend or Config.hands_backend
    if backend == "dryrun":
        return DryRunHands()
    selected = discover_pico_port(explicit_port=port) if port else None
    return PicoHands(port=selected)
