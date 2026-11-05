# One-command CD timing calibration from probe output (read-only data, no drive access).
#
#   python -I calibrate.py [--head <dir>\head_lba0-7.bin] [--x BYTES] [--sectors 359845] <ladder dir> [<ladder dir> ...]
#   python -I calibrate.py --pitch ...   adds the constant / quadratic / cubic pitch fit of calibrate_pitch.py after the
#                                        output below (model selection, app values, ruler prediction, paste block);
#                                        without --pitch the output is unchanged
#
# Steps:
#   1. (--head, optional) framing offset s from the interleaver zero staircase. DIAGNOSTIC ONLY: it shows that
#      the disc is an app burn with interleave on and that the byte order is as modelled, and it fingerprints the
#      drive pair. It is NOT applied to r0/r1. On the HP BU20N s = -532 B, while the physical along-track
#      constant measured on burned discs is x = 0 +- ~100 B (spec: Erratum, sections 2.4-2.5).
#   2. Robust per-rung phases; joint constant-pitch fit with one free phase constant per run, in the fit frame
#      (READ CD completion of LBA k <-> file byte 2352(k+1)). The per-rung estimator is fv/common.py reduce_ladder:
#      clipping about the plain circular mean, period search +-2e-3. It is NOT the median centring of spec 3.3;
#      on the four runs of the spec the two differ by about +-2 nm in r0/r1 (spec 3.3 and 3.6 row 12).
#   3. Burn values: the per-drive along-track constant x (--x, bytes, default 0; determined once per drive with a
#      ruler or photo of a burned radial edge, spec section 6.3) is applied through the exact identity
#      u2^2 = u^2 + w*x/pi (w unchanged); radii for the burn's sector count; uncertainty; residuals; the S-bend
#      E(r) in the form analysis\prewarp.py takes.
import argparse, math, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fv'))
from common import B, theta, grad, radius, P, from_radii, reduce_ladder, solve, polyval

# ---- framing offset from the app's CIRC pre-compensation zero staircase (port of the app's interleaver)
FPC, BPF = 112, 24


