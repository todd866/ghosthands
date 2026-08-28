import json
import types
import unittest
from unittest import mock

from ghosthands import hands


def port(device, description="CircuitPython RP2040", vid=0x239A):
    return types.SimpleNamespace(
        device=device, description=description, manufacturer="Adafruit", product="QT Py", vid=vid
    )


class DiscoveryTests(unittest.TestCase):
    def test_discovers_one_healthy_board_by_handshake(self):
        reply = {"ok": True, "pong": True, "kbd": True, "abs_mouse": True}
        with mock.patch.object(hands.PicoHands, "ping", return_value=reply):
            self.assertEqual(hands.discover_pico_port([port("/dev/cu.usbmodem101")]),
                             "/dev/cu.usbmodem101")

    def test_rejects_multiple_healthy_boards(self):
        reply = {"ok": True, "pong": True, "kbd": True, "abs_mouse": True}
        candidates = [port("/dev/cu.usbmodem101"), port("/dev/cu.usbmodem102")]
        with mock.patch.object(hands.PicoHands, "ping", return_value=reply):
            with self.assertRaisesRegex(RuntimeError, "multiple healthy"):
                hands.discover_pico_port(candidates)

    def test_does_not_probe_unrelated_serial_device(self):
        unrelated = port("/dev/cu.Bluetooth-Incoming-Port", "Bluetooth", vid=None)
        unrelated.manufacturer = "Apple"
        unrelated.product = ""
        with mock.patch.object(hands.PicoHands, "ping") as ping:
            with self.assertRaisesRegex(RuntimeError, "no CircuitPython"):
                hands.discover_pico_port([unrelated])
        ping.assert_not_called()


class ProtocolTests(unittest.TestCase):
    def test_accepts_only_matching_ack(self):
        class FakeSerial:
            def __init__(self, *args, **kwargs):
                self.lines = []
                self.dtr = False

            def reset_input_buffer(self):
                pass

            def write(self, payload):
                request = json.loads(payload)
                self.lines = [
                    (json.dumps(request) + "\n").encode(),
                    (json.dumps({"id": request["id"], "ok": True, "pong": True}) + "\n").encode(),
                ]

            def flush(self):
                pass

            def readline(self):
                return self.lines.pop(0) if self.lines else b""

            def close(self):
                pass

        with mock.patch.object(hands.serial, "Serial", FakeSerial):
            reply = hands.PicoHands("/dev/fake").ping()
        self.assertTrue(reply["ok"])
        self.assertTrue(reply["pong"])

    def test_rejected_command_raises(self):
        class RejectingSerial:
            def __init__(self, *args, **kwargs):
                self.reply = b""

            def reset_input_buffer(self):
                pass

            def write(self, payload):
                request = json.loads(payload)
                self.reply = (json.dumps({"id": request["id"], "ok": False, "err": "bad"}) + "\n").encode()

            def flush(self):
                pass

            def readline(self):
                reply, self.reply = self.reply, b""
                return reply

            def close(self):
                pass

        with mock.patch.object(hands.serial, "Serial", RejectingSerial):
            with self.assertRaisesRegex(RuntimeError, "bad"):
                hands.PicoHands("/dev/fake").ping()

    def test_non_typing_timeout_covers_a_worst_case_firmware_move(self):
        self.assertGreaterEqual(hands._NON_TYPING_COMMAND_TIMEOUT_SECONDS, 2.0)


if __name__ == "__main__":
    unittest.main()
