#!/usr/bin/env python3
"""Pre-distort a full-disc CD design PNG so that radial lines burn straight (standard library only).

Burned with the constant-pitch radii of the timing fit (model F: r0 = 24.9216305, r1 = 57.8390244 mm),
the picture shows a reproducible S-bend: the content of image angle phi lands at disc angle
phi + E(r), with E in degrees and + meaning "further along the track" = clockwise in the app
preview (x right, y down, phi = atan2(y, x)). This tool writes an image whose pixel at (r, phi) is
the input pixel at (r, phi + E(r)) (bilinear), so the burn puts every input pixel back on its own
radius line.

    python -I prewarp.py in.png out.png [--r1 57.8390244] [--coeffs c0,c1,c2,c3,c4] [--const -0.2670]
                         [--input-r1 MM] [--size N] [--rmin 25.0] [--rmax 58.0] [--jobs N] [--table]

E(r) = sum_k c_k X^k + const, X = (r - 41.25) / 16.25, r in mm (defaults: the measured S-bend).
Geometry: the image centre is the disc centre and its larger side spans 2*r1 mm, which is how the
app places a design layer at 100 % scale (fit rule: larger side = 2 x project outer radius).
--input-r1 is the input's half-width when it differs from r1, e.g. 57.5 for the app's own
composite (design-composite-cd-export.png); the output then spans +-r1 and imports at 100 %.
Pixels outside rmin..rmax stay unchanged (copied; resampled only when the geometry changes).
Input: 8-bit gray, gray+alpha, RGB, RGBA or palette PNG (1/2/4/8-bit gray and palette, 16-bit
reduced to 8), non-interlaced, every PNG filter type. Output: 8-bit PNG with the input's channels
(palette expanded), filter 0. Channels, alpha included, are interpolated independently; the CD
engine itself reads only RGB luminance (RasterImage.cs).
Speed (one process, 4096 x 4096): ~14 s gray, ~25 s RGB, ~30 s RGBA; app composite 8192 -> 4096
RGBA ~50 s. --jobs N splits the rows over N processes (each gets a copy of the input).
"""
import argparse, math, struct, sys, time, zlib

DEFAULT_COEFFS = [-0.05078, -1.99834, 2.03311, 3.09415, -1.85344]
DEFAULT_CONST = -0.2670
DEFAULT_R1 = 57.8390244
XC, XS = 41.25, 16.25
PNG_SIG = b'\x89PNG\r\n\x1a\n'


# ---------------------------------------------------------------- PNG reading
def _unfilter(raw, h, stride, bpp):
    out = bytearray(h * stride)
    prev = bytes(stride)
    # Byte-lane (SWAR) addition on whole rows held as big integers: (a + b) mod 256 per byte.
    m7 = int.from_bytes(b'\x7f' * stride, 'big')
    m8 = int.from_bytes(b'\x80' * stride, 'big')

    def lanes_add(a, b):
        return ((a & m7) + (b & m7)) ^ ((a ^ b) & m8)
    pos = 0
    for y in range(h):
        ft = raw[pos]
        line = raw[pos + 1:pos + 1 + stride]
        pos += 1 + stride
        if len(line) != stride:
            raise ValueError('truncated image data')
        if ft == 0:
            cur = line
        elif ft == 1:                                   # Sub: prefix scan over pixels
            s = int.from_bytes(line, 'big')
            k = bpp
            while k < stride:
                s = lanes_add(s, s >> (8 * k))
                k *= 2
            cur = s.to_bytes(stride, 'big')
        elif ft == 2:                                   # Up
            cur = lanes_add(int.from_bytes(line, 'big'), int.from_bytes(prev, 'big')).to_bytes(stride, 'big')
        elif ft == 3:                                   # Average
            cur = bytearray(line)
            for i in range(min(bpp, stride)):
                cur[i] = (cur[i] + (prev[i] >> 1)) & 255
            for i in range(bpp, stride):
                cur[i] = (cur[i] + ((cur[i - bpp] + prev[i]) >> 1)) & 255
        elif ft == 4:                                   # Paeth
            cur = bytearray(line)
            for i in range(min(bpp, stride)):
                cur[i] = (cur[i] + prev[i]) & 255
            for i in range(bpp, stride):
                a = cur[i - bpp]; b = prev[i]; c = prev[i - bpp]
                pa = b - c if b > c else c - b
                pb = a - c if a > c else c - a
                pc = a + b - c - c
                if pc < 0:
                    pc = -pc
                if pa <= pb and pa <= pc:
                    cur[i] = (cur[i] + a) & 255
                elif pb <= pc:
                    cur[i] = (cur[i] + b) & 255
                else:
                    cur[i] = (cur[i] + c) & 255
        else:
            raise ValueError(f'invalid PNG filter type {ft} in row {y}')
        out[y * stride:(y + 1) * stride] = cur
        prev = cur
    return out


