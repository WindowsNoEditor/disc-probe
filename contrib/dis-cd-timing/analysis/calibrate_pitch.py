# Pitch-model CD timing calibration: constant, quadratic and cubic track pitch fitted jointly to probe ladder runs
# (read-only data, no drive access).
#
#   python -I calibrate_pitch.py [--x BYTES] [--sectors N] [--burn RI,RO[,C1,C2,C3]] [--json OUT] <ladder dir> [...]
#   python -I calibrate.py --pitch [calibrate.py options] <ladder dir> [...]   (calibrate.py's output, then this one)
#   python -I calibrate_pitch.py --rungs rungs.csv                                (reduced rungs instead of ladder dirs)
#   python -I calibrate_pitch.py --sectors N --link 65536 [--link LBA=G ...] [--localsteps localsteps_<ref>.csv ...]
#          [--localsteps-prior R0 R1 SECTORS] <ladder dir> [...]                (write link gap, extra localsteps runs)
#
# Model: the test build's own DvdTrackGeometry (exact), dr/dtheta = b (1 + c1 X + c2 X^2 + c3 X^3), X = (r - ri)/(ro - ri),
#   exact polar arc length, b solved from L = sectors/75*1200 mm, angle 0 at ri; file byte q at arc q*1200/(75*2352) mm.
#   When all three coefficients are zero the app uses its legacy area formula r^2 = ri^2 + (ro^2 - ri^2) s/L,
#   theta = 2 s/(r + ri); the constant model reported here is that formula (= calibrate.py's joint fit). Its exact-arc twin
#   (same data, ri/ro within ~1e-9 mm) is fitted as well, because only it is nested in the quadratic and cubic models.
#   Geometry and fit engine: pitchfit/spiral.py and pitchfit/fitlib.py (validated copies, see their headers).
# Timing model: y_k = Theta(q_k) - Theta(q_ref) + kappa_run with q_k = 2352 (k+1) - x bytes, weights 1/sigma^2, one kappa
#   per run; per-rung phases from fv/common.py reduce_ladder (as calibrate.py). x is calibrate.py's --x: the content of
#   file byte q lands at the fit-frame angle of q + x (spec 2.5); the refit with q_k = 2352 (k+1) - x is the spec 3.5
#   route for the polynomial models. NOTE: pitchfit/fitlib.py's own s_of_lba(k, x) and the C# harness use the opposite
#   sign, s = (2352 (k+1) + x) B; at x = 0 (this drive) the two agree.
# Model selection: a pitch model replaces the simpler one only if (1) the F-test of the added terms has p < --alpha,
#   (2) the held-out chi2 falls (leave one run out with that run's kappa refitted; with a single run, leave one rung
#   out), and (3) with >= 2 runs its shape parameters are stable: no leave-one-run-out shift beyond 3 sigma of the shift
#   expected from the data removed. Otherwise the smaller model is kept.
# Write links (--link LBA, repeatable): a drive that pauses and resumes a burn (lossless link; HP BU20N at 4x near LBA
#   65 500, r ~ 33.42 mm) displaces all content at LBA >= k_link by a gap g mm along the track, so every rung phase gains
#   g (h(lba) - h(ref)) with h(k) = [k >= k_link] / r(k) (rad; g, r in mm). Each link adds one free linear parameter g,
#   shared by all runs of the invocation (they must be one disc), after the kappas in the parameter vector, with the
#   analytic Jacobian column (h(lba) - h(ref)) / sigma; --link LBA=G subtracts a known gap G mm instead (no parameter).
#   r(k) is that of the rung's arc on ONE fixed constant-pitch geometry, not the current fit: the area-formula fit of all
#   the data with the links, iterated until its ri / ro move by < 1e-9 mm (the first pass takes h on the start values,
#   --start or ri 24.92 mm / 1.4865 um pitch, which therefore only seed it; two passes in practice). h is then identical
#   in every model and every cross-validation fold, so all model kinds carry the same link term and the F-test and the
#   held-out tests stay nested and fair; the fitted spirals differ from it by a few um, which changes h by < 1e-4
#   relative (g h by < 1e-6 rad).
#   The free gaps must be measured as steps: the free links cut the LBA axis into segments, a run ties together the
#   segments it has rungs in (a reference LBA counts for nothing: its run's kappa takes it), and gap j is measured iff
#   the segments on its two sides are connected (one link: some run has rungs on both sides of it). Else the tool stops
#   and names the links (e.g. two links with no rung, or only a reference LBA, between them: only the sum of their gaps
#   is seen). A cross-validation fold without which a free gap is no longer measured tests no pitch model: it is
#   skipped for every model alike and its rungs leave the held-out chi2 (printed); if every fold is skipped, the held-out
#   and stability tests are not testable and the F-test decides. The gaps are printed per model; the recommended
#   model's gaps get the radius of LBA k_link on that fitted spiral (arc 16 k_link mm, its first byte) and the prewarp.py
#   command that pre-compensates them. "==> app values" stay the smooth spiral: the app has no link term, the design is
#   pre-warped instead (fit and prewarp go together, or neither).
# localsteps runs (--localsteps CSV, repeatable; columns target,radius_mm,bytes_per_deg,measured_minus_prior_deg,
#   sigma_deg,used, reference LBA in the file name localsteps_<ref>.csv): each file is one more run with its own kappa,
#   y = area_angle(16 (k+1)) - area_angle(16 (ref+1)) + radians(measured_minus_prior) with the probe's constant-pitch prior
#   (--localsteps-prior R0 R1 SECTORS, default 24.9216305 57.8390244 359845) on the PRIOR's own track length
#   SECTORS/75*1200 mm, exactly as the probe predicted (src_extra/LinkScan.cs): this undoes the probe's subtraction and
#   leaves the measured phase difference, which the fit then models on its own frame like any rung. The prior's sector
#   count therefore never enters the fit, but the prior must be the one the probe used: one wrong by 4 sectors moves the
#   localsteps phases of disc 5 by 0.4 .. 4.2 deg. Checks: each file's radius column (the probe's prior radius of each
#   target) must agree with the prior to 6e-5 mm if some radius has a non-zero 4th decimal (the probe's own 4-decimal
#   column), else (3-decimal text, e.g. disc5_jog, rebuilt from the console output) to 5e-4 mm, with a warning beyond
#   6e-5 mm; the report gives each file's blind range (the prior sector-count error that would still pass) and a file
#   beyond its tolerance is refused. The prior's sector count is also compared with the MEASURED disc's own count when a
#   summary.json in the ladder directories gives it (warning if they differ: the probe's prior normally takes the disc's
#   own count); without one that count is unknown and only the radius columns check the prior (--sectors is the count of
#   the burn the values are for, which need not be the measured disc). localsteps runs are taken across the write link
#   by design, so without --link the tool warns that the step is not modelled. localsteps runs are local: they stay in
#   every cross-validation fit, and the folds are the ladder runs (rungs) as without them.
import argparse, bisect, csv, json, math, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
for _sub in ('pitchfit', 'fv'):
    _p = os.path.join(HERE, _sub)
    if _p not in sys.path:
        sys.path.insert(0, _p)
import fitlib                      # noqa: E402  pitchfit/fitlib.py
import spiral                      # noqa: E402  pitchfit/spiral.py
from common import reduce_ladder   # noqa: E402  fv/common.py

DEFAULT_SECTORS = 359845
DEG = 180 / math.pi
REF_BAND = (24.9216305, 57.8390244)      # Lenovo 80 min box (constant fit): the band the ruler radii were chosen on
GRID_BASE = [(510 + i) / 20.0 for i in range(637)]        # 25.50 .. 57.30 mm on that band, 0.05 mm steps
I28, I57, I30, I55 = 50, 630, 90, 590                       # ruler points 28 / 57 mm, bow range 30 .. 55 mm
SAMPLES_BASE = (25.5, 28, 30, 32, 35, 40, 45, 50, 55, 57.3)
NAMES = {'area': 'constant', 'constant': 'constant (exact arc)', 'quadratic': 'quadratic', 'cubic': 'cubic'}
SELECT = ('constant', 'quadratic', 'cubic')                 # nested family used for the tests
Z_MAX = 3.0
Z_RUNG = 4.0     # fit check: a rung more than 4 sigma off the recommended model is flagged (good runs here: <= 3.1)
LOCALSTEPS_PRIOR = (24.9216305, 57.8390244, 359845)     # the probe's localsteps prior (constant pitch) on disc 5
LOCALSTEPS_RADIUS_TOL = 6e-5     # mm: radius column (F4: half a unit of the 4th decimal plus margin) vs the prior
LOCALSTEPS_RADIUS_TOL_LOOSE = 5e-4   # mm: F3 radii (disc5_jog, rebuilt from the console text): accepted with a warning


# ------------------------------------------------------------------------------------------------ data
def load_runs(dirs):
    return runs_from_reduced(dirs, [reduce_ladder(d) for d in dirs])


def load_rungs_csv(path):
    runs = {}
    with open(path, newline='', encoding='utf-8') as fh:
        for rec in csv.DictReader(fh):
            r = runs.setdefault(rec['run'], {'name': rec['run'], 'dir': path, 'ref': int(rec['ref_lba']), 'data': []})
            if int(rec['ref_lba']) != r['ref']:
                raise SystemExit(f'{path}: run {rec["run"]} has more than one reference LBA')
            r['data'].append((int(rec['lba']), float(rec['y_rad']), float(rec['sigma_rad'])))
    return list(runs.values())


def rows_of(runs):
    return [{'run': r['name'], 'ref': r['ref'], 'lba': lba, 'y': y, 'sig': s} for r in runs for lba, y, s in r['data']]


def _radius_dev(targets, r0, r1, n):
    """Largest |radius column - prior radius| over [(k, radius_mm, text)] for the prior (r0, r1, n sectors): (mm, k)."""
    t = track_mm(n)
    return max(((abs(spiral.area_radius(16.0 * (k + 1), r0, r1, t) - rc), k) for k, rc, _ in targets),
               default=(0.0, None))


def prior_shift_deg(ref, lbas, r0, r1, n, n2):
    """Largest change (deg) of the converted localsteps phases y(k) of a run (reference ref, targets lbas) if its prior
    had n2 sectors instead of n (same r0, r1)."""
    def dth(k, t):
        return spiral.area_angle(16.0 * (k + 1), r0, r1, t) - spiral.area_angle(16.0 * (ref + 1), r0, r1, t)
    t, t2 = track_mm(n), track_mm(n2)
    return max(abs(dth(k, t2) - dth(k, t)) for k in lbas) * DEG


