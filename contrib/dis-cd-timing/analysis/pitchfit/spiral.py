# ---- attribution ------------------------------------------------------------------------------
# Copied on 2026-11-04, unchanged apart from this comment block, from the workflow scratchpad file
#   <scratchpad>/wf3/cubic_py/spiral.py
#   sha256 69805dee91edba6f39457895b4716a1a028fbb749a691057fe237304721618ea (byte-identical copy: analysis/review_checks/spiral.py).
# Origin: workflow wf3, task B ("cubic_py"): independent Python re-implementation of DiscImageStudio.Core.DvdTrackGeometry (exact-arc
# spiral, cubic relative pitch, angle 0 at ri; zero coefficients: closed constant-pitch arc) plus
# area_angle(), the app's legacy CD (area) formula used when all coefficients are zero.
# Validation there: the app's own DvdTrackGeometry.cs, compiled unmodified, agrees with spiral.py to
# |dtheta| <= 1.5e-10 rad and b to 2e-16 relative at the fitted parameters, and gives the same chi2 to 3e-7
# (wf3/cubic_py/cs_crosscheck.json); the C# fit harness wf3/cubic_cs reproduces the fits to ~5e-12 mm.
# Used by analysis/calibrate_pitch.py. Keep the code below identical to the validated source; a fix
# belongs in a new copy that is re-validated against the app.
# -----------------------------------------------------------------------------------------------
"""Independent Python re-implementation of DiscImageStudio.Core.DvdTrackGeometry.

Definitions taken from DvdTrackGeometry.cs (upstream main fb0a598):

  local pitch   dr/dtheta = b * q(x),  q(x) = 1 + c1 x + c2 x^2 + c3 x^3,
                x = (r - ri) / (ro - ri)                         (Shape / Polynomial)
  angle         theta(r) = (1/b) * Int_ri^r dr'/q                (angle starts at 0 at ri)
  arc length    s(r) = Int_ri^r sqrt(1 + z^2) dr',  z = r'/(b q) (exact polar arc, Hypot(1, z))
  scale b       solved so that s(ro) = T exactly (exact arc, not the thin integral; the
                C# 'thin' flag only provides the upper bracket T / Int r/q dr for 1/b)
  AngleAtArcLength(s) = AngleAtRadius(RadiusAtArcLength(s)) = theta(r(s)).
  Zero coefficients: C# uses the closed-form Archimedean arc
                (P(r2) - P(r1)) / b, P(r) = (r sqrt(r^2+b^2) + b^2 asinh(r/b)) / 2,
                and theta = (r - ri)/b.

Own numerics (nothing is ported from the C# code):
  * Gauss-Legendre nodes/weights computed here in 60-digit Decimal and rounded to double.
  * The integrals are split into an exactly known leading part plus a small correction:
      Int dr/q       = (r - ri)          + Int (1/q - 1) dr
      Int r dr/q     = (r-ri)(r+ri)/2    + Int r (1/q - 1) dr
      Int hypot(1,z) = g Int r/q dr      + Int dr/(hypot(1,z) + z),   g = 1/b
    The last term is the exact-minus-thin excess (about 1e-4 mm over the band); it is
    written without cancellation.  Corrections are integrated with adaptive 20-point
    Gauss-Legendre (panel vs. two half panels).
  * g = 1/b solved by fixed point g <- (T - E(g)) / A  (contraction about 2e-11).
  * r(s) by safeguarded Newton with ds/dr = hypot(1, z).
"""
import math
from decimal import Decimal, localcontext

GL_ORDER = 20


def gauss_legendre(n, prec=60):
    """n-point Gauss-Legendre nodes and weights on [-1, 1] as Decimals (Newton on P_n)."""
    nodes, weights = [], []
    with localcontext() as ctx:
        ctx.prec = prec
        eps = Decimal(10) ** (-(prec - 6))
        for i in range(1, n + 1):
            x = Decimal(repr(math.cos(math.pi * (i - 0.25) / (n + 0.5))))
            for _ in range(200):
                p0, p1 = Decimal(1), x
                for k in range(1, n):
                    p0, p1 = p1, ((2 * k + 1) * x * p1 - k * p0) / (k + 1)
                dp = n * (x * p1 - p0) / (x * x - 1)
                dx = p1 / dp
                x -= dx
                if abs(dx) < eps:
                    break
            p0, p1 = Decimal(1), x
            for k in range(1, n):
                p0, p1 = p1, ((2 * k + 1) * x * p1 - k * p0) / (k + 1)
            dp = n * (x * p1 - p0) / (x * x - 1)
            nodes.append(x)
            weights.append(2 / ((1 - x * x) * dp * dp))
    return nodes, weights


