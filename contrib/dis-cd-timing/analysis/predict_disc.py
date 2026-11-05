#!/usr/bin/env python3
# Predicted look of a burned CD-DA picture disc, and the ruler / spiral-arm readings that check it.
#
#   python -I predict_disc.py --burn RI RO [C1 C2 C3] --true RI RO [C1 C2 C3] [--x BYTES] [--sectors N]
#          [--pattern PNG] [--features auto|probe|v2] [--span MM] [--canvas MM] [--contacts RA RB] [--ref-ring R]
#          [--out PNG] [--report TXT] [--json JSON] [--title TEXT]
#   (renders only with --out; the readings always go to stdout)
# Example, probe disc of a new box: --burn <nominal ri ro [c]> --true <fitted ri ro [c]> --x 0
#   --pattern ../patterns/probe_pattern_4096.png --out probe_predicted.png
#
# Physics [I, as spec 6.4]: file byte q (0 .. TotalBytes) carries the image content at the BURN model's
# (r_b(q), theta_b(q)); on the disc it lies at the TRUE model's (r_t(q + x), theta_t(q + x) + kappa), where
# x is the per-drive along-track constant (bytes; 0 on the HP BU20N) and kappa the free rotation of the disc.
# So content the burn model placed at image angle theta lands at the true angle of the same byte:
#   D(q) = theta_t(q + x) - theta_b(q),  image (R, a)  ->  disc (r_t(q_b(R) + x), a + D + kappa).
# Rings stay rings (only their radius moves); spokes become spiral arms a + D(r) + kappa.
# Models are the app's, exactly: s = clamp(q / TotalBytes) * L, L = sectors / 75 * 1200 mm;
#   any pitch term != 0: DvdTrackGeometry, dr/dtheta = b (1 + c1 X + c2 X^2 + c3 X^3), X = (r - ri)/(ro - ri),
#     exact polar arc, b solved from L, angle 0 at ri; evaluated with the validated SpiralGeometry
#     (review_checks/spiral.py; agrees with the app to 1e-10 rad);
#   all pitch terms 0: the app's CD area formula r^2 = ri^2 + (ro^2 - ri^2) s / L, theta = 2 s / (r + ri).
# Canvas: the app's Design page composes a CD design on a square of +-57.5 mm (DesignViewModel.CanvasOuterRadiusMm =
#   CdDiscParameters.StandardImageOuterRadiusMm) and the track sampler reads white outside it, so pattern parts with
#   |x| or |y| > 57.5 mm in the image frame burn white (--canvas; 0 = off, e.g. for a cd-generate track with a larger --outer).
# Frame: the app's image frame, x right, y down, angle = atan2(y, x), clockwise on screen = along the track
# = the data-side view, unmirrored (as the app preview). kappa is fixed so that the reference ring's
# crossings sit at their design angles.
# Ruler reading (spec 6.3-6.5): ruler through one half-spoke's crossings with the two contact rings,
# extended across the hub; B = offset of the opposite half at the same rings, + = clockwise of the ruler;
# bow = deviation of the same half from its own ruler at the rings between. Exact plane geometry.
import argparse, json, math, os, struct, sys, zlib

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
BYTES_PER_SECTOR = 2352
BYTE_MM = 1200.0 / 75.0 / BYTES_PER_SECTOR        # mm of track per byte at 1.2 m/s
DISC_R, HOLE_R = 60.0, 7.5
CANVAS_MM = 57.5                                  # CdDiscParameters.StandardImageOuterRadiusMm (app's CD composite)
PROBE_KEY = 'DiscImageStudio-probe-pattern'
deg, rad = math.degrees, math.radians
_SG = None


def spiral_class(path=None):
    global _SG
    if _SG is None:
        sys.path.insert(0, path or os.path.join(HERE, 'pitchfit'))
        from spiral import SpiralGeometry
        _SG = SpiralGeometry
    return _SG


# ====================================================================== track models
class Track:
    """One of the app's CD track models: byte q -> arc s = clamp(q / TB) * L -> (r, theta), theta(ri) = 0."""

    def __init__(self, ri, ro, c1=0.0, c2=0.0, c3=0.0, sectors=359845, velocity=1200.0):
        self.ri, self.ro = float(ri), float(ro)
        self.c = (float(c1), float(c2), float(c3))
        self.sectors = int(sectors)
        self.total_bytes = self.sectors * BYTES_PER_SECTOR
        self.L = self.sectors / 75.0 * velocity
        self.pitched = any(v != 0.0 for v in self.c)
        if self.pitched:
            self.geo = spiral_class()(self.ri, self.ro, self.L, *self.c)
            self.b = self.geo.b
        else:
            self.range2 = (self.ro - self.ri) * (self.ro + self.ri)
            self.b = self.range2 / (2.0 * self.L)

    def at_arc(self, s):
        s = min(max(s, 0.0), self.L)
        if self.pitched:
            return self.geo.radius_and_angle_at_arc(s)
        r = math.sqrt(self.ri * self.ri + self.range2 * (s / self.L))
        return r, 2.0 * s / (r + self.ri)

    def at_radius(self, r):
        r = min(max(r, self.ri), self.ro)
        if self.pitched:
            return self.geo.arc_and_angle_at_radius(r)
        s = self.L * (r - self.ri) * (r + self.ri) / self.range2
        return s, 2.0 * s / (r + self.ri)

    def label(self):
        if self.pitched:
            return (f'ri {self.ri:.10g} ro {self.ro:.10g} c {self.c[0]:.6g}/{self.c[1]:.6g}/{self.c[2]:.6g} '
                    f'(pitch spiral)')
        return f'ri {self.ri:.10g} ro {self.ro:.10g} constant pitch (area formula)'

    def short(self):
        s = f'{self.ri:.7f} / {self.ro:.7f}'
        if self.pitched:
            s += ' C ' + '/'.join(f'{v:.3g}' for v in self.c)
        return s


