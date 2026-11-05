# Size of an along-track step (write link) from one localsteps run whose reference sits on one side of it.
# Smooth part: the disc's own quadratic-pitch fit; free: one constant offset and the step g (mm along the track)
# for every target beyond r_step. Reads the probe's console output (or the localsteps CSV).
# Usage: python -I jog_estimate.py <localsteps console output or csv> <r_step mm> [--quad RI RO C1 C2] [--prior R0 R1] [--sectors N]
import sys, os, re, math, csv
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'pitchfit'))
from spiral import SpiralGeometry, area_angle, area_radius

import argparse
ap = argparse.ArgumentParser(description='size of an along-track step from one localsteps run')
ap.add_argument('path', help='localsteps console output or localsteps_<ref>.csv')
ap.add_argument('r_step', type=float, help='radius of the step (mm, on the prior)')
ap.add_argument('--quad', type=float, nargs=4, metavar=('RI', 'RO', 'C1', 'C2'),
                default=[24.92154395, 57.8389518, -4.801288177e-05, 2.399225826e-05],
                help="the disc's own smooth fit (default: disc 5 of the Lenovo box)")
ap.add_argument('--prior', type=float, nargs=2, metavar=('R0', 'R1'), default=[24.9216305, 57.8390244],
                help='the constant-pitch prior the probe used for localsteps (its printed r0 and the r1 passed)')
ap.add_argument('--sectors', type=int, default=359845)
a = ap.parse_args()
L = a.sectors / 75.0 * 1200.0
PRIOR = tuple(a.prior)
path, r_step = a.path, a.r_step
quad = a.quad
geo = SpiralGeometry(quad[0], quad[1], L, quad[2], quad[3], 0.0)

pts = []
if path.endswith('.csv'):
    ref = int(os.path.basename(path).split('_')[1].split('.')[0])
    for rec in csv.DictReader(open(path)):
        pts.append((int(rec['target']), float(rec['measured_minus_prior_deg']), float(rec['sigma_deg'])))
else:
    text = open(path, encoding='utf-8', errors='replace').read()
    ref = int(re.search(r'reference (\d+)', text).group(1))
    for m in re.finditer(r'target\s+(\d+) r=\S+ mm: measured-prior\s+(-?[\d.]+) deg \+- ([\d.]+)', text):
        pts.append((int(m.group(1)), float(m.group(2)), float(m.group(3))))

s = lambda k: 16.0 * (k + 1)
rad = lambda k: area_radius(s(k), *PRIOR, L)
r_ref = rad(ref)
rows = []
for k, miss, sg in pts:
    smooth = math.degrees((geo.angle_at_arc(s(k)) - geo.angle_at_arc(s(ref)))
                          - (area_angle(s(k), *PRIOR, L) - area_angle(s(ref), *PRIOR, L)))
    r = rad(k)
    # step column: angle change (deg) per mm of along-track step for this target relative to the reference
    h = math.degrees((1 / r if r > r_step else 0.0) - (1 / r_ref if r_ref > r_step else 0.0))
    rows.append((k, r, miss - smooth, sg, h))

# weighted least squares for [offset, g]
S = [[0.0, 0.0], [0.0, 0.0]]; b = [0.0, 0.0]
for _, _, y, sg, h in rows:
    w = 1 / sg ** 2
    a = (1.0, h)
    for i in range(2):
        b[i] += w * a[i] * y
        for j in range(2):
            S[i][j] += w * a[i] * a[j]
det = S[0][0] * S[1][1] - S[0][1] * S[1][0]
inv = [[S[1][1] / det, -S[0][1] / det], [-S[1][0] / det, S[0][0] / det]]
off = inv[0][0] * b[0] + inv[0][1] * b[1]
g = inv[1][0] * b[0] + inv[1][1] * b[1]
chi = sum(((y - off - g * h) / sg) ** 2 for _, _, y, sg, h in rows)
dof = max(len(rows) - 2, 1)
chi_nostep = sum(((y - sum(yy / ss ** 2 for _, _, yy, ss, _ in rows) / sum(1 / ss ** 2 for *_, ss, _ in rows)) / sg) ** 2
                 for _, _, y, sg, _ in rows)
print(f'reference LBA {ref} (r = {r_ref:.2f} mm), step tested at r = {r_step} mm, smooth = quadratic {quad}')
for k, r, y, sg, h in rows:
    side = 'outside' if r > r_step else 'inside '
    print(f'  {side} LBA {k:6d} r {r:6.2f} mm: residual vs smooth {y:+.3f} +- {sg:.3f} deg   after fit {y - off - g * h:+.3f}')
print(f'step g = {g * 1000:+.0f} +- {math.sqrt(inv[1][1]) * 1000:.0f} um along the track '
      f'(chi2/dof {chi / dof:.2f}; scaled +- {math.sqrt(inv[1][1] * max(chi / dof, 1)) * 1000:.0f} um); '
      f'no-step chi2 {chi_nostep:.1f} -> with step {chi:.1f}')
