# Shared model and ladder-reduction code (ported from D:\CD\cd-timing-probe\analysis\refit.py).
import csv, math

B = 1200 / (75 * 2352)          # mm per byte at 1.2 m/s
N = 359845
TB = N * 2352                   # total bytes
R0_APP, R1_APP = 24.921633, 57.839017   # burn parameters of disc 3 (= disc-1 fit)


def from_radii(r0, r1):
    L = B * TB
    pitch = math.pi * (r1 * r1 - r0 * r0) / L
    return r0 / B, pitch / B


def theta(u, w, q):
    s = math.sqrt(u * u + w * q / math.pi)
    return 2 * q / (s + u)


def radius(u, w, q):
    return B * math.sqrt(u * u + w * q / math.pi)


def q_at_radius(u, w, r):
    return (((r / B) ** 2) - u * u) * math.pi / w


def grad(u, w, q):
    s = math.sqrt(u * u + w * q / math.pi)
    return (-2 * q / (s * (s + u)), -q * q / (math.pi * s * (s + u) ** 2))


def P(lba):
    return 2352 * (lba + 1)


def wrap(a):
    return math.remainder(a, 2 * math.pi)


def cmean(v):
    return math.atan2(sum(math.sin(x) for x in v), sum(math.cos(x) for x in v))


def robust_keep(vals, floor_deg=1.5):
    m = cmean(vals)
    dev = sorted(abs(wrap(v - m)) for v in vals)
    sig = max(dev[len(dev) // 2] * 1.4826, math.radians(0.15))
    keep = [v for v in vals if abs(wrap(v - m)) <= max(4 * sig, math.radians(floor_deg))]
    return keep, cmean(keep)


def reduce_ladder(directory):
    """Per-rung X-R phase (radians, unwrapped with the probe's own turn count) and sigma."""
    raw = list(csv.DictReader(open(directory + '/ladder_raw.csv')))
    rungs = list(csv.DictReader(open(directory + '/ladder_rungs.csv')))
    refs = {x['lba'] for x in raw if x['role'] == 'R'}
    out = []
    for r in rungs:
        i = r['rung']
        T0 = float(r['period_ms'])
        rows = [x for x in raw if x['rung'] == i and x['ok'] == '1' and float(x['duration_ms']) > 8.5]
        R = [float(x['completion_ms']) for x in rows if x['role'] == 'R']
        X = [float(x['completion_ms']) for x in rows if x['role'] == 'X']
        keepR = R
        T = T0
        for _ in range(3):
            best = -1
            for k in range(-1000, 1001):
                p = T0 * (1 + k * 2e-6)
                c = abs(sum(complex(math.cos(2 * math.pi * t / p), math.sin(2 * math.pi * t / p)) for t in keepR)) / len(keepR)
                if c > best:
                    best, T = c, p
            ph = [2 * math.pi * t / T for t in R]
            _, m = robust_keep(ph)
            res = [wrap(v - m) for v in ph]
            dev = sorted(abs(x) for x in res)
            sig = max(dev[len(dev) // 2] * 1.4826, math.radians(0.15))
            lim = max(4 * sig, math.radians(1.5))
            keepR = [t for t, e in zip(R, res) if abs(e) <= lim]
        tm = sum(keepR) / len(keepR)
        rr = [wrap(2 * math.pi * t / T - m) for t in keepR]
        dt = [t - tm for t in keepR]
        sxx = sum(d * d for d in dt)
        slope = sum(d * e for d, e in zip(dt, rr)) / sxx if sxx else 0
        icpt = sum(rr) / len(rr)
        rres = [e - icpt - slope * d for e, d in zip(rr, dt)]
        refsd = math.sqrt(sum(e * e for e in rres) / max(1, len(rres) - 2))
        deltas = [wrap(2 * math.pi * t / T - (m + icpt + slope * (t - tm))) for t in X]
        keepX, d = robust_keep(deltas)
        sd = math.sqrt(sum(wrap(v - d) ** 2 for v in keepX) / max(1, len(keepX) - 1))
        sigma = math.sqrt(sd * sd / len(keepX) + refsd * refsd / len(keepR))
        unwrapped_old = float(r['unwrapped'])
        n = round((unwrapped_old - d) / (2 * math.pi))
        out.append((int(r['target']), d + 2 * math.pi * n, sigma))
    assert len(refs) == 1, refs
    return int(refs.pop()), out


def fit_uw(data, ref, u, w, free_const=False):
    """Weighted LS fit of y = Theta(P(lba)) - Theta(P(ref)) [+ c]."""
    c = 0.0
    for _ in range(40):
        n = 3 if free_const else 2
        A = [[0.0] * n for _ in range(n)]
        bvec = [0.0] * n
        for lba, y, s in data:
            f = theta(u, w, P(lba)) - theta(u, w, P(ref)) + c
            gx = grad(u, w, P(lba)); gr = grad(u, w, P(ref))
            J = [gx[0] - gr[0], gx[1] - gr[1]] + ([1.0] if free_const else [])
            wt = 1 / (s * s); e = y - f
            for a in range(n):
                bvec[a] += wt * J[a] * e
                for bb in range(n):
                    A[a][bb] += wt * J[a] * J[bb]
        dx = solve(A, bvec)
        u += dx[0]; w += dx[1]
        if free_const:
            c += dx[2]
        if abs(dx[0]) < 1e-12 and abs(dx[1]) < 1e-15:
            break
    return u, w, c


def solve(A, b):
    n = len(b)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for i in range(n):
        p = max(range(i, n), key=lambda k: abs(M[k][i]))
        M[i], M[p] = M[p], M[i]
        for k in range(i + 1, n):
            f = M[k][i] / M[i][i]
            for j in range(i, n + 1):
                M[k][j] -= f * M[i][j]
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        x[i] = (M[i][n] - sum(M[i][j] * x[j] for j in range(i + 1, n))) / M[i][i]
    return x


def polyfit(xs, ys, ws, deg):
    n = deg + 1
    A = [[0.0] * n for _ in range(n)]
    b = [0.0] * n
    for x, y, wt in zip(xs, ys, ws):
        pw = [x ** k for k in range(n)]
        for i in range(n):
            b[i] += wt * pw[i] * y
            for j in range(n):
                A[i][j] += wt * pw[i] * pw[j]
    return solve(A, b)


def polyval(c, x):
    return sum(ci * x ** i for i, ci in enumerate(c))