class DiscMap:
    """Where content placed by `burn` lands on a disc whose track follows `true` (shifted by x bytes)."""

    def __init__(self, burn, true, x=0.0, step=0.005):
        self.burn, self.true, self.x = burn, true, float(x)
        self.ds = self.x * BYTE_MM
        lo, hi = true.ri, true.ro
        n = int(math.ceil((hi - lo) / step)) + 1
        self.lo, self.n = lo, n
        self.h = (hi - lo) / (n - 1)
        self.tD, self.tR = [], []
        for k in range(n):
            d, rb = self.at_true_radius(lo + k * self.h if k < n - 1 else hi)
            self.tD.append(d)
            self.tR.append(rb)
        self.kappa = 0.0

    def at_true_radius(self, r):
        """(D, image radius) of the byte that lies at true radius r."""
        s_t, th_t = self.true.at_radius(r)
        r_b, th_b = self.burn.at_arc(s_t - self.ds)
        return th_t - th_b, r_b

    def at_image_radius(self, R):
        """(true radius, D) of the byte the burn model put at image radius R."""
        s_b, th_b = self.burn.at_radius(R)
        r_t, th_t = self.true.at_arc(s_b + self.ds)
        return r_t, th_t - th_b

    def lookup(self, r):
        p = (r - self.lo) / self.h
        i = int(p)
        i = 0 if i < 0 else (self.n - 2 if i > self.n - 2 else i)
        a = p - i
        d0, r0 = self.tD[i], self.tR[i]
        return d0 + (self.tD[i + 1] - d0) * a, r0 + (self.tR[i + 1] - r0) * a

    def slope(self, r, dr=0.01):
        """dD/dr (rad/mm) at true radius r."""
        lo, hi = max(self.true.ri, r - dr), min(self.true.ro, r + dr)
        return (self.at_true_radius(hi)[0] - self.at_true_radius(lo)[0]) / (hi - lo)


# ====================================================================== PNG I/O
def read_png(path):
    """8-bit PNG (gray, gray+alpha, RGB, RGBA; any filter) -> (w, h, gray bytearray, tEXt dict)."""
    data = open(path, 'rb').read()
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        raise SystemExit(f'{path}: not a PNG')
    pos, idat, texts = 8, [], {}
    while pos < len(data):
        ln = struct.unpack('>I', data[pos:pos + 4])[0]
        typ, body = data[pos + 4:pos + 8], data[pos + 8:pos + 8 + ln]
        pos += 12 + ln
        if typ == b'IHDR':
            w, h, bd, ct, _, _, il = struct.unpack('>IIBBBBB', body)
        elif typ == b'IDAT':
            idat.append(body)
        elif typ == b'tEXt':
            k, v = body.split(b'\x00', 1)
            texts[k.decode('latin-1')] = v.decode('latin-1')
        elif typ == b'IEND':
            break
    if bd != 8 or il != 0 or ct not in (0, 2, 4, 6):
        raise SystemExit(f'{path}: only 8-bit non-interlaced gray/RGB(A) PNGs are supported')
    ch = {0: 1, 2: 3, 4: 2, 6: 4}[ct]
    raw = zlib.decompress(b''.join(idat))
    stride = w * ch
    gray = bytearray(w * h)
    prev = bytearray(stride)
    p = 0
    for y in range(h):
        ft = raw[p]
        line = bytearray(raw[p + 1:p + 1 + stride])
        p += 1 + stride
        if ft == 1:
            for i in range(ch, stride):
                line[i] = (line[i] + line[i - ch]) & 255
        elif ft == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 255
        elif ft == 3:
            for i in range(stride):
                line[i] = (line[i] + (((line[i - ch] if i >= ch else 0) + prev[i]) >> 1)) & 255
        elif ft == 4:
            for i in range(stride):
                a = line[i - ch] if i >= ch else 0
                b, c = prev[i], (prev[i - ch] if i >= ch else 0)
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else (b if pb <= pc else c))) & 255
        if ch == 1:
            gray[y * w:(y + 1) * w] = line
        else:
            for i in range(w):
                px = line[i * ch:(i + 1) * ch]
                g = px[0] if ch <= 2 else (299 * px[0] + 587 * px[1] + 114 * px[2]) // 1000
                if ch in (2, 4):
                    al = px[-1]
                    g = (g * al + 255 * (255 - al)) // 255
                gray[y * w + i] = g
        prev = line
    return w, h, gray, texts


class Layer:
    """The pattern as an app layer at 100 % scale, zero offset/rotation: larger side spans 2 * span mm."""

    def __init__(self, path, span):
        self.path = path
        self.w, self.h, self.gray, self.texts = read_png(path)
        self.span = float(span)
        self.mmpx = 2.0 * self.span / max(self.w, self.h)

    def at_mm(self, x, y):
        i = int(math.floor(x / self.mmpx + self.w / 2))
        j = int(math.floor(y / self.mmpx + self.h / 2))
        if 0 <= i < self.w and 0 <= j < self.h:
            return self.gray[j * self.w + i]
        return 255


# ====================================================================== pattern features
V2_E = [-0.05078, -1.99834, 2.03311, 3.09415, -1.85344]   # deg, poly4 in X = (r - 41.25)/16.25
V2_E0 = 0.2670
V2_SPAN = 57.8390395                                       # the v2 PNG's own design span


def v2_E(r):
    X = (r - 41.25) / 16.25
    return sum(c * X ** k for k, c in enumerate(V2_E)) - V2_E0