_GLD_X, _GLD_W = gauss_legendre(GL_ORDER)
GL_X = [float(v) for v in _GLD_X]
GL_W = [float(v) for v in _GLD_W]
GL_NODES = list(zip(GL_X, GL_W))


class SpiralGeometry:
    """Exact-arc spiral with cubic-in-x pitch shape (same model as DvdTrackGeometry)."""

    def __init__(self, ri, ro, track_length, c1=0.0, c2=0.0, c3=0.0,
                 rel_tol=1e-15, force_numeric=False):
        if not (ri > 0 and ro > ri and track_length > ro - ri):
            raise ValueError("invalid radii / track length")
        self.ri = float(ri)
        self.ro = float(ro)
        self.T = float(track_length)
        self.c1, self.c2, self.c3 = float(c1), float(c2), float(c3)
        self.width = self.ro - self.ri
        self.rel_tol = rel_tol
        self.constant = (c1 == 0 and c2 == 0 and c3 == 0) and not force_numeric
        self.panels = 0
        if not self._shape_positive():
            raise ValueError("1 + c1 x + c2 x^2 + c3 x^3 must stay positive on [0, 1]")
        # Thin (area) integral A = Int_ri^ro r/q dr; exact length L(g) = g*A + E(g).
        _, a_corr, _ = self._corrections(self.ri, self.ro, 1.0)
        self.A_total = 0.5 * (self.ro - self.ri) * (self.ro + self.ri) + a_corr
        g = self.T / self.A_total          # thin solution: an upper bound of the exact g
        self.g_thin = g
        history = []
        for _ in range(60):
            e = self._excess(self.ri, self.ro, g)
            g_new = (self.T - e) / self.A_total
            history.append(g_new)
            if g_new == g or (len(history) > 2 and g_new == history[-3]):
                g = g_new
                break
            g = g_new
        self.g = g
        self.b = 1.0 / g
        self.excess_total = self._excess(self.ri, self.ro, g)

    # ------------------------------------------------------------------ shape
    def shape(self, r):
        x = (r - self.ri) / self.width
        return 1.0 + x * (self.c1 + x * (self.c2 + x * self.c3))

    def _shape_positive(self):
        # dense check plus stationary points of the cubic
        c1, c2, c3 = self.c1, self.c2, self.c3
        pts = [i / 64 for i in range(65)]
        if c3 != 0:
            disc = c2 * c2 - 3 * c1 * c3
            if disc >= 0:
                for sgn in (-1, 1):
                    pts.append((-c2 + sgn * math.sqrt(disc)) / (3 * c3))
        elif c2 != 0:
            pts.append(-c1 / (2 * c2))
        return all(1 + x * (c1 + x * (c2 + x * c3)) > 0 for x in pts if 0 <= x <= 1)

    # ------------------------------------------------------- one GL panel
    def _panel(self, a, b, g):
        """Returns (Int (1/q-1), Int r(1/q-1), Int 1/(hypot(1,z)+z)) over [a, b]."""
        self.panels += 1
        m = 0.5 * (a + b)
        h = 0.5 * (b - a)
        ri, w_inv = self.ri, 1.0 / self.width
        c1, c2, c3 = self.c1, self.c2, self.c3
        sp = sa = se = 0.0
        hyp = math.hypot
        for t, w in GL_NODES:
            r = m + h * t
            x = (r - ri) * w_inv
            poly = x * (c1 + x * (c2 + x * c3))
            q = 1.0 + poly
            d = -poly / q                 # 1/q - 1, no cancellation
            z = g * r / q
            sp += w * d
            sa += w * (r * d)
            se += w / (hyp(1.0, z) + z)
        return h * sp, h * sa, h * se

    def _adaptive(self, a, b, g, depth, whole):
        m = 0.5 * (a + b)
        left = self._panel(a, m, g)
        right = self._panel(m, b, g)
        split = (left[0] + right[0], left[1] + right[1], left[2] + right[2])
        span = b - a
        # tolerances relative to the full quantities each correction belongs to
        tol_p = self.rel_tol * span
        tol_a = self.rel_tol * span * max(abs(a), abs(b))
        tol_e = 1e-14 * abs(split[2]) + 1e-300
        if ((abs(split[0] - whole[0]) <= tol_p and abs(split[1] - whole[1]) <= tol_a
             and abs(split[2] - whole[2]) <= tol_e) or depth >= 40 or m == a or m == b):
            return split
        l2 = self._adaptive(a, m, g, depth + 1, left)
        r2 = self._adaptive(m, b, g, depth + 1, right)
        return (l2[0] + r2[0], l2[1] + r2[1], l2[2] + r2[2])

    def _corrections(self, a, b, g):
        if a == b:
            return 0.0, 0.0, 0.0
        if self.constant:
            return 0.0, 0.0, self._excess_closed(a, b, g)
        return self._adaptive(a, b, g, 0, self._panel(a, b, g))

    # exact-minus-thin arc excess, closed form for constant pitch
    @staticmethod
    def _f_excess(z):
        return z / (math.sqrt(1.0 + z * z) + z) + math.asinh(z)

    def _excess_closed(self, a, b, g):
        return (self._f_excess(g * b) - self._f_excess(g * a)) / (2.0 * g)

    def _excess(self, a, b, g):
        if self.constant:
            return self._excess_closed(a, b, g)
        return self._corrections(a, b, g)[2]

    # --------------------------------------------------------- public API
    def arc_and_angle_at_radius(self, r):
        """(s(r), theta(r)) with s measured from ri along the exact arc."""
        p_corr, a_corr, e = self._corrections(self.ri, r, self.g)
        dr = r - self.ri
        s = self.g * (0.5 * dr * (r + self.ri) + a_corr) + e
        theta = self.g * (dr + p_corr)
        return s, theta

    def angle_at_radius(self, r):
        return self.arc_and_angle_at_radius(r)[1]

    def radius_at_arc(self, s):
        """Inverse of s(r) on [ri, ro] by safeguarded Newton (ds/dr = hypot(1, z))."""
        if s <= 0:
            return self.ri, 0
        if s >= self.T:
            return self.ro, 0
        g, ri, ro = self.g, self.ri, self.ro
        r = math.sqrt(ri * ri + 2.0 * s / g)     # thin constant-pitch first guess
        r = min(max(r, ri), ro)
        lo, hi = ri, ro
        it = 0
        for it in range(1, 60):
            s_r, _ = self.arc_and_angle_at_radius(r)
            err = s_r - s
            if err > 0:
                hi = min(hi, r)
            else:
                lo = max(lo, r)
            z = g * r / self.shape(r)
            step = err / math.hypot(1.0, z)
            r_new = r - step
            if not (lo <= r_new <= hi):
                r_new = 0.5 * (lo + hi)
            if r_new == r or abs(r_new - r) <= 2e-16 * r:
                r = r_new
                break
            r = r_new
        return r, it

    def angle_at_arc(self, s):
        """AngleAtArcLength(s): cumulative spiral angle (rad) at arc length s (mm)."""
        r, _ = self.radius_at_arc(s)
        return self.angle_at_radius(r)

    def radius_and_angle_at_arc(self, s):
        r, _ = self.radius_at_arc(s)
        return r, self.angle_at_radius(r)

    @property
    def total_angle(self):
        return self.angle_at_radius(self.ro)

    @property
    def pitch_mm(self):
        return 2 * math.pi * self.b


def area_angle(s, ri, ro, T):
    """App CD path (CalibrationGeometry, non-DVD): r^2 = ri^2 + (ro^2-ri^2) s/T,
    theta = (r - ri)/b, b = (ro^2-ri^2)/(2T)  ==  2 s / (r + ri)."""
    r = math.sqrt(ri * ri + (ro - ri) * (ro + ri) * (s / T))
    return 2.0 * s / (r + ri)


def area_radius(s, ri, ro, T):
    return math.sqrt(ri * ri + (ro - ri) * (ro + ri) * (s / T))
