import json
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

    def test_legacy_pico_wrapper_forwards_the_write_gate(self):
        wrapper = (ROOT / "scripts" / "reflash-pico.sh").read_text()
        self.assertIn('flash-board.sh" pico "$@"', wrapper)

    def test_xiao_case_assets_are_shipped_and_manifold(self):
        case = ROOT / "hardware" / "xiao-rp2040-case"
        expected = (
            "README.md",
            "build_case.py",
            "validate_case.py",
            "ghosthands_xiao_rp2040_bottom.stl",
            "ghosthands_xiao_rp2040_lid.stl",
            "ghosthands_xiao_rp2040_case_print_plate.stl",
            "ghosthands_xiao_rp2040_case.blend",
            "case_parts_preview.png",
            "case_lid_underside_preview.png",
            "validation.json",
        )
        for filename in expected:
            self.assertTrue((case / filename).is_file(), filename)
        report = json.loads((case / "validation.json").read_text())
        for part in ("bottom", "lid", "print_plate"):
            self.assertEqual(report[part]["non_manifold_edges"], 0)
            self.assertEqual(report[part]["boundary_edges"], 0)


if __name__ == "__main__":
    unittest.main()