def features_v2(scale=1.0):
    """verify_pattern_v2_4096.png (analysis/pattern_v2.py), in image mm after the app's import scaling."""
    sp = []
    for a in (0, 60, 120, 180, 240, 300):
        sp.append({'angle': a, 'r0': 25.6 * scale, 'r1': 57.3 * scale, 'width': 0.45, 'set': 'S', 'bend': None})
    for a in (30, 90, 150, 210, 270, 330):
        sp.append({'angle': a, 'r0': 25.6 * scale, 'r1': 57.3 * scale, 'width': 0.45, 'set': 'P',
                   'bend': (lambda R, k=scale: -rad(v2_E(R / k))),
                   'segments': [(lo * scale, hi * scale) for lo, hi in
                                ((25.6, 26.3), (27.3, 32.0), (33.0, 37.0), (38.0, 42.0), (43.0, 47.0),
                                 (48.0, 52.0), (53.0, 55.5), (56.5, 57.3))]})
    rings = [{'r': R * scale, 'width': 0.30, 'edge': None} for R in (28.0, 30.0, 35.0, 40.0, 45.0, 50.0, 55.0, 57.0)]
    return {'kind': 'v2', 'spokes': sp, 'rings': rings, 'ticks': [],
            'glyph': {'char': 'F', 'style': 'upright', 'r': 42.6 * scale, 'angle': 15.0, 'height': 5.0,
                      'width': 2.6, 'stroke': 0.7},
            'contacts': (28.0 * scale, 57.0 * scale), 'ref_ring': 40.0 * scale}


def features_probe(js, scale=1.0):
    f = json.loads(js)
    sp = [{'angle': s['angle'], 'r0': s['r0'] * scale, 'r1': s['r1'] * scale, 'width': s['width'],
           'set': 'A', 'bend': None} for s in f['spokes']]
    rings = [{'r': r['r'] * scale, 'width': r['width'], 'edge': r['edge']} for r in f['rings']]
    ticks = [{'ring': t['ring'] * scale, 'angle': t['angle'], 'r0': t['r0'] * scale, 'r1': t['r1'] * scale,
              'width': t['width']} for t in f['ticks']]
    if 'gauge' in f:                                   # half-plane twist gauge: its two straight edges
        gg = f['gauge']
        for e in gg['edges']:
            sp.append({'angle': e, 'r0': gg['r0'] * scale, 'r1': gg['r1'] * scale, 'width': None, 'set': 'G',
                       'bend': None})
    g = dict(f['glyph'])
    g['r'] *= scale
    near = lambda v: min((r['r'] for r in rings), key=lambda R: abs(R - v * scale))
    return {'kind': 'probe', 'spokes': sp, 'rings': rings, 'ticks': ticks, 'glyph': g,
            'contacts': (near(28.0), near(57.0)), 'ref_ring': near(40.0), 'band': [b * scale for b in f['band']]}


def load_features(kind, layer):
    if kind == 'auto':
        kind = 'probe' if PROBE_KEY in layer.texts else ('v2' if 'verify_pattern_v2' in os.path.basename(layer.path) else None)
        if kind is None:
            raise SystemExit('cannot tell the pattern kind; pass --features probe or v2')
    if kind == 'probe':
        js = layer.texts.get(PROBE_KEY)
        if js is None:
            raise SystemExit('the PNG has no probe-pattern tEXt chunk')
        own_span = json.loads(js)['span_mm']
        feat = features_probe(js, layer.span / own_span)
    else:
        feat = features_v2(layer.span / V2_SPAN)
    feat['spokes'].sort(key=lambda s: s['angle'] % 360.0)
    return feat


# ====================================================================== readings
def spoke_point(m, sp, R):
    """Disc position of spoke sp's centreline where it crosses image radius R: (r_true, phi, (X, Y))."""
    r_t, D = m.at_image_radius(R)
    phi = rad(sp['angle']) + (sp['bend'](R) if sp['bend'] else 0.0) + D + m.kappa
    return r_t, phi, (r_t * math.cos(phi), r_t * math.sin(phi))


def ruler(m, near, far, contacts, between):
    """Ruler through `near` at the two contact rings; B of `far` at both rings (+ = clockwise); bows."""
    _, _, p1 = spoke_point(m, near, contacts[0])
    _, _, p2 = spoke_point(m, near, contacts[1])
    ux, uy = p2[0] - p1[0], p2[1] - p1[1]
    ln = math.hypot(ux, uy)
    ux, uy = ux / ln, uy / ln
    nx, ny = -uy, ux                                   # clockwise normal of the near half (screen, y down)
    B = []
    for R in contacts:
        _, _, q = spoke_point(m, far, R)
        B.append(-((q[0] - p1[0]) * nx + (q[1] - p1[1]) * ny))   # far half's clockwise = -n
    bow = {}
    for R in between:
        _, _, p = spoke_point(m, near, R)
        bow[R] = (p[0] - p1[0]) * nx + (p[1] - p1[1]) * ny
    return {'B': B, 'bow': bow, 'p1': p1, 'u': (ux, uy), 'n': (nx, ny)}


