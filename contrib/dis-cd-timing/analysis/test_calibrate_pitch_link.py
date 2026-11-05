#!/usr/bin/env python3
"""Tests of calibrate_pitch.py --link / --localsteps (standard library only; no drive access). Prints PASS or FAIL per
test and exits 1 if any test failed.

    python -I analysis\\test_calibrate_pitch_link.py [--baseline DIR] [--only abce] [--keep DIR] [--jobs N]

(a) regression: without --link and --localsteps, stdout and JSON are byte-identical to the baseline captured from the
    tool BEFORE the change. DIR/cases.json lists the exact command lines (absolute run directories, a relative --json
    name); each is replayed with cwd = a scratch directory, so the printed "JSON written to <name>.json" line matches.
    Default DIR: the workflow scratch folder the baseline was written to (pass --baseline when it moved).
(b) synthetic recovery on results\\disc5_cubic_r3's rung LBAs, reference and sigmas: a known quadratic truth (the
    Lenovo box values, 359845 sectors) plus a write link g at LBA 65500, h from the TRUE spiral's radii, Gaussian noise
    with a fixed seed (SEED below). With --link 65500: g and ri/ro/c1/c2 within 3 SE (g = +0.20 and -0.15 mm); without
    it the known bias reappears (exactly the noiseless no-link bias, scaled by the fitted g: the restricted fit equals
    the full fit plus the regression of h on the smooth model times g); a fixed gap (--link 65500=0.20) equals the fit
    of the same noise without a step. (b-mc) repeats the recovery in-process over MC_N noise draws (mean and rms of
    the z values), so the result does not hang on one draw. (b0) unit checks of the link columns, the Jacobian, the
    joint identifiability test of several free links (against the rank of the linear block), the localsteps conversion
    and radius-column check, and the argument parsing.
(c) real disc 5: results\\disc5_cubic_r3 plus the four localsteps runs with --link 65536 (g expected near +0.20 mm,
    step_scan.py / link_locate.py), compared with the same data without --link (which must warn) and with the ladder
    alone.
(e) edge cases: two free links with no rung or only a reference LBA between them are refused; a cross-validation fold
    that alone measures a link is skipped for every model (a link with one rung beyond it; synthetic ladder runs that
    each measure one of two links, with and without a third run, the latter leaving no fold); the localsteps prior is
    checked against the measured disc's own sector count (summary.json), not --sectors; --start only seeds the fit.
"""
import argparse, concurrent.futures, csv, json, locale, math, os, random, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TOOL = os.path.join(HERE, 'calibrate_pitch.py')
RES = os.path.join(ROOT, 'results')
for _p in (HERE, os.path.join(HERE, 'pitchfit'), os.path.join(HERE, 'fv')):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import calibrate_pitch as cp       # noqa: E402
import fitlib                      # noqa: E402
import spiral                      # noqa: E402
from common import reduce_ladder   # noqa: E402

# contrib: the regression baseline (stdout and JSON of the tool before --link existed) is not
# included; run with --only bce, or capture one from the original tool and pass --baseline DIR.
DEFAULT_BASELINE = 'baseline-not-included'
SECTORS = 359845
TRACK = cp.track_mm(SECTORS)
TRUE = [24.921551846562572, 57.838950219991993, -3.8950535120452173e-05, 1.5748336087855265e-05, 0.0]   # README box
K_SYN = 65500
# Noise seed of the CLI runs: the first of 1, 2, 3, ... (seed 1; its no-step quadratic fit lies at Mahalanobis^2 3.3
# from the truth, a typical draw). The step-bias study's seed 20261105 draws a ~4 sigma realization of the noise itself
# on this rung set (the no-step fit of that noise is off by z = -4.05 in c2), which fails a 3-sigma check for any model,
# link or not; the Monte Carlo check (b-mc) shows the coverage independently of the seed.
SEED = 1
MC_N, MC_SEED0 = 60, 1000
KAPPA_SYN = 0.0123              # rad, an arbitrary run constant the fit must absorb
LS_FILES = [os.path.join(RES, 'disc5_jog', 'localsteps_60067.csv'), os.path.join(RES, 'disc5_jog2', 'localsteps_60067.csv'),
            os.path.join(RES, 'disc5_link', 'localsteps_44898.csv'), os.path.join(RES, 'disc5_link2', 'localsteps_93936.csv')]
DISC5 = os.path.join(RES, 'disc5_cubic_r3')
NM = ('ri', 'ro', 'c1', 'c2')

results = []


def report(name, ok, msg):
    results.append((name, ok))
    print(f'{"PASS" if ok else "FAIL"} {name}: {msg}', flush=True)


def run_tool(args, cwd):
    p = subprocess.run([sys.executable, '-I', TOOL] + args, cwd=cwd, capture_output=True)
    return p.returncode, p.stdout, p.stderr


def load_json(path):
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def first_diff(a, b):
    la, lb = a.split(b'\n'), b.split(b'\n')
    for i, (x, y) in enumerate(zip(la, lb)):
        if x != y:
            return (f'line {i + 1}: baseline {x.decode("utf-8", "replace")[:160]!r} / now '
                    f'{y.decode("utf-8", "replace")[:160]!r}')
    return f'line count {len(la)} vs {len(lb)}'


def fmt_d(p, q):
    """Parameter differences p - q as 'ri +x nm, ro +x nm, c1 +x, c2 +x'."""
    return ', '.join(f'{n} {(a - b) * 1e6:+.1f} nm' if n in ('ri', 'ro') else f'{n} {a - b:+.2e}'
                     for n, a, b in zip(NM, p, q))


# ------------------------------------------------------------------------------------------------ (a) regression
def jobs_a(base, work):
    meta = load_json(os.path.join(base, 'cases.json'))
    os.makedirs(work, exist_ok=True)
    return {f'a:{c["name"]}': (c['args'], work) for c in meta['cases']}, meta


def eval_a(base, work, meta, out):
    for c in meta['cases']:
        rc, so, se = out[f'a:{c["name"]}']
        with open(os.path.join(base, f'{c["name"]}.stdout'), 'rb') as fh:
            so0 = fh.read()
        with open(os.path.join(base, c['json']), 'rb') as fh:
            js0 = fh.read()
        try:
            with open(os.path.join(work, c['json']), 'rb') as fh:
                js = fh.read()
        except OSError:
            js = None
        problems = []
        if rc != c['returncode']:
            problems.append(f'exit code {rc} (baseline {c["returncode"]}); stderr {se.decode("utf-8", "replace")[-300:]!r}')
        if so != so0:
            problems.append('stdout differs at ' + first_diff(so0, so))
        if js != js0:
            problems.append('JSON differs' + ('' if js is None else ' at ' + first_diff(js0, js)))
        report(f'(a) regression {c["name"]}', not problems,
               '; '.join(problems) if problems else f'stdout {len(so)} B and JSON {len(js)} B byte-identical to the baseline')


