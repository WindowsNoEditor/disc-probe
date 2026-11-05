#!/usr/bin/env python3
# Probe pattern for calibrating a NEW CD-R model with one disc (spec 6.1: the probe disc), burned with
# nominal parameters that may be far from the truth.
#
#   python -I make_probe_pattern.py [--band R0 R1] [--size 4096] [--out PNG] [--preview PNG]
#
# Image frame = the app's: x right, y down, angle = atan2(y, x), i.e. clockwise on screen = along the track
# = the data-side view, unmirrored. The larger image side spans 2*R1 mm, as an app layer at 100 % scale does
# when R1 is the project's CD outer radius at import time (DesignLayerViewModel.LoadImage). Enter the burn
# radii before importing the pattern; import it at 100 %, zero offset, zero rotation, as the only layer.
#
# Features (binary: black lines on white):
#   - 12 solid straight spokes every 30 deg (0, 30, ..., 330), 0.45 mm wide, from the band start R0 to the
#     band end R1 (flat ends).
#   - Rings 0.30 mm wide at every multiple of 5 mm inside the band, plus one ring at each band edge, drawn
#     just inside the band ([R0, R0+0.3] and [R1-0.3, R1]). A multiple of 5 closer than 1.3 mm to a band edge
#     is left out (it would merge with the edge ring).
#   - One short radial tick at each ring, at 10 deg (10 deg clockwise of spoke 0, 20 deg counter-clockwise of
#     spoke 30), 0.45 mm wide and 1.6 mm long, centred on the ring; at an edge ring it starts at the edge and
#     points into the band. A twisted disc keeps the tick next to spoke 0's arm at every ring, so the arms can
#     be numbered ring by ring and counted between rings.
#   - A chirality glyph "F" in the ring gap nearest the band middle, centred on 195 deg (between spokes 180
#     and 210). It is built from three polar strokes: a radial stem and two arcs (the bars) that leave the stem
#     clockwise. Up = outward, right = clockwise: with the F turned to 12 o'clock it reads as a normal F when
#     the view is the data side, unmirrored. A twist rotates each radius as a whole, so the arcs stay arcs and
#     keep pointing clockwise; the glyph only shears.
#   - Optional (--gauge, off by default): a twist gauge. Everything in the half band from 105 to 285 deg
#     (clockwise) is inverted (XOR with a half-plane whose straight edges lie at 105 and 285 deg, 15 deg from the
#     nearest spokes). Thin spokes turn into hairlines once the twist exceeds about half a turn (burn radii about
#     1 um off the truth); the half-plane turns into a two-start spiral of light and dark bands that stays visible
#     up to about 50 turns (about 100 um off). See predict_disc.py for the widths.
# The PNG carries its feature list as JSON in a tEXt chunk 'DiscImageStudio-probe-pattern'; predict_disc.py
# reads it.
import argparse, json, math, os, struct, sys, zlib

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
TEXT_KEY = 'DiscImageStudio-probe-pattern'


def png_bytes(w, h, rows, texts=None):
    """8-bit grayscale PNG, filter 0 on every row."""
    raw = b''.join(b'\x00' + r for r in rows)

    def chunk(t, d):
        c = struct.pack('>I', len(d)) + t + d
        return c + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    out = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 0, 0, 0, 0))
    for k, v in (texts or {}).items():
        out += chunk(b'tEXt', k.encode('latin-1') + b'\x00' + v.encode('latin-1'))
    return out + chunk(b'IDAT', zlib.compress(raw, 9)) + chunk(b'IEND', b'')