def readings(m, feat):
    rings = sorted(r['r'] for r in feat['rings'])
    ca, cb = feat['contacts']
    ref = feat['ref_ring']
    r_ref, D_ref = m.at_image_radius(ref)
    m.kappa = -D_ref
    out = {'kappa_deg': deg(m.kappa), 'ref_ring': ref, 'contacts': [ca, cb], 'rings': [], 'diameters': []}
    for R in rings:
        r_t, D = m.at_image_radius(R)
        dD = m.slope(r_t)
        out['rings'].append({'R': R, 'r_true': r_t, 'shift_um': (r_t - R) * 1000, 'twist_deg': deg(D - D_ref),
                             'dDdr_deg_per_mm': deg(dD)})
    sp = feat['spokes']
    for near in sp:
        if near['angle'] % 360.0 >= 180.0:
            continue
        far = [s for s in sp if abs(math.remainder(s['angle'] - near['angle'] - 180.0, 360.0)) < 1e-6]
        if not far:
            continue
        far = far[0]
        rd = ruler(m, near, far, (ca, cb), [R for R in rings if ca < R < cb])
        out['diameters'].append({'near': near['angle'], 'far': far['angle'], 'set': near.get('set', 'A'),
                                 'B_mm': rd['B'], 'bow_mm': rd['bow']})
    # arm angles at every ring (mod 360, kappa as above) and the tick angle
    arms = []
    for R in rings:
        row = []
        for s in sp:
            _, phi, _ = spoke_point(m, s, R)
            row.append(deg(phi) % 360.0)
        tick = None
        for t in feat['ticks']:
            if abs(t['ring'] - R) < 1e-9:
                r_t, D = m.at_image_radius(R)
                tick = (t['angle'] + deg(D + m.kappa)) % 360.0
        arms.append({'R': R, 'arms_deg': row, 'tick_deg': tick})
    out['arms'] = arms
    # twisted arms: inclination, line width across the arm, radial spacing of crossings at every ring.
    # A feature of tangential width w at radius r keeps width w along the circle; inclined by beta from radial
    # (tan beta = r |dD/dr|) its width across itself is w cos(beta).
    thin = [s for s in sp if s['width']]
    w = thin[0]['width']
    nsp = len(thin)
    gauge = any(s.get('set') == 'G' for s in sp)
    out['gauge'] = gauge
    for rg in out['rings']:
        g = rad(rg['dDdr_deg_per_mm'])
        rr = rg['r_true']
        beta = math.atan(abs(rr * g))
        rg['incl_deg'] = deg(beta)
        rg['arm_width_mm'] = w * math.cos(beta)
        rg['crossing_spacing_mm'] = (2 * math.pi / nsp) / abs(g) if g != 0 else float('inf')
        if gauge:
            rg['gauge_band_mm'] = rr * math.pi * math.cos(beta)
    for a, b in zip(out['rings'], out['rings'][1:]):
        a['turns_to_next'] = (b['twist_deg'] - a['twist_deg']) / 360.0
        a['crossings_to_next'] = abs(b['twist_deg'] - a['twist_deg']) / (360.0 / nsp)
        if gauge:
            a['gauge_edges_to_next'] = abs(b['twist_deg'] - a['twist_deg']) / 180.0
    out['straight'] = all(abs(v) <= 2.0 for d in out['diameters'] for v in d['bow_mm'].values()) and \
        all(abs(rg['twist_deg']) <= 45.0 for rg in out['rings'])
    # glyph: rotation at its centre and shear across its height
    g = feat['glyph']
    lo, hi = g['r'] - g['height'] / 2, g['r'] + g['height'] / 2
    (_, d_lo), (_, d_hi), (_, d_c) = m.at_image_radius(lo), m.at_image_radius(hi), m.at_image_radius(g['r'])
    out['glyph'] = {'r': g['r'], 'angle': g['angle'], 'rotation_deg': deg(d_c - D_ref),
                    'shear_deg': deg(d_hi - d_lo), 'shear_mm': g['r'] * (d_hi - d_lo),
                    'readable': abs(g['r'] * (d_hi - d_lo)) < 0.5 * g['width']}
    tot = m.at_image_radius(rings[-1])[1] - m.at_image_radius(rings[0])[1]
    out['twist_total_turns'] = tot / (2 * math.pi)
    out['twisted'] = max(abs(rg['twist_deg']) for rg in out['rings']) > 2.0
    return out


def canvas_reach(feat):
    """Largest image radius the pattern's features reach (mm)."""
    return max([s['r1'] for s in feat['spokes']] + [r['r'] + r['width'] / 2 for r in feat['rings']])


