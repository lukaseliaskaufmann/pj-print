#!/usr/bin/env python3
"""
pj-print - Treiberersatz fuer Brother PocketJet PJ-600/700/800 Serie auf macOS.

Erzeugt aus PDF / Bild / Text den nativen Raster-Bytestream des Druckers
(Brother PJ-600/700/800 Series Raster Command Reference) und schickt ihn
per USB (CUPS raw queue), serielle Schnittstelle (Bluetooth SPP) oder in
eine Datei.

Abhaengigkeiten:  pip install pillow pypdfium2      (pypdfium2 nur fuer PDF)
"""

import argparse
import os
import subprocess
import sys

# ---------------------------------------------------------------- Modelle ---
# dpi, Druckbereich-Breite in Dots je Papierformat, Seitenlaenge in Rasterzeilen
MODELS = {
    # 300 dpi
    "pj623": 300, "pj663": 300, "pj673": 300,
    "pj723": 300, "pj763": 300, "pj773": 300,
    "pj823": 300, "pj863": 300, "pj883": 300,
    # 200 dpi
    "pj622": 200, "pj662": 200,
    "pj722": 200, "pj762": 200,
    "pj822": 200, "pj862": 200,
}

# Papier -> (Breite Druckbereich in Dots, Laenge in Rasterzeilen)  Quelle: 3.2.2 / 3.2.3
PAPER = {
    300: {
        "a4":     (2400, 3300),
        "letter": (2464, 3200),
        "legal":  (2464, 4100),
        "a5":     (1668, 2289),
    },
    200: {
        "a4":     (1600, 2200),
        "letter": (1632, 2133),
        "legal":  (1632, 2733),
        "a5":     (1111, 1526),
    },
}

# 2-Byte-Werte fuer "Set paper height" (Kap. 5.2) = Laenge Druckbereich
ESC = 0x1B

INVERT = bytes(255 - i for i in range(256))


# ------------------------------------------------------------ Bytestream ----
def le16(v):
    return bytes((v & 0xFF, (v >> 8) & 0xFF))