# ------------------------------------------------------------------------------------------------ (b) synthetic
def synth_setup():
    ref, data = reduce_ladder(DISC5)
    sp = spiral.SpiralGeometry(TRUE[0], TRUE[1], TRACK, *TRUE[2:])
    ks = [k for k, _, _ in data]
    th = {k: sp.angle_at_arc(16.0 * (k + 1)) for k in ks + [ref]}
    rad = {k: sp.radius_at_arc(16.0 * (k + 1))[0] for k in ks + [ref]}
    rng = random.Random(SEED)
    noise = [rng.gauss(0.0, s) for _, _, s in data]
    return ref, data, th, rad, noise


def synth_rows(setup, g, noisy=True, noise=None):
    ref, data, th, rad, noise0 = setup
    noise = noise0 if noise is None else noise

    def h(k):
        return 1.0 / rad[k] if k >= K_SYN else 0.0
    return [{'run': 'synth', 'ref': ref, 'lba': k, 'sig': s,
             'y': th[k] - th[ref] + g * (h(k) - h(ref)) + KAPPA_SYN + (e if noisy else 0.0)}
            for (k, _, s), e in zip(data, noise)]


def mc_checks(setup, g_true=0.20):
    """In-process Monte Carlo (fit_model, as the tool fits): MC_N noise draws with the step in the data, quadratic fit
    with and without the link term. With it: z = (estimate - truth) / formal SE must have mean ~0 and rms ~1 for g, ri,
    ro, c1, c2; without it the mean deviation must equal the noiseless (known) bias."""
    ref, data, th, rad, _ = setup
    true4 = TRUE[:4]
    known = [a - b for a, b in zip(cp.nl(cp.fit_model(synth_rows(setup, g_true, noisy=False), 'quadratic', list(true4),
                                                     TRACK, 0.0, diagnostics=False)), true4)]
    zl, dn, sn = [], [], []
    for i in range(MC_N):
        rng = random.Random(MC_SEED0 + i)
        rows = synth_rows(setup, g_true, noise=[rng.gauss(0.0, s) for _, _, s in data])
        lk, _ = cp.link_geometry(rows, [(K_SYN, None)], TRACK, 0.0)      # the tool's h geometry for these data
        fl = cp.fit_model(rows, 'quadratic', list(true4), TRACK, 0.0, diagnostics=False, links=lk)
        sf = fl['sigma_formal']
        m = fl['problem'].n_nl + fl['problem'].n_kappa
        zl.append([(a - b) / s for a, b, s in zip(cp.nl(fl), true4, sf)] + [(fl['p'][m] - g_true) / sf[m]])
        fn = cp.fit_model(rows, 'quadratic', list(true4), TRACK, 0.0, diagnostics=False)
        dn.append([a - b for a, b in zip(cp.nl(fn), true4)])
        sn.append(fn['sigma_formal'][:4])
    names = list(NM) + ['g']
    mean = [sum(z[j] for z in zl) / MC_N for j in range(5)]
    rms = [math.sqrt(sum(z[j] ** 2 for z in zl) / MC_N) for j in range(5)]
    ok_l = all(abs(m) <= 3 / math.sqrt(MC_N) for m in mean) and all(0.67 <= r <= 1.38 for r in rms)
    report(f'(b-mc) {MC_N} noise draws, g = {g_true:+.2f} mm, --link: unbiased, SE right', ok_l,
           'z mean ' + ', '.join(f'{n} {m:+.2f}' for n, m in zip(names, mean)) + f' (limit +-{3 / math.sqrt(MC_N):.2f}); '
           'z rms ' + ', '.join(f'{n} {r:.2f}' for n, r in zip(names, rms)) + ' (limits 0.67 .. 1.38)')
    mdev = [sum(d[j] for d in dn) / MC_N for j in range(4)]
    sd = [math.sqrt(sum((d[j] - mdev[j]) ** 2 for d in dn) / (MC_N - 1)) for j in range(4)]
    zb = [(m - k) / (s / math.sqrt(MC_N)) for m, k, s in zip(mdev, known, sd)]
    z0 = [m / (s / math.sqrt(MC_N)) for m, s in zip(mdev, sd)]
    ok_n = all(abs(z) <= 3 for z in zb) and max(abs(z) for z in z0) >= 3
    report(f'(b-mc) {MC_N} noise draws, no --link: the known bias reappears', ok_n,
           'mean deviation from the truth ' + fmt_d([a + b for a, b in zip(true4, mdev)], true4)
           + ' vs the known bias ' + fmt_d([a + b for a, b in zip(true4, known)], true4) + ' (z ' +
           ', '.join(f'{z:+.2f}' for z in zb) + '); the mean differs from zero by up to '
           f'{max(abs(z) for z in z0):.1f} sigma of the mean')


def write_rungs(path, rows):
    with open(path, 'w', newline='', encoding='utf-8') as fh:
        w = csv.writer(fh)
        w.writerow(['run', 'ref_lba', 'lba', 'y_rad', 'sigma_rad'])
        for r in rows:
            w.writerow([r['run'], r['ref'], r['lba'], repr(r['y']), repr(r['sig'])])


B_CASES = {   # name: (g in the data, noisy, extra arguments)
    'link_p20': (0.20, True, ['--link', str(K_SYN)]),
    'nolink_p20': (0.20, True, []),
    'link_m15': (-0.15, True, ['--link', str(K_SYN)]),
    'nolink_m15': (-0.15, True, []),
    'fixed_p20': (0.20, True, ['--link', f'{K_SYN}=0.20']),
    'nostep': (0.0, True, []),
    'noiseless_link_p20': (0.20, False, ['--link', str(K_SYN)]),
    'noiseless_nolink_p20': (0.20, False, []),
    'noiseless_nolink_m15': (-0.15, False, []),
}