def report_text(m, feat, rd, pattern_path, span, canvas=None):
    L = []
    L.append(f'pattern: {pattern_path} ({feat["kind"]}), layer span +-{span:.10g} mm')
    L.append(f'burn:  {m.burn.label()}, {m.burn.sectors} sectors')
    L.append(f'true:  {m.true.label()}, x = {m.x:+g} B')
    L.append(f'frame: data side, unmirrored, + = clockwise = along the track; kappa fixed so that the '
             f'{rd["ref_ring"]:.2f} mm ring crossings sit at their design angles (kappa {rd["kappa_deg"]:+.4f} deg)')
    L.append(f'twist of the content between the outermost and innermost ring: {rd["twist_total_turns"]:+.4f} turns '
             f'({rd["twist_total_turns"] * 360:+.2f} deg)')
    reach = canvas_reach(feat)
    if canvas and reach > canvas:
        L.append(f'app canvas: the Design page composes CD designs on +-{canvas:g} mm and burns white outside it, so the '
                 f'pattern beyond {canvas:g} mm is cut within +-{deg(math.acos(canvas / reach)):.1f} deg of the image axes '
                 f'(at {reach:.2f} mm): four white cut-outs (gaps in the outer edge ring) where the 0/90/180/270 deg arms '
                 f'meet it (drawn in --out; --canvas 0 turns this off)')
    L.append('')
    L.append('RINGS STAY RINGS: image ring R lands at true radius r; twist = rotation of that radius vs the reference ring')
    gh = '  gauge band (mm)  gauge edges/next' if rd['gauge'] else ''
    L.append('    R (mm)   r true (mm)  shift (um)  twist (deg)   dD/dr (deg/mm)  arm incl. (deg)  arm width (mm)  '
             'crossings/next' + gh)
    for rg in rd['rings']:
        nxt = f'{rg["crossings_to_next"]:14.2f}' if 'crossings_to_next' in rg else '             -'
        gx = ''
        if rd['gauge']:
            gx = f'  {rg["gauge_band_mm"]:15.3f}  ' + (f'{rg["gauge_edges_to_next"]:16.2f}' if 'gauge_edges_to_next' in rg
                                                     else '               -')
        L.append(f'  {rg["R"]:7.2f}  {rg["r_true"]:12.6f}  {rg["shift_um"]:+9.2f}  {rg["twist_deg"]:+11.3f}  '
                 f'{rg["dDdr_deg_per_mm"]:+14.4f}  {rg["incl_deg"]:14.2f}  {rg["arm_width_mm"]:14.3f}  {nxt}{gx}')
    L.append('  arm incl. = angle of a spoke arm from radial; arm width = its line width across itself (0.45 mm when '
             'straight; below about 0.1 mm an arm is hard to see); crossings/next = arms met along a radius between this '
             'ring and the next' + ('; gauge band = width of the light and dark gauge bands across themselves' if rd['gauge'] else ''))
    L.append('')
    ca, cb = rd['contacts']
    L.append(f'RULER READINGS: ruler through one half at the {ca:.2f} and {cb:.2f} mm rings, extended across the hub'
             + ('' if rd['straight'] else '  [spokes are twisted: these numbers do not describe a ruler test; use the arm angles]'))
    L.append('  B = offset of the other half at the same rings (+ = clockwise); bow = same half vs its own ruler')
    for d in rd['diameters']:
        bows = ' '.join(f'{R:.0f}:{v:+.2f}' for R, v in d['bow_mm'].items())
        L.append(f'  {d["set"]} {d["near"]:5.0f}/{d["far"]:<5.0f} B {d["B_mm"][0]:+7.3f} / {d["B_mm"][1]:+7.3f} mm | bow {bows}')
    if rd['twisted']:
        L.append('')
        L.append(f'SPIRAL ARMS: angle (deg, clockwise, mod 360) of each arm at every ring, the {rd["ref_ring"]:.2f} mm '
                 'ring at its design angles' + (' (G = gauge edges; the inverted half runs clockwise from the first one)'
                                               if rd['gauge'] else ''))
        L.append('  ring    ' + ' '.join(f'{(s.get("set") if s.get("set") == "G" else "") + format(s["angle"], ".0f"):>6s}'
                                         for s in feat['spokes']) + '    tick')
        for a in rd['arms']:
            t = f'{a["tick_deg"]:7.2f}' if a['tick_deg'] is not None else '     -'
            L.append(f'  {a["R"]:6.2f}  ' + ' '.join(f'{v:6.1f}' for v in a['arms_deg']) + '  ' + t)
    g = rd['glyph']
    L.append('')
    L.append(f'GLYPH F at {g["r"]:.2f} mm / {g["angle"]:.0f} deg: rotated {g["rotation_deg"]:+.2f} deg, sheared '
             f'{g["shear_deg"]:+.3f} deg ({g["shear_mm"]:+.2f} mm) across its height: '
             + ('readable' if g['readable'] else 'UNREADABLE (sheared); a mirrored photo shows the arms and gauge '
                'bands winding the other way than predicted'))
    return '\n'.join(L)


# ====================================================================== drawing
G5 = {
    'A': ".###.|#...#|#...#|#####|#...#|#...#|#...#", 'B': "####.|#...#|#...#|####.|#...#|#...#|####.",
    'C': ".###.|#...#|#....|#....|#....|#...#|.###.", 'D': "###..|#..#.|#...#|#...#|#...#|#..#.|###..",
    'E': "#####|#....|#....|####.|#....|#....|#####", 'F': "#####|#....|#....|####.|#....|#....|#....",
    'G': ".###.|#...#|#....|#.###|#...#|#...#|.####", 'H': "#...#|#...#|#...#|#####|#...#|#...#|#...#",
    'I': ".###.|..#..|..#..|..#..|..#..|..#..|.###.", 'J': "..###|...#.|...#.|...#.|...#.|#..#.|.##..",
    'K': "#...#|#..#.|#.#..|##...|#.#..|#..#.|#...#", 'L': "#....|#....|#....|#....|#....|#....|#####",
    'M': "#...#|##.##|#.#.#|#.#.#|#...#|#...#|#...#", 'N': "#...#|#...#|##..#|#.#.#|#..##|#...#|#...#",
    'O': ".###.|#...#|#...#|#...#|#...#|#...#|.###.", 'P': "####.|#...#|#...#|####.|#....|#....|#....",
    'Q': ".###.|#...#|#...#|#...#|#.#.#|#..#.|.##.#", 'R': "####.|#...#|#...#|####.|#.#..|#..#.|#...#",
    'S': ".####|#....|#....|.###.|....#|....#|####.", 'T': "#####|..#..|..#..|..#..|..#..|..#..|..#..",
    'U': "#...#|#...#|#...#|#...#|#...#|#...#|.###.", 'V': "#...#|#...#|#...#|#...#|#...#|.#.#.|..#..",
    'W': "#...#|#...#|#...#|#.#.#|#.#.#|#.#.#|.#.#.", 'X': "#...#|#...#|.#.#.|..#..|.#.#.|#...#|#...#",
    'Y': "#...#|#...#|.#.#.|..#..|..#..|..#..|..#..", 'Z': "#####|....#|...#.|..#..|.#...|#....|#####",
    '0': ".###.|#...#|#..##|#.#.#|##..#|#...#|.###.", '1': "..#..|.##..|..#..|..#..|..#..|..#..|.###.",
    '2': ".###.|#...#|....#|...#.|..#..|.#...|#####", '3': "#####|...#.|..#..|...#.|....#|#...#|.###.",
    '4': "...#.|..##.|.#.#.|#..#.|#####|...#.|...#.", '5': "#####|#....|####.|....#|....#|#...#|.###.",
    '6': "..##.|.#...|#....|####.|#...#|#...#|.###.", '7': "#####|....#|...#.|..#..|.#...|.#...|.#...",
    '8': ".###.|#...#|#...#|.###.|#...#|#...#|.###.", '9': ".###.|#...#|#...#|.####|....#|...#.|.##..",
    '.': ".....|.....|.....|.....|.....|.##..|.##..", ',': ".....|.....|.....|.....|.##..|..#..|.#...",
    '-': ".....|.....|.....|#####|.....|.....|.....", '+': ".....|..#..|..#..|#####|..#..|..#..|.....",
    '=': ".....|.....|#####|.....|#####|.....|.....", '/': ".....|....#|...#.|..#..|.#...|#....|.....",
    ':': ".....|.##..|.##..|.....|.##..|.##..|.....", '(': "...#.|..#..|.#...|.#...|.#...|..#..|...#.",
    ')': ".#...|..#..|...#.|...#.|...#.|..#..|.#...", '%': "##...|##..#|...#.|..#..|.#...|#..##|...##",
    '<': "...#.|..#..|.#...|#....|.#...|..#..|...#.", '>': ".#...|..#..|...#.|....#|...#.|..#..|.#...",
    '_': ".....|.....|.....|.....|.....|.....|#####", "'": "..#..|..#..|.#...|.....|.....|.....|.....",
    '|': "..#..|..#..|..#..|..#..|..#..|..#..|..#..", '~': ".....|.....|.#...|#.#.#|...#.|.....|.....",
    '*': ".....|..#..|#.#.#|.###.|#.#.#|..#..|.....", '?': ".###.|#...#|....#|...#.|..#..|.....|..#..",
    '!': "..#..|..#..|..#..|..#..|..#..|.....|..#..", ';': ".....|.##..|.##..|.....|.##..|..#..|.#...",
    '[': ".###.|.#...|.#...|.#...|.#...|.#...|.###.", ']': ".###.|...#.|...#.|...#.|...#.|...#.|.###.",
    '#': ".#.#.|#####|.#.#.|.#.#.|.#.#.|#####|.#.#.", '^': "..#..|.#.#.|#...#|.....|.....|.....|.....",
}
FONT = {k: v.split('|') for k, v in G5.items()}
WHITE, HUB, LIGHT, DARK = (255, 255, 255), (225, 225, 225), (205, 205, 205), (70, 70, 70)
RED, BLUE, ORANGE, BLACK, GREEN, GREY = (220, 30, 30), (60, 120, 220), (245, 140, 0), (20, 20, 20), (20, 150, 60), (90, 90, 90)