def _delays():
    k0e = [0, 8, 16, 2, 10, 18]; k0o = [4, 12, 20, 6, 14, 22]; d = [0] * 24
    for i in range(12):
        odd = i & 1
        d[i] = (1 if odd else 0) - 24 * ((i * 4) + (2 if odd else 3)) + k0e[i // 2]
    for i in range(12, 24):
        odd = (i - 12) & 1
        d[i] = (1 if odd else 0) - 24 * (((i + 4) * 4) + (0 if odd else 1)) + k0o[(i - 12) // 2]
    return d


def _interleave(values, delay):
    seq = bytearray(FPC * BPF); head = FPC - 1; pos = 0; out = bytearray(); sector = bytearray()
    for v in values:
        idx = head * BPF + delay[pos]
        idx = idx - len(seq) if idx >= len(seq) else (idx + len(seq) if idx < 0 else idx)
        seq[idx] = v; pos += 1
        if pos < BPF:
            continue
        pos = 0; head = 0 if head + 1 >= FPC else head + 1
        sector += seq[head * BPF:(head + 1) * BPF]
        if len(sector) == 2352:
            for i in range(0, 2352, 2):
                sector[i], sector[i + 1] = sector[i + 1], sector[i]
            out += sector; sector = bytearray()
    return out


def framing_offset(head_path, span=6000, search=6000):
    expected = [b == 0 for b in _interleave([0xAA] * (2352 * 12), _delays())]
    obs = [b == 0 for b in open(head_path, 'rb').read()]
    if len(obs) < span:
        raise SystemExit(f'{head_path}: need at least {span} bytes from LBA 0, got {len(obs)}')

    def bad(s):
        n = 0
        for j in range(span):
            f = j + s
            e = True if f < 0 else (expected[f] if f < len(expected) else False)
            n += e != obs[j]
        return n
    scores = sorted((bad(s), s) for s in range(-search, search + 1))
    (b0, s0), (b1, _) = scores[0], scores[1]
    print(f'framing offset (diagnostic): s = {s0} bytes ({s0 / 4:.2f} samples, {s0 / 24:.3f} frames); '
          f'{b0} mismatches, runner-up {b1} (margin {b1 - b0})')
    if b0 > 2 or b1 - b0 < 20:
        print('WARNING: staircase match is not unique enough; check that the disc was burned by the app with interleave on.')
    return s0


# ---- joint fit: theta(P(x)) - theta(P(ref)) + kappa_run = Y   (fit frame)
def joint_fit(runs, u, w):
    n = len(runs)
    kap = [0.0] * n
    for _ in range(50):
        npar = 2 + n
        A = [[0.0] * npar for _ in range(npar)]; bv = [0.0] * npar
        for i, (ref, data) in enumerate(runs):
            gr = grad(u, w, P(ref))
            for lba, y, s in data:
                gx = grad(u, w, P(lba))
                J = [gx[0] - gr[0], gx[1] - gr[1]] + [1.0 if k == i else 0.0 for k in range(n)]
                e = y - (theta(u, w, P(lba)) - theta(u, w, P(ref)) + kap[i])
                wt = 1 / (s * s)
                for a in range(npar):
                    bv[a] += wt * J[a] * e
                    for b in range(npar):
                        A[a][b] += wt * J[a] * J[b]
        dx = solve(A, bv)
        u += dx[0]; w += dx[1]
        kap = [k + d for k, d in zip(kap, dx[2:])]
        if abs(dx[0]) < 1e-12 and abs(dx[1]) < 1e-15:
            break
    chi, m = 0.0, 0
    for i, (ref, data) in enumerate(runs):
        for lba, y, s in data:
            chi += ((y - (theta(u, w, P(lba)) - theta(u, w, P(ref)) + kap[i])) / s) ** 2; m += 1
    dof = max(1, m - 2 - n)
    # covariance of (u, w) from the normal matrix (inverse via solving unit vectors)
    cov = [solve(A, [1.0 if k == j else 0.0 for k in range(len(A))]) for j in range(2)]
    return u, w, kap, chi / dof, dof, (cov[0][0], cov[1][1], cov[0][1])


def burn_radii(u, w, x, sectors):
    """Exact identity: Theta_u(q + x) = Theta_u2(q) + const with u2^2 = u^2 + w*x/pi, w unchanged."""
    u2sq = u * u + w * x / math.pi
    if u2sq <= 0:
        raise SystemExit(f'--x {x:g} is outside the disc')
    u2 = math.sqrt(u2sq)
    return u2, u2 * B, B * math.sqrt(u2sq + w * sectors * 2352 / math.pi)


def main():
    ap = argparse.ArgumentParser(allow_abbrev=False,
                                 description='CD read-timing calibration: fit-frame radii plus the per-drive along-track constant x.')
    ap.add_argument('--head', help='head_lba0-7.bin from "Probe.exe <dir> head": prints the framing offset s '
                                   '(diagnostic only, never applied to r0/r1)')
    ap.add_argument('--x', type=float, default=0.0, metavar='BYTES',
                    help='per-drive along-track constant x in bytes (default 0): the content of file byte q lands at '
                         'the fit-frame angle of q + x. Determined once per drive physically (spec section 6.3) and '
                         'applied as u2^2 = u^2 + w*x/pi. It is not -s.')
    ap.add_argument('--s', type=int, help=argparse.SUPPRESS)          # withdrawn; kept only to refuse old command lines
    ap.add_argument('--sectors', type=int, default=None,
                    help='sector count of the final burn (default 359845; with --pitch, the runs\' summary.json if present)')
    ap.add_argument('--pitch', action='store_true',
                    help='also fit quadratic and cubic pitch (calibrate_pitch.py): model selection, app-ready values, '
                         'predicted ruler reading, project-settings block')
    ap.add_argument('runs', nargs='+', help='ladder output directories (ladder_raw.csv + ladder_rungs.csv)')
    a = ap.parse_args()
    if a.s is not None:
        raise SystemExit('--s is withdrawn: the framing offset s is a diagnostic and is no longer applied to r0/r1 '
                         '(spec, Erratum). Use --head to print s, and --x BYTES (default 0) for the per-drive '
                         'along-track constant.')
    sectors_given = a.sectors is not None
    if a.pitch:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import calibrate_pitch
        if not sectors_given:           # same default as calibrate_pitch.py, so both parts use one sector count
            a.sectors = calibrate_pitch.resolve_sectors([{'name': d, 'dir': d} for d in a.runs], None)[0]
    if a.sectors is None:
        a.sectors = 359845

    if a.head:
        framing_offset(a.head)
        print('  s says which file bytes READ CD returns for LBA k: the disc is an app burn with interleave on, the byte\n'
              '  order is as modelled, and s fingerprints the drive pair. It does not say where the drive writes or where a\n'
              '  read completes, so it is NOT applied to r0/r1. On the HP BU20N s = -532 B while the physical along-track\n'
              '  constant is x = 0 +- ~100 B. If s differs from the value stored for this drive, re-check x (spec 6.3).\n')
    runs = []
    for d in a.runs:
        ref, data = reduce_ladder(d)
        runs.append((ref, data))
        sig = sorted(math.degrees(x[2]) for x in data)
        print(f'run {d}: reference LBA {ref}, {len(data)} rungs, per-rung sigma median {sig[len(sig) // 2]:.3f} deg, max {sig[-1]:.3f} deg')

    u0, w0 = from_radii(24.92, 57.84)
    u, w, kap, chi, dof, (cuu, cww, cuw) = joint_fit(runs, u0, w0)
    scale = max(1.0, chi)
    x = a.x
    T = a.sectors * 2352
    ua, r0, r1 = burn_radii(u, w, x, a.sectors)
    # uncertainty: map the (u, w) covariance through the identity (x is exact)
    du_dw = (x / math.pi) / (2 * ua)
    var_ua = (u / ua) ** 2 * cuu + 2 * (u / ua) * du_dw * cuw + du_dw ** 2 * cww
    sr0 = math.sqrt(var_ua * scale) * B
    S1 = r1 / B
    g_u, g_w = u / S1, (x + T) / (2 * math.pi * S1)
    sr1 = math.sqrt((g_u ** 2 * cuu + 2 * g_u * g_w * cuw + g_w ** 2 * cww) * scale) * B
    _, r0p, r1p = burn_radii(u, w, x + 100, a.sectors)
    print(f'\njoint fit (fit frame): r0={u * B:.7f} r1={B * math.sqrt(u * u + w * T / math.pi):.7f} '
          f'pitch {w * B * 1000:.6f} um  chi2/dof={chi:.2f} (dof {dof})  kappa(deg)={[round(math.degrees(k), 3) for k in kap]}')
    print(f'along-track constant x = {x:+g} bytes ({x * B:+.3f} mm along the track), from --x: per drive, set by a physical '
          f'check{" (0 = the fit frame itself)" if x == 0 else ""}')
    print(f'\n==> burn values: inner radius r0 = {r0:.7f} mm, outer radius r1 = {r1:.7f} mm, sectors = {a.sectors}')
    print(f'    statistical sigma(r0) ~ {sr0 * 1e6:.1f} nm, sigma(r1) ~ {sr1 * 1e6:.1f} nm (chi2-scaled); '
          f'model floor: constant-pitch residual below')
    print(f'    per +100 bytes of x: r0 {(r0p - r0) * 1e6:+.2f} nm, r1 {(r1p - r1) * 1e6:+.2f} nm; the ruler reading B of a '
          f'burned straight radial edge moves {200 * B:+.2f} mm (x = {1 / (2 * B):.1f} B per mm of B)')

    # residuals against the fit-frame model, per run, with that run's kappa. By the identity they equal the residuals
    # against the burn model at q = 2352(k+1) - x, whatever x is.
    print('\n  r(mm)  residual(deg)  sigma  run')
    allpts = []
    for i, (ref, data) in enumerate(runs):
        for lba, y, sg in data:
            e = y - (theta(u, w, P(lba)) - theta(u, w, P(ref))) - kap[i]
            allpts.append((radius(u, w, P(lba)), math.degrees(e), math.degrees(sg), i))
    allpts.sort()
    for r, e, sg, i in allpts:
        print(f'  {r:6.2f}  {e:+8.3f}     {sg:.3f}  {i}')
    rms = math.sqrt(sum(p[1] ** 2 for p in allpts) / len(allpts))
    # smooth part E(r): poly4 in X = (r-41.25)/16.25 plus one offset per run, weights 1/(sigma^2 + 0.04 deg^2)
    # (the method of pattern_v2.py), then its mean over 25.5-57.3 mm removed
    n_runs = len(runs)
    npar = 5 + n_runs - 1
    A = [[0.0] * npar for _ in range(npar)]; bv = [0.0] * npar
    for r, e, sg, i in allpts:
        X = (r - 41.25) / 16.25
        row = [X ** k for k in range(5)] + [1.0 if (i > 0 and j == i - 1) else 0.0 for j in range(n_runs - 1)]
        wt = 1 / (sg * sg + 0.04)
        for p in range(npar):
            bv[p] += wt * row[p] * e
            for q in range(npar):
                A[p][q] += wt * row[p] * row[q]
    c = solve(A, bv)[:5]
    grid = [25.5 + 0.05 * k for k in range(637)]
    mean_grid = sum(polyval(c, (r - 41.25) / 16.25) for r in grid) / len(grid)
    sm = [polyval(c, (r - 41.25) / 16.25) - mean_grid for r in grid]
    print(f'\nresidual rms {rms:.3f} deg; smooth (poly4) part E(r) {max(sm) - min(sm):.2f} deg peak-to-peak over 25.5-57.3 mm '
          f'(~{max(abs(v) * math.pi / 180 * r for v, r in zip(sm, grid)):.2f} mm tangential at worst)')
    print('A smooth part well above ~0.5 deg is real track structure if it is speed-invariant; constant-pitch radii cannot '
          'remove it.\nTo cancel it without an app change, pre-distort the design with analysis\\prewarp.py, used with exactly '
          'these burn values:\n    python -I prewarp.py in.png out.png --r1 '
          f'{r1:.7f} --coeffs={",".join(f"{v:.5f}" for v in c)} --const={-mean_grid:.4f}')

    if a.pitch:
        calibrate_pitch.report(calibrate_pitch.runs_from_reduced(a.runs, runs), x=x,
                               sectors=a.sectors if sectors_given else None, print_runs=False)


if __name__ == '__main__':
    main()
