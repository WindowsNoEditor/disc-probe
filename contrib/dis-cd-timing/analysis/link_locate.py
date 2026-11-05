# Where exactly is the along-track step? Combines localsteps runs that share one reference sector, removes the
# disc's smooth quadratic-pitch spiral, and scans the step position (a sector boundary) with a common offset and
# step size g: residual = offset + g/r * [target beyond the step] (reference inside).
# Usage: python -I link_locate.py <console or csv> [...] [--quad RI RO C1 C2] [--prior R0 R1] [--sectors N]
import sys, os, re, math, csv
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'pitchfit'))
from spiral import SpiralGeometry, area_angle, area_radius

import argparse
ap = argparse.ArgumentParser(description='locate an along-track step from localsteps runs sharing one reference')
ap.add_argument('paths', nargs='+', help='localsteps console outputs or localsteps_<ref>.csv files')
ap.add_argument('--quad', type=float, nargs=4, metavar=('RI', 'RO', 'C1', 'C2'),
                default=[24.92154395, 57.8389518, -4.801288177e-05, 2.399225826e-05],
                help="the disc's own smooth fit (default: disc 5 of the Lenovo box)")
ap.add_argument('--prior', type=float, nargs=2, metavar=('R0', 'R1'), default=[24.9216305, 57.8390244],
                help='the constant-pitch prior the probe used for localsteps')
ap.add_argument('--sectors', type=int, default=359845)
A = ap.parse_args()
L = A.sectors / 75.0 * 1200.0
PRIOR = tuple(A.prior)
QUAD = tuple(A.quad)
geo = SpiralGeometry(QUAD[0], QUAD[1], L, QUAD[2], QUAD[3], 0.0)
s = lambda k: 16.0 * (k + 1)
rad = lambda k: area_radius(s(k), *PRIOR, L)


def load(path):
    if path.endswith('.csv'):
        ref = int(os.path.basename(path).split('_')[1].split('.')[0])
        return ref, [(int(r['target']), float(r['measured_minus_prior_deg']), float(r['sigma_deg'])) for r in csv.DictReader(open(path))]
    text = open(path, encoding='utf-8', errors='replace').read()
    ref = int(re.search(r'reference (\d+)', text).group(1))
    pts = [(int(m.group(1)), float(m.group(2)), float(m.group(3))) for m in
           re.finditer(r'target\s+(\d+) r=\S+ mm: measured-prior\s+(-?[\d.]+) deg \+- ([\d.]+)', text)]
    return ref, pts


pts = []
refs = set()
for p in A.paths:
    ref, rows = load(p)
    refs.add(ref)
    for k, miss, sg in rows:
        smooth = math.degrees((geo.angle_at_arc(s(k)) - geo.angle_at_arc(s(ref)))
                              - (area_angle(s(k), *PRIOR, L) - area_angle(s(ref), *PRIOR, L)))
        pts.append((k, miss - smooth, sg))
assert len(refs) == 1, 'runs must share the reference sector'
ref = refs.pop()
pts.sort()
print(f'reference LBA {ref} (r {rad(ref):.3f} mm); residuals vs the disc\'s smooth spiral:')
for k, y, sg in pts:
    print(f'  LBA {k:6d} (0x{k:05X}) r {rad(k):.3f} mm: {y:+.3f} +- {sg:.3f} deg')


def fit(k_step):
    S = [[0.0, 0.0], [0.0, 0.0]]; b = [0.0, 0.0]
    for k, y, sg in pts:
        h = math.degrees(1 / rad(k)) if k >= k_step else 0.0
        w = 1 / sg ** 2
        a = (1.0, h)
        for i in range(2):
            b[i] += w * a[i] * y
            for j in range(2):
                S[i][j] += w * a[i] * a[j]
    det = S[0][0] * S[1][1] - S[0][1] * S[1][0]
    if abs(det) < 1e-12:
        return None
    off = (S[1][1] * b[0] - S[0][1] * b[1]) / det
    g = (-S[1][0] * b[0] + S[0][0] * b[1]) / det
    chi = sum(((y - off - (g * math.degrees(1 / rad(k)) if k >= k_step else 0.0)) / sg) ** 2 for k, y, sg in pts)
    return off, g, math.sqrt(S[0][0] / det), chi


ks = sorted({k for k, _, _ in pts})
print('step between consecutive targets (sector after the step = the outer target):')
best = None
for lo, hi in zip(ks, ks[1:]):
    if hi <= ref:
        continue
    r = fit(hi)
    if r is None:
        continue
    off, g, sg_g, chi = r
    print(f'  after {lo:6d}, at/before {hi:6d} (r {rad(lo):.3f}..{rad(hi):.3f} mm): g {g * 1000:+5.0f} +- {sg_g * 1000:3.0f} um, chi2 {chi:5.1f} / {len(pts) - 2} dof')
    if best is None or chi < best[0]:
        best = (chi, lo, hi, g, sg_g)
print(f'best: step between LBA {best[1]} and {best[2]}, g = {best[3] * 1000:+.0f} +- {best[4] * 1000:.0f} um')