class Canvas:
    def __init__(self, w, h, bg=WHITE):
        self.w, self.h = w, h
        self.px = bytearray(bytes(bg) * (w * h))

    def get(self, x, y):
        k = 3 * (y * self.w + x)
        return tuple(self.px[k:k + 3])

    def set(self, x, y, col):
        if 0 <= x < self.w and 0 <= y < self.h:
            k = 3 * (y * self.w + x)
            self.px[k:k + 3] = bytes(int(round(c)) for c in col)

    def blend(self, x, y, col, a):
        if a <= 0 or not (0 <= x < self.w and 0 <= y < self.h):
            return
        a = min(1.0, a)
        o = self.get(x, y)
        self.set(x, y, tuple(o[i] * (1 - a) + col[i] * a for i in range(3)))

    def rect(self, x, y, w, h, col):
        for yy in range(max(0, y), min(self.h, y + h)):
            x0, x1 = max(0, x), min(self.w, x + w)
            if x1 > x0:
                k = 3 * (yy * self.w + x0)
                self.px[k:k + 3 * (x1 - x0)] = bytes(col) * (x1 - x0)

    def text(self, x, y, s, sc=2, col=BLACK):
        cx = x
        for ch in s.upper():
            g = FONT.get(ch)
            if g:
                for gy, row in enumerate(g):
                    for gx, c in enumerate(row):
                        if c == '#':
                            self.rect(cx + gx * sc, y + gy * sc, sc, sc, col)
            cx += 6 * sc
        return cx

    def segment(self, p0, p1, hw, col):
        """anti-aliased thick segment between pixel-space points (pixel centres at i + 0.5)"""
        ux, uy = p1[0] - p0[0], p1[1] - p0[1]
        L = math.hypot(ux, uy)
        if L < 1e-9:
            return
        ux, uy = ux / L, uy / L
        nx, ny = -uy, ux
        x0 = int(math.floor(min(p0[0], p1[0]) - hw - 2)); x1 = int(math.ceil(max(p0[0], p1[0]) + hw + 2))
        y0 = int(math.floor(min(p0[1], p1[1]) - hw - 2)); y1 = int(math.ceil(max(p0[1], p1[1]) + hw + 2))
        for j in range(max(0, y0), min(self.h, y1 + 1)):
            for i in range(max(0, x0), min(self.w, x1 + 1)):
                xc, yc = i + 0.5, j + 0.5
                t = (xc - p0[0]) * ux + (yc - p0[1]) * uy
                if t < -hw - 1 or t > L + hw + 1:
                    continue
                d = abs((xc - p0[0]) * nx + (yc - p0[1]) * ny)
                if t < 0:
                    d = math.hypot(d, t)
                elif t > L:
                    d = math.hypot(d, t - L)
                self.blend(i, j, col, hw + 0.5 - d)

    def save(self, path):
        raw = b''.join(b'\x00' + bytes(self.px[3 * self.w * y:3 * self.w * (y + 1)]) for y in range(self.h))

        def chunk(t, d):
            c = struct.pack('>I', len(d)) + t + d
            return c + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
        with open(path, 'wb') as f:
            f.write(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', self.w, self.h, 8, 2, 0, 0, 0))
                    + chunk(b'IDAT', zlib.compress(raw, 6)) + chunk(b'IEND', b''))


def tw(s, sc):
    return len(s) * 6 * sc


def scalebar(cv, x, y, ppmm, mm, label, sc=2):
    L = int(round(mm * ppmm))
    cv.rect(x, y, L, 4, BLACK)
    cv.rect(x, y - 6, 2, 16, BLACK)
    cv.rect(x + L - 2, y - 6, 2, 16, BLACK)
    cv.text(x + L + 10, y - 5, label, sc)