def jobs_b(work, setup):
    os.makedirs(work, exist_ok=True)
    jobs = {}
    for name, (g, noisy, extra) in B_CASES.items():
        csv_path = os.path.join(work, f'rungs_g{g:+.2f}_{"noisy" if noisy else "noiseless"}.csv')
        write_rungs(csv_path, synth_rows(setup, g, noisy))         # (shared by the cases with the same data)
        jobs[f'b:{name}'] = (['--rungs', csv_path, '--sectors', str(SECTORS), '--json', f'b_{name}.json'] + extra, work)
    return jobs


def quad(js):
    q = js['fits']['quadratic']
    return q['params5'][:4], q['se'][:4], q


def line_B(p_fit):
    """Ruler B / bow of a radial line burned with p_fit on the smooth TRUE spiral (the step excluded), as in the
    independent step-bias study (step_bias.py line_stats)."""
    true_sp = spiral.SpiralGeometry(TRUE[0], TRUE[1], TRACK, *TRUE[2:])
    band = cp.Band(TRUE[0], TRUE[1])
    sg = [cp.arc_at_radius(true_sp, r) for r in band.grid]
    fit_sp = cp.make_spiral('quadratic', list(p_fit), TRACK)
    st = cp.map_stats([true_sp.angle_at_arc(s) - fit_sp.angle_at_arc(s) for s in sg], band.grid)
    return st['B_mm'], st['bow_mm']


def unit_checks(setup):
    ref, data, th, rad, noise = setup
    rows = synth_rows(setup, 0.20)
    h_true = [((1 / rad[r['lba']]) if r['lba'] >= K_SYN else 0.0) - ((1 / rad[r['ref']]) if r['ref'] >= K_SYN else 0.0)
              for r in rows]

    def h_err(links):
        H = cp.LinkProblem(rows, 'quadratic', TRACK, 0.0, links).H[0]
        return (max(abs(a - b) / abs(b) for a, b in zip(H, h_true) if b != 0),
                max(abs(a - b) * 0.20 for a, b in zip(H, h_true)))
    rel0, _ = h_err(cp.WriteLinks([(K_SYN, None)], *cp.default_start(TRACK), TRACK))
    lk, info = cp.link_geometry(rows, [(K_SYN, None)], TRACK, 0.0)
    rel, abs_rad = h_err(lk)
    report('(b0) link column vs the true spiral', rel < 1e-4 and info['converged'],
           f'h on the converged area fit with the link ({info["passes"]} passes, last move {info["last_move_mm"]:.0e} '
           f'mm) differs from h on the true spiral by max {rel:.1e} relative (on the default start geometry: '
           f'{rel0:.1e}), g h by max {abs_rad:.1e} rad at g = 0.20 mm (rung sigma >= '
           f'{min(s for _, _, s in data):.1e} rad)')
    pr = cp.LinkProblem(rows, 'quadratic', TRACK, 0.0, lk)
    p = list(TRUE[:4]) + pr.initial_kappa(TRUE[:4])
    J = pr.jacobian(p)
    m = pr.n_nl + pr.n_kappa
    dg = 1e-3
    q = list(p)
    q[m] += dg
    fd = [(a - b) / dg for a, b in zip(pr.residuals(p), pr.residuals(q))]       # d(model)/dg / sigma = -d(res)/dg
    err = max(abs(a[m] - b) / abs(b) for a, b in zip(J, fd) if b != 0)
    kap_ok = all(abs(row[pr.n_nl] - 1.0 / s) <= 1e-12 / s for row, s in zip(J, pr.sig))
    report('(b0) analytic Jacobian column of g', err < 1e-8 and kap_ok and len(J[0]) == pr.n_par,
           f'column (h(lba) - h(ref)) / sigma vs finite difference of the residuals: max rel. diff {err:.1e}; '
           f'{len(J[0])} columns = n_par {pr.n_par}')
    try:
        cp.LinkProblem([r for r in rows if r['lba'] >= K_SYN], 'quadratic', TRACK, 0.0, lk)
        ok, msg = False, 'no error'
    except ValueError as e:
        ok, msg = True, str(e)
    report('(b0) unmeasurable free gap refused', ok, f'rungs on one side of the link only -> {msg}')
    ok_p = (cp.parse_links(['65536']) == [(65536, None)] and cp.parse_links(['65536=0.2', '90000']) ==
            [(65536, 0.2), (90000, None)])
    for bad in (['65536', '65536=0.1'], ['x'], ['0'], ['65536=nan']):
        try:
            cp.parse_links(bad)
            ok_p = False
        except SystemExit:
            pass
    report('(b0) --link parsing', ok_p, 'LBA and LBA=G accepted; duplicate, non-numeric, LBA 0 and NaN gap refused')
    # localsteps conversion, recomputed here the step_scan.py way (localsteps_rows)
    worst = 0.0
    for path in LS_FILES:
        ref_ls, dat, dev = cp.localsteps_run(path, cp.LOCALSTEPS_PRIOR)
        r0, r1, n = cp.LOCALSTEPS_PRIOR
        L = n / 75 * 1200
        with open(path, newline='', encoding='utf-8') as fh:
            recs = list(csv.DictReader(fh))
        for (k, y, s), rec in zip(dat, recs):
            y2 = (spiral.area_angle(16.0 * (k + 1), r0, r1, L) - spiral.area_angle(16.0 * (ref_ls + 1), r0, r1, L)
                  + math.radians(float(rec['measured_minus_prior_deg'])))
            worst = max(worst, abs(y - y2), abs(s - math.radians(float(rec['sigma_deg']))))
    try:
        cp.localsteps_run(LS_FILES[0], (24.9216305, 57.8390244, 333000))
        refused = False
    except SystemExit:
        refused = True
    report('(b0) localsteps conversion', worst < 1e-12 and refused,
           f'y and sigma equal step_scan.py\'s conversion to {worst:.1e} rad; a 333000-sector prior is refused by the '
           f'radius-column check: {refused}')


def linear_block_cond(rows, specs):
    """2-norm condition number of the column-scaled weighted linear block [kappas | free gap columns] (inf: singular)."""
    pr = cp.LinkProblem(rows, 'area', TRACK, 0.0, cp.WriteLinks([(k, None) for k in specs], *cp.default_start(TRACK),
                                                                TRACK), check=False)
    A = [[(1.0 / s) if pr.run_idx[i] == j else 0.0 for j in range(pr.n_kappa)] + [c[i] / s for c in pr.H]
         for i, s in enumerate(pr.sig)]
    try:
        return fitlib.lstsq_qr(A, [0.0] * len(A))[2]
    except ZeroDivisionError:
        return float('inf')


