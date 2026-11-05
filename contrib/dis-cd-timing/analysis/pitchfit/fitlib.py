# ---- attribution ------------------------------------------------------------------------------
# Copied on 2026-11-04, unchanged apart from this comment block, from the workflow scratchpad file
#   <scratchpad>/wf3/cubic_py/fitlib.py
#   sha256 202422e3b16dcb6f1f8c7bec732771be934aacc9bc29cb900c87ebfe4efe7d8b (byte-identical copy: analysis/review_checks/fitlib.py).
# Origin: workflow wf3, task B ("cubic_py"): weighted Gauss-Newton fit (1/sigma^2, one kappa per run, Householder QR, 4-point finite-difference
# Jacobian) of the rung timing data with spiral.py. Its Problem class is hard-wired to the
# four runs of the Lenovo box (RUN_ORDER, SECTORS = 359845, s = (2352(k+1) + x) B); calibrate_pitch.py
# subclasses it for arbitrary runs, sector counts and the spec's x convention, and reuses fit().
# Validation there: the app's own DvdTrackGeometry.cs, compiled unmodified, agrees with spiral.py to
# |dtheta| <= 1.5e-10 rad and b to 2e-16 relative at the fitted parameters, and gives the same chi2 to 3e-7
# (wf3/cubic_py/cs_crosscheck.json); the C# fit harness wf3/cubic_cs reproduces the fits to ~5e-12 mm.
# Used by analysis/calibrate_pitch.py. Keep the code below identical to the validated source; a fix
# belongs in a new copy that is re-validated against the app.
# -----------------------------------------------------------------------------------------------
"""Weighted Gauss-Newton fits of the rung timing data with the exact-arc spiral."""
import csv
import math
import os

from spiral import SpiralGeometry, area_angle

DATA_CSV = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "rungs_all_runs.csv")  # contrib: was an absolute path
SECTORS = 359845
TRACK_MM = SECTORS / 75 * 1200            # CalibrationParameters.TrackLengthMm (CD) = 5757520
BYTE_MM = 1200 / (75 * 2352)              # bb, mm per byte
SECTOR_MM = 2352 * BYTE_MM                # 16 mm per sector (exactly 16 in the model)
RUN_ORDER = ["disc1_run1", "disc1_run2", "disc3", "disc3_2482rpm"]

NL_NAMES = {
    "area": ["ri", "ro"],
    "constant": ["ri", "ro"],
    "quadratic": ["ri", "ro", "c1", "c2"],
    "cubic": ["ri", "ro", "c1", "c2", "c3"],
}
# finite-difference steps (4-point Richardson central differences)
FD_STEP = {"ri": 1e-4, "ro": 1e-4, "c1": 1e-4, "c2": 1e-4, "c3": 1e-4}


def load_rows(path=DATA_CSV):
    rows = []
    with open(path, newline="", encoding="utf-8") as fh:
        for rec in csv.DictReader(fh):
            rows.append({"run": rec["run"], "ref": int(rec["ref_lba"]), "lba": int(rec["lba"]),
                         "y": float(rec["y_rad"]), "sig": float(rec["sigma_rad"])})
    return rows


def s_of_lba(k, x_bytes=0.0):
    """Arc length (mm) of LBA k in the measurement frame P(k) = 2352 (k+1) + x bytes."""
    if x_bytes == 0.0:
        return 16.0 * (k + 1)             # 2352 (k+1) B * 1200/(75*2352) mm/B, exact
    return (2352.0 * (k + 1) + x_bytes) * BYTE_MM


def full_params(kind, p_nl):
    d = dict(zip(NL_NAMES[kind], p_nl))
    return d["ri"], d["ro"], d.get("c1", 0.0), d.get("c2", 0.0), d.get("c3", 0.0)


def make_angle_fn(kind, p_nl, T=TRACK_MM):
    ri, ro, c1, c2, c3 = full_params(kind, p_nl)
    if kind == "area":
        return lambda s: area_angle(s, ri, ro, T)
    geo = SpiralGeometry(ri, ro, T, c1, c2, c3)
    return geo.angle_at_arc