def localsteps_run(path, prior):
    """One probe localsteps CSV as a run (see the header): y = prior(k) - prior(ref) + radians(measured_minus_prior),
    the prior being the probe's constant-pitch area formula (r0, r1, sectors) on its own track sectors/75*1200 mm with
    LBA k at arc 16 (k+1) mm (Geometry.ThetaOfLba). Returns (ref, data, check): check = the radius-column check, dict
    with max_mm / target (largest deviation from the prior), decimals4 (some radius has a non-zero 4th decimal: the
    probe's own 4-decimal column, checked to LOCALSTEPS_RADIUS_TOL; else it may be 3-decimal text, e.g. rebuilt from
    the console output, checked to LOCALSTEPS_RADIUS_TOL_LOOSE and warned beyond the strict one), tol_mm, blind_sectors
    (the largest prior sector-count error that would pass the same check) and blind_deg (that error's largest effect on
    the file's phases); all None without a radius column."""
    m = re.search(r'localsteps_(\d+)', os.path.basename(path))
    if not m:
        raise SystemExit(f'{path}: the reference LBA must be in the file name (localsteps_<ref>.csv)')
    ref = int(m.group(1))
    r0, r1, n = prior
    t_prior = track_mm(n)
    th_ref = spiral.area_angle(16.0 * (ref + 1), r0, r1, t_prior)
    data, targets = [], []
    try:
        with open(path, newline='', encoding='utf-8') as fh:
            recs = list(csv.DictReader(fh))
    except OSError as e:
        raise SystemExit(f'{path}: unreadable ({e})')
    for rec in recs:
        try:
            k, miss, sd = int(rec['target']), float(rec['measured_minus_prior_deg']), float(rec['sigma_deg'])
            if rec.get('radius_mm'):    # the probe's prior radius of the target: checks that this is its prior
                targets.append((k, float(rec['radius_mm']), rec['radius_mm'].strip()))
        except (KeyError, TypeError, ValueError):
            raise SystemExit(f'{path}: expected columns target,radius_mm,bytes_per_deg,measured_minus_prior_deg,'
                             f'sigma_deg,used')
        if not (sd > 0 and math.isfinite(sd) and math.isfinite(miss)) or k < 0:
            raise SystemExit(f'{path}: target {k}: invalid row (sigma {sd}, value {miss})')
        s = 16.0 * (k + 1)
        data.append((k, spiral.area_angle(s, r0, r1, t_prior) - th_ref + math.radians(miss), math.radians(sd)))
    if not data:
        raise SystemExit(f'{path}: no targets')
    check = {'max_mm': None, 'target': None, 'decimals4': None, 'tol_mm': None, 'blind_sectors': None,
             'blind_deg': None}
    if targets:
        dev, k_dev = _radius_dev(targets, r0, r1, n)
        fine = any(t.lower().count('e') or t.partition('.')[2][3:].strip('0') for _, _, t in targets)
        tol = LOCALSTEPS_RADIUS_TOL if fine else LOCALSTEPS_RADIUS_TOL_LOOSE
        if dev > tol:
            raise SystemExit(f'{path}: target {k_dev}: radius column differs from the prior r0 {r0:g}, r1 {r1:g}, {n} '
                             f'sectors by {dev:.2e} mm (> {tol:g} mm, the tolerance for '
                             + ('its 4-decimal radii' if fine else 'radii without a 4th decimal')
                             + '): this is not the prior the probe used; pass --localsteps-prior R0 R1 SECTORS')
        blind, d = 0, 1             # prior sector-count errors the same check would let through (the scan stops 3
        while d < min(n, 2000) and d <= blind + 3:      # sectors past the last pass: rounding makes the edge ragged)
            if min(_radius_dev(targets, r0, r1, n + d)[0], _radius_dev(targets, r0, r1, n - d)[0]) <= tol:
                blind = d
            d += 1
        deg = max([0.0] + [prior_shift_deg(ref, [k for k, _, _ in data], r0, r1, n, n2)
                           for n2 in ((n - blind, n + blind) if blind else ())])
        check = {'max_mm': dev, 'target': k_dev, 'decimals4': bool(fine), 'tol_mm': tol, 'blind_sectors': blind,
                 'blind_deg': deg}
    return ref, data, check


def load_localsteps(paths, prior, taken):
    """--localsteps files as runs named <folder>/<file stem> (unique against `taken`), one kappa each."""
    runs, names = [], list(taken)
    for p in paths:
        ref, data, chk = localsteps_run(p, prior)
        base = (os.path.basename(os.path.dirname(os.path.abspath(p))) + '/'
                + os.path.splitext(os.path.basename(p))[0])
        name, i = base, 2
        while name in names:
            name, i = f'{base}#{i}', i + 1
        names.append(name)
        runs.append({'name': name, 'dir': p, 'ref': ref, 'data': data,
                     'localsteps': {'prior': [prior[0], prior[1], prior[2]], 'prior_track_mm': track_mm(prior[2]),
                                    'radius_check_max_mm': chk['max_mm'], 'radius_check_target': chk['target'],
                                    'radius_check_decimals4': chk['decimals4'], 'radius_check_tol_mm': chk['tol_mm'],
                                    'radius_check_blind_sectors': chk['blind_sectors'],
                                    'radius_check_blind_deg': chk['blind_deg']}})
    return runs


def _msf_lba(text):
    mm, ss, ff = (int(v) for v in str(text).split(':'))
    return (mm * 60 + ss) * 75 + ff - 150


def summary_sectors(directory):
    """Sector count from <run dir>/summary.json, if the probe wrote one: (value, key) or (None, note)."""
    path = os.path.join(directory, 'summary.json')
    if not os.path.isfile(path):
        return None, None
    try:
        with open(path, encoding='utf-8') as fh:
            js = json.load(fh)
    except (OSError, ValueError) as e:
        raise SystemExit(f'{path}: unreadable ({e})')

    def get(keys):
        v = js
        for k in keys:
            v = v.get(k) if isinstance(v, dict) else None
        return v
    # The probe (src/Calibrate.cs WriteSummary) writes capacity.sectors_used (the count it used: the TOC lead-out, or its
    # --sectors), capacity.toc_lead_out_lba, prior.sectors and atip.last_lead_out_start; the flat keys are for hand-made files.
    for keys in (('capacity', 'sectors_used'), ('capacity', 'toc_lead_out_lba'), ('prior', 'sectors'),
                 ('sectors',), ('burn', 'sectors'), ('disc', 'sectors'), ('toc_leadout_lba',), ('leadout_lba',),
                 ('toc', 'leadout_lba'), ('toc', 'lead_out_lba')):
        v = get(keys)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v == int(v) and v > 0:
            return int(v), f'"{".".join(keys)}"'
    for keys in (('atip', 'last_lead_out_start'), ('atip_last_leadout',), ('atip', 'last_leadout'),
                 ('atip', 'last_lead_out')):
        v = get(keys)
        if isinstance(v, str) and v.count(':') == 2:     # blank's capacity: equals the sector count of a full-length burn
            return _msf_lba(v), f'"{".".join(keys)}" = {v}, the ATIP capacity: assumes a full-length burn'
    return None, f'{path}: no sector count (keys capacity.sectors_used / capacity.toc_lead_out_lba / sectors / atip)'


def resolve_sectors(runs, explicit):
    """--sectors if given, else the runs' summary.json (they must agree), else 359845. Returns (out, disc, notes)."""
    found, notes, sources = {}, [], {}
    for r in runs:
        if os.path.isdir(r['dir']):
            v, src = summary_sectors(r['dir'])
            if v is not None:
                found[r['name']] = v
                sources.setdefault((v, src), []).append(os.path.basename(os.path.normpath(r['dir'])))
            elif src:
                notes.append(src)
    for (v, key), names in sources.items():
        notes.insert(0, f'summary.json of {", ".join(names)}: {v} sectors [{key}]')
    disc = None
    if found:
        vals = sorted(set(found.values()))
        if len(vals) > 1 and explicit is None:
            raise SystemExit(f'the runs disagree on the sector count {found}; pass --sectors N')
        disc = vals[-1]
    out = explicit if explicit is not None else (disc if disc is not None else DEFAULT_SECTORS)
    return out, disc, notes


def track_mm(sectors):
    return sectors / 75 * 1200                       # CalibrationParameters.TrackLengthMm for CD (app formula)


def arc_mm(lba, x):
    """Arc length of the READ CD completion of LBA k: q_k = 2352 (k+1) - x bytes (spec 2.5)."""
    return fitlib.s_of_lba(lba, -x)


# ------------------------------------------------------------------------------------------------ model
class RunsProblem(fitlib.Problem):
    """fitlib.Problem for any runs, any track length and the spec's x convention (fitlib.fit is reused unchanged)."""

    def __init__(self, rows, kind, track, x_bytes=0.0):
        self.kind, self.track, self.x = kind, track, x_bytes
        self.rows = list(rows)
        self.runs = list(dict.fromkeys(r['run'] for r in self.rows))
        self.run_idx = [self.runs.index(r['run']) for r in self.rows]
        self.s_lba = [arc_mm(r['lba'], x_bytes) for r in self.rows]
        self.s_ref = [arc_mm(r['ref'], x_bytes) for r in self.rows]
        self.s_unique = sorted(set(self.s_lba) | set(self.s_ref))
        if self.s_unique[0] <= 0 or self.s_unique[-1] >= track:
            raise ValueError('a rung lies outside the track (0, L)')
        self.y = [r['y'] for r in self.rows]
        self.sig = [r['sig'] for r in self.rows]
        self.n_nl = len(fitlib.NL_NAMES[kind])
        self.n_par = self.n_nl + len(self.runs)

    def diffs(self, p_nl):
        f = fitlib.make_angle_fn(self.kind, p_nl, T=self.track)
        th = {s: f(s) for s in self.s_unique}
        return [th[a] - th[b] for a, b in zip(self.s_lba, self.s_ref)]