def unit_checks_links(setup):
    """Joint identifiability of several free links (WriteLinks.unmeasured, also LinkProblem(check=True)), on disc 5's
    ladder and localsteps runs, against the numerical rank of the linear block."""
    ref, data, th, rad, _ = setup
    runs = cp.load_runs([DISC5])
    lad = cp.rows_of(runs)
    allr = cp.rows_of(runs + cp.load_localsteps(LS_FILES, cp.LOCALSTEPS_PRIOR, [r['name'] for r in runs]))
    # (rows, links, degenerate, text the reason must contain)
    cases = [('ladder + localsteps, links 60000 / 60100: only the reference LBA 60067 between them', allr, (60000, 60100),
              True, 'no rung in LBA 60000 .. 60099 (only the reference LBA 60067'),
             ('ladder alone, links 60000 / 65536: no rung between them', lad, (60000, 65536), True,
              'no rung in LBA 60000 .. 65535'),
             ('ladder + localsteps, links 65536 / 65540', allr, (65536, 65540), True, 'no rung in LBA 65536 .. 65539'),
             ('ladder + localsteps, links 65536 / 131072', allr, (65536, 131072), False, ''),
             ('ladder + localsteps, links 65536 / 65600 (targets 65556 between)', allr, (65536, 65600), False, '')]
    ok_all, parts = True, []
    for label, rows, specs, degen, text in cases:
        bad = cp.WriteLinks([(k, None) for k in specs], *cp.default_start(TRACK), TRACK).unmeasured(rows)
        cond = linear_block_cond(rows, specs)
        try:
            cp.LinkProblem(rows, 'area', TRACK, 0.0, cp.WriteLinks([(k, None) for k in specs], *cp.default_start(TRACK),
                                                                   TRACK))
            raised = False
        except ValueError:
            raised = True
        ok = (bool(bad) == degen == raised and (not degen or (len(bad) == 2 and all(text in w for _, w in bad)
                                                                and cond > 1e10)) and (degen or cond < 1e7))
        ok_all &= ok
        parts.append(f'{label}: {"refused" if bad else "accepted"}, linear-block cond {cond:.1e}'
                     + (f' ({bad[0][1]})' if bad else '') + ('' if ok else ' <- WRONG'))
    report('(b0) joint identifiability of two free links', ok_all, '; '.join(parts))
    # stricter than the rank: run A has rungs on both sides of both links, run B only between them. Each link alone has
    # a run with rungs on both sides (the old per-link test passed), yet only g1 + g2 is seen as a step; B sees g1 alone
    # through 1/r across its rungs, which the smooth spiral can mimic.
    k1, k2 = 65500, 200000
    rows = ([{'run': 'A', 'ref': ref, 'lba': k, 'y': 0.0, 'sig': s} for k, _, s in data if k < k1 or k >= k2] +
            [{'run': 'B', 'ref': ref, 'lba': k, 'y': 0.0, 'sig': s} for k, _, s in data if k1 <= k < k2])
    bad = cp.WriteLinks([(k1, None), (k2, None)], *cp.default_start(TRACK), TRACK).unmeasured(rows)
    per_link = all(any({r['lba'] >= k for r in rows if r['run'] == run} == {True, False} for run in 'AB')
                   for k in (k1, k2))
    cond = linear_block_cond(rows, (k1, k2))
    report('(b0) a chain of runs: stricter than the rank', len(bad) == 2 and per_link and math.isfinite(cond),
           f'run A across both links {k1} / {k2}, run B between them only: refused ({bad[0][1] if bad else "-"}) '
           f'although each link has a run with rungs on both sides ({per_link}) and the linear block has cond {cond:.1e}')


def unit_checks_radius():
    """localsteps radius-column check: the probe's 4-decimal radii (jog2, link2) are checked to 6e-5 mm, columns without
    a non-zero 4th decimal (jog, rebuilt from 3-decimal console text; link, round targets) to 5e-4 mm. A prior off by 4
    sectors is then refused by jog2 and link2, while the right one passes (jog with a warning in the report)."""
    names = ['jog', 'jog2', 'link', 'link2']
    r0, r1, n0 = cp.LOCALSTEPS_PRIOR
    res = {}
    for n in (n0, n0 + 4, n0 - 4):
        for nm, p in zip(names, LS_FILES):
            try:
                res[n, nm] = cp.localsteps_run(p, (r0, r1, n))[2]
            except SystemExit:
                res[n, nm] = None
    good = [res[n0, nm] for nm in names]
    ok = (all(c is not None for c in good) and [c['decimals4'] for c in good] == [False, True, False, True] and
          good[0]['max_mm'] > cp.LOCALSTEPS_RADIUS_TOL and all(c['max_mm'] <= cp.LOCALSTEPS_RADIUS_TOL for c in good[1:])
          and all(res[n, nm] is None for n in (n0 + 4, n0 - 4) for nm in ('jog2', 'link2')) and
          all(res[n, nm] is not None for n in (n0 + 4, n0 - 4) for nm in ('jog', 'link')) and
          all(c['blind_sectors'] <= 2 for c in (good[1], good[3])))
    report('(b0) localsteps radius-column check', ok,
           f'prior {n0}: ' + ', '.join(f'{nm} {c["max_mm"]:.1e} mm ({"4" if c["decimals4"] else "no 4th"} decimals, a '
                                       f'prior off by <= {c["blind_sectors"]} passes)' for nm, c in zip(names, good))
           + '; priors of ' + ' / '.join(str(n) for n in (n0 + 4, n0 - 4)) + ' sectors: ' + ', '.join(
               f'{nm} ' + ('/'.join('refused' if res[n, nm] is None else 'passed' for n in (n0 + 4, n0 - 4)))
               for nm in names))