class Predictor:
    """Predicted disc appearance at a true position (mm, app frame, y down)."""

    def __init__(self, m, layer, canvas=None):
        self.m, self.layer, self.canvas = m, layer, canvas

    def colour(self, X, Y):
        r = math.hypot(X, Y)
        if r > DISC_R or r < HOLE_R:
            return WHITE
        t = self.m.true
        if r < t.ri or r > t.ro:
            return HUB
        D, rb = self.m.lookup(r)
        a = math.atan2(Y, X) - self.m.kappa - D
        ix, iy = rb * math.cos(a), rb * math.sin(a)
        if self.canvas and (abs(ix) > self.canvas or abs(iy) > self.canvas):
            return LIGHT                  # outside the app's composite canvas: sampled as white
        g = self.layer.at_mm(ix, iy)
        return DARK if g < 128 else LIGHT


def render_map(cv, ox, oy, wpx, hpx, point_of, colour, ss=4):
    """Render pixels (i, j) -> disc point point_of(i + 0.5, j + 0.5); supersample where neighbours differ."""
    base = [[colour(*point_of(i + 0.5, j + 0.5)) for i in range(wpx)] for j in range(hpx)]
    for j in range(hpx):
        row = base[j]
        for i in range(wpx):
            c = row[i]
            edge = ((i > 0 and row[i - 1] != c) or (i < wpx - 1 and row[i + 1] != c) or
                    (j > 0 and base[j - 1][i] != c) or (j < hpx - 1 and base[j + 1][i] != c))
            if edge:
                acc = [0.0, 0.0, 0.0]
                for sj in range(ss):
                    for si in range(ss):
                        cc = colour(*point_of(i + (si + 0.5) / ss, j + (sj + 0.5) / ss))
                        acc[0] += cc[0]; acc[1] += cc[1]; acc[2] += cc[2]
                c = tuple(a / (ss * ss) for a in acc)
            cv.set(ox + i, oy + j, c)


def disc_view(size, ppmm):
    c0 = size / 2
    return lambda fi, fj: ((fi - c0) / ppmm, (fj - c0) / ppmm)


def crop_view(wpx, hpx, ppmm, r_mid, phi_c):
    """Crop centred on (r_mid, phi_c), turned so that outward = up and clockwise = right (unmirrored)."""
    rx, ry = math.cos(phi_c), math.sin(phi_c)
    tx, ty = -math.sin(phi_c), math.cos(phi_c)
    cx, cy = r_mid * rx, r_mid * ry

    def f(fi, fj):
        u = (fi - wpx / 2) / ppmm
        v = (hpx / 2 - fj) / ppmm
        return cx + u * tx + v * rx, cy + u * ty + v * ry
    return f


def render_prediction(path, m, layer, feat, rd, title, canvas=None):
    pred = Predictor(m, layer, canvas)
    PP, S = 8.0, 1000
    INS = 3 * PP
    iw, ih = int(30 * INS), int(9 * INS)
    x0 = S + 40
    W, H = x0 + iw + 110, 80 + S + 20
    cv = Canvas(W, H)
    for k, line in enumerate(title):
        cv.text(20, 12 + 26 * k, line, 2)
    oy = 80
    render_map(cv, 10, oy, S, S, disc_view(S, PP), pred.colour)
    c0x, c0y = 10 + S / 2, oy + S / 2
    outer = max(r['r'] for r in feat['rings'])
    for sp in feat['spokes']:
        _, phi, _ = spoke_point(m, sp, min(sp['r1'], outer))
        st = sp.get('set', 'A')
        lab = st if st in 'SP' else (('G' if st == 'G' else '') + f'{sp["angle"]:.0f}')
        x = c0x + 61.8 * PP * math.cos(phi)
        y = c0y + 61.8 * PP * math.sin(phi)
        cv.text(int(x - tw(lab, 2) / 2), int(y - 7), lab, 2, RED if sp['angle'] == 0 else (BLUE if st == 'G' else BLACK))
    scalebar(cv, 30, oy + S - 20, PP, 10, '10 MM', 2)
    # 3x insets centred on arm 0: hub 24.5..33.5 mm and rim
    for n, (name, r_mid) in enumerate((('HUB', 29.0), ('RIM', m.true.ro - 3.5))):
        y0 = oy + n * (ih + 64)
        D, rb = m.lookup(r_mid)
        phi_c = rad(feat['spokes'][0]['angle']) + D + m.kappa
        cv.text(x0, y0, f'{name} 3X: R {r_mid - 4.5:.1f}-{r_mid + 4.5:.1f} MM AT ARM 0. UP = OUT, RIGHT = CW', 2)
        render_map(cv, x0, y0 + 22, iw, ih, crop_view(iw, ih, INS, r_mid, phi_c), pred.colour, ss=3)
        for rg in rd['rings']:
            v = rg['r_true'] - r_mid
            if abs(v) < 4.5:
                yy = int(y0 + 22 + ih / 2 - v * INS)
                cv.rect(x0 - 8, yy, 6, 1, BLACK)
                cv.text(x0 - 10 - tw(f'{rg["R"]:.0f}', 1), yy - 3, f'{rg["R"]:.0f}', 1)
        scalebar(cv, x0 + iw - 150, y0 + 22 + ih + 14, INS, 5, '5 MM', 2)
    ty = oy + 2 * (ih + 64) + 6
    lines = []
    ca, cb = rd['contacts']
    lines.append((f'TWIST, INNER TO OUTER RING: {rd["twist_total_turns"]:+.3f} TURNS', BLACK))
    if rd['straight']:
        lines.append((f'RULER ON RINGS {ca:.2f}/{cb:.2f} MM (+ = CLOCKWISE):', BLACK))
        for d in rd['diameters']:
            mb = max(d['bow_mm'].values(), key=abs) if d['bow_mm'] else 0.0
            lines.append((f'  {d["set"]} {d["near"]:.0f}/{d["far"]:.0f}: B {d["B_mm"][0]:+.2f} MM, MAX BOW {mb:+.2f} MM', BLACK))
    else:
        wmin = min(rg['arm_width_mm'] for rg in rd['rings'])
        wmax = max(rg['arm_width_mm'] for rg in rd['rings'])
        lines.append((f'SPOKES ARE SPIRAL ARMS, LINE WIDTH {wmin:.3f}-{wmax:.3f} MM'
                      + (' (HARD TO SEE)' if wmin < 0.1 else ''), RED if wmin < 0.1 else BLACK))
        hdr = 'RING: TICK (BESIDE ARM 0), ARM 0' + (', GAUGE EDGE' if rd['gauge'] else '') + ' DEG CW'
        lines.append((hdr, BLACK))
        gi = [i for i, s in enumerate(feat['spokes']) if s.get('set') == 'G']
        a0 = [i for i, s in enumerate(feat['spokes']) if s.get('set') != 'G' and abs(s['angle']) < 1e-9]
        for a, rg in zip(rd['arms'], rd['rings']):
            s = f'  {a["R"]:5.2f}: '
            s += (f'{a["tick_deg"]:6.1f}' if a['tick_deg'] is not None else '     -')
            s += f', {a["arms_deg"][a0[0]]:6.1f}' if a0 else ''
            if gi:
                s += f', {a["arms_deg"][gi[0]]:6.1f} (BAND {rg["gauge_band_mm"]:.2f} MM)'
            lines.append((s, BLACK))
    mx = max(abs(rg['shift_um']) for rg in rd['rings'])
    lines.append((f'RINGS STAY RINGS: LARGEST RADIUS SHIFT {mx:.1f} UM', BLACK))
    if canvas and canvas_reach(feat) > canvas:
        lines.append((f'APP CANVAS +-{canvas:g} MM: 4 WHITE CUT-OUTS AT THE OUTER RING (ARMS 0/90/180/270)', BLACK))
    g = rd['glyph']
    lines.append((f'F: ' + ('READABLE' if g['readable'] else f'SHEARED {g["shear_mm"]:+.1f} MM ACROSS ITS HEIGHT'), BLACK))
    for k, (s, c) in enumerate(lines):
        if ty + 24 * k + 14 < H:
            cv.text(x0, ty + 24 * k, s, 2, c)
    cv.save(path)


