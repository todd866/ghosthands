from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DistributionTests(unittest.TestCase):
    def test_pinned_board_images_are_present(self):
        script = (ROOT / "scripts" / "flash-board.sh").read_text()
        self.assertIn("204013349c233a1ee09c7f69c59c846a566736b964dfecd70df3a9617656f92d", script)
        self.assertIn("b685e2ffa51e62f3ddebe12278fb013e764a87b0a011de1af1320ee17b5de2fe", script)
        self.assertIn("4568ecbf69a4623ec5bfcbf9efc983e9d264c7b0d4ab56f14fe336543c708318", script)

    def test_flashed_hid_library_is_bundled(self):
        library = ROOT / "scripts" / "firmware" / "lib" / "adafruit_hid"
        self.assertTrue((library / "keyboard.py").is_file())
        self.assertTrue((library / "keyboard_layout_us.py").is_file())
        self.assertTrue((library / "keycode.py").is_file())

    def test_firmware_uses_honest_identity_and_exact_typing(self):
        boot = (ROOT / "scripts" / "firmware" / "boot.py").read_text()
        code = (ROOT / "scripts" / "firmware" / "code.py").read_text()
        self.assertNotIn("0x046D", boot)
        self.assertNotIn("Logitech", boot)
        self.assertIn("TYPE_TYPO_PROB = 0.0", code)
        self.assertIn("usb_cdc.enable(console=True, data=False)", boot)


if __name__ == "__main__":
    unittest.main()