def eval_b(work, out):
    js = {}
    for name in B_CASES:
        rc, so, se = out[f'b:{name}']
        if rc != 0:
            report(f'(b) run {name}', False, f'exit code {rc}: {se.decode("utf-8", "replace")[-400:]}')
            return
        js[name] = load_json(os.path.join(work, f'b_{name}.json'))
    true4 = TRUE[:4]

    # recovery with a fitted gap
    for name, g_true in (('link_p20', 0.20), ('link_m15', -0.15)):
        p, se, q = quad(js[name])
        e = q['links'][0]
        zg = (e['g_mm'] - g_true) / e['sigma_scaled_mm']
        zp = [(a - b) / s for a, b, s in zip(p, true4, se)]
        ok = abs(zg) <= 3 and all(abs(z) <= 3 for z in zp) and not e['fixed']
        report(f'(b) recovery g = {g_true:+.2f} mm, --link {K_SYN}', ok,
               f'g {e["g_mm"]:+.4f} mm +- {e["sigma_formal_mm"]:.4f} formal / {e["sigma_scaled_mm"]:.4f} scaled '
               f'(z {zg:+.2f}); quadratic minus truth: {fmt_d(p, true4)} (z ' + ', '.join(f'{z:+.2f}' for z in zp)
               + f'); chi2/dof {q["chi2_dof"]:.2f}; recommended {js[name]["selection"]["recommended"]}')

    # noiseless: exact recovery with the link, and the known bias without it
    p, se, q = quad(js['noiseless_link_p20'])
    e = q['links'][0]
    dz = max(abs(a - b) / s for a, b, s in zip(p, true4, se))
    report('(b) noiseless, --link: exact recovery', dz < 1e-3 and abs(e['g_mm'] - 0.20) < 1e-3 * e['sigma_formal_mm'],
           f'max |p - truth| {dz:.1e} SE, g {e["g_mm"]:+.7f} mm, chi2 {q["chi2"]:.2e}')
    bias, ruler = {}, {}
    for g_true, name in ((0.20, 'noiseless_nolink_p20'), (-0.15, 'noiseless_nolink_m15')):
        pb, seb, qb = quad(js[name])
        bias[g_true] = [a - b for a, b in zip(pb, true4)]
        ruler[g_true] = line_B(pb)
        print(f'      known bias of an unmodelled {g_true:+.2f} mm step (noiseless, this rung set): {fmt_d(pb, true4)}; '
              f'ruler B {ruler[g_true][0]:+.3f} mm, bow {ruler[g_true][1]:+.3f} mm; chi2 {qb["chi2"]:.2f} / '
              f'{qb["dof"]}; recommended {js[name]["selection"]["recommended"]}')
    lin = max(abs(a / 0.20 - b / -0.15) / (abs(a / 0.20) + 1e-300) for a, b in zip(bias[0.20], bias[-0.15]))
    b20 = bias[0.20]
    B20 = ruler[0.20][0]
    sign_ok = b20[2] > 0 and b20[3] < 0 and b20[1] < 0 and 0.2 <= B20 <= 0.8
    report('(b) known bias of an unmodelled +0.20 mm step', sign_ok and lin < 0.02,
           f'{fmt_d([a + b for a, b in zip(true4, b20)], true4)}, ruler B {B20:+.3f} mm (independent study on its '
           f'simulated ladder: ri +3 nm, ro -6 nm, c1 +1.1e-05, c2 -1.1e-05, B +0.40 mm); linear in g to {lin:.1e}')
    for name_l, name_n, g_true in (('link_p20', 'nolink_p20', 0.20), ('link_m15', 'nolink_m15', -0.15)):
        pl, sel, ql = quad(js[name_l])
        pn, sen, qn = quad(js[name_n])
        ghat = ql['links'][0]['g_mm']
        pred = [b * ghat / g_true for b in bias[g_true]]
        dev = [((a - c) - d) / s for a, c, d, s in zip(pn, pl, pred, sen)]
        dz_true = [(a - b) / s for a, b, s in zip(pn, true4, sen)]
        dchi = qn['chi2'] - ql['chi2']
        ok = max(abs(v) for v in dev) < 0.02 and abs(dchi - (ghat / ql['links'][0]['sigma_formal_mm']) ** 2) < 0.05 * dchi + 0.05
        report(f'(b) bias reappears without --link (g = {g_true:+.2f} mm)', ok,
               f'no-link minus link fit {fmt_d(pn, pl)} = known bias x g_fit/g ({ghat:+.4f}/{g_true:+.2f}) to max '
               f'{max(abs(v) for v in dev):.1e} SE; no-link minus truth z ' + ', '.join(f'{z:+.2f}' for z in dz_true)
               + f'; chi2 +{dchi:.2f} = (g/sigma_g)^2 {(ghat / ql["links"][0]["sigma_formal_mm"]) ** 2:.2f}; selection '
               f'{js[name_n]["selection"]["recommended"]} (no link) / {js[name_l]["selection"]["recommended"]} (link)')

    # fixed gap
    pf, sef, qf = quad(js['fixed_p20'])
    p0, se0, q0 = quad(js['nostep'])
    e = qf['links'][0]
    dz = max(abs(a - b) / s for a, b, s in zip(pf, p0, se0))
    zt = [(a - b) / s for a, b, s in zip(pf, true4, sef)]
    ok = (dz < 2e-3 and e['fixed'] and e['g_mm'] == 0.20 and qf['dof'] == q0['dof'] and
          all(abs(z) <= 3 for z in zt))
    report(f'(b) fixed gap --link {K_SYN}=0.20', ok,
           f'equals the fit of the same noise without a step to {dz:.1e} SE (dof {qf["dof"]} = {q0["dof"]}: no '
           f'parameter); minus truth z ' + ', '.join(f'{z:+.2f}' for z in zt))


# ------------------------------------------------------------------------------------------------ (c) disc 5
C_CASES = {
    'link': ['--link', '65536'] + sum((['--localsteps', p] for p in LS_FILES), []) + [DISC5],
    'nolink': sum((['--localsteps', p] for p in LS_FILES), []) + [DISC5],
    'ladder_link': ['--link', '65536', DISC5],
    'link65600': ['--link', '65600'] + sum((['--localsteps', p] for p in LS_FILES), []) + [DISC5],   # information
}


def jobs_c(work):
    os.makedirs(work, exist_ok=True)
    return {f'c:{n}': (['--sectors', str(SECTORS), '--json', f'c_{n}.json'] + a, work) for n, a in C_CASES.items()}


def rec_fit(js):
    k = js['selection']['recommended']
    return k, js['fits'][k]