def build_job_header(width_dots, height_lines, density, formfeed_mode,
                     two_ply=False, dashline=False):
    """Initialisierungsdaten (Kap. 3.1 Punkt 1)."""
    out = bytearray()
    out += b"\x00" * 700                      # Invalid command -> Puffer leeren
    out += bytes((ESC, 0x69, 0x61, 0x00))     # ESC i a 0  -> ESC/P + Raster Mode
    out += bytes((ESC, 0x40))                 # ESC @      -> Initialize
    out += bytes((ESC, 0x7E, 0x70, 1 if two_ply else 0, 0x00))   # 2-ply
    out += bytes((ESC, 0x7E, 0x64, density & 0xFF, 0x00))        # Dichte
    out += bytes((ESC, 0x7E, 0x66, formfeed_mode & 0xFF))        # Form-Feed-Modus
    out += bytes((ESC, 0x7E, 0x2D, 1 if dashline else 0))        # Trennlinie
    out += bytes((ESC, 0x7E, 0x77)) + le16(width_dots // 8)      # Breite in BYTES
    out += bytes((ESC, 0x7E, 0x68)) + le16(height_lines)         # Hoehe in Zeilen
    return bytes(out)


def build_page(packed_rows, row_bytes, skip_blank=True):
    """Eine Seite: Rasterzeilen + Form Feed (Kap. 3.1 Punkt 2 und 3)."""
    out = bytearray()
    pending_feed = 0

    # abschliessende Leerzeilen abschneiden - der Form Feed erledigt den Rest
    last = len(packed_rows) - 1
    while last >= 0 and not any(packed_rows[last]):
        last -= 1

    for row in packed_rows[:last + 1]:
        # fuehrende / abschliessende Leerbytes wegschneiden
        start = 0
        end = row_bytes
        while start < end and row[start] == 0:
            start += 1
        while end > start and row[end - 1] == 0:
            end -= 1

        if start == end:                       # komplett leere Zeile
            pending_feed += 1
            if pending_feed == 255:
                out += bytes((ESC, 0x7E, 0x4A, 255))
                pending_feed = 0
            continue

        if pending_feed:
            out += bytes((ESC, 0x7E, 0x4A, pending_feed))
            pending_feed = 0

        # X-Position bleibt nach einem Zeilenvorschub stehen -> immer setzen
        if not skip_blank:
            start = 0
        out += bytes((ESC, 0x7E, 0x24)) + le16(start * 8)       # Set left margin (Bits)
        chunk = row[start:end]

        out += bytes((ESC, 0x7E, 0x2A)) + le16(len(chunk)) + chunk
        out += bytes((ESC, 0x7E, 0x4A, 1))     # Multi-line feed 1

    # abschliessende Leerzeilen nicht senden - das erledigt der Form Feed
    out += bytes((ESC, 0x7E, 0x0C))            # Form feed
    return bytes(out)


# -------------------------------------------------------------- Rendering ---
def _fit(img, w, h, mode):
    from PIL import Image
    if mode == "fill":
        return img.resize((w, h), Image.LANCZOS)
    ratio = min(w / img.width, h / img.height)
    if mode == "fit-width":
        ratio = w / img.width
    nw, nh = max(1, int(img.width * ratio)), max(1, int(img.height * ratio))
    img = img.resize((nw, nh), Image.LANCZOS)
    canvas = Image.new("L", (w, max(h, nh)), 255)
    canvas.paste(img, ((w - nw) // 2, 0))
    return canvas


def render_pages(path, w, h, dpi, scale_mode, halftone, threshold,
                 rotate, invert_img):
    """-> Liste von PIL-'1'-Bildern, exakt w Pixel breit."""
    from PIL import Image, ImageOps
    ext = os.path.splitext(path)[1].lower()
    pages = []

    if ext == ".pdf":
        try:
            import pypdfium2 as pdfium
        except ImportError:
            sys.exit("Fuer PDF wird pypdfium2 gebraucht:  pip install pypdfium2")
        doc = pdfium.PdfDocument(path)
        for page in doc:
            pil = page.render(scale=dpi / 72).to_pil().convert("L")
            pages.append(pil)
    elif ext in (".txt", ".text", ".md", ""):
        pages.extend(render_text(path, w, h, dpi))
    else:
        pages.append(Image.open(path).convert("L"))

    out = []
    for pil in pages:
        if rotate:
            pil = pil.rotate(rotate, expand=True, fillcolor=255)
        if invert_img:
            pil = ImageOps.invert(pil)
        pil = _fit(pil, w, h, scale_mode)
        # ggf. auf mehrere Seiten aufteilen (langes Bild / fit-width)
        for top in range(0, pil.height, h):
            slice_ = pil.crop((0, top, w, min(top + h, pil.height)))
            if slice_.height < h:
                canvas = Image.new("L", (w, h), 255)
                canvas.paste(slice_, (0, 0))
                slice_ = canvas
            if halftone == "fs":
                bw = slice_.convert("1")                       # Floyd-Steinberg
            else:
                bw = slice_.point(lambda p: 255 if p > threshold else 0).convert("1")
            out.append(bw)
    return out


def render_text(path, w, h, dpi):
    from PIL import Image, ImageDraw, ImageFont
    text = sys.stdin.read() if path == "-" else open(path, encoding="utf-8",
                                                     errors="replace").read()
    size = max(20, int(dpi / 300 * 42))
    font = None
    for cand in ("/System/Library/Fonts/Menlo.ttc",
                 "/System/Library/Fonts/SFNSMono.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"):
        if os.path.exists(cand):
            font = ImageFont.truetype(cand, size)
            break
    if font is None:
        font = ImageFont.load_default()

    line_h = int(size * 1.35)
    margin = int(dpi / 300 * 40)
    max_chars = max(20, (w - 2 * margin) // max(1, font.getbbox("M")[2]))

    lines = []
    for raw in text.splitlines() or [""]:
        raw = raw.replace("\t", "    ")
        while len(raw) > max_chars:
            lines.append(raw[:max_chars])
            raw = raw[max_chars:]
        lines.append(raw)

    per_page = max(1, (h - 2 * margin) // line_h)
    pages = []
    for i in range(0, len(lines), per_page):
        img = Image.new("L", (w, h), 255)
        d = ImageDraw.Draw(img)
        y = margin
        for ln in lines[i:i + per_page]:
            d.text((margin, y), ln, fill=0, font=font)
            y += line_h
        pages.append(img)
    return pages


# ---------------------------------------------------------------- Ausgabe ---
def send_cups(data, queue):
    p = subprocess.run(["lp", "-d", queue, "-o", "raw", "-"], input=data)
    if p.returncode != 0:
        sys.exit(f"lp ist fehlgeschlagen (Queue '{queue}')")


def send_serial(data, dev, chunk=4096):
    import time
    fd = os.open(dev, os.O_WRONLY | os.O_NOCTTY)
    try:
        for i in range(0, len(data), chunk):
            os.write(fd, data[i:i + chunk])
            time.sleep(0.02)          # SPP-Puffer nicht ueberfahren
    finally:
        os.close(fd)


def send_usb(data, vid=0x04F9, pid=None):
    try:
        import usb.core, usb.util
    except ImportError:
        sys.exit("Fuer --usb wird pyusb + libusb gebraucht:\n"
                 "  brew install libusb && pip install pyusb")
    dev = usb.core.find(idVendor=vid, idProduct=pid) if pid else \
          usb.core.find(idVendor=vid)
    if dev is None:
        sys.exit("Kein Brother-Drucker am USB gefunden.")
    dev.set_configuration()
    cfg = dev.get_active_configuration()
    intf = cfg[(0, 0)]
    ep = usb.util.find_descriptor(
        intf, custom_match=lambda e:
        usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT)
    if ep is None:
        sys.exit("Kein OUT-Endpoint gefunden.")
    for i in range(0, len(data), 4096):
        ep.write(data[i:i + 4096], timeout=10000)


# ------------------------------------------------------------------ main ----
def main():
    ap = argparse.ArgumentParser(
        prog="pj-print",
        description="Druckt PDF/Bild/Text auf einem Brother PocketJet "
                    "(PJ-600/700/800) ohne Herstellertreiber.")
    ap.add_argument("file", help="PDF, PNG/JPG, TXT oder '-' fuer stdin")
    ap.add_argument("--model", default="pj663", choices=sorted(MODELS),
                    help="Druckermodell (Default: pj663)")
    ap.add_argument("--paper", default="a4", choices=("a4", "letter", "legal", "a5"))
    ap.add_argument("--density", type=int, default=120,
                    help="0-255, Stufe 0-10 (Default 120 = Stufe 5)")
    ap.add_argument("--formfeed", type=int, default=1, choices=(0, 1, 2, 3),
                    help="0=kein Vorschub 1=feste Seite 2=Seitenende 3=Seitenende+zurueck")
    ap.add_argument("--halftone", default="fs", choices=("fs", "threshold"),
                    help="fs=Floyd-Steinberg (Fotos), threshold=hart (Text/Strich)")
    ap.add_argument("--threshold", type=int, default=160)
    ap.add_argument("--scale", default="fit", choices=("fit", "fit-width", "fill"))
    ap.add_argument("--rotate", type=int, default=0, choices=(0, 90, 180, 270))
    ap.add_argument("--invert", action="store_true", help="Bild invertieren")
    ap.add_argument("--two-ply", action="store_true")
    ap.add_argument("--dashline", action="store_true",
                    help="Trennlinie zwischen Seiten (nur Rollenpapier)")

    g = ap.add_mutually_exclusive_group()
    g.add_argument("--cups", metavar="QUEUE", help="an eine CUPS-Raw-Queue senden (USB)")
    g.add_argument("--serial", metavar="DEV", help="z.B. /dev/tty.PJ-663")
    g.add_argument("--usb", action="store_true", help="direkt per libusb")
    g.add_argument("--out", metavar="FILE", help="Bytestream in Datei schreiben")

    ap.add_argument("--preview", metavar="PNG",
                    help="Rendering als PNG speichern statt/vor dem Drucken")
    args = ap.parse_args()

    dpi = MODELS[args.model]
    width, height = PAPER[dpi][args.paper]
    row_bytes = width // 8
    width = row_bytes * 8          # Rasterzeile muss auf Bytegrenze passen

    pages = render_pages(args.file, width, height, dpi, args.scale,
                         args.halftone, args.threshold, args.rotate, args.invert)
    if not pages:
        sys.exit("Nichts zu drucken.")

    if args.preview:
        base, ext = os.path.splitext(args.preview)
        for i, p in enumerate(pages):
            name = args.preview if len(pages) == 1 else f"{base}-{i+1}{ext or '.png'}"
            p.save(name)
        print(f"Preview: {len(pages)} Seite(n) gespeichert.", file=sys.stderr)

    stream = bytearray(build_job_header(width, height, args.density,
                                        args.formfeed, args.two_ply, args.dashline))
    for p in pages:
        raw = p.tobytes()                      # 1 = weiss -> invertieren
        raw = raw.translate(INVERT)
        rows = [raw[i * row_bytes:(i + 1) * row_bytes] for i in range(height)]
        stream += build_page(rows, row_bytes)
    stream = bytes(stream)

    print(f"{args.model} @ {dpi}dpi, {args.paper}: {len(pages)} Seite(n), "
          f"{width}x{height} Dots, {len(stream)} Bytes", file=sys.stderr)

    if args.out:
        open(args.out, "wb").write(stream)
    elif args.cups:
        send_cups(stream, args.cups)
    elif args.serial:
        send_serial(stream, args.serial)
    elif args.usb:
        send_usb(stream)
    elif not args.preview:
        sys.stdout.buffer.write(stream)


if __name__ == "__main__":
    main()