class WriteLinks:
    """Write links [(k_link, fixed gap G mm or None = fitted)]: content at LBA >= k_link lies g mm further along the
    track, a rung's phase gains g (h(lba) - h(ref)), h(k) = [k >= k_link] / r(k). r(k) = radius of the rung's arc on the
    FIXED constant-pitch geometry (area formula, ri, ro, track): see link_geometry() and the header."""

    def __init__(self, specs, ri, ro, track):
        self.specs = [(int(k), None if g is None else float(g)) for k, g in specs]
        self.ri, self.ro, self.track = ri, ro, track
        self.free = [j for j, (_, g) in enumerate(self.specs) if g is None]

    def __len__(self):
        return len(self.specs)

    def h(self, j, lba, s):
        return 1.0 / spiral.area_radius(s, self.ri, self.ro, self.track) if lba >= self.specs[j][0] else 0.0

    def columns(self, rows, s_lba, s_ref):
        """h_j(lba) - h_j(ref) per row (rad per mm of gap), one list per link."""
        return [[self.h(j, r['lba'], a) - self.h(j, r['ref'], b) for r, a, b in zip(rows, s_lba, s_ref)]
                for j in range(len(self.specs))]

    def unmeasured(self, rows):
        """The free links whose gaps `rows` do not measure as steps: [(k_link, reason)], [] = all measured (the joint
        test of all free links). The free links cut the LBA axis into segments (segment i: i free links at or below the
        LBA); a run ties together the segments it has rungs in, while its reference LBA counts for nothing (the run's
        kappa takes it). Gap j is measured iff the segments on its two sides are connected through runs: one link, some
        run has rungs on both sides of it; two links with no rung, or only a reference, between them are seen only as
        the sum of their gaps. Connected segments make the linear block [kappas | gaps] of full rank; the test is
        stricter than that rank, since a gap seen only through the 1/r variation within one segment would be degenerate
        with the smooth spiral."""
        ks = sorted(self.specs[j][0] for j in self.free)
        if not ks:
            return []
        parent = list(range(len(ks) + 1))

        def root(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i
        segs, refs = {}, {}
        for r in rows:
            segs.setdefault(r['run'], set()).add(bisect.bisect_right(ks, r['lba']))
            refs.setdefault(bisect.bisect_right(ks, r['ref']), set()).add(r['ref'])
        for s in segs.values():
            first, *rest = sorted(s)
            for t in rest:
                parent[root(t)] = root(first)
        filled = set().union(*segs.values())

        def empty(e):
            where = ('below it' if e == 0 else 'at or beyond it' if e == len(ks) else
                     f'in LBA {ks[e - 1]} .. {ks[e] - 1}')
            only = (f' (only the reference LBA {", ".join(str(v) for v in sorted(refs[e]))}, which does not count)'
                    if refs.get(e) else '')
            return f'no rung {where}{only}'
        bad = []
        for i, k in enumerate(ks):          # link k: segment i below it, segment i + 1 at and beyond it
            if root(i) == root(i + 1):
                continue
            if i not in filled or i + 1 not in filled:
                why = empty(i if i not in filled else i + 1)
            else:
                why = ('no run has rungs on both sides of it' if len(ks) == 1 else
                       'no run, nor a chain of runs across the neighbouring links, has rungs on both sides of it')
            bad.append((k, why))
        return bad


class LinkProblem(RunsProblem):
    """RunsProblem plus write links. Parameters: p_nl, one kappa per run, then one gap g (mm) per free link (linear,
    analytic Jacobian columns (h(lba) - h(ref)) / sigma); fixed gaps are a known part of diffs()."""

    def __init__(self, rows, kind, track, x_bytes, links, check=True):
        super().__init__(rows, kind, track, x_bytes)
        self.links = links
        cols = links.columns(self.rows, self.s_lba, self.s_ref)
        self.H = [cols[j] for j in links.free]
        fixed = [(g, cols[j]) for j, (_, g) in enumerate(links.specs) if g is not None]
        self.fixed_part = [math.fsum(g * c[i] for g, c in fixed) for i in range(len(self.rows))]
        self.n_kappa = len(self.runs)
        self.n_par = self.n_nl + self.n_kappa + len(self.H)
        if check:
            bad = links.unmeasured(self.rows)
            if bad:
                raise ValueError('free gap(s) not measured as steps: ' + '; '.join(f'link at LBA {k}: {why}'
                                                                                  for k, why in bad))

    def diffs(self, p_nl):
        return [d + f for d, f in zip(super().diffs(p_nl), self.fixed_part)]

    def link_model(self, gaps):
        """Phase of the free links per row (rad) for the gaps (mm)."""
        return [math.fsum(g * c[i] for g, c in zip(gaps, self.H)) for i in range(len(self.rows))]

    def residuals(self, p):
        base = super().residuals(p)          # fitlib: (y - diffs - kappa_run) / sigma (the kappas are p[n_nl:][run])
        lm = self.link_model(p[self.n_nl + self.n_kappa:])
        return [b - v / s for b, v, s in zip(base, lm, self.sig)]

    def jacobian(self, p):
        J = super().jacobian(p)              # finite-difference shape columns and the kappa columns, 1/sigma weighted
        for i, row in enumerate(J):
            row.extend(c[i] / self.sig[i] for c in self.H)
        return J

    def initial_kappa(self, p_nl):
        """Start of the linear parameters (kappas, then free gaps): their exact least squares at p_nl."""
        if not self.H:
            return super().initial_kappa(p_nl)
        d = self.diffs(p_nl)
        A = [[(1.0 / sg) if self.run_idx[i] == j else 0.0 for j in range(self.n_kappa)] + [c[i] / sg for c in self.H]
             for i, sg in enumerate(self.sig)]
        sol, _, _ = fitlib.lstsq_qr(A, [(y - di) / sg for y, di, sg in zip(self.y, d, self.sig)])
        return sol


def link_table(res, pr):
    """Gaps of a fit: [{lba, fixed, g_mm, sigma_formal_mm, sigma_scaled_mm}] (scaled: x sqrt(max(1, chi2/dof)))."""
    out, m = [], pr.n_nl + pr.n_kappa
    for k, gfix in pr.links.specs:
        if gfix is not None:
            out.append({'lba': k, 'fixed': True, 'g_mm': gfix, 'sigma_formal_mm': None, 'sigma_scaled_mm': None})
            continue
        sf = res['sigma_formal'][m]
        out.append({'lba': k, 'fixed': False, 'g_mm': res['p'][m], 'sigma_formal_mm': sf,
                    'sigma_scaled_mm': math.sqrt(res['scale']) * sf})
        m += 1
    return out


class AreaSpiral:
    """The app's CD formula when all pitch terms are zero (CalibrationGeometry / CdDiscParameters closed forms)."""

    def __init__(self, ri, ro, track):
        self.ri, self.ro, self.T = ri, ro, track
        self.b = (ro - ri) * (ro + ri) / (2 * track)

    def angle_at_arc(self, s):
        return spiral.area_angle(s, self.ri, self.ro, self.T)

    def radius_at_arc(self, s):
        return spiral.area_radius(s, self.ri, self.ro, self.T), 0

    def arc_at_radius(self, r):
        return (r - self.ri) * (r + self.ri) / (2 * self.b)


def make_spiral(kind, p_nl, track):
    ri, ro, c1, c2, c3 = fitlib.full_params(kind, p_nl)
    if kind == 'area':
        return AreaSpiral(ri, ro, track)
    return spiral.SpiralGeometry(ri, ro, track, c1, c2, c3)


def arc_at_radius(sp, r):
    return sp.arc_at_radius(r) if isinstance(sp, AreaSpiral) else sp.arc_and_angle_at_radius(r)[0]


def nl(res):
    return list(res['p'][:len(fitlib.NL_NAMES[res['kind']])])


def p5(res):
    return list(fitlib.full_params(res['kind'], nl(res)))


def fit_model(rows, kind, start, track, x, diagnostics=True, links=None):
    pr = LinkProblem(rows, kind, track, x, links) if links else RunsProblem(rows, kind, track, x)
    res = fitlib.fit(pr, start)
    n = pr.n_nl
    sf = res['sigma_formal']
    res['cov_formal'] = [[res['corr_nl'][i][j] * sf[i] * sf[j] for j in range(n)] for i in range(n)]
    res['scale'] = max(1.0, res['chi2'] / res['dof']) if res['dof'] > 0 else 1.0
    res['se'] = [math.sqrt(res['scale']) * sf[k] for k in range(n)]
    res['problem'] = pr
    if links:
        res['names'] = res['names'] + [f'g_{links.specs[j][0]}' for j in links.free]
        res['links'] = link_table(res, pr)
    if diagnostics:   # final undamped Gauss-Newton step at the solution, in units of each parameter's formal sigma
        delta, cov, _ = fitlib.lstsq_qr(pr.jacobian(res['p']), pr.residuals(res['p']))
        res['final_step_sigma'] = max(abs(d) / math.sqrt(cov[k][k]) for k, d in enumerate(delta))
    return res


def kappas(res):
    pr = res['problem']
    return res['p'][pr.n_nl:pr.n_nl + len(pr.runs)]


def default_start(track):
    """ri 24.92 mm and the Lenovo box's pitch (1.4865 um) over this track length: ~57.84 mm for 359845 sectors."""
    return 24.92, math.sqrt(24.92 ** 2 + 1.4865e-3 * track / math.pi)


def fit_chain(rows, track, x, start=None, links=None):
    area = fit_model(rows, 'area', list(start or default_start(track)), track, x, links=links)
    const = fit_model(rows, 'constant', nl(area), track, x, links=links)
    quad = fit_model(rows, 'quadratic', nl(const) + [0.0, 0.0], track, x, links=links)
    cubic = fit_model(rows, 'cubic', nl(quad) + [0.0], track, x, links=links)
    return {'area': area, 'constant': const, 'quadratic': quad, 'cubic': cubic}


def link_geometry(rows, specs, track, x, start=None, tol=1e-9, max_passes=8):
    """The links' fixed h geometry (see the header): WriteLinks(specs) on the converged area-formula fit of `rows` WITH
    those links. Pass 1 takes h on the start values (--start or default_start), each further pass on the previous pass's
    fit, until ri and ro move by < tol mm, so the geometry no longer depends on the start. Returns (WriteLinks, info)."""
    geo = tuple(start or default_start(track))
    moved, n = float('inf'), 0
    while n < max_passes and not moved < tol:
        n += 1
        res = fit_model(rows, 'area', list(geo), track, x, diagnostics=False, links=WriteLinks(specs, *geo, track))
        new = tuple(nl(res))
        moved = max(abs(a - b) for a, b in zip(new, geo))
        geo = new
    return WriteLinks(specs, geo[0], geo[1], track), {'passes': n, 'last_move_mm': moved, 'converged': moved < tol}


def to_frame(kind, params, t_fit, t_out):
    """Same physical spiral for another sector count (exact): ro is the radius at the new length, X is rescaled."""
    ri, ro, c1, c2, c3 = params
    if t_out == t_fit:
        return list(params), None
    if kind == 'area':
        return [ri, math.sqrt(ri * ri + (ro - ri) * (ro + ri) * t_out / t_fit), 0.0, 0.0, 0.0], None
    g = spiral.SpiralGeometry(ri, ro, t_fit, c1, c2, c3)
    if t_out < t_fit:
        r = g.radius_at_arc(t_out)[0]
    else:                                 # beyond the fitted band: the polynomial is extrapolated
        r = ro
        for _ in range(60):
            s, _ = g.arc_and_angle_at_radius(r)
            step = (s - t_out) / math.hypot(1.0, g.g * r / g.shape(r))
            r -= step
            if abs(step) < 1e-15 * r:
                break
    lam = (r - ri) / (ro - ri)
    out = [ri, r, c1 * lam, c2 * lam ** 2, c3 * lam ** 3]
    g2 = spiral.SpiralGeometry(ri, r, t_out, *out[2:])
    s_chk = [t_out * f for f in (0.05, 0.3, 0.6, 0.95)]
    s_chk = [s for s in s_chk if s < min(t_fit, t_out)]
    dth = max(abs((g2.angle_at_arc(s) - g2.angle_at_arc(s_chk[0])) - (g.angle_at_arc(s) - g.angle_at_arc(s_chk[0])))
              for s in s_chk)
    return out, {'b_rel_diff': g2.b / g.b - 1, 'max_dtheta_rad': dth, 'extrapolated': t_out > t_fit}


# ------------------------------------------------------------------------------------------------ statistics
def _betacf(a, b, x):
    tiny, qab, qap, qam = 1e-300, a + b, a + 1, a - 1
    c, d = 1.0, 1 - qab * x / qap
    d = 1 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 1001):
        m2 = 2 * m
        for aa in (m * (b - m) * x / ((qam + m2) * (a + m2)), -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))):
            d = 1 + aa * d
            d = 1 / (d if abs(d) > tiny else tiny)
            c = 1 + aa / c
            c = c if abs(c) > tiny else tiny
            h *= d * c
        if abs(d * c - 1) < 1e-16:
            break
    return h


