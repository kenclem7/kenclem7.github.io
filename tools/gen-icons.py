#!/usr/bin/env python3
"""Generate /apple-touch-icon.png (180x180) and /favicon.ico (32x32, PNG-in-ICO) for
kenclements.com. Stdlib only; rerun only if the icon design changes, then commit both.

Design: the site's own materials - flat UI blue (#1976d2), white temperature curve,
warm sun disc. Rendered supersampled and box-downsampled for clean edges. Safari renders
no SVG-data-URI favicons (the emoji icons stay for Chrome/Firefox tabs), the home-screen
tile uses the PNG, and a real /favicon.ico satisfies the probe everywhere else.
See DESIGN.md section 1."""
import math
import os
import struct
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BLUE = (0x19, 0x76, 0xD2)
WHITE = (0xFF, 0xFF, 0xFF)
SUN = (0xFF, 0xC2, 0x4D)


def render(size, ss=4):
    big = size * ss
    sun_cx, sun_cy, sun_r = 0.70, 0.30, 0.155
    curve_y, curve_amp, thick = 0.635, 0.130, 0.062
    rows = []
    for y in range(big):
        row = bytearray()
        for x in range(big):
            u = (x + 0.5) / big
            v = (y + 0.5) / big
            c = BLUE
            if math.hypot(u - sun_cx, v - sun_cy) <= sun_r:
                c = SUN
            cy = curve_y - curve_amp * math.sin((u * 1.35 + 0.07) * 2 * math.pi * 0.55)
            if abs(v - cy) <= thick / 2:
                c = WHITE
            row += bytes(c)
        rows.append(bytes(row))
    out = []
    for oy in range(size):
        row = bytearray()
        for ox in range(size):
            r = g = b = 0
            for sy in range(ss):
                src = rows[oy * ss + sy]
                base = ox * ss * 3
                for sx in range(ss):
                    r += src[base + sx * 3]
                    g += src[base + sx * 3 + 1]
                    b += src[base + sx * 3 + 2]
            n = ss * ss
            row += bytes((r // n, g // n, b // n))
        out.append(bytes(row))
    return out


def png(size, rows):
    def chunk(tag, data):
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + r for r in rows)
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def ico(png_bytes, size):
    entry = struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(png_bytes), 22)
    return struct.pack("<HHH", 0, 1, 1) + entry + png_bytes


touch = png(180, render(180))
with open(os.path.join(ROOT, "apple-touch-icon.png"), "wb") as f:
    f.write(touch)
fav = ico(png(32, render(32, ss=6)), 32)
with open(os.path.join(ROOT, "favicon.ico"), "wb") as f:
    f.write(fav)
print("apple-touch-icon.png: %d bytes; favicon.ico: %d bytes" % (len(touch), len(fav)))
