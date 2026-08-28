#!/usr/bin/env bash
# Flash a supported RP2040 board on macOS with the exact board-specific
# CircuitPython image, then install the ghosthands firmware.
set -euo pipefail

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
FIRMWARE_DIR="$SCRIPT_DIR/firmware"
CP_VERSION="10.2.1"
BOARD="${1:-}"
MODE="${2:-}"

case "$BOARD" in
  qtpy-rp2040)
    BOARD_NAME="Adafruit QT Py RP2040"
    BOARD_SLUG="adafruit_qtpy_rp2040"
    UF2_SHA256="204013349c233a1ee09c7f69c59c846a566736b964dfecd70df3a9617656f92d"
    ;;
  xiao-rp2040)
    BOARD_NAME="Seeed Studio XIAO RP2040"
    BOARD_SLUG="seeeduino_xiao_rp2040"
    UF2_SHA256="b685e2ffa51e62f3ddebe12278fb013e764a87b0a011de1af1320ee17b5de2fe"
    ;;
  pico)
    BOARD_NAME="Raspberry Pi Pico"
    BOARD_SLUG="raspberry_pi_pico"
    UF2_SHA256="4568ecbf69a4623ec5bfcbf9efc983e9d264c7b0d4ab56f14fe336543c708318"
    ;;
  *)
    echo "Usage: scripts/flash-board.sh qtpy-rp2040|xiao-rp2040|pico [--write]" >&2
    exit 2
    ;;
esac
if [ -n "$MODE" ] && [ "$MODE" != "--write" ]; then
  echo "Unknown option: $MODE" >&2
  exit 2
fi

if [ "$(uname -s)" != "Darwin" ]; then
  echo "This installer currently supports macOS only." >&2
  exit 2
fi
if [ ! -f "$FIRMWARE_DIR/boot.py" ] || [ ! -f "$FIRMWARE_DIR/code.py" ]; then
  echo "Firmware files are missing from $FIRMWARE_DIR" >&2
  exit 1
fi
if [ ! -f "$FIRMWARE_DIR/lib/adafruit_hid/keyboard.py" ] || [ ! -f "$FIRMWARE_DIR/lib/adafruit_hid/keycode.py" ]; then
  echo "Bundled adafruit_hid firmware library is incomplete; refusing to flash." >&2
  exit 1
fi

UF2_URL="https://downloads.circuitpython.org/bin/$BOARD_SLUG/en_US/adafruit-circuitpython-$BOARD_SLUG-en_US-$CP_VERSION.uf2"
STAGING_DIR=$(mktemp -d "${TMPDIR:-/tmp}/ghosthands-flash.XXXXXX")
UF2_PATH="$STAGING_DIR/circuitpython.uf2"
trap 'rm -rf "$STAGING_DIR"' EXIT

wait_volume() {
  local names="$1" timeout="${2:-90}" elapsed=0 node="" name=""
  MOUNT_PATH=""
  while [ "$elapsed" -lt "$timeout" ]; do
    for name in $names; do
      node=$(diskutil list 2>/dev/null | awk -v name="$name" '$0 ~ name {print $NF}' | grep -E '^disk[0-9]' | head -1 || true)
      if [ -n "$node" ]; then
        diskutil mount "$node" >/dev/null 2>&1 || true
      fi
      if [ -d "/Volumes/$name" ]; then
        MOUNT_PATH="/Volumes/$name"
        echo "  $name mounted"
        return 0
      fi
    done
    sleep 1
    elapsed=$((elapsed + 1))
  done
  return 1
}

echo "Board: $BOARD_NAME"
echo "CircuitPython: $CP_VERSION"
echo "Image: $UF2_URL"
echo "SHA-256: $UF2_SHA256"
if [ "$MODE" != "--write" ]; then
  echo "Plan only; no board was touched. Re-run with --write when the exact board is connected."
  exit 0
fi
if [ "${GH_FLASH_ASSUME_YES:-0}" != "1" ]; then
  read -r -p "Flash this exact board? [y/N] " reply
  case "$reply" in
    y|Y|yes|YES) ;;
    *) echo "Cancelled."; exit 1 ;;
  esac
fi

echo "[1/5] downloading the board-specific CircuitPython image..."
curl --fail --location --retry 3 --output "$UF2_PATH" "$UF2_URL"
ACTUAL_SHA256=$(shasum -a 256 "$UF2_PATH" | awk '{print $1}')
if [ "$ACTUAL_SHA256" != "$UF2_SHA256" ]; then
  echo "CircuitPython checksum mismatch; refusing to flash." >&2
  exit 1
fi

echo "[2/5] waiting for RPI-RP2. Hold BOOT/BOOTSEL while connecting the board."
if ! wait_volume "RPI-RP2 RP1-RP2" 90; then
  echo "RPI-RP2 did not appear. Hold BOOT, then connect or tap RESET." >&2
  exit 1
fi

echo "[3/5] installing CircuitPython..."
cp "$UF2_PATH" "$MOUNT_PATH/"
sync

echo "[4/5] waiting for CIRCUITPY..."
if ! wait_volume "CIRCUITPY" 90; then
  echo "CIRCUITPY did not appear after the UF2 was copied." >&2
  exit 1
fi
sleep 2

echo "[5/5] installing ghosthands firmware..."
mkdir -p /Volumes/CIRCUITPY/lib
cp -R "$FIRMWARE_DIR/lib/." /Volumes/CIRCUITPY/lib/
cp "$FIRMWARE_DIR/code.py" /Volumes/CIRCUITPY/code.py
cp "$FIRMWARE_DIR/boot.py" /Volumes/CIRCUITPY/boot.py
sync
diskutil eject /Volumes/CIRCUITPY >/dev/null

echo "Done. Unplug and reconnect the board normally, then run: ghosthands --doctor --ping"