def eval_c(work, out, base_ladder_json):
    js = {}
    for name in C_CASES:
        rc, so, se = out[f'c:{name}']
        if rc != 0:
            report(f'(c) run {name}', False, f'exit code {rc}: {se.decode("utf-8", "replace")[-400:]}')
            return
        js[name] = load_json(os.path.join(work, f'c_{name}.json'))
        js[name]['_stdout'] = so.decode(locale.getpreferredencoding(False), 'replace')   # the child's console encoding
    js['ladder'] = load_json(base_ladder_json) if base_ladder_json and os.path.exists(base_ladder_json) else None
    L = js['link']
    kind, f = rec_fit(L)
    e = f['links'][0]
    r = L['links']['recommended'][0]
    av = L['app_values']
    print(f'      disc 5, ladder + 4 localsteps, --link 65536 ({kind}): g = {e["g_mm"]:+.4f} mm +- '
          f'{e["sigma_formal_mm"]:.4f} formal / {e["sigma_scaled_mm"]:.4f} chi2-scaled; LBA 65536 at r = '
          f'{r["r_link_mm"]:.4f} mm; chi2 {f["chi2"]:.2f} / {f["dof"]}')
    print(f'      app values: ri {av["ri"]!r} ro {av["ro"]!r} c1 {av["c1"]!r} c2 {av["c2"]!r} c3 {av["c3"]!r}')
    print(f'      {L["links"]["prewarp_command"]}')
    for k2 in ('area', 'quadratic', 'cubic'):
        e2 = L['fits'][k2]['links'][0]
        print(f'      gap per model: {k2:9s} g {e2["g_mm"]:+.4f} +- {e2["sigma_formal_mm"]:.4f} / {e2["sigma_scaled_mm"]:.4f} mm')
    for nm_cmp, label in (('nolink', 'same data without --link'), ('ladder', 'ladder alone, no --link (baseline)'),
                          ('ladder_link', 'ladder alone, --link 65536')):
        J = js[nm_cmp]
        if J is None:
            print(f'      {label}: not available')
            continue
        k3, f3 = rec_fit(J)
        p3 = f3['params5'][:4]
        extra = ''
        if 'links' in f3:
            extra = f'; g {f3["links"][0]["g_mm"]:+.4f} +- {f3["links"][0]["sigma_scaled_mm"]:.4f} mm'
        print(f'      {label} ({k3}): ri {p3[0]!r} ro {p3[1]!r} c1 {p3[2]:.4e} c2 {p3[3]:.4e}; chi2 {f3["chi2"]:.2f} / '
              f'{f3["dof"]}{extra}; minus the --link fit: {fmt_d(p3, f["params5"][:4])}')
    # ruler B of a line burned with the no-link values on the --link fit's spiral (the step excluded)
    N = js['nolink']
    kn, fn = rec_fit(N)
    sp_l = cp.make_spiral(kind, f['params5'][:len(fitlib.NL_NAMES[kind])], TRACK)
    sp_n = cp.make_spiral(kn, fn['params5'][:len(fitlib.NL_NAMES[kn])], TRACK)
    band = cp.Band(*f['params5'][:2])
    sg = [cp.arc_at_radius(sp_l, rr) for rr in band.grid]
    ms = cp.map_stats([sp_l.angle_at_arc(s) - sp_n.angle_at_arc(s) for s in sg], band.grid)
    print(f'      line burned with the no-link values on the --link spiral: ruler B {ms["B_mm"]:+.3f} mm, bow '
          f'{ms["bow_mm"]:+.3f} mm @ {ms["bow_at_mm"]:.2f} mm, max tangential {ms["max_tangential_mm"]:.3f} mm')
    k6, f6 = rec_fit(js['link65600'])
    e6 = f6['links'][0]
    print(f'      (information) --link 65600 instead, between the localsteps targets 65556 and 65636 (link_locate.py\'s '
          f'best interval): g {e6["g_mm"]:+.4f} +- {e6["sigma_formal_mm"]:.4f} / {e6["sigma_scaled_mm"]:.4f} mm, '
          f'{k6} chi2 {f6["chi2"]:.2f} vs {f["chi2"]:.2f} at 65536')
    qn, ql = N['fits']['quadratic'], L['fits']['quadratic']
    dchi = qn['chi2'] - ql['chi2']
    smooth = (av['ri'], av['ro'], av['c1'], av['c2'], av['c3']) == tuple(f['params5']) and kind == av['model']
    app_line = [ln for ln in L['_stdout'].splitlines() if ln.startswith('==> app values')]
    cmd_ok = L['links']['prewarp_command'] == (
        f'python -I analysis\\prewarp.py <design.png> <out.png> --r1 {cp.fmt_num(av["ro"])} --coeffs 0 --const 0 '
        f'--link {r["r_link_mm"]:.4f},{e["g_mm"]:.4f}')
    ok = (e['g_mm'] / e['sigma_scaled_mm'] >= 3 and abs(e['g_mm'] - 0.20) <= 2 * e['sigma_scaled_mm'] and
          33.3 <= r['r_link_mm'] <= 33.5 and dchi >= 9 and smooth and cmd_ok and app_line and
          L['_stdout'].count(L['links']['prewarp_command']) == 1)
    report('(c) disc 5 write link at LBA 65536', ok,
           f'g {e["g_mm"]:+.4f} mm detected at {e["g_mm"] / e["sigma_scaled_mm"]:.1f} sigma (scaled), '
           f'{(e["g_mm"] - 0.20) / e["sigma_scaled_mm"]:+.2f} sigma from +0.20 mm (step_scan/link_locate); quadratic '
           f'chi2 {ql["chi2"]:.2f} -> {qn["chi2"]:.2f} without --link (+{dchi:.1f}); app values = the smooth '
           f'{kind} fit: {smooth}; prewarp command as specified: {cmd_ok}')
    warn = ('WARNING: localsteps runs without --link', 'WARNING: localsteps runs fitted without --link')
    n_no = [N['_stdout'].count(w) for w in warn]
    n_yes = [L['_stdout'].count(w) for w in warn]
    report('(c) localsteps without --link warns', n_no == [1, 1] and n_yes == [0, 0],
           f'without --link: {n_no[0]} warning at the top and {n_no[1]} at the app values; with --link 65536: '
           f'{sum(n_yes)}')


# ------------------------------------------------------------------------------------------------ (e) edge cases
K_E1, K_E2 = 65500, 200000      # synthetic ladder runs with two links (gaps G_E1, G_E2)
G_E1, G_E2 = 0.20, -0.10
SEED_E = 7
LSA = sum((['--localsteps', p] for p in LS_FILES), [])