class Raster:
    """Binary canvas; pixel (i, j) has its centre at ((i + 0.5 - W/2) * mmpx, (j + 0.5 - W/2) * mmpx) mm."""

    def __init__(self, size, span_mm):
        self.W = size
        self.mmpx = 2.0 * span_mm / size
        self.px = bytearray(b'\xff') * (size * size)

    def col_range(self, lo, hi):
        i0 = max(0, int(math.ceil(lo / self.mmpx + self.W / 2 - 0.5)))
        i1 = min(self.W - 1, int(math.floor(hi / self.mmpx + self.W / 2 - 0.5)))
        return i0, i1

    def ycoord(self, j):
        return (j + 0.5 - self.W / 2) * self.mmpx

    def fill_row(self, j, i0, i1):
        if i1 >= i0:
            self.px[j * self.W + i0: j * self.W + i1 + 1] = bytes(i1 - i0 + 1)

    def strip(self, angle_deg, s0, s1, width):
        """Rectangle along direction angle: s0 <= p.u <= s1, |p.n| <= width/2 (u = (cos, sin), n = (-sin, cos))."""
        a = math.radians(angle_deg)
        ux, uy = math.cos(a), math.sin(a)
        hw = width / 2
        ys = [s * uy + t * ux for s in (s0, s1) for t in (-hw, hw)]
        j0, j1 = self.col_range(min(ys), max(ys))
        for j in range(j0, j1 + 1):
            y = self.ycoord(j)
            lo, hi = -1e9, 1e9
            for a_, b_, vlo, vhi in ((ux, y * uy, s0, s1), (-uy, y * ux, -hw, hw)):
                if abs(a_) < 1e-15:
                    if not (vlo <= b_ <= vhi):
                        lo, hi = 1.0, 0.0
                    continue
                xa, xb = sorted(((vlo - b_) / a_, (vhi - b_) / a_))
                lo, hi = max(lo, xa), min(hi, xb)
            if lo <= hi:
                self.fill_row(j, *self.col_range(lo, hi))

    def annulus(self, r_lo, r_hi):
        j0, j1 = self.col_range(-r_hi, r_hi)
        for j in range(j0, j1 + 1):
            y = self.ycoord(j)
            if abs(y) > r_hi:
                continue
            xo = math.sqrt(r_hi * r_hi - y * y)
            if abs(y) < r_lo:
                xi = math.sqrt(r_lo * r_lo - y * y)
                self.fill_row(j, *self.col_range(-xo, -xi))
                self.fill_row(j, *self.col_range(xi, xo))
            else:
                self.fill_row(j, *self.col_range(-xo, xo))

    def sector(self, r_lo, r_hi, a_lo_deg, a_hi_deg):
        """Annular sector r_lo <= r <= r_hi, a_lo <= angle <= a_hi (degrees, clockwise on screen)."""
        mid = math.radians((a_lo_deg + a_hi_deg) / 2)
        half = math.radians((a_hi_deg - a_lo_deg) / 2)
        pts = [(r * math.cos(mid + t * half), r * math.sin(mid + t * half))
               for r in (r_lo, r_hi) for t in [k / 8 - 1 for k in range(17)]]
        i0, i1 = self.col_range(min(p[0] for p in pts) - self.mmpx, max(p[0] for p in pts) + self.mmpx)
        j0, j1 = self.col_range(min(p[1] for p in pts) - self.mmpx, max(p[1] for p in pts) + self.mmpx)
        for j in range(j0, j1 + 1):
            y = self.ycoord(j)
            for i in range(i0, i1 + 1):
                x = (i + 0.5 - self.W / 2) * self.mmpx
                r = math.hypot(x, y)
                if r_lo <= r <= r_hi and abs(math.remainder(math.atan2(y, x) - mid, 2 * math.pi)) <= half:
                    self.px[j * self.W + i] = 0

    def invert_halfplane(self, edge_deg, r_lo, r_hi):
        """Invert pixels with r_lo <= r <= r_hi on the clockwise side of the diameter at edge_deg
        (the half from edge_deg to edge_deg + 180 deg, clockwise on screen)."""
        a = math.radians(edge_deg)
        nx, ny = -math.sin(a), math.cos(a)            # n.p > 0 on that side
        inv = bytes(255 - v for v in range(256))
        j0, j1 = self.col_range(-r_hi, r_hi)
        for j in range(j0, j1 + 1):
            y = self.ycoord(j)
            if abs(y) > r_hi:
                continue
            xo = math.sqrt(r_hi * r_hi - y * y)
            parts = [(-xo, xo)]
            if abs(y) < r_lo:
                xi = math.sqrt(r_lo * r_lo - y * y)
                parts = [(-xo, -xi), (xi, xo)]
            for lo, hi in parts:
                # n.p = nx x + ny y > 0
                if abs(nx) < 1e-15:
                    if ny * y <= 0:
                        continue
                elif nx > 0:
                    lo = max(lo, -ny * y / nx)
                else:
                    hi = min(hi, -ny * y / nx)
                if lo <= hi:
                    i0, i1 = self.col_range(lo, hi)
                    if i1 >= i0:
                        k0, k1 = j * self.W + i0, j * self.W + i1 + 1
                        self.px[k0:k1] = self.px[k0:k1].translate(inv)

    def rows(self):
        return [bytes(self.px[j * self.W:(j + 1) * self.W]) for j in range(self.W)]


