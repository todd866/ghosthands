import os
import tempfile
import unittest
from unittest import mock

from ghosthands.agent import Agent, safari_navigate
from ghosthands.config import Config


class RecordingHands:
    def __init__(self):
        self.scrolls = []
        self.releases = 0

    def scroll(self, amount):
        self.scrolls.append(amount)

    def release_all(self):
        self.releases += 1


class SafetyTests(unittest.TestCase):
    def test_default_backend_is_dryrun(self):
        self.assertEqual(Config.hands_backend, "dryrun")

    def test_safari_rejects_non_web_url(self):
        with self.assertRaises(ValueError):
            safari_navigate('javascript:alert("x")')

    def test_safari_passes_url_as_argument(self):
        url = 'https://example.com/a?x="quoted"'
        with mock.patch("ghosthands.agent.subprocess.run") as run:
            safari_navigate(url)
        args = run.call_args.args[0]
        self.assertEqual(args[-1], url)
        self.assertNotIn(url, args[2])

    def test_scroll_direction_matches_firmware_contract(self):
        with tempfile.TemporaryDirectory() as run_dir:
            recorder = RecordingHands()
            agent = Agent(object(), object(), recorder, eyes=object(), run_dir=run_dir)
            agent._execute({"action": "scroll", "direction": "up", "amount": 3}, (100, 100), "")
            agent._execute({"action": "scroll", "direction": "down", "amount": 4}, (100, 100), "")
        self.assertEqual(recorder.scrolls, [3, -4])

    def test_abort_flag_is_observed(self):
        with tempfile.TemporaryDirectory() as run_dir:
            agent = Agent(object(), object(), RecordingHands(), eyes=object(), run_dir=run_dir)
            open(os.path.join(run_dir, "ABORT"), "w").close()
            self.assertTrue(agent._abort_requested())

    def test_execution_error_releases_held_input(self):
        class Planner:
            def decide(self, *args):
                return {"action": "unknown"}, ""

        class Eyes:
            def __init__(self, frame):
                self.frame = frame

            def capture(self):
                return self.frame

            def dims(self, frame):
                return 100, 100

        with tempfile.TemporaryDirectory() as run_dir:
            frame = os.path.join(run_dir, "frame.jpg")
            with open(frame, "wb") as image:
                image.write(b"not-a-real-jpeg")
            recorder = RecordingHands()
            agent = Agent(Planner(), object(), recorder, eyes=Eyes(frame), run_dir=run_dir)
            agent.run("test", "", max_steps=1)
        self.assertEqual(recorder.releases, 1)


if __name__ == "__main__":
    unittest.main()