def betai(a, b, x):
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lbt = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x)
    if x < (a + 1) / (a + b + 2):
        return math.exp(lbt) * _betacf(a, b, x) / a
    return 1 - math.exp(lbt) * _betacf(b, a, 1 - x) / b


def f_survival(f, d1, d2):
    return 1.0 if f <= 0 else betai(d2 / 2, d1 / 2, d2 / (d2 + d1 * f))


def f_test(small, big):
    dp = big['problem'].n_nl - small['problem'].n_nl
    dchi = small['chi2'] - big['chi2']
    if big['dof'] <= 0 or big['chi2'] <= 0:
        return {'dchi2': dchi, 'dp': dp, 'dof': big['dof'], 'F': float('nan'), 'p': 1.0}
    F = dchi / dp / (big['chi2'] / big['dof'])
    return {'dchi2': dchi, 'dp': dp, 'dof': big['dof'], 'F': F, 'p': f_survival(F, dp, big['dof'])}


# ------------------------------------------------------------------------------------------------ maps and ruler
class Band:
    """The ruler radii scaled from the Lenovo band to this disc's band [ri, ro] (identity for that box)."""

    def __init__(self, ri, ro):
        self.ri, self.ro = ri, ro
        self.lam = (ro - ri) / (REF_BAND[1] - REF_BAND[0])
        self.grid = [self.at(r) for r in GRID_BASE]

    def at(self, r):
        return self.ri + (r - REF_BAND[0]) * self.lam

    def X(self, r):
        return (r - self.at(41.25)) / (16.25 * self.lam)


def ruler(t, grid):
    """Ruler through t(r) = r*D(r) at the 28 / 57 mm points: B = 2 x intercept at r = 0 (offset of the far half of the
    line, + along +Theta = the track direction); bow = largest signed departure from the ruler over 30 .. 55 mm."""
    g28, g57 = grid[I28], grid[I57]
    slope = (t[I57] - t[I28]) / (g57 - g28)
    icpt = t[I28] - g28 * slope
    bow, at = 0.0, float('nan')
    for i in range(I30, I55 + 1):
        dev = t[i] - (icpt + slope * grid[i])
        if abs(dev) > abs(bow):
            bow, at = dev, grid[i]
    return 2 * icpt, bow, at


def map_stats(d, grid):
    """d: angle difference (rad) at the same byte on the grid; a constant part is a rotation and drops out."""
    mean = sum(d) / len(d)
    B, bow, at = ruler([r * v for r, v in zip(grid, d)], grid)
    return {'pp_deg': (max(d) - min(d)) * DEG, 'rms_deg': math.sqrt(sum((v - mean) ** 2 for v in d) / len(d)) * DEG,
            'max_tangential_mm': max(abs(r * (v - mean)) for r, v in zip(grid, d)), 'B_mm': B, 'bow_mm': bow,
            'bow_at_mm': at}


def theta_on(kind, p_nl, track, sgrid):
    sp = make_spiral(kind, p_nl, track)
    return [sp.angle_at_arc(s) for s in sgrid]


def smooth_residual_line(res, band):
    """Straight radial line burned with the model's own values: D(r) = smooth part of the post-fit residual (weighted
    poly4 in X plus one offset per run, weights 1/(sigma_deg^2 + 0.2^2)), as in the C# harness and calibrate.py."""
    pr = res['problem']
    sp = make_spiral(res['kind'], nl(res), pr.track)
    radii = [sp.radius_at_arc(s)[0] for s in pr.s_lba]
    nk = len(pr.runs)
    npar = 5 + nk - 1
    A, b = [], []
    for i, r in enumerate(radii):
        sd = pr.sig[i] * DEG
        w = 1 / math.sqrt(sd * sd + 0.04)
        X = band.X(r)
        A.append([X ** k * w for k in range(5)] + [w if pr.run_idx[i] == j + 1 else 0.0 for j in range(nk - 1)])
        b.append(res['residual_rad'][i] * DEG * w)
    sol, cov, _ = fitlib.lstsq_qr(A, b)
    chi2 = sum((bi - sum(a * s for a, s in zip(row, sol))) ** 2 for row, bi in zip(A, b))
    red = chi2 / max(1, len(b) - npar)
    scale = max(1.0, red)
    c = sol[:5]

    def D(r):
        X = band.X(r)
        return sum(c[k] * X ** k for k in range(5))
    dg = [D(r) for r in band.grid]
    B, bow, at = ruler([r * math.radians(v) for r, v in zip(band.grid, dg)], band.grid)
    g28, g57 = band.grid[I28], band.grid[I57]
    span = g57 - g28
    gB, gW = [], []
    for k in range(5):
        t28, t57, tat = (rr * math.radians(band.X(rr) ** k) for rr in (g28, g57, at))
        gB.append(2 * (g57 / span * t28 - g28 / span * t57))
        gW.append(tat - t28 * (g57 - at) / span - t57 * (at - g28) / span)
    vB = sum(gB[i] * cov[i][j] * gB[j] for i in range(5) for j in range(5)) * scale
    vW = sum(gW[i] * cov[i][j] * gW[j] for i in range(5) for j in range(5)) * scale
    mean = sum(dg) / len(dg)
    return {'D_pp_deg': max(dg) - min(dg), 'max_tangential_mm': max(abs(r * math.radians(v - mean))
                                                                    for r, v in zip(band.grid, dg)),
            'B_mm': B, 'B_se_mm': math.sqrt(vB), 'bow_mm': bow, 'bow_se_mm': math.sqrt(vW), 'bow_at_mm': at,
            'poly4_reduced_chi2': red, 'D_poly4_deg_in_X': c,
            'D_samples_deg': [D(band.at(r)) - mean for r in SAMPLES_BASE]}


def model_map_sigma(res, sgrid, band):
    """1-sigma uncertainty of the model's own burned map (chi2-scaled shape covariance; kappas only rotate it)."""
    kind, p, track = res['kind'], nl(res), res['problem'].track
    grid = band.grid
    deriv = []
    for k, name in enumerate(fitlib.NL_NAMES[kind]):
        h = fitlib.FD_STEP[name]
        q1, q2 = list(p), list(p)
        q1[k] += h
        q2[k] -= h
        a, bb = theta_on(kind, q1, track, sgrid), theta_on(kind, q2, track, sgrid)
        deriv.append([(u - v) / (2 * h) for u, v in zip(a, bb)])
    cov = [[res['scale'] * v for v in row] for row in res['cov_formal']]
    n = len(deriv)

    def sd(comp):
        v = sum(comp[a] * cov[a][b] * comp[b] for a in range(n) for b in range(n))
        return math.sqrt(max(v, 0.0))
    tang = [[r * v for r, v in zip(grid, d)] for d in deriv]
    means = [sum(d) / len(d) for d in deriv]
    se_b = sd([ruler(t, grid)[0] for t in tang])

    def dev_at(t, i):
        slope = (t[I57] - t[I28]) / (grid[I57] - grid[I28])
        return t[i] - (t[I28] - grid[I28] * slope + slope * grid[i])
    se_bow = max(sd([dev_at(t, i) for t in tang]) for i in range(I30, I55 + 1))
    se_tan = max(sd([grid[i] * (deriv[a][i] - means[a]) for a in range(n)]) for i in range(len(grid)))
    return {'se_B_mm': se_b, 'se_bow_max_mm': se_bow, 'se_tangential_max_mm': se_tan}