class Problem:
    def __init__(self, rows, kind, runs=None, x_bytes=0.0):
        self.kind = kind
        self.runs = [r for r in RUN_ORDER if runs is None or r in runs]
        self.rows = [r for r in rows if r["run"] in self.runs]
        self.x = x_bytes
        self.run_idx = [self.runs.index(r["run"]) for r in self.rows]
        self.s_lba = [s_of_lba(r["lba"], x_bytes) for r in self.rows]
        self.s_ref = [s_of_lba(r["ref"], x_bytes) for r in self.rows]
        self.s_unique = sorted(set(self.s_lba) | set(self.s_ref))
        self.y = [r["y"] for r in self.rows]
        self.sig = [r["sig"] for r in self.rows]
        self.n_nl = len(NL_NAMES[kind])
        self.n_par = self.n_nl + len(self.runs)

    def diffs(self, p_nl):
        f = make_angle_fn(self.kind, p_nl)
        th = {s: f(s) for s in self.s_unique}
        return [th[a] - th[b] for a, b in zip(self.s_lba, self.s_ref)]

    def residuals(self, p):
        d = self.diffs(p[:self.n_nl])
        kap = p[self.n_nl:]
        return [(y - di - kap[j]) / sg for y, di, j, sg in zip(self.y, d, self.run_idx, self.sig)]

    def jacobian(self, p):
        """d(model)/dp, weighted by 1/sigma (model = diffs + kappa)."""
        p_nl = list(p[:self.n_nl])
        names = NL_NAMES[self.kind]
        cols = []
        for k, name in enumerate(names):
            h = FD_STEP[name]

            def at(delta):
                q = list(p_nl)
                q[k] += delta
                return self.diffs(q)
            f1, m1, f2, m2 = at(h), at(-h), at(2 * h), at(-2 * h)
            cols.append([(8 * (a - b) - (c - d)) / (12 * h) for a, b, c, d in zip(f1, m1, f2, m2)])
        J = []
        for i in range(len(self.rows)):
            row = [cols[k][i] / self.sig[i] for k in range(self.n_nl)]
            row += [(1.0 / self.sig[i]) if self.run_idx[i] == j else 0.0 for j in range(len(self.runs))]
            J.append(row)
        return J

    def initial_kappa(self, p_nl):
        d = self.diffs(p_nl)
        num = [0.0] * len(self.runs)
        den = [0.0] * len(self.runs)
        for y, di, j, sg in zip(self.y, d, self.run_idx, self.sig):
            w = 1 / (sg * sg)
            num[j] += w * (y - di)
            den[j] += w
        return [n / d_ for n, d_ in zip(num, den)]


# ----------------------------------------------------------------- linear algebra
def lstsq_qr(A, b):
    """min ||A x - b|| by Householder QR with column scaling.
    Returns x, (A^T A)^-1, 2-norm condition number of the column-scaled A."""
    n, p = len(A), len(A[0])
    scale = [math.sqrt(math.fsum(A[i][j] ** 2 for i in range(n))) or 1.0 for j in range(p)]
    M = [[A[i][j] / scale[j] for j in range(p)] for i in range(n)]
    y = list(b)
    for k in range(p):
        norm = math.sqrt(math.fsum(M[i][k] ** 2 for i in range(k, n)))
        if norm == 0:
            continue
        alpha = -norm if M[k][k] > 0 else norm
        v = [0.0] * n
        v[k] = M[k][k] - alpha
        for i in range(k + 1, n):
            v[i] = M[i][k]
        vv = math.fsum(v[i] ** 2 for i in range(k, n))
        if vv == 0:
            continue
        for j in range(k, p):
            f = 2 * math.fsum(v[i] * M[i][j] for i in range(k, n)) / vv
            for i in range(k, n):
                M[i][j] -= f * v[i]
        f = 2 * math.fsum(v[i] * y[i] for i in range(k, n)) / vv
        for i in range(k, n):
            y[i] -= f * v[i]
    R = [[M[i][j] if j >= i else 0.0 for j in range(p)] for i in range(p)]
    x = [0.0] * p
    for i in reversed(range(p)):
        x[i] = (y[i] - math.fsum(R[i][j] * x[j] for j in range(i + 1, p))) / R[i][i]
    Rinv = [[0.0] * p for _ in range(p)]
    for i in range(p):
        Rinv[i][i] = 1 / R[i][i]
        for j in range(i + 1, p):
            Rinv[i][j] = -math.fsum(Rinv[i][k] * R[k][j] for k in range(i, j)) / R[j][j]
    cov_s = [[math.fsum(Rinv[i][k] * Rinv[j][k] for k in range(max(i, j), p)) for j in range(p)]
             for i in range(p)]
    cov = [[cov_s[i][j] / (scale[i] * scale[j]) for j in range(p)] for i in range(p)]
    RtR = [[math.fsum(R[k][i] * R[k][j] for k in range(p)) for j in range(p)] for i in range(p)]
    ev = jacobi_eigenvalues(RtR)
    cond = math.sqrt(max(ev) / min(ev)) if min(ev) > 0 else float("inf")
    return [x[i] / scale[i] for i in range(p)], cov, cond