def _unpack_bits(rows, w, h, depth, stride):
    """Sub-byte samples -> one byte per sample (values 0 .. 2^depth-1)."""
    per = 8 // depth
    mask = (1 << depth) - 1
    table = [bytes((b >> (8 - depth * (k + 1))) & mask for k in range(per)) for b in range(256)]
    out = bytearray(w * h)
    for y in range(h):
        row = b''.join(table[b] for b in rows[y * stride:(y + 1) * stride])
        out[y * w:(y + 1) * w] = row[:w]
    return out


def read_png(path):
    """Returns (width, height, channels, pixels) with 8-bit samples, channels 1/2/3/4."""
    with open(path, 'rb') as f:
        data = f.read()
    if data[:8] != PNG_SIG:
        raise ValueError(f'{path}: not a PNG file')
    pos, ihdr, plte, trns, idat = 8, None, None, None, []
    while pos + 8 <= len(data):
        ln, typ = struct.unpack('>I4s', data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + ln]
        pos += 12 + ln
        if typ == b'IHDR':
            ihdr = struct.unpack('>IIBBBBB', body)
        elif typ == b'PLTE':
            plte = body
        elif typ == b'tRNS':
            trns = body
        elif typ == b'IDAT':
            idat.append(body)
        elif typ == b'IEND':
            break
    if ihdr is None or not idat:
        raise ValueError(f'{path}: missing IHDR or IDAT')
    w, h, depth, ctype, comp, filt, interlace = ihdr
    if interlace:
        raise ValueError(f'{path}: interlaced (Adam7) PNG is not supported; save it without interlacing')
    if comp != 0 or filt != 0:
        raise ValueError(f'{path}: unknown compression/filter method')
    nch = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(ctype)
    if nch is None or (depth < 8 and ctype not in (0, 3)) or depth not in (1, 2, 4, 8, 16) or (ctype == 3 and depth == 16):
        raise ValueError(f'{path}: unsupported PNG (colour type {ctype}, bit depth {depth})')
    raw = zlib.decompress(b''.join(idat))
    bits = nch * depth
    stride = (w * bits + 7) // 8
    bpp = max(1, bits // 8)
    px = _unfilter(raw, h, stride, bpp)
    if depth == 16:
        px = px[0::2]                                   # big-endian high bytes
    elif depth < 8:
        px = _unpack_bits(px, w, h, depth, stride)
        if ctype == 0:                                  # scale gray to 0..255
            scale = 255 // ((1 << depth) - 1)
            px = bytearray(v * scale for v in px)
    if ctype == 3:                                      # palette -> RGB or RGBA
        if plte is None:
            raise ValueError(f'{path}: palette image without PLTE')
        n = len(plte) // 3
        alpha = bytes(trns or b'') + b'\xff' * 256
        if trns:
            lut = [plte[3 * i:3 * i + 3] + alpha[i:i + 1] for i in range(n)] + [b'\0\0\0\xff'] * (256 - n)
            nch = 4
        else:
            lut = [plte[3 * i:3 * i + 3] for i in range(n)] + [b'\0\0\0'] * (256 - n)
            nch = 3
        px = bytearray(b''.join(lut[i] for i in px))
    elif trns is not None:
        print('note: tRNS colour key ignored (the CD engine ignores alpha anyway)', file=sys.stderr)
    return w, h, nch, bytes(px)


def write_png(path, w, h, nch, px, comment=None, level=6):
    ctype = {1: 0, 2: 4, 3: 2, 4: 6}[nch]
    stride = w * nch
    raw = b''.join(b'\x00' + px[y * stride:(y + 1) * stride] for y in range(h))

    def chunk(t, d):
        return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    parts = [PNG_SIG, chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, ctype, 0, 0, 0))]
    if comment:
        parts.append(chunk(b'tEXt', b'Comment\x00' + comment.encode('latin-1', 'replace')))
    parts += [chunk(b'IDAT', zlib.compress(raw, level)), chunk(b'IEND', b'')]
    with open(path, 'wb') as f:
        f.write(b''.join(parts))