# ------------------------------------------------------------------------------------------------ cross-validation
def cross_validate(rows, fits, track, x, band, sgrid, log, links=None, stay=()):
    """Held-out chi2 and coefficient stability for the nested family. Folds: runs (>= 2 runs), else single rungs.
    Runs named in `stay` (localsteps) are never held out: they stay in every fold fit. Every fold fit carries the same
    write links as the full fits, and the held-out prediction includes them with the fold's own gaps. A fold without
    which a free gap is no longer measured (WriteLinks.unmeasured: the same for every model) tests no pitch model: it is
    skipped for all models alike and its rungs leave cv_n; with every fold skipped, cv_n is 0 (not testable)."""
    run_names = list(dict.fromkeys(r['run'] for r in rows if r['run'] not in stay))
    by_run = len(run_names) >= 2
    folds = run_names if by_run else [i for i in range(len(rows)) if rows[i]['run'] not in stay]
    n_held = sum(1 for r in rows if r['run'] not in stay)

    def split(f):
        return ([r for r in rows if r['run'] != f] if by_run else rows[:f] + rows[f + 1:],
                [r for r in rows if r['run'] == f] if by_run else [rows[f]])
    blind = {}          # fold -> the free links only it measures
    if links:
        for f in folds:
            bad = links.unmeasured(split(f)[0])
            if bad:
                blind[f] = [k for k, _ in bad]
    n_blind = sum(len(split(f)[1]) for f in blind)
    out = {}
    for kind in SELECT:
        full = fits[kind]
        th_full = theta_on(kind, nl(full), track, sgrid)
        n = len(nl(full))
        cv_total, per_fold, worst = 0.0, [], {'shift_se': (0.0, None), 'z': (0.0, None), 'dB': (0.0, None),
                                               'pp': (0.0, None)}
        for f in folds:
            keep, held = split(f)
            if f in blind:
                per_fold.append({'left_out': f if by_run else f'{rows[f]["run"]}:{rows[f]["lba"]}', 'n': len(held),
                                 'skipped': 'the only measurement of the gap(s) at LBA '
                                            + ', '.join(str(k) for k in blind[f])})
                continue
            try:
                g = fit_model(keep, kind, nl(full), track, x, diagnostics=False, links=links)
            except (ValueError, ZeroDivisionError):    # too few rungs left for this model, or an invalid shape
                cv_total = float('inf')
                per_fold.append({'left_out': f if by_run else f'{rows[f]["run"]}:{rows[f]["lba"]}', 'failed': True})
                continue
            if links:
                hp = LinkProblem(held, kind, track, x, links, check=False)
                gaps = g['p'][g['problem'].n_nl + g['problem'].n_kappa:]
                d = [a + b for a, b in zip(hp.diffs(nl(g)), hp.link_model(gaps))]
            else:
                d = RunsProblem(held, kind, track, x).diffs(nl(g))
            if by_run:      # the held-out run's own kappa (weighted mean), as in the C# harness
                w = [1 / r['sig'] ** 2 for r in held]
                kap = sum(wi * (r['y'] - di) for wi, r, di in zip(w, held, d)) / sum(w)
            else:           # one rung: its run's kappa from the fold fit
                kap = g['p'][g['problem'].n_nl + g['problem'].runs.index(held[0]['run'])]
            chi = sum(((r['y'] - di - kap) / r['sig']) ** 2 for r, di in zip(held, d))
            cv_total += chi
            dp = [a - b for a, b in zip(nl(g), nl(full))]
            shift = max(abs(v) / s for v, s in zip(dp, full['se']))
            z = None
            if by_run:      # shift against its expectation: Var(p_fold - p_full) = s^2 (C_fold - C_full)
                zs = []
                for k in range(n):
                    var = full['scale'] * (g['cov_formal'][k][k] - full['cov_formal'][k][k])
                    zs.append(abs(dp[k]) / math.sqrt(var) if var > 0 else float('inf'))
                z = max(zs)
            ms = map_stats([a - b for a, b in zip(theta_on(kind, nl(g), track, sgrid), th_full)], band.grid)
            label = f if by_run else f'{rows[f]["run"]}:{rows[f]["lba"]}'
            per_fold.append({'left_out': label, 'held_out_chi2': chi, 'n': len(held), 'p_nl': nl(g), 'chi2': g['chi2'],
                             'dof': g['dof'], 'max_shift_se': shift, 'max_z': z, 'map_change': ms})
            if links:
                per_fold[-1]['gaps_mm'] = [e['g_mm'] for e in g['links']]
            for key, val in (('shift_se', shift), ('z', z if z is not None else 0.0), ('dB', abs(ms['B_mm'])),
                             ('pp', ms['pp_deg'])):
                if val > worst[key][0]:
                    worst[key] = (val, label)
        out[kind] = {'by_run': by_run, 'cv_chi2': cv_total, 'cv_n': n_held - n_blind, 'folds': per_fold,
                     'max_shift_se': worst['shift_se'], 'max_z': worst['z'] if by_run else None,
                     'max_abs_dB_mm': worst['dB'], 'max_map_pp_deg': worst['pp']}
        if links:
            out[kind]['skipped_folds'] = [fo['left_out'] for fo in per_fold if fo.get('skipped')]
            if len(blind) == len(folds):    # nothing held out: no held-out chi2, no stability
                out[kind].update(max_shift_se=None, max_z=None, max_abs_dB_mm=None, max_map_pp_deg=None)
        log(f'  cross-validation {NAMES[kind]}: {len(folds)} folds done')
    return out


def select_model(fits, ftests, cv, alpha):
    chosen, steps = 'constant', []
    for cand in ('quadratic', 'cubic'):
        ft = ftests[f'{chosen}->{cand}']
        cv_a, cv_b = cv[chosen]['cv_chi2'], cv[cand]['cv_chi2']
        z = cv[cand]['max_z']
        if cv[cand]['cv_n'] == 0:       # write links: every fold skipped (cross_validate), nothing was held out
            ok = {'F': ft['p'] < alpha, 'cv': True, 'stable': True}
            why = (f'{chosen} -> {cand}: F-test p = {ft["p"]:.2g} ({"<" if ok["F"] else ">="} {alpha:g}), held-out '
                   f'chi2 and stability: not testable (every fold skipped: each one alone measures a free gap)')
            steps.append(('accepted: ' if all(ok.values()) else 'rejected: ') + why)
            if all(ok.values()):
                chosen = cand
            continue
        ok = {'F': ft['p'] < alpha, 'cv': cv_b < cv_a, 'stable': z is None or z[0] <= Z_MAX}
        why = (f'{chosen} -> {cand}: F-test p = {ft["p"]:.2g} ({"<" if ok["F"] else ">="} {alpha:g}), '
               f'held-out chi2 {cv_a:.1f} -> {cv_b:.1f} ({"falls" if ok["cv"] else "does not fall"})')
        if z is not None:
            why += f', stability max z {z[0]:.2f} ({"<=" if ok["stable"] else ">"} {Z_MAX:g}, worst without {z[1]})'
        else:
            why += ', stability: not testable with one run'
        steps.append(('accepted: ' if all(ok.values()) else 'rejected: ') + why)
        if all(ok.values()):
            chosen = cand
    return chosen, steps


# ------------------------------------------------------------------------------------------------ report
def fmt_num(v):
    """Shortest round-trip decimal (parses back to the same double, like .NET "R" / G17); 0 stays 0."""
    return '0' if v == 0 else repr(float(v))


def _encodable(text):
    """The UI labels are Chinese; a console or redirect that cannot encode them gets the English labels only."""
    try:
        text.encode(getattr(sys.stdout, 'encoding', None) or 'ascii')
        return True
    except (UnicodeEncodeError, LookupError):
        return False


def runs_from_reduced(dirs, reduced):
    """calibrate.py --pitch: wrap its already reduced runs [(ref, data), ...] for report()."""
    runs, names = [], []
    for d, (ref, data) in zip(dirs, reduced):
        base = os.path.basename(os.path.normpath(d)) or d
        name, i = base, 2
        while name in names:
            name, i = f'{base}#{i}', i + 1
        names.append(name)
        runs.append({'name': name, 'dir': d, 'ref': ref, 'data': data})
    return runs


def burn_prediction(burn, burn_sectors, rec_kind, rec_nl, track_fit, band, line):
    """Straight radial design line on a disc burned with `burn` while the truth is the recommended fit (fit frame)."""
    ri, ro, c1, c2, c3 = burn
    t_b = track_mm(burn_sectors)
    used = AreaSpiral(ri, ro, t_b) if c1 == c2 == c3 == 0 else spiral.SpiralGeometry(ri, ro, t_b, c1, c2, c3)
    true = make_spiral(rec_kind, rec_nl, track_fit)
    sg = [arc_at_radius(true, r) for r in band.grid]
    d = [true.angle_at_arc(s) - used.angle_at_arc(s) for s in sg]
    st = map_stats(d, band.grid)
    samp_s = [arc_at_radius(true, band.at(r)) for r in SAMPLES_BASE]
    samp = [true.angle_at_arc(s) - used.angle_at_arc(s) for s in samp_s]
    dr = [(used.radius_at_arc(s)[0] - band.at(r)) * 1000 for s, r in zip(samp_s, SAMPLES_BASE)]
    resid = [math.radians(sum(line['D_poly4_deg_in_X'][k] * band.X(r) ** k for k in range(5))) for r in band.grid]
    st_tot = map_stats([a + b for a, b in zip(d, resid)], band.grid)
    return {'burn': list(burn), 'burn_sectors': burn_sectors, 'map': st, 'with_residual': st_tot,
            'samples_deg_rel_first': [(v - samp[0]) * DEG for v in samp], 'samples_r_burn_minus_true_um': dr}