def jacobi_eigenvalues(S, sweeps=100):
    a = [row[:] for row in S]
    n = len(a)
    for _ in range(sweeps):
        off = math.fsum(a[i][j] ** 2 for i in range(n) for j in range(n) if i != j)
        if off < 1e-30 * math.fsum(a[i][i] ** 2 for i in range(n)):
            break
        for p_ in range(n - 1):
            for q in range(p_ + 1, n):
                if a[p_][q] == 0:
                    continue
                theta = (a[q][q] - a[p_][p_]) / (2 * a[p_][q])
                t = math.copysign(1.0, theta) / (abs(theta) + math.sqrt(theta * theta + 1))
                c = 1 / math.sqrt(t * t + 1)
                s = t * c
                for k in range(n):
                    akp, akq = a[k][p_], a[k][q]
                    a[k][p_] = c * akp - s * akq
                    a[k][q] = s * akp + c * akq
                for k in range(n):
                    apk, aqk = a[p_][k], a[q][k]
                    a[p_][k] = c * apk - s * aqk
                    a[q][k] = s * apk + c * aqk
    return [a[i][i] for i in range(n)]


# ----------------------------------------------------------------------- fitting
def fit(problem, p_nl0, max_iter=40, verbose=False):
    p = list(p_nl0) + problem.initial_kappa(p_nl0)
    res = problem.residuals(p)
    chi2 = math.fsum(r * r for r in res)
    history = [chi2]
    small_steps = 0
    it = 0
    for it in range(1, max_iter + 1):
        J = problem.jacobian(p)
        delta, cov, cond = lstsq_qr(J, res)
        sig_formal = [math.sqrt(cov[k][k]) for k in range(len(p))]
        lam = 1.0
        accepted = False
        while lam >= 1e-6:
            p_new = [a + lam * d for a, d in zip(p, delta)]
            try:
                res_new = problem.residuals(p_new)
                chi2_new = math.fsum(r * r for r in res_new)
            except ValueError:
                chi2_new = float("inf")
            if chi2_new <= chi2 * (1 + 1e-12) + 1e-12:
                accepted = True
                break
            lam *= 0.5
        if not accepted:
            if verbose:
                print(f"  it {it}: no chi2-decreasing step; stop")
            break
        step_rel = max(abs(lam * d) / s for d, s in zip(delta, sig_formal))
        p, res, chi2 = p_new, res_new, chi2_new
        history.append(chi2)
        if verbose:
            print(f"  it {it}: chi2 {chi2:.12f} max|step|/sigma {step_rel:.3e} lam {lam}")
        # converged: step below 1e-7 of the formal sigma (far below 1e-10 mm here)
        if step_rel < 1e-7:
            small_steps += 1
            if small_steps >= 2:
                break
        else:
            small_steps = 0
    J = problem.jacobian(p)
    _, cov, cond = lstsq_qr(J, res)
    n = len(res)
    dof = n - problem.n_par
    raw = [r * s for r, s in zip(res, problem.sig)]          # y - model, rad
    wsum = math.fsum(1 / s ** 2 for s in problem.sig)
    names = NL_NAMES[problem.kind] + ["kappa_" + r for r in problem.runs]
    sig_formal = [math.sqrt(cov[k][k]) for k in range(len(p))]
    birge = math.sqrt(chi2 / dof)
    corr = [[cov[i][j] / (sig_formal[i] * sig_formal[j]) for j in range(problem.n_nl)]
            for i in range(problem.n_nl)]
    return {
        "kind": problem.kind, "runs": problem.runs, "x_bytes": problem.x,
        "names": names, "p": p, "sigma_formal": sig_formal,
        "sigma_scaled": [s * birge for s in sig_formal],
        "corr_nl": corr, "cond_scaled_jacobian": cond,
        "chi2": chi2, "n": n, "dof": dof, "chi2_dof": chi2 / dof,
        "rms_rad": math.sqrt(math.fsum(r * r for r in raw) / n),
        "wrms_rad": math.sqrt(math.fsum((r / s) ** 2 for r, s in zip(raw, problem.sig)) / wsum),
        "max_abs_res_rad": max(abs(r) for r in raw),
        "residual_rad": raw, "iterations": it, "chi2_history": history,
    }
