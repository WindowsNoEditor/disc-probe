# Is there an along-track step (write link) on a disc? Fit the smooth quadratic-pitch spiral plus one step:
# every sector beyond arc position s_k is displaced along the track by g mm (angle + g / r), scanning s_k.
# Datasets: the box ladders (rungs_all_runs.csv), the test disc's ladder and its localsteps runs.
# Usage: python -I step_scan.py <probe results dir>
import sys, math, csv, os
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'pitchfit')); sys.path.insert(0, os.path.join(HERE, 'fv'))
import fitlib
from spiral import area_angle, area_radius
from common import reduce_ladder

RES = sys.argv[1]
L = fitlib.TRACK_MM
PRIOR = (24.9216305, 57.8390244)          # the probe's localsteps prior (constant pitch)
P0 = [24.92155075, 57.8389505, -4.021350773e-05, 1.691056535e-05]


def localsteps_rows(path, run):
    ref = int(os.path.basename(path).split('_')[1].split('.')[0])
    rows = []
    for rec in csv.DictReader(open(path)):
        k = int(rec['target'])
        pred = area_angle(16.0 * (k + 1), *PRIOR, L) - area_angle(16.0 * (ref + 1), *PRIOR, L)
        rows.append({'run': run, 'ref': ref, 'lba': k, 'y': pred + math.radians(float(rec['measured_minus_prior_deg'])),
                     'sig': math.radians(float(rec['sigma_deg']))})
    return rows


def ladder_rows(directory, run):
    ref, data = reduce_ladder(directory)
    return [{'run': run, 'ref': ref, 'lba': lba, 'y': y, 'sig': s} for lba, y, s in data]


def radius_of_lba(k):
    return area_radius(16.0 * (k + 1), *PRIOR, L)


def scan(label, rows, runs, lo=26.0, hi=45.0, step=0.1):
    for r in runs:
        if r not in fitlib.RUN_ORDER:
            fitlib.RUN_ORDER.append(r)
    prob = fitlib.Problem(rows, 'quadratic', runs=runs)
    res = fitlib.fit(prob, P0)
    p = res['p']
    J = prob.jacobian(p)
    r0 = prob.residuals(p)
    chi0 = res['chi2']
    best = None
    out = []
    rs = lo
    while rs <= hi + 1e-9:
        # step at radius rs: sectors with radius > rs moved by g mm along the track
        h = []
        for row, sg in zip(prob.rows, prob.sig):
            ra, rb = radius_of_lba(row['lba']), radius_of_lba(row['ref'])
            h.append(((1 / ra if ra > rs else 0.0) - (1 / rb if rb > rs else 0.0)) / sg)
        if max(abs(v) for v in h) == 0:
            rs += step
            continue
        A = [jr + [hv] for jr, hv in zip(J, h)]
        delta, cov, _ = fitlib.lstsq_qr(A, r0)
        fitted = [sum(a * d for a, d in zip(row, delta)) for row in A]
        chi = math.fsum((a - b) ** 2 for a, b in zip(r0, fitted))
        g, sg_g = delta[-1], math.sqrt(cov[-1][-1])
        out.append((rs, g, sg_g, chi0 - chi))
        if best is None or chi0 - chi > best[3]:
            best = (rs, g, sg_g, chi0 - chi)
        rs += step
    dof = res['dof']
    birge = math.sqrt(chi0 / dof)
    print(f'\n== {label}: {len(prob.rows)} points, runs {runs}; smooth quadratic chi2/dof {chi0 / dof:.2f}')
    print(f'   best single step at r = {best[0]:.1f} mm: g = {best[1] * 1000:+.0f} um +- {best[2] * 1000:.0f} '
          f'(x{birge:.2f} scaled: +- {best[2] * birge * 1000:.0f}), delta chi2 = {best[3]:.1f}')
    for rs, g, sg_g, dchi in out:
        if abs(rs * 10 - round(rs * 2) * 5) < 1e-6 and 28.0 <= rs <= 38.0:   # every 0.5 mm in 28..38
            print(f'     r_step {rs:4.1f} mm: g {g * 1000:+5.0f} +- {sg_g * 1000:3.0f} um   dchi2 {dchi:5.1f}')
    return out


box = fitlib.load_rows()
out1 = scan('disc 1 (two ladders)', box, ['disc1_run1', 'disc1_run2'])
out3 = scan('disc 3 (two ladders)', box, ['disc3', 'disc3_2482rpm'])
d5 = ladder_rows(os.path.join(RES, 'disc5_cubic_r3'), 'disc5_r3')
d5 += localsteps_rows(os.path.join(RES, 'disc5_link', 'localsteps_44898.csv'), 'disc5_ls1')
d5 += localsteps_rows(os.path.join(RES, 'disc5_link2', 'localsteps_93936.csv'), 'disc5_ls2')
runs5 = ['disc5_r3', 'disc5_ls1', 'disc5_ls2']
for sub in ('disc5_jog', 'disc5_jog2'):       # targeted runs around the jog (reference 60067, r = 32.8 mm)
    jog = os.path.join(RES, sub, 'localsteps_60067.csv')
    if os.path.exists(jog):
        d5 += localsteps_rows(jog, sub)
        runs5.append(sub)
out5 = scan(f'disc 5 = test disc (ladder + {len(runs5) - 1} localsteps)', d5, runs5)
print('   disc 5, 32.0..35.0 mm in 0.1 mm steps:')
for rs, g, sg_g, dchi in out5:
    if 32.0 - 1e-9 <= rs <= 35.0 + 1e-9:
        print(f'     r_step {rs:4.1f} mm: g {g * 1000:+5.0f} +- {sg_g * 1000:3.0f} um   dchi2 {dchi:5.1f}')

# Same step radius on every disc (a drive-made link at a fixed LBA), own size per disc: sum of delta chi2.
print()
print('== joint profile: one step radius for discs 1, 3 and 5, own g per disc')
by = {}
for name, out in (('disc1', out1), ('disc3', out3), ('disc5', out5)):
    for rs, g, sg_g, dchi in out:
        by.setdefault(round(rs, 1), {})[name] = (g, sg_g, dchi)
rows = [(rs, d) for rs, d in sorted(by.items()) if len(d) == 3]
best = max(rows, key=lambda x: sum(v[2] for v in x[1].values()))
for rs, d in rows:
    if 31.0 <= rs <= 36.0 and abs(rs * 10 - round(rs * 5) * 2) < 1e-6:
        tot = sum(v[2] for v in d.values())
        print(f'   r_step {rs:4.1f}: total dchi2 {tot:5.1f}   ' + '  '.join(f'{n} {v[0]*1000:+4.0f}+-{v[1]*1000:3.0f}' for n, v in d.items()))
print(f'   best common radius {best[0]:.1f} mm: total dchi2 {sum(v[2] for v in best[1].values()):.1f}; '
      + ', '.join(f'{n} g = {v[0]*1000:+.0f} +- {v[1]*1000:.0f} um' for n, v in best[1].items()))