def report(runs, x=0.0, sectors=None, burn=None, burn_sectors=None, alpha=0.01, json_path=None, start=None,
           print_runs=True, out=print, links=None):
    """links: write links [(LBA, None = fit the gap | G = fixed gap in mm)]; runs with a 'localsteps' entry come from
    load_localsteps (local data: never held out in the cross-validation)."""
    rows = rows_of(runs)
    if not rows:
        raise SystemExit('no rungs')
    s_out, s_disc, notes = resolve_sectors(runs, sectors)
    s_fit = s_disc if s_disc is not None else s_out
    q_max = max(max(2352 * (r['lba'] + 1), 2352 * (r['ref'] + 1)) - x for r in rows)
    if q_max >= s_fit * 2352:            # the burn is shorter than the measured band: fit on a covering frame
        s_fit = max(DEFAULT_SECTORS, int(q_max // 2352) + 2)
        notes.append(f'rungs reach beyond {s_out} sectors: fitted on a {s_fit}-sector frame, then converted exactly')
    t_fit, t_out = track_mm(s_fit), track_mm(s_out)
    nruns = len(runs)
    ls_runs = [r for r in runs if r.get('localsteps')]
    stay = {r['name'] for r in ls_runs}
    lk = None
    if links:
        lk = WriteLinks(links, *(start or default_start(t_fit)), t_fit)    # (geometry: link_geometry below)
        for k, gfix in lk.specs:
            if not 0 < k < s_fit:
                raise SystemExit(f'--link {k}: outside the track (1 .. {s_fit - 1})')
        bad = lk.unmeasured(rows)       # all free links jointly (a fold that alone measures one: cross_validate)
        if bad:
            raise SystemExit(f'--link: {len(bad)} free gap(s) not measured as steps: ' + '; '.join(
                f'LBA {k}: {why}' for k, why in bad) + '. A run measures a step only with rungs on both sides of it (its '
                'reference LBA does not count: the run\'s kappa takes it), so these gaps are degenerate with the kappas, '
                'the smooth spiral or each other (two links with no rung between them: only their sum is seen). Merge '
                'links with no rung between them into one --link, add localsteps runs across them, or fix a gap with '
                '--link LBA=G')

    def fit_failed(e):
        return SystemExit(f'fit failed ({e}): too few rungs for the cubic model, a rung outside the track for this --x, '
                          f'or a start too far off (--start RI,RO)')

    out('\n=== pitch-model fit: constant / quadratic / cubic (calibrate_pitch.py) ===')
    if print_runs:
        for r in runs:
            sig = sorted(math.degrees(v[2]) for v in r['data'])
            out(f'{"localsteps " if r.get("localsteps") else ""}run {r["name"]} ({r["dir"]}): reference LBA {r["ref"]}, '
                f'{len(r["data"])} rungs, per-rung sigma median {sig[len(sig) // 2]:.3f} deg, max {sig[-1]:.3f} deg')
    out(f'{len(rows)} rungs in {nruns} run(s); weights 1/sigma^2; one kappa per run; q_k = 2352 (k+1) - x with x = {x:+g} B')
    src = 'given' if sectors is not None else ('from summary.json' if s_disc is not None else
                                               'default: no sector count from a summary.json')
    out(f'sectors: values for a burn of {s_out} sectors ({src}); fit frame {s_fit} sectors, L = {t_fit!r} mm')
    for n_ in notes:
        out(f'  note: {n_}')
    ls_priors = sorted({tuple(r['localsteps']['prior']) for r in ls_runs})
    for pr0, pr1, pn in ls_priors:
        group = [r for r in ls_runs if tuple(r['localsteps']['prior']) == (pr0, pr1, pn)]
        out(f'localsteps: y = prior(k) - prior(ref) + measured_minus_prior, prior = the probe\'s constant-pitch area formula '
            f'r0 {fmt_num(pr0)}, r1 {fmt_num(pr1)} mm, {pn} sectors on its own L = {track_mm(pn)!r} mm (LBA k at arc '
            f'16 (k+1) mm); the fit models y on its own frame; never held out in the cross-validation')
        out(f'  radius column vs the prior (refused beyond {LOCALSTEPS_RADIUS_TOL:g} mm where some radius has a non-zero '
            f'4th decimal, the probe\'s own column; else beyond {LOCALSTEPS_RADIUS_TOL_LOOSE:g} mm, warned beyond '
            f'{LOCALSTEPS_RADIUS_TOL:g} mm):')
        for r in group:
            c = r['localsteps']
            if c['radius_check_max_mm'] is None:
                out(f'    {r["name"]}: no radius column, not checked')
                continue
            out(f'    {r["name"]}: {c["radius_check_max_mm"]:.1e} mm, '
                + ('4-decimal radii' if c['radius_check_decimals4'] else 'no 4th decimal')
                + f': a prior off by up to {c["radius_check_blind_sectors"]} sector(s) would pass '
                f'({c["radius_check_blind_deg"]:.2f} deg on its phases)')
        for r in group:
            c = r['localsteps']
            if c['radius_check_max_mm'] is not None and c['radius_check_max_mm'] > LOCALSTEPS_RADIUS_TOL:
                out(f'  WARNING: {r["name"]}: its radius column agrees with the prior only to '
                    f'{c["radius_check_max_mm"]:.1e} mm (> {LOCALSTEPS_RADIUS_TOL:g} mm) and has no 4th decimal (3-decimal '
                    f'radii, e.g. rebuilt from the console text?), so it was accepted at {LOCALSTEPS_RADIUS_TOL_LOOSE:g} '
                    f'mm: for this file a prior off by up to {c["radius_check_blind_sectors"]} sectors (up to '
                    f'{c["radius_check_blind_deg"]:.2f} deg on its phases) is not excluded')
        checked = [r for r in group if r['localsteps']['radius_check_max_mm'] is not None]
        best = min(checked, key=lambda r: r['localsteps']['radius_check_blind_sectors']) if checked else None
        if s_disc is not None and pn != s_disc:
            shift = max(prior_shift_deg(r['ref'], [k for k, _, _ in r['data']], pr0, pr1, pn, s_disc) for r in group)
            out(f'  WARNING: the localsteps prior has {pn} sectors, the measured disc {s_disc} (summary.json): the prior '
                f'is used as given (the conversion only undoes what the probe subtracted), but the probe\'s prior '
                f'normally takes the disc\'s own sector count, and had the probe used {s_disc}, these localsteps phases '
                f'would be off by up to {shift:.2f} deg: check --localsteps-prior')
        elif s_disc is None:
            out(f'  note: the measured disc\'s own sector count is unknown (no summary.json in the ladder directories), '
                f'so the prior\'s {pn} sectors could not be checked against it, '
                + (f'only by the radius columns (best: +-{best["localsteps"]["radius_check_blind_sectors"]} sector(s), '
                   f'{best["name"]}, if the probe used one prior for all these files)' if best else
                   'and no file has a radius column')
                + (f'; --sectors {sectors} differs from the prior\'s count: fine if it is the count of another burn, but '
                   f'if it is this disc\'s, check --localsteps-prior' if sectors is not None and sectors != pn else ''))
    if ls_runs and not links:
        out('  WARNING: localsteps runs without --link: they are taken across the write link by design (HP BU20N at 4x: '
            'LBA ~65 500, g ~ +0.20 mm), and an unmodelled step biases the smooth fit while the model selection does not '
            'notice (disc 5: c1 +2.8e-5, c2 -2.9e-5, a ruler offset B of +0.6 mm): pass --link 65536, or --link LBA=0 '
            'to state that this disc has no link')
    h_info = None
    if lk:
        try:
            lk, h_info = link_geometry(rows, lk.specs, t_fit, x, start)
        except (ValueError, ZeroDivisionError) as e:
            raise fit_failed(e)
        out(f'write link(s), in every model and fold: phase + g (h(lba) - h(ref)), h(k) = [k >= k_link] / r(k), r of the '
            f'rung arc on one fixed constant-pitch geometry, the area-formula fit of these data with the link(s) '
            f'(ri {lk.ri:.6f}, ro {lk.ro:.6f} mm after {h_info["passes"]} passes, the start values only seed it); '
            + '; '.join(f'LBA {k} ' + ('gap fitted (one g for all runs: one disc)' if g is None else
                                       f'gap fixed at {g:+.4f} mm') for k, g in lk.specs))
        if not h_info['converged']:
            out(f'  WARNING: that geometry still moved by {h_info["last_move_mm"]:.1e} mm in the last pass')

    try:
        fits = fit_chain(rows, t_fit, x, start, links=lk)
    except (ValueError, ZeroDivisionError) as e:
        raise fit_failed(e)
    for k, f in fits.items():
        if f['final_step_sigma'] > 1e-3:
            out(f'WARNING: {NAMES[k]} fit not converged (final step {f["final_step_sigma"]:.1e} sigma)')

    out('\nfits (fit frame; SE chi2-scaled with max(1, chi2/dof)):')
    out(f'  {"model":21s} {"ri (mm)":>19s} {"ro (mm)":>19s} {"c1":>23s} {"c2":>23s} {"c3":>23s}  {"chi2":>9s} dof  chi2/dof  rms deg')
    for k in ('area', 'constant', 'quadratic', 'cubic'):
        f = fits[k]
        v = p5(f)
        rms = math.sqrt(sum(e * e for e in f['residual_rad']) / len(f['residual_rad'])) * DEG
        out(f'  {NAMES[k]:21s} {v[0]!r:>19} {v[1]!r:>19} {fmt_num(v[2]):>23s} {fmt_num(v[3]):>23s} {fmt_num(v[4]):>23s}  '
            f'{f["chi2"]:9.4f} {f["dof"]:3d}  {f["chi2_dof"]:8.4f}  {rms:6.4f}')
    for k in ('area', 'quadratic', 'cubic'):
        f = fits[k]
        se = ', '.join(f'{nm} {s * 1e6:.1f} nm' if nm in ('ri', 'ro') else f'{nm} {s:.2e}'
                       for nm, s in zip(fitlib.NL_NAMES[k], f['se']))
        kap = ', '.join(f'{math.degrees(v):+.4f}' for v in kappas(f))
        out(f'  {NAMES[k]:9s} SE: {se}; kappa (deg) {kap}; GN iterations {f["iterations"]}, final step '
            f'{f["final_step_sigma"]:.1e} sigma')
        if lk:
            out(f'  {"":9s} write link(s): ' + '; '.join(
                f'LBA {e["lba"]} g {e["g_mm"]:+.4f} mm (fixed)' if e['fixed'] else
                f'LBA {e["lba"]} g {e["g_mm"]:+.4f} mm +- {e["sigma_formal_mm"]:.4f} formal / '
                f'{e["sigma_scaled_mm"]:.4f} chi2-scaled' for e in f['links']))
    da = [a - b for a, b in zip(nl(fits['constant']), nl(fits['area']))]
    out(f'  exact-arc constant minus area constant: ri {da[0]:+.1e} mm, ro {da[1]:+.1e} mm, chi2 '
        f'{fits["constant"]["chi2"] - fits["area"]["chi2"]:+.4f} (the tests below use the exact-arc twin: it is nested)')
    for k, f in fits.items():         # single rungs (the binned table below averages them; README / spec 6.6 fit check)
        i = max(range(len(rows)), key=lambda j: abs(f['residual_rad'][j] / rows[j]['sig']))
        f['worst_rung'] = {'run': rows[i]['run'], 'lba': rows[i]['lba'], 'residual_deg': f['residual_rad'][i] * DEG,
                           'sigma_deg': rows[i]['sig'] * DEG, 'z': f['residual_rad'][i] / rows[i]['sig']}
    out(f'  largest rung residual in sigma (z = residual / sigma; fit check: |z| <= {Z_RUNG:g}): ' + '; '.join(
        f'{NAMES[k]} z {w["z"]:+.1f} ({w["residual_deg"]:+.3f} deg, sigma {w["sigma_deg"]:.3f}, run {w["run"]} LBA {w["lba"]})'
        for k, w in ((k, fits[k]['worst_rung']) for k in ('area', 'quadratic', 'cubic'))))

    # ---- model selection
    ftests = {f'{a}->{b}': f_test(fits[a], fits[b]) for a, b in (('constant', 'quadratic'), ('quadratic', 'cubic'),
                                                                ('constant', 'cubic'))}
    rec_prelim = fits['cubic']
    band_fit = Band(*p5(rec_prelim)[:2])
    s_grid_fit = [arc_at_radius(make_spiral('cubic', nl(rec_prelim), t_fit), r) for r in band_fit.grid]
    cv = cross_validate(rows, fits, t_fit, x, band_fit, s_grid_fit, log=lambda s: None, links=lk, stay=stay)
    chosen, steps = select_model(fits, ftests, cv, alpha)
    rec_kind = 'area' if chosen == 'constant' else chosen

    out('\nmodel selection (prefer the smallest adequate model):')
    for key, ft in ftests.items():
        out(f'  F-test {key.replace("->", " -> "):24s} dchi2 {ft["dchi2"]:9.3f} for {ft["dp"]} term(s): '
            f'F({ft["dp"]},{ft["dof"]}) = {ft["F"]:8.3f}, p = {ft["p"]:.3g}')
    by_run = cv['constant']['by_run']
    if stay:
        n_folds = len(cv['constant']['folds'])
        what = (f'leave one ladder run out ({n_folds} folds; the held-out run gets its own kappa' if by_run else
                f'leave one ladder rung out ({n_folds} folds; one ladder run only, so its kappa comes from the fold fit')
        what += f'; the {len(stay)} localsteps run(s) stay in every fold fit)'
    else:
        what = (f'leave one run out ({nruns} folds; the held-out run gets its own kappa)' if by_run else
                f'leave one rung out ({len(rows)} folds; one run only, so its kappa comes from the fold fit)')
    out(f'  held-out chi2, {what}:')
    for k in SELECT:
        c = cv[k]
        per = ', '.join(f'{fo["left_out"]} ' + ('failed' if fo.get('failed') else 'skipped' if fo.get('skipped') else
                                                f'{fo["held_out_chi2"]:.1f}')
                        for fo in c['folds']) if by_run else ''
        if c['cv_n'] == 0:
            out(f'    {NAMES[k]:21s} not testable: every fold skipped' + (f'  ({per})' if per else ''))
            continue
        out(f'    {NAMES[k]:21s} {c["cv_chi2"]:9.2f} for {c["cv_n"]} rungs' + (f'  ({per})' if per else ''))
    skipped = [fo for fo in cv['constant']['folds'] if fo.get('skipped')]
    if skipped:
        out(f'  ({len(skipped)} of {len(cv["constant"]["folds"])} folds skipped for every model alike, as leaving one out '
            f'leaves a free gap unmeasured and tests no pitch model: ' + '; '.join(
                f'{fo["left_out"]}, {fo["n"]} rung(s), {fo["skipped"]}' for fo in skipped) + ')')
    out('  coefficient stability (refits without each fold, against the full fit):')
    for k in SELECT:
        c = cv[k]
        if c['cv_n'] == 0:
            out(f'    {NAMES[k]:21s} not testable: every fold skipped')
            continue
        z = f'max z {c["max_z"][0]:.2f} (without {c["max_z"][1]})' if c['max_z'] else 'z: n/a (one run)'
        out(f'    {NAMES[k]:21s} max |dp|/SE {c["max_shift_se"][0]:.2f} (without {c["max_shift_se"][1]}); {z}; '
            f'map change max {c["max_map_pp_deg"][0]:.3f} deg p-p, ruler |dB| max {c["max_abs_dB_mm"][0]:.3f} mm')
    for s in steps:
        out('  ' + s)
    if not by_run:
        out('  (one run: a second ladder run of the same disc, e.g. at the other speed, adds the run-to-run stability test)')
    out(f'  -> recommended: {NAMES[rec_kind] if rec_kind != "area" else "constant (area formula, all terms zero)"}')
    if fits[chosen]['chi2_dof'] > 3:
        out(f'  WARNING: chi2/dof of the recommended model is {fits[chosen]["chi2_dof"]:.2f}: structure is left that '
            f'no model here describes; check the residual table and the runs.')
    big = [(r, e) for r, e in zip(rows, fits[rec_kind]['residual_rad']) if abs(e / r['sig']) > Z_RUNG]
    if big:
        out(f'  WARNING: {len(big)} rung(s) of the recommended model lie more than {Z_RUNG:g} sigma off (fit check of '
            f'README / spec 6.6; a local read anomaly?): ' + ', '.join(
                f'run {r["run"]} LBA {r["lba"]} {e * DEG:+.2f} deg (sigma {r["sig"] * DEG:.2f}, z {e / r["sig"]:+.1f})'
                for r, e in big))

    # ---- app values in the output frame
    rec = fits[rec_kind]
    vals, chk = to_frame(rec_kind, p5(rec), t_fit, t_out)
    if chk:
        out(f'  frame change {s_fit} -> {s_out} sectors: b rel. diff {chk["b_rel_diff"]:.1e}, max |dtheta| '
            f'{chk["max_dtheta_rad"]:.1e} rad' + (' (EXTRAPOLATED beyond the measured band)' if chk['extrapolated'] else ''))
    out(f'\n==> app values ({NAMES[rec_kind]}, sectors {s_out}, x = {x:+g} B):')
    out(f'    ri = {fmt_num(vals[0])} mm   ro = {fmt_num(vals[1])} mm   c1 = {fmt_num(vals[2])}   '
        f'c2 = {fmt_num(vals[3])}   c3 = {fmt_num(vals[4])}')
    se = dict(zip(fitlib.NL_NAMES[rec_kind], rec['se']))
    out('    statistical SE: ' + ', '.join(f'{nm} {s * 1e6:.1f} nm' if nm in ('ri', 'ro') else f'{nm} {s:.2e}'
                                          for nm, s in se.items()) + ' (fit frame, chi2-scaled)')
    if ls_runs and not links:
        out('    WARNING: localsteps runs fitted without --link: an unmodelled write link step biases these values '
            '(see the warning above)')
    link_res = None
    if lk:      # gaps of the recommended fit; radius of LBA k_link's first byte (arc 16 k_link mm) on that spiral
        sp_l = make_spiral(rec_kind, nl(rec), t_fit)
        ent = [dict(e, arc_mm=16.0 * e['lba'], r_link_mm=sp_l.radius_at_arc(16.0 * e['lba'])[0]) for e in rec['links']]
        cmd = (f'python -I analysis\\prewarp.py <design.png> <out.png> --r1 {fmt_num(vals[1])} --coeffs 0 --const 0'
               + ''.join(f' --link {e["r_link_mm"]:.4f},{e["g_mm"]:.4f}' for e in ent))
        out(f'\n==> write link(s) of the {NAMES[rec_kind]} fit (not in the app values: the app has no link term, so '
            f'pre-compensate the design with prewarp.py; do both or neither):')
        for e in ent:
            sg = ('fixed' if e['fixed'] else
                  f'+- {e["sigma_formal_mm"]:.4f} formal, +- {e["sigma_scaled_mm"]:.4f} chi2-scaled')
            out(f'    LBA {e["lba"]}: g = {e["g_mm"]:+.4f} mm ({sg}); radius {e["r_link_mm"]:.4f} mm on the fitted spiral')
        bad = [e for e in ent if not (25.0 <= e['r_link_mm'] < 58.0 and abs(e['g_mm']) <= 2.0)]
        if bad:
            out('    (prewarp.py accepts --link only for radii 25 .. 58 mm and |g| <= 2 mm: LBA '
                + ', '.join(str(e['lba']) for e in bad) + ' would be refused)')
        out(f'    {cmd}')
        link_res = {'h': 'h(k) = [k >= k_link] / r(k), r = area_radius(rung arc) on the converged area-formula fit of '
                         'all the data with the links (link_geometry)',
                    'h_geometry': dict({'ri': lk.ri, 'ro': lk.ro, 'track_mm': lk.track}, **h_info),
                    'specs': [{'lba': k, 'fixed_g_mm': g} for k, g in lk.specs], 'model': rec_kind,
                    'recommended': ent, 'prewarp_command': cmd}

    # ---- predicted straight radial line (on the measured disc's band, fit frame)
    sp_rec = make_spiral(rec_kind, nl(rec), t_fit)
    band_f = Band(*p5(rec)[:2])
    s_grid = [arc_at_radius(sp_rec, r) for r in band_f.grid]
    lines = {k: smooth_residual_line(fits[k], band_f) for k in ('area', 'quadratic', 'cubic')}
    sig = {k: model_map_sigma(fits[k], s_grid, band_f) for k in ('area', 'quadratic', 'cubic')}
    g = band_f.grid
    out(f'\npredicted error of a straight radial line burned with each model\'s own values (band {band_f.ri:.4f} .. '
        f'{band_f.ro:.4f} mm = {band_f.lam:.5f} x the Lenovo band: ruler at r = {g[I28]:.3f} / {g[I57]:.3f} mm, '
        f'bow over {g[I30]:.3f} .. {g[I55]:.3f} mm; + = along the track direction):')
    if s_out != s_fit:
        out(f'  (radii of the measured disc; the {s_out}-sector burn ends at ro = {vals[1]:.4f} mm)')
    out('  D(r) = smooth part of that model\'s post-fit residual; B = offset of the far half; SE from the smoothing; '
        '"own map" = 1 sigma of the fitted values themselves')
    if lk:
        out('  (smooth spiral only: the write link steps are modelled, so they are not in D(r); on a disc burned without '
            'prewarp --link, the content beyond each link is also displaced by its g)')
    for k in ('area', 'quadratic', 'cubic'):
        L_, S_ = lines[k], sig[k]
        mark = '  <- recommended' if k == rec_kind else ''
        out(f'  {NAMES[k]:9s} B {L_["B_mm"]:+.3f} +- {L_["B_se_mm"]:.3f} mm, bow {L_["bow_mm"]:+.3f} +- {L_["bow_se_mm"]:.3f}'
            f' mm @ {L_["bow_at_mm"]:.2f} mm, D p-p {L_["D_pp_deg"]:.3f} deg; own map: B {S_["se_B_mm"]:.3f}, bow '
            f'{S_["se_bow_max_mm"]:.3f}, tangential {S_["se_tangential_max_mm"]:.3f} mm{mark}')
    out('  D(r) at ' + '/'.join(f'{band_f.at(r):.1f}' for r in SAMPLES_BASE) + ' mm (deg, mean removed):')
    for k in ('area', 'quadratic', 'cubic'):
        out(f'    {NAMES[k]:9s} ' + ' '.join(f'{v:+.2f}' for v in lines[k]['D_samples_deg']))
    th = {k: theta_on(k, nl(fits[k]), t_fit, s_grid) for k in ('area', 'quadratic', 'cubic')}
    pairs = [(a, b) for a, b in (('quadratic', 'area'), ('cubic', 'area'), ('cubic', 'quadratic'))]
    out('  model A taken as the truth, line burned with model B (same byte, A - B):')
    model_maps = {}
    for a, b in pairs:
        ms = map_stats([u - v for u, v in zip(th[a], th[b])], band_f.grid)
        model_maps[f'{a}_minus_{b}'] = ms
        out(f'    {NAMES[a]} - {NAMES[b]:9s} B {ms["B_mm"]:+.3f} mm, bow {ms["bow_mm"]:+.3f} mm @ {ms["bow_at_mm"]:.2f}, '
            f'p-p {ms["pp_deg"]:.3f} deg, max tangential {ms["max_tangential_mm"]:.3f} mm')

    # ---- probe disc as burned
    burn_res = None
    if burn is not None:
        bs = burn_sectors if burn_sectors is not None else s_fit
        burn_res = burn_prediction(burn, bs, rec_kind, nl(rec), t_fit, band_f, lines[rec_kind])
        m, w = burn_res['map'], burn_res['with_residual']
        out(f'\nprobe disc as burned with ri {fmt_num(burn[0])}, ro {fmt_num(burn[1])}, c {fmt_num(burn[2])} / '
            f'{fmt_num(burn[3])} / {fmt_num(burn[4])}, {bs} sectors, against the fit ({NAMES[rec_kind]}, x = {x:+g} B):')
        out(f'  angle of a straight radial design line, relative to r = {band_f.at(25.5):.1f} (deg): ' + '  '.join(
            f'{band_f.at(r):.1f}: {v:+.2f}' for r, v in zip(SAMPLES_BASE, burn_res['samples_deg_rel_first'])))
        out(f'  twist p-p {m["pp_deg"]:.2f} deg ({m["pp_deg"] / 360:.3f} turns); ruler B {m["B_mm"]:+.3f} mm, bow '
            f'{m["bow_mm"]:+.3f} mm @ {m["bow_at_mm"]:.2f}; with the fit\'s own residual: B {w["B_mm"]:+.3f}, bow {w["bow_mm"]:+.3f} mm'
            + ('' if m['pp_deg'] < 20 else '  (large twist: the line is a spiral arm; read angles, not the ruler)'))
        out('  radius of the same byte, burn model minus truth (um): ' + ' '.join(
            f'{v:+.0f}' for v in burn_res['samples_r_burn_minus_true_um']) + ' (rings stay circles, shifted by this)')
        if lk:
            out('  (smooth spiral only: the write link steps come on top of this)')

    # ---- binned residuals
    out('\nresidual versus radius (deg, weighted mean per 0.1 mm bin +- SE; radii from the recommended model):')
    radii = [sp_rec.radius_at_arc(s)[0] for s in rec['problem'].s_lba]
    bins = {}
    for i, r in enumerate(radii):
        bins.setdefault(round(r, 1), []).append(i)
    out(f'  {"r (mm)":>7s} {"n":>3s}  ' + '  '.join(f'{NAMES[k]:>16s}' for k in ('area', 'quadratic', 'cubic')))
    for key in sorted(bins):
        idx = bins[key]
        cells = []
        for k in ('area', 'quadratic', 'cubic'):
            res_k = fits[k]['residual_rad']
            w = [1 / rows[i]['sig'] ** 2 for i in idx]
            m_ = sum(wi * res_k[i] for wi, i in zip(w, idx)) / sum(w)
            cells.append(f'{m_ * DEG:+7.3f} +- {math.sqrt(1 / sum(w)) * DEG:5.3f}')
        out(f'  {sum(radii[i] for i in idx) / len(idx):7.2f} {len(idx):3d}  ' + '  '.join(f'{c:>16s}' for c in cells))

    # ---- paste block
    out(f'\nproject settings for the test build (DiscImageStudio v1.3.6-rawpw.1-cdcubic.1), {NAMES[rec_kind]} model, '
        f'paste field by field:')
    fields = (('内半径 r0 (mm)', 'Inner r0 (mm)', fmt_num(vals[0])), ('外半径 r1 (mm)', 'Outer r1 (mm)', fmt_num(vals[1])),
              ('扇区数', 'Sectors', str(s_out)), ('相对一次项', 'Linear term', fmt_num(vals[2])),
              ('相对二次项', 'Quadratic term', fmt_num(vals[3])), ('相对三次项', 'Cubic term', fmt_num(vals[4])))
    for zh, en, v in fields:
        out(f'  {zh} / {en}: {v}' if out is not print or _encodable(zh) else f'  {en}: {v}')
    geo = {'innerRadiusMm': vals[0], 'outerRadiusMm': vals[1], 'sectors': s_out, 'pitchLinear': vals[2],
           'pitchQuadratic': vals[3], 'pitchCubic': vals[4]}
    out('  .discproj "geometry": {' + ', '.join(f'"{k}": {v if k == "sectors" else fmt_num(v)}' for k, v in geo.items()) + '}')
    if rec_kind == 'area':
        out('  (all terms 0: the app keeps its closed constant-pitch formulas, exactly the model fitted here)')

    result = {
        'tool': 'calibrate_pitch.py', 'x_bytes': x, 'x_convention': 'q_k = 2352 (k+1) - x (calibrate.py --x, spec 2.5)',
        'sectors_out': s_out, 'sectors_fit': s_fit, 'sectors_notes': notes, 'track_fit_mm': t_fit,
        'runs': [dict({'name': r['name'], 'dir': r['dir'], 'ref': r['ref'], 'n': len(r['data'])},
                      **({'localsteps': r['localsteps']} if r.get('localsteps') else {})) for r in runs],
        'fits': {k: dict({'params5': p5(f), 'se': f['se'], 'chi2': f['chi2'], 'dof': f['dof'], 'chi2_dof': f['chi2_dof'],
                          'kappa_rad': kappas(f), 'corr_nl': f['corr_nl'], 'iterations': f['iterations'],
                          'final_step_sigma': f['final_step_sigma'], 'worst_rung': f['worst_rung']},
                         **({'links': f['links']} if lk else {})) for k, f in fits.items()},
        'f_tests': ftests,
        'cross_validation': {k: {kk: vv for kk, vv in c.items()} for k, c in cv.items()},
        'selection': {'alpha': alpha, 'z_max': Z_MAX, 'steps': steps, 'recommended': rec_kind,
                      'z_rung_max': Z_RUNG,
                      'rungs_beyond_z': [{'run': r['run'], 'lba': r['lba'], 'residual_deg': e * DEG,
                                          'sigma_deg': r['sig'] * DEG, 'z': e / r['sig']} for r, e in big]},
        'app_values': {'model': rec_kind, 'ri': vals[0], 'ro': vals[1], 'c1': vals[2], 'c2': vals[3], 'c3': vals[4],
                       'sectors': s_out, 'frame_change_check': chk},
        'radial_line': {'band': [band_f.ri, band_f.ro], 'ruler_mm': [g[I28], g[I57]], 'bow_range_mm': [g[I30], g[I55]],
                        'own_values': lines, 'own_map_sigma': sig, 'model_maps': model_maps},
        'burn_prediction': burn_res,
    }
    if lk:
        result['links'] = link_res
    if ls_runs:
        result['localsteps'] = {'conversion': 'y = area_angle(16 (k+1)) - area_angle(16 (ref+1)) + radians('
                                              'measured_minus_prior), prior on its own track sectors/75*1200 mm',
                                'runs': [r['name'] for r in ls_runs], 'held_out_in_cv': False}
    if json_path:
        with open(json_path, 'w', encoding='utf-8') as fh:
            json.dump(result, fh, indent=1, ensure_ascii=False)
        out(f'\nJSON written to {json_path}')
    return result


def parse_burn(text):
    v = [float(t) for t in text.split(',')]
    if len(v) not in (2, 5):
        raise SystemExit('--burn takes RI,RO or RI,RO,C1,C2,C3')
    return v + [0.0, 0.0, 0.0] if len(v) == 2 else v


def parse_links(texts):
    """--link LBA (gap fitted) or LBA=G (gap fixed at G mm) -> [(LBA, None | G)]."""
    out = []
    for t in texts:
        k, sep, g = t.partition('=')
        try:
            spec = (int(k), float(g) if sep else None)
        except ValueError:
            raise SystemExit(f'--link {t!r}: expected LBA or LBA=G (G in mm), e.g. 65536 or 65536=0.20')
        if spec[0] <= 0 or (spec[1] is not None and not math.isfinite(spec[1])):
            raise SystemExit(f'--link {t!r}: LBA must be > 0 and G finite')
        if any(spec[0] == o[0] for o in out):
            raise SystemExit(f'--link {spec[0]} given twice')
        out.append(spec)
    return out


def parse_prior(v):
    r0, r1, n = v
    if not (0 < r0 < r1) or n != int(n) or n <= 0:
        raise SystemExit('--localsteps-prior takes R0 R1 SECTORS with 0 < R0 < R1 and an integer sector count')
    return r0, r1, int(n)


def main(argv=None):
    ap = argparse.ArgumentParser(allow_abbrev=False, description='CD read-timing calibration with constant, quadratic '
                                 'and cubic track pitch (the test build\'s DvdTrackGeometry), joint over ladder runs; '
                                 'optional write link gaps (--link) and probe localsteps runs (--localsteps).')
    ap.add_argument('--x', type=float, default=0.0, metavar='BYTES',
                    help='per-drive along-track constant x in bytes (default 0), as calibrate.py --x: the content of file '
                         'byte q lands at the fit-frame angle of q + x; the fit uses q_k = 2352 (k+1) - x')
    ap.add_argument('--sectors', type=int, metavar='N',
                    help='sector count of the burn the printed values are for (default: the probe\'s summary.json in '
                         'the run directories, capacity.sectors_used; else 359845)')
    ap.add_argument('--burn', metavar='RI,RO[,C1,C2,C3]',
                    help='values the measured disc was burned with: print the predicted shape of its straight radial lines')
    ap.add_argument('--burn-sectors', type=int, metavar='N', help='sector count of that burn (default: the fit frame)')
    ap.add_argument('--alpha', type=float, default=0.01, help='F-test level for adding pitch terms (default 0.01)')
    ap.add_argument('--start', metavar='RI,RO', help='start of the constant fit, and with --link of the fit that fixes '
                    'the link geometry; it only seeds them (default ri 24.92 mm and ro for a 1.4865 um pitch over the fit '
                    'track, 57.84 mm at 359845 sectors)')
    ap.add_argument('--json', metavar='PATH', help='also write all results as JSON')
    ap.add_argument('--rungs', metavar='CSV', help='reduced rungs (run,ref_lba,lba,y_rad,sigma_rad) instead of ladder dirs')
    ap.add_argument('--link', action='append', metavar='LBA[=G]',
                    help='write link (repeatable): all content at LBA >= this one lies g mm further along the track '
                         '(HP BU20N at 4x: 65536, g ~ +0.20 mm); g is fitted in every model, one value for all runs (give '
                         'runs of ONE disc only), or fixed with LBA=G (mm). The fit prints g, the radius of the link on '
                         'the fitted spiral and the prewarp.py --link command; the app values stay the smooth spiral')
    ap.add_argument('--localsteps', action='append', metavar='CSV',
                    help='probe localsteps_<ref>.csv (repeatable): one more run with its own kappa, converted with '
                         '--localsteps-prior; never held out in the cross-validation')
    ap.add_argument('--localsteps-prior', type=float, nargs=3, metavar=('R0', 'R1', 'SECTORS'),
                    help='the constant-pitch prior the probe subtracted when it took the localsteps data (default '
                         f'{LOCALSTEPS_PRIOR[0]} {LOCALSTEPS_PRIOR[1]} {LOCALSTEPS_PRIOR[2]}); its own track length '
                         'SECTORS/75*1200 mm is used for the conversion only, never for the fit')
    ap.add_argument('runs', nargs='*', help='ladder output directories (ladder_raw.csv + ladder_rungs.csv)')
    a = ap.parse_args(argv)
    if bool(a.rungs) == bool(a.runs):
        ap.error('give ladder directories or --rungs CSV (one of the two); --localsteps adds runs to either')
    if a.localsteps_prior is not None and not a.localsteps:
        ap.error('--localsteps-prior needs --localsteps')
    links = parse_links(a.link) if a.link else None
    runs = load_rungs_csv(a.rungs) if a.rungs else load_runs(a.runs)
    if a.localsteps:
        prior = parse_prior(a.localsteps_prior) if a.localsteps_prior is not None else LOCALSTEPS_PRIOR
        runs += load_localsteps(a.localsteps, prior, [r['name'] for r in runs])
    start = tuple(float(v) for v in a.start.split(',')) if a.start else None
    if start is not None and len(start) != 2:
        ap.error('--start takes RI,RO')
    report(runs, x=a.x, sectors=a.sectors, burn=parse_burn(a.burn) if a.burn else None, burn_sectors=a.burn_sectors,
           alpha=a.alpha, json_path=a.json, start=start, links=links)


if __name__ == '__main__':
    main()