# ---------------------------------------------------------------- warp
_S = None   # per-process state


def _init(state):
    global _S
    _S = state


def _warp_rows(y0, y1):
    S = _S
    src, win, hin, nch = S['src'], S['win'], S['hin'], S['nch']
    wout, hout = S['wout'], S['hout']
    mmo, imi = S['mm_out'], 1.0 / S['mm_in']
    rmin2, rmax2 = S['rmin'] ** 2, S['rmax'] ** 2
    k = S['k']                                   # radians, Horner order high -> low after padding
    same = S['same']
    sqrt, cos, sin = math.sqrt, math.cos, math.sin
    wc, hc = wout / 2.0, hout / 2.0
    ucen, vcen = win / 2.0 - 0.5, hin / 2.0 - 0.5
    sin_ = win * nch
    sout = wout * nch
    out = bytearray((y1 - y0) * sout)
    xc, ixs = S['xc'], 1.0 / S['xs']
    links = S.get('links', ())                   # (r_mm, g_mm): beyond r, content lands g mm further along
    generic = len(k) != 5
    if not generic:
        k4, k3, k2, k1, k0 = k
    umax, vmax = win - 1.0, hin - 1.0

    def sample(u, v, o):
        """Bilinear sample at continuous pixel-index coordinates (edge clamped); o = output index."""
        if u < 0.0:
            u = 0.0
        elif u > umax:
            u = umax
        if v < 0.0:
            v = 0.0
        elif v > vmax:
            v = vmax
        iu = int(u); iv = int(v)
        if iu > win - 2:
            iu = max(win - 2, 0)
        if iv > hin - 2:
            iv = max(hin - 2, 0)
        fu = u - iu; fv = v - iv
        iu1 = min(iu + 1, win - 1); iv1 = min(iv + 1, hin - 1)
        for c in range(nch):
            a = src[(iv * win + iu) * nch + c]; b = src[(iv * win + iu1) * nch + c]
            cc = src[(iv1 * win + iu) * nch + c]; d = src[(iv1 * win + iu1) * nch + c]
            t = a + (b - a) * fu
            out[o + c] = int(t + (cc + (d - cc) * fu - t) * fv + 0.5)

    for oy in range(y0, y1):
        yy = (oy + 0.5 - hc) * mmo
        yy2 = yy * yy
        ob = (oy - y0) * sout
        if same:
            # Same pixel grid: copy the row, then redo only the band rmin..rmax.
            out[ob:ob + sout] = src[oy * sin_:(oy + 1) * sin_]
            if yy2 > rmax2:
                continue
            xo = sqrt(rmax2 - yy2)
            xi = sqrt(rmin2 - yy2) if yy2 < rmin2 else 0.0
            lo_out = max(0, int(math.floor(-xo / mmo + wc - 0.5)))
            hi_out = min(wout - 1, int(math.ceil(xo / mmo + wc - 0.5)))
            if xi > 0.0:
                a_ = int(math.ceil(-xi / mmo + wc - 0.5))
                b_ = int(math.floor(xi / mmo + wc - 0.5))
                spans = ((lo_out, min(a_, hi_out)), (max(b_, lo_out), hi_out))
            else:
                spans = ((lo_out, hi_out),)
        else:
            # Different grid or span: every pixel is resampled, identity outside the band.
            spans = ((0, wout - 1),)
        for s0, s1 in spans:
            for ox in range(s0, s1 + 1):
                xx = (ox + 0.5 - wc) * mmo
                r2 = xx * xx + yy2
                if r2 < rmin2 or r2 > rmax2:
                    if same:
                        continue
                    ce, se = 1.0, 0.0
                else:
                    r = sqrt(r2)
                    X = (r - xc) * ixs
                    if generic:
                        e = 0.0
                        for kk in k:
                            e = e * X + kk
                    else:
                        e = (((k4 * X + k3) * X + k2) * X + k1) * X + k0
                    for rl, gl in links:
                        if r > rl:
                            e += gl / r
                    ce = cos(e); se = sin(e)
                u = (xx * ce - yy * se) * imi + ucen
                v = (xx * se + yy * ce) * imi + vcen
                iu = int(u); iv = int(v)
                o = ob + ox * nch
                if u >= 0.0 and v >= 0.0 and iu < win - 1 and iv < hin - 1:
                    fu = u - iu; fv = v - iv
                    if nch == 1:
                        p = iv * win + iu
                        a = src[p]; b = src[p + 1]; c = src[p + win]; d = src[p + win + 1]
                        t = a + (b - a) * fu
                        out[o] = int(t + (c + (d - c) * fu - t) * fv + 0.5)
                    else:
                        p = (iv * win + iu) * nch
                        q = p + sin_
                        for ch in range(nch):
                            a = src[p + ch]; b = src[p + nch + ch]; c = src[q + ch]; d = src[q + nch + ch]
                            t = a + (b - a) * fu
                            out[o + ch] = int(t + (c + (d - c) * fu - t) * fv + 0.5)
                else:
                    sample(u, v, o)
    return bytes(out)


