# pj-print

Driver-free printing to **Brother PocketJet** thermal printers (PJ-600 / PJ-700 / PJ-800 series) on macOS.

Brother's macOS driver for the older PocketJet models is fragile and no longer maintained. This tool sidesteps it entirely: it rasterises a PDF, image or text file to the printer's native bitmap and sends the bytestream over USB, Bluetooth (serial) or a CUPS raw queue, following the *Brother PJ-600/700/800 Series Raster Command Reference*.

Two ways to use it:

| | |
|---|---|
| `pj_print.py` | Command-line tool. Python 3, needs only Pillow (and `pypdfium2` for PDF input). |
| `PJ Print.app` | Point-and-click macOS app for non-technical users. Pick a file, pick a target, done. Ships as a DMG on the [Releases](../../releases) page with Python dependencies bundled. |

<p align="center"><img src="docs/icon-preview.png" width="200" alt="PJ Print icon"></p>

## Supported models

| dpi | Models |
|---|---|
| 300 | PJ-623, PJ-663, PJ-673, PJ-723, PJ-763, PJ-773, PJ-823, PJ-863, PJ-883 |
| 200 | PJ-622, PJ-662, PJ-722, PJ-762, PJ-822, PJ-862 |

Paper: A4, Letter, Legal, A5. Tested on a PJ-663 (USB and Bluetooth).

## Command line

```bash
git clone https://github.com/lukaseliaskaufmann/pj-print.git
cd pj-print
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# render only, check the result first
./pj-print invoice.pdf --preview /tmp/preview.png

# print via a CUPS raw queue (USB)
./pj-print invoice.pdf --model pj663 --cups PJ663

# print via Bluetooth SPP
./pj-print photo.jpg --halftone fs --serial /dev/tty.PJ-663

# write the raw job to a file
./pj-print notes.txt --out job.prn
```

`./pj-print` is a thin wrapper that runs `pj_print.py` with the `.venv` next to it. Run `./pj-print --help` for all options:

* `--model` printer model (default `pj663`), `--paper` a4 / letter / legal / a5
* `--halftone fs` Floyd-Steinberg dithering for photos, `threshold` for crisp text and line art
* `--density 0-255` print darkness (default 120 = level 5), `--formfeed`, `--two-ply`, `--dashline`
* `--scale fit | fit-width | fill`, `--rotate`, `--invert`
* Input: PDF (multi-page), PNG/JPG, plain text, or `-` for stdin

### Setting up a USB queue (once)

```bash
lpinfo -v | grep -i brother
sudo lpadmin -p PJ663 -E -v "usb://Brother/PJ-663?serial=XXXX" -m raw
```

Bluetooth (PJ-663 and other Bluetooth models): pair the printer in System Settings, then a `/dev/tty.PJ-663…` device appears.

Direct libusb output (`--usb`) is also available: `brew install libusb && pip install pyusb`.

## macOS app

Download `PJ-Print-x.y.dmg` from Releases, drag *PJ Print.app* to Applications, open it. The app asks for a file, then lists every reachable target (USB printers found by CUPS, existing print queues, Bluetooth serial devices, or "preview only"). Model, paper, halftone and density are remembered in `~/Library/Preferences/media.marswalk.pjprint.conf`.

The app is a bash + AppleScript launcher (`app/pjprint`) around the same `pj_print.py`. It is unsigned, so on first launch right-click → Open, or run `xattr -dr com.apple.quarantine "/Applications/PJ Print.app"`.

Rebuild it yourself:

```bash
./build-app.sh          # -> dist/PJ-Print-1.0.dmg
```

## How it works

1. The input is rendered to a greyscale bitmap exactly as wide as the printable area (e.g. 2400 dots for A4 at 300 dpi) and split into pages.
2. Each page is thresholded or dithered to 1-bit and packed into raster lines.
3. A job header (`ESC i a`, `ESC @`, density, form-feed mode, width, height) is emitted, then for each line only the non-blank span is sent (`ESC ~ $` left margin + `ESC ~ *` raster data), blank lines are collapsed into multi-line feeds, and the page ends with `ESC ~ FF`.

See the comments in `pj_print.py` for chapter references into Brother's command reference.

## License

MIT