def synth_runs(setup, names):
    """Synthetic ladder runs on disc 5's rung LBAs and sigmas (reference as the ladder's, between the links): A = the
    rungs below K_E2 (across K_E1 only), B = those at or beyond K_E1 (across K_E2 only), C = those between the links
    (across neither); the TRUE spiral, gaps G_E1 at K_E1 and G_E2 at K_E2 (h on the TRUE spiral), seeded noise."""
    ref, data, th, rad, _ = setup
    rng = random.Random(SEED_E)

    def step(k):
        return sum(g * (1.0 / rad[k] if k >= K else 0.0) for K, g in ((K_E1, G_E1), (K_E2, G_E2)))
    sel = {'A': lambda k: k < K_E2, 'B': lambda k: k >= K_E1, 'C': lambda k: K_E1 <= k < K_E2}
    return [{'run': nm, 'ref': ref, 'lba': k, 'sig': s,
             'y': th[k] - th[ref] + step(k) - step(ref) + KAPPA_SYN + rng.gauss(0.0, s)}
            for nm in names for k, _, s in data if sel[nm](k)]


def jobs_e(work, setup):
    os.makedirs(work, exist_ok=True)
    rungs = {}
    for names in ('ABC', 'AB'):
        rungs[names] = os.path.join(work, f'rungs_{names}.csv')
        write_rungs(rungs[names], synth_runs(setup, names))
    summ = os.path.join(work, 'disc5_summary')      # disc 5's ladder with a summary.json of 359849 sectors
    os.makedirs(summ, exist_ok=True)
    for f in ('ladder_raw.csv', 'ladder_rungs.csv'):
        shutil.copyfile(os.path.join(DISC5, f), os.path.join(summ, f))
    with open(os.path.join(summ, 'summary.json'), 'w', encoding='utf-8') as fh:
        json.dump({'capacity': {'sectors_used': 359849}}, fh)
    S = ['--sectors', str(SECTORS)]
    links2 = ['--link', str(K_E1), '--link', str(K_E2)]
    cases = {'two_links_ref_between': S + ['--link', '60000', '--link', '60100'] + LSA + [DISC5],
             'two_links_no_rung': S + ['--link', '60000', '--link', '65536', DISC5],
             'link_356000': S + ['--link', '356000', DISC5],
             'runs_abc': S + ['--rungs', rungs['ABC']] + links2,
             'runs_ab': S + ['--rungs', rungs['AB']] + links2,
             'sectors_330000': ['--sectors', '330000', '--link', '65536'] + LSA + [DISC5],
             'summary_359849': ['--link', '65536'] + LSA + [summ],
             'start_far': S + ['--start', '24.6,58.1', '--link', '65536'] + LSA + [DISC5]}
    return {f'e:{n}': (a + ['--json', f'e_{n}.json'], work) for n, a in cases.items()}


def eval_e(work, out, setup, base_ladder_json, c_link_json):
    enc = locale.getpreferredencoding(False)

    def get(name):
        rc, so, se = out[f'e:{name}']
        p = os.path.join(work, f'e_{name}.json')
        return rc, so.decode(enc, 'replace'), se.decode(enc, 'replace'), (load_json(p) if rc == 0 and
                                                                           os.path.exists(p) else None)

    def brief(text):
        return ' '.join(text.split())[:420]

    for name, must in (('two_links_ref_between', ('LBA 60000: no rung in LBA 60000 .. 60099 (only the reference LBA '
                                                  '60067', 'LBA 60100: no rung in LBA 60000 .. 60099')),
                       ('two_links_no_rung', ('LBA 60000: no rung in LBA 60000 .. 65535',
                                              'LBA 65536: no rung in LBA 60000 .. 65535'))):
        rc, so, se, _ = get(name)
        report(f'(e) {name}: refused', rc == 1 and all(m in se for m in must), f'exit {rc}: {brief(se)}')

    # one rung beyond the link: its rung fold is skipped for every model, the selection is that of the ladder
    rc, so, se, js = get('link_356000')
    if js is None:
        report('(e) link_356000', False, f'exit {rc}: {brief(se)}')
    else:
        base = load_json(base_ladder_json) if base_ladder_json and os.path.exists(base_ladder_json) else None
        cvs = js['cross_validation']
        ok = (all(c['skipped_folds'] == ['disc5_cubic_r3:356500'] and c['cv_n'] == 23 and math.isfinite(c['cv_chi2'])
                  for c in cvs.values()) and base is not None and
              js['selection']['recommended'] == base['selection']['recommended'] and 'folds skipped for every model' in so)
        report('(e) a link with one rung beyond it: that fold is skipped, not inf', ok,
               'held-out chi2 ' + ' / '.join(f'{k} {c["cv_chi2"]:.1f}' for k, c in cvs.items()) + f' for '
               f'{cvs["quadratic"]["cv_n"]} rungs, skipped {cvs["quadratic"]["skipped_folds"]}; recommended '
               f'{js["selection"]["recommended"]} (ladder without --link: '
               f'{base["selection"]["recommended"] if base else "baseline missing"}); gap '
               f'{js["links"]["recommended"][0]["g_mm"]:+.3f} +- {js["links"]["recommended"][0]["sigma_scaled_mm"]:.3f} mm')

    # synthetic runs: A measures K_E1 only, B K_E2 only, C neither (run folds)
    n_c = sum(1 for r in synth_runs(setup, 'C'))
    for name, skipped, n_cv in (('runs_abc', ['A', 'B'], n_c), ('runs_ab', ['A', 'B'], 0)):
        rc, so, se, js = get(name)
        if js is None:
            report(f'(e) {name}', False, f'exit {rc}: {brief(se)}')
            continue
        cvs = js['cross_validation']
        q = js['fits']['quadratic']         # the truth's model
        zs = [(e['g_mm'] - g) / e['sigma_scaled_mm'] for e, g in zip(q['links'], (G_E1, G_E2))]
        ok = (all(c['by_run'] and c['skipped_folds'] == skipped and c['cv_n'] == n_cv for c in cvs.values())
              and all(abs(z) <= 4 for z in zs) and 'A skipped, B skipped' in so)
        if n_cv:
            ok &= all(math.isfinite(c['cv_chi2']) and c['max_z'] is not None for c in cvs.values())
            what = f'fold C only ({n_cv} rungs held out)'
        else:
            ok &= (all(c['max_z'] is None for c in cvs.values()) and so.count('not testable: every fold skipped') == 6
                   and all('not testable (every fold skipped' in s for s in js['selection']['steps']))
            what = 'no fold left: held-out chi2 and stability not testable, the F-test decides'
        report(f'(e) synthetic runs {"A, B, C" if n_cv else "A, B"}: folds A and B skipped', ok,
               f'{what}; recommended {js["selection"]["recommended"]} ({"; ".join(js["selection"]["steps"])[:200]}); '
               f'quadratic gaps ' + ', '.join(f'LBA {e["lba"]} {e["g_mm"]:+.3f} +- {e["sigma_scaled_mm"]:.3f} mm (z '
                                              f'{z:+.2f})' for e, z in zip(q['links'], zs)))

    # the localsteps prior against the measured disc's sector count, not --sectors
    rc, so, se, js = get('sectors_330000')
    note = ("note: the measured disc's own sector count is unknown (no summary.json in the ladder directories)",
            '--sectors 330000 differs from the prior')
    ok = js is not None and 'WARNING: the localsteps prior' not in so and all(m in so for m in note)
    report('(e) --sectors 330000 (another burn): no prior warning', ok,
           f'exit {rc}; ' + brief(next((ln for ln in so.splitlines() if 'sector count is unknown' in ln), se)))
    rc, so, se, js = get('summary_359849')
    w = 'WARNING: the localsteps prior has 359845 sectors, the measured disc 359849 (summary.json)'
    report('(e) summary.json 359849 vs a 359845 prior: warned', js is not None and w in so,
           f'exit {rc}; ' + brief(next((ln for ln in so.splitlines() if 'WARNING: the localsteps prior' in ln), se)))

    # --start only seeds the fit (the link geometry is the converged area fit)
    rc, so, se, js = get('start_far')
    L = load_json(c_link_json) if os.path.exists(c_link_json) else None
    if js is None or L is None:
        report('(e) --start 24.6,58.1', False, f'exit {rc}: {brief(se)}; c_link.json there: {L is not None}')
        return
    worst, at = 0.0, None
    for k in ('area', 'quadratic', 'cubic'):
        fa, fb = L['fits'][k], js['fits'][k]
        for i, s in enumerate(fa['se']):
            d = abs(fa['params5'][i] - fb['params5'][i]) / s
            if d > worst:
                worst, at = d, f'{k} {fitlib.NL_NAMES[k][i]}'
        d = abs(fa['links'][0]['g_mm'] - fb['links'][0]['g_mm']) / fa['links'][0]['sigma_formal_mm']
        if d > worst:
            worst, at = d, f'{k} g'
    dchi = max(abs(L['fits'][k]['chi2'] - js['fits'][k]['chi2']) for k in L['fits'])
    ok = worst < 1e-4 and dchi < 1e-6 and js['selection']['recommended'] == L['selection']['recommended']
    report('(e) --start 24.6,58.1 only seeds the fit', ok,
           f'against the default start: max {worst:.1e} SE ({at}), chi2 within {dchi:.1e}, recommended '
           f'{js["selection"]["recommended"]} / {L["selection"]["recommended"]}; link geometry ri '
           f'{js["links"]["h_geometry"]["ri"]!r} / {L["links"]["h_geometry"]["ri"]!r}')


