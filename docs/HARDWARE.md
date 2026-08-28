# Hands: build the USB-HID actuator on macOS

Ghosthands needs an RP2040 board with native USB, flashed with CircuitPython and the firmware in
`scripts/firmware/`. It then appears to macOS as a keyboard, absolute-position mouse, and one
serial command port.

## Recommended USB-C boards

| Target | Board | Size | Why choose it |
|---|---|---:|---|
| `qtpy-rp2040` | Adafruit QT Py RP2040 | 21.8 × 17.8 mm | Best documentation, 8 MB flash, separate BOOT and RESET buttons |
| `xiao-rp2040` | Seeed Studio XIAO RP2040 | 21 × 17.8 mm | Smallest and least expensive polished option |
| `pico` | Raspberry Pi Pico | 51 × 21 mm | Original upstream target; Micro-USB |

Buy the board without headers. Use a short, flexible, **data-capable** USB-C-to-C cable rather
than a rigid adapter: a rigid board hanging from a MacBook port creates an avoidable lever arm.
A fitted snap case should leave BOOT/RESET accessible and should not place force on the USB-C
socket.

The compact USB-C targets use official board-specific CircuitPython builds and the same RP2040
USB peripheral as the original Pico. They are supported by the installer, but should be treated
as experimental until the composite keyboard + absolute mouse + CDC setup has been exercised on
the physical board.

## Compact XIAO enclosure

`hardware/xiao-rp2040-case/` contains an original CC0 enclosure for a bare, headerless Seeed
Studio XIAO RP2040. It is approximately 28 × 24.8 × 7.2 mm assembled and provides:

- a wide USB-C opening;
- access to BOOT and RESET;
- an RGB LED window;
- hidden side detents for cap retention; and
- support-free print orientation for a 0.4 mm FDM nozzle.

Upload `ghosthands_xiao_rp2040_case_print_plate.stl` for a one-job print containing both parts.
The directory also includes the separate part STLs, Blender source, generator, validation script,
mesh report, and rendered previews. The generated meshes are watertight and manifold, but this is
a first-print design until it has been physically test-fitted to a board.

The suggested bureau settings are matte PLA, 0.16–0.20 mm layers, three walls, and 20% infill.
See the enclosure README for fit tolerances and the CC0 dedication.

## Install the host software

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
ghosthands --help
```

## Flash the exact board

First inspect the plan; this does not touch a drive:

```bash
scripts/flash-board.sh qtpy-rp2040
# or: scripts/flash-board.sh xiao-rp2040
```

Then run the write explicitly:

```bash
scripts/flash-board.sh qtpy-rp2040 --write
```

The script downloads the pinned CircuitPython 10.2.1 UF2 for that exact board, verifies its
SHA-256 checksum, waits for the RP2040 boot volume, installs CircuitPython, copies only the
ghosthands firmware, and ejects the drive. Do not use a Pico UF2 on a QT Py or XIAO.

The legacy Pico wrapper uses the same explicit write gate:

```bash
scripts/reflash-pico.sh --write
```

To enter the bootloader:

- **QT Py:** hold BOOT, tap RESET, then release BOOT.
- **XIAO:** hold **B**, tap **R**, then release **B**.
- **Pico:** hold BOOTSEL while connecting the USB cable.

After flashing, unplug and reconnect normally, then verify all interfaces:

```bash
ghosthands --doctor --ping
```

If more than one board is connected, select one explicitly:

```bash
ghosthands --doctor --ping --port /dev/cu.usbmodemXXXX
```

## Firmware notes

- The RP2040 endpoint budget is kept to keyboard HID + absolute-mouse HID + one console CDC +
  mass storage. `code.py` uses that one console as its JSON command channel.
- The board retains its honest CircuitPython USB identity; the firmware does not spoof another
  manufacturer's VID/PID.
- Typing uses a US keyboard layout and rejects unsupported characters instead of silently
  dropping them. Exact non-US/Unicode text needs a future layout or clipboard transport.
- Hold BOOT/BOOTSEL during reset to recover from a bad firmware edit.

## Command protocol

One JSON object per line over the serial port at 115200; one matching-ID acknowledgement per
command: `{"move":{"x":0,"y":0}}`, `{"click":"left"}`, `{"type":"..."}`,
`{"key":["cmd","space"]}`, `{"scroll":3}`, `{"ping":1}`, and `{"release_all":1}`.
Coordinates use an absolute 0..32767 grid; ghosthands maps screenshot fractions onto that grid.