def parse_model(vals, sectors):
    if len(vals) not in (2, 5):
        raise SystemExit('a model is RI RO or RI RO C1 C2 C3')
    return Track(*vals, sectors=sectors)


def main(argv=None):
    ap = argparse.ArgumentParser(description='Predicted look of a burned picture disc (burn model vs true model).')
    ap.add_argument('--burn', nargs='+', type=float, required=True, metavar='V', help='RI RO [C1 C2 C3] used for the burn')
    ap.add_argument('--true', nargs='+', type=float, required=True, metavar='V', help='RI RO [C1 C2 C3] fitted truth')
    ap.add_argument('--x', type=float, default=0.0, help='per-drive along-track constant, bytes (default 0)')
    ap.add_argument('--sectors', type=int, default=359845)
    ap.add_argument('--pattern', default=os.path.join(HERE, '..', 'patterns', 'probe_pattern_4096.png'))
    ap.add_argument('--features', default='auto', choices=('auto', 'probe', 'v2'))
    ap.add_argument('--span', type=float, help='layer half-span in mm (default: burn RO, the app import rule)')
    ap.add_argument('--canvas', type=float, default=CANVAS_MM, metavar='MM',
                    help='half-width of the app\'s CD composite canvas; image parts beyond it burn white (default 57.5, '
                         'the Design page; 0 = off, e.g. for a track made by cd-generate with a larger --outer)')
    ap.add_argument('--contacts', nargs=2, type=float, metavar=('RA', 'RB'), help='ruler contact rings (image mm)')
    ap.add_argument('--ref-ring', type=float, help='ring whose crossings keep their design angles (fixes kappa)')
    ap.add_argument('--out', help='PNG of the predicted look')
    ap.add_argument('--report', help='write the text report here too')
    ap.add_argument('--json', help='write the readings as JSON')
    ap.add_argument('--title', default='')
    a = ap.parse_args(argv)
    burn = parse_model(a.burn, a.sectors)
    true = parse_model(a.true, a.sectors)
    layer = Layer(a.pattern, a.span if a.span else burn.ro)
    feat = load_features(a.features, layer)
    if a.contacts:
        feat['contacts'] = tuple(a.contacts)
    if a.ref_ring:
        feat['ref_ring'] = a.ref_ring
    m = DiscMap(burn, true, a.x)
    rd = readings(m, feat)
    canvas = a.canvas if a.canvas > 0 else None
    txt = report_text(m, feat, rd, a.pattern, layer.span, canvas)
    print(txt)
    if a.report:
        with open(a.report, 'w', encoding='utf-8') as f:
            f.write(txt + '\n')
    if a.json:
        with open(a.json, 'w', encoding='utf-8') as f:
            json.dump({'burn': [burn.ri, burn.ro, *burn.c], 'true': [true.ri, true.ro, *true.c], 'x': m.x,
                       'sectors': a.sectors, 'canvas_mm': canvas, 'readings': rd}, f, indent=1, default=str)
    if a.out:
        title = [a.title or 'PREDICTED LOOK, TRUE SCALE, DATA SIDE, NOT MIRRORED (+ = CLOCKWISE = ALONG THE TRACK)',
                 f'BURNED {burn.short()}   TRUE {true.short()}   X = {m.x:+g} B']
        render_prediction(a.out, m, layer, feat, rd, title, canvas)
        print(f'wrote {os.path.abspath(a.out)}')


if __name__ == '__main__':
    main()