# ------------------------------------------------------------------------------------------------ main
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--baseline', default=DEFAULT_BASELINE, help='baseline directory with cases.json (test a)')
    ap.add_argument('--only', default='abce', help='which test groups to run (any of a, b, c, e; default abce)')
    ap.add_argument('--keep', help='work directory to keep the outputs in (default: a temporary one, removed)')
    ap.add_argument('--jobs', type=int, default=min(16, os.cpu_count() or 4), help='parallel tool runs')
    a = ap.parse_args(argv)
    tmp = None
    if a.keep:
        work = os.path.abspath(a.keep)
        os.makedirs(work, exist_ok=True)
    else:
        tmp = tempfile.TemporaryDirectory(prefix='test_cp_link_')
        work = tmp.name
    jobs, meta, setup = {}, None, None
    if 'a' in a.only:
        if os.path.isfile(os.path.join(a.baseline, 'cases.json')):
            ja, meta = jobs_a(a.baseline, os.path.join(work, 'a'))
            jobs.update(ja)
        else:
            report('(a) regression', False, f'no baseline at {a.baseline} (cases.json); pass --baseline DIR')
    if 'b' in a.only or 'e' in a.only:
        setup = synth_setup()
    if 'b' in a.only:
        jobs.update(jobs_b(os.path.join(work, 'b'), setup))
    if 'c' in a.only:
        jobs.update(jobs_c(os.path.join(work, 'c')))
    if 'e' in a.only:
        jobs.update(jobs_e(os.path.join(work, 'e'), setup))
        if 'c' not in a.only:      # (e) compares --start with the default start of (c)
            jobs['c:link'] = jobs_c(os.path.join(work, 'c'))['c:link']
    # the slowest runs first, so the parallel pool ends together
    order = sorted(jobs, key=lambda n: (not n.startswith(('c:', 'e:')), n))
    print(f'{len(jobs)} tool runs, {a.jobs} in parallel ...', flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, a.jobs)) as ex:
        futs = {n: ex.submit(run_tool, *jobs[n]) for n in order}
        if 'b' in a.only:          # in-process checks while the tool runs
            unit_checks(setup)
            unit_checks_links(setup)
            unit_checks_radius()
            mc_checks(setup)
        out = {n: fu.result() for n, fu in futs.items()}
    if meta is not None:
        eval_a(a.baseline, os.path.join(work, 'a'), meta, out)
    if 'b' in a.only:
        eval_b(os.path.join(work, 'b'), out)
    ladder_json = os.path.join(work, 'a', 'disc5_cubic_r3.json') if meta is not None else None
    if ladder_json is None or not os.path.exists(ladder_json):
        ladder_json = os.path.join(a.baseline, 'disc5_cubic_r3.json')
    if 'c' in a.only:
        eval_c(os.path.join(work, 'c'), out, ladder_json)
    if 'e' in a.only:
        eval_e(os.path.join(work, 'e'), out, setup, ladder_json, os.path.join(work, 'c', 'c_link.json'))
    nfail = sum(1 for _, ok in results if not ok)
    print(f'\n{len(results) - nfail} PASS, {nfail} FAIL' + (f'; outputs kept in {work}' if a.keep else ''))
    if tmp is not None:
        tmp.cleanup()
    return 1 if nfail else 0


if __name__ == '__main__':
    sys.exit(main())