def design(r0, r1, spoke_w=0.45, ring_w=0.30, ring_step=5.0, edge_gap=1.3, tick_angle=10.0, tick_len=1.6,
           tick_w=0.45, glyph_angle=195.0, glyph_h=3.6, glyph_w=2.8, glyph_st=0.6, nspokes=12, gauge=False,
           gauge_edge=105.0):
    """Feature list in image mm (also written into the PNG)."""
    if not (0 < r0 < r1):
        raise SystemExit('band must satisfy 0 < R0 < R1')
    rings = [{'r': r0 + ring_w / 2, 'width': ring_w, 'edge': 'inner'}]
    k = math.ceil(r0 / ring_step)
    while k * ring_step < r1:
        R = k * ring_step
        if R - r0 >= edge_gap and r1 - R >= edge_gap:
            rings.append({'r': R, 'width': ring_w, 'edge': None})
        k += 1
    rings.append({'r': r1 - ring_w / 2, 'width': ring_w, 'edge': 'outer'})
    ticks = []
    for rg in rings:
        if rg['edge'] == 'inner':
            a, b = r0, r0 + tick_len
        elif rg['edge'] == 'outer':
            a, b = r1 - tick_len, r1
        else:
            a, b = rg['r'] - tick_len / 2, rg['r'] + tick_len / 2
        ticks.append({'ring': rg['r'], 'angle': tick_angle, 'r0': a, 'r1': b, 'width': tick_w})
    # glyph: in the ring gap whose middle is nearest the band middle and that is wide enough
    gaps = []
    for ra, rb in zip(rings, rings[1:]):
        lo, hi = ra['r'] + ra['width'] / 2, rb['r'] - rb['width'] / 2
        if hi - lo >= glyph_h + 0.8:
            gaps.append(((lo + hi) / 2, lo, hi))
    if not gaps:
        raise SystemExit('no ring gap is wide enough for the glyph')
    mid = (r0 + r1) / 2
    gc = min(gaps, key=lambda g: abs(g[0] - mid))[0]
    spokes = [{'angle': 360.0 * i / nspokes, 'r0': r0, 'r1': r1, 'width': spoke_w} for i in range(nspokes)]
    feat = {'version': 1, 'band': [r0, r1], 'span_mm': r1, 'spokes': spokes, 'rings': rings, 'ticks': ticks,
            'glyph': {'char': 'F', 'style': 'polar', 'r': gc, 'angle': glyph_angle, 'height': glyph_h,
                      'width': glyph_w, 'stroke': glyph_st, 'mid_bar': 0.8, 'mid_bar_v': 0.05},
            'frame': 'x right, y down, angle = atan2(y, x) clockwise on screen (data side, unmirrored); '
                     'image spans +-span_mm at 100 % scale'}
    if gauge:
        feat['gauge'] = {'type': 'halfplane-xor', 'edges': [gauge_edge, gauge_edge + 180.0],
                         'inverted': [gauge_edge, gauge_edge + 180.0], 'r0': r0, 'r1': r1}
    return feat


def glyph_strokes(g):
    """F as three annular sectors (r_lo, r_hi, a_lo, a_hi) in degrees; up = outward, right = clockwise."""
    rc, ac, h, wd, st = g['r'], g['angle'], g['height'], g['width'], g['stroke']
    left = ac - math.degrees(wd / 2 / rc)
    right = ac + math.degrees(wd / 2 / rc)
    stem = (rc - h / 2, rc + h / 2, left, left + math.degrees(st / rc))
    top = (rc + h / 2 - st, rc + h / 2, left, right)
    vm = rc + g['mid_bar_v'] * h
    midb = (vm - st / 2, vm + st / 2, left, left + math.degrees(g['mid_bar'] * wd / rc))
    return [stem, top, midb]