def _work(rng):
    return rng[0], _warp_rows(rng[0], rng[1])


def E_deg(r, coeffs, const, xc=XC, xs=XS, links=()):
    X = (r - xc) / xs
    return (sum(c * X ** i for i, c in enumerate(coeffs)) + const
            + sum(math.degrees(g / r) for rl, g in links if r > rl))


def prewarp(src, win, hin, nch, wout, hout, mm_in, mm_out, coeffs, const, rmin, rmax,
            xc=XC, xs=XS, jobs=1, links=()):
    radc = [math.radians(c) for c in coeffs]
    radc[0] += math.radians(const)
    k = list(reversed(radc))
    if len(k) < 5:
        k = [0.0] * (5 - len(k)) + k
    same = (win == wout and hin == hout and abs(mm_in - mm_out) <= 1e-12 * mm_out)
    state = dict(src=src, win=win, hin=hin, nch=nch, wout=wout, hout=hout, mm_in=mm_in,
                 mm_out=mm_out, rmin=rmin, rmax=rmax, k=k, same=same, xc=xc, xs=xs,
                 links=tuple(links))
    out = bytearray(wout * hout * nch)
    sout = wout * nch
    if jobs <= 1:
        _init(state)
        out[:] = _warp_rows(0, hout)
    else:
        from concurrent.futures import ProcessPoolExecutor
        step = max(16, hout // (jobs * 8))
        chunks = [(y, min(y + step, hout)) for y in range(0, hout, step)]
        with ProcessPoolExecutor(max_workers=jobs, initializer=_init, initargs=(state,)) as ex:
            for y0, block in ex.map(_work, chunks):
                out[y0 * sout:y0 * sout + len(block)] = block
    return bytes(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('input')
    ap.add_argument('output')
    ap.add_argument('--r1', type=float, default=DEFAULT_R1,
                    help='half-width of the OUTPUT image in mm = project outer radius r1 (default %(default)s)')
    ap.add_argument('--input-r1', type=float, default=None,
                    help='half-width of the INPUT image in mm if it differs (57.5 for the app composite)')
    ap.add_argument('--coeffs', default=','.join(f'{c:g}' for c in DEFAULT_COEFFS),
                    help='E(r) polynomial coefficients in degrees, c0,c1,... in X=(r-41.25)/16.25')
    ap.add_argument('--const', type=float, default=DEFAULT_CONST, help='constant added to E(r), degrees')
    ap.add_argument('--rmin', type=float, default=25.0, help='inner edge of the warped band, mm')
    ap.add_argument('--rmax', type=float, default=58.0, help='outer edge of the warped band, mm')
    ap.add_argument('--size', type=int, default=None, help='output size in px (square); default: input size')
    ap.add_argument('--jobs', type=int, default=1, help='worker processes (default 1)')
    ap.add_argument('--table', action='store_true', help='print E(r) and the tangential shift, then continue')
    ap.add_argument('--link', action='append', default=[], metavar='R_MM,G_MM',
                    help='write link (repeatable): beyond radius R the burn lands G mm further along the track '
                         '(+ = clockwise in the preview); the output pre-rotates that part by -G/r. HP BU20N at '
                         '4x: 33.45,0.21. With the test build\'s pitch terms (no S-bend left) add --coeffs 0 --const 0')
    a = ap.parse_args(argv)
    coeffs = [float(v) for v in a.coeffs.replace(' ', '').split(',') if v]
    if not coeffs:
        raise SystemExit('--coeffs needs at least one value')
    if not (0 < a.rmin < a.rmax):
        raise SystemExit('need 0 < rmin < rmax')
    links = []
    for spec in a.link:
        try:
            rl, gl = (float(v) for v in spec.split(','))
        except ValueError:
            raise SystemExit(f'--link {spec!r}: expected R_MM,G_MM, e.g. 33.45,0.21')
        if not (a.rmin <= rl < a.rmax) or abs(gl) > 2.0:
            raise SystemExit(f'--link {spec!r}: radius must lie in the band {a.rmin}..{a.rmax} mm and |G| <= 2 mm')
        links.append((rl, gl))
    if a.table:
        print('  r(mm)   E(deg)   shift of the content r*E (mm)   pre-warp moves pixels by -E')
        for r in (25.0, 25.5, 26, 28, 30, 32, 35, 38, 40, 42, 45, 48, 50, 52, 55, 57, 57.8, 58.0):
            e = E_deg(r, coeffs, a.const, links=links)
            print(f'  {r:5.1f}  {e:+7.3f}   {r * math.radians(e):+7.3f}')
    t0 = time.perf_counter()
    win, hin, nch, src = read_png(a.input)
    t1 = time.perf_counter()
    in_r1 = a.input_r1 if a.input_r1 is not None else a.r1
    mm_in = 2.0 * in_r1 / max(win, hin)
    if a.size:
        wout = hout = a.size
    elif a.input_r1 is not None and abs(in_r1 - a.r1) > 1e-12:
        wout = hout = max(win, hin)
    else:
        wout, hout = win, hin
    mm_out = 2.0 * a.r1 / max(wout, hout)
    if win != hin:
        print(f'note: input is {win}x{hin}, not square; its larger side is taken as 2 x {in_r1} mm', file=sys.stderr)
    if max(wout, hout) > 4096:
        print('note: the app decodes layer images at 4096 px width (DesignComposer.MaxDecodeWidth); '
              '--size 4096 gives the same result faster', file=sys.stderr)
    out = prewarp(src, win, hin, nch, wout, hout, mm_in, mm_out, coeffs, a.const, a.rmin, a.rmax, jobs=a.jobs,
                  links=links)
    t2 = time.perf_counter()
    comment = (f'prewarp.py: out(r,phi) = in(r, phi + E(r)); E(deg) = poly({",".join(f"{c:g}" for c in coeffs)}; '
               f'X=(r-{XC:g})/{XS:g}) {a.const:+g}'
               + ''.join(f' + g/r for r > {rl:g} mm (g = {gl:g} mm)' for rl, gl in links)
               + f'; band {a.rmin:g}..{a.rmax:g} mm; output spans +-{a.r1:g} mm; input spanned +-{in_r1:g} mm')
    write_png(a.output, wout, hout, nch, out, comment)
    t3 = time.perf_counter()
    print(f'{a.input}: {win}x{hin}, {nch} channel(s), {mm_in * 1000:.3f} um/px -> {a.output}: {wout}x{hout}, '
          f'{mm_out * 1000:.3f} um/px, spans +-{a.r1} mm')
    print(f'E(r) at 25.5/40/57 mm: {E_deg(25.5, coeffs, a.const, links=links):+.3f}/'
          f'{E_deg(40, coeffs, a.const, links=links):+.3f}/{E_deg(57, coeffs, a.const, links=links):+.3f} deg; '
          f'band {a.rmin}..{a.rmax} mm' + ''.join(f'; link at {rl:g} mm, {gl:+g} mm' for rl, gl in links))
    print(f'time: read {t1 - t0:.1f} s, warp {t2 - t1:.1f} s ({a.jobs} job(s)), write {t3 - t2:.1f} s')


if __name__ == '__main__':
    main()