def render(feat, size):
    ras = Raster(size, feat['span_mm'])
    for sp in feat['spokes']:
        ras.strip(sp['angle'], sp['r0'], sp['r1'], sp['width'])
    for rg in feat['rings']:
        ras.annulus(rg['r'] - rg['width'] / 2, rg['r'] + rg['width'] / 2)
    for tk in feat['ticks']:
        ras.strip(tk['angle'], tk['r0'], tk['r1'], tk['width'])
    for s in glyph_strokes(feat['glyph']):
        ras.sector(*s)
    if 'gauge' in feat:
        g = feat['gauge']
        ras.invert_halfplane(g['edges'][0], g['r0'], g['r1'])
    return ras


def preview(ras, n):
    """Box-filtered n x n preview (gray)."""
    W = ras.W
    f = W // n
    rows = []
    for j in range(n):
        acc = [0] * n
        for jj in range(j * f, (j + 1) * f):
            row = ras.px[jj * W:(jj + 1) * W]
            for i in range(n):
                acc[i] += sum(row[i * f:(i + 1) * f])
        rows.append(bytes(int(a / (f * f) + 0.5) for a in acc))
    return rows


def main():
    ap = argparse.ArgumentParser(description='Probe pattern for one-disc calibration of a new CD-R model.')
    ap.add_argument('--band', nargs=2, type=float, default=[24.92, 57.84], metavar=('R0', 'R1'),
                    help='band start and end in mm = the burn values ri/ro (default 24.92 57.84)')
    ap.add_argument('--size', type=int, default=4096)
    ap.add_argument('--out', default=os.path.join(HERE, '..', 'patterns', 'probe_pattern_4096.png'))
    ap.add_argument('--preview', help='optional box-filtered 512 px preview PNG')
    ap.add_argument('--tick-angle', type=float, default=10.0)
    ap.add_argument('--glyph-angle', type=float, default=195.0)
    ap.add_argument('--gauge', action='store_true',
                    help='add the half-plane twist gauge (invert 105..285 deg); for burns far from the truth')
    a = ap.parse_args()
    feat = design(a.band[0], a.band[1], tick_angle=a.tick_angle, glyph_angle=a.glyph_angle, gauge=a.gauge)
    feat['size_px'] = a.size
    ras = render(feat, a.size)
    with open(a.out, 'wb') as f:
        f.write(png_bytes(a.size, a.size, ras.rows(), {TEXT_KEY: json.dumps(feat, separators=(',', ':'))}))
    print(f'wrote {os.path.abspath(a.out)}: {a.size}x{a.size} px, {ras.mmpx * 1000:.4f} um/px, '
          f'spans +-{feat["span_mm"]} mm at 100 % scale')
    print(f'band {feat["band"][0]} .. {feat["band"][1]} mm; spokes: {len(feat["spokes"])} x 0.45 mm at '
          + ' '.join(f'{s["angle"]:g}' for s in feat['spokes']) + ' deg')
    print('rings (centre mm): ' + ' '.join(f'{r["r"]:.2f}' + ('(edge)' if r['edge'] else '') for r in feat['rings']))
    print(f'ticks: at {feat["ticks"][0]["angle"]:g} deg, 1.6 mm long; glyph F at r = {feat["glyph"]["r"]:.2f} mm, '
          f'{feat["glyph"]["angle"]:g} deg')
    if 'gauge' in feat:
        print('twist gauge: band inverted from {:g} to {:g} deg (clockwise)'.format(*feat['gauge']['edges']))
    if a.preview:
        n = 512
        with open(a.preview, 'wb') as f:
            f.write(png_bytes(n, n, preview(ras, n)))
        print(f'wrote preview {os.path.abspath(a.preview)}')


if __name__ == '__main__':
    main()
