// Track models in millimetres and the prior geometry.
interface ITrack
{
    // Cumulative spiral angle (rad) from the start of the track at the completion byte of LBA k, 2352 (k + 1).
    double ThetaOfLba(int lba);

    double RadiusOfLba(int lba);
}

// Thin-spiral form of the app's track model (DvdTrackGeometry): dr/dtheta = b q(x), q = 1 + c1 x + c2 x^2 + c3 x^3,
// x = (r - ri) / (ro - ri), arc ds = r dtheta, angle 0 at ri, b from the track length L = sectors * 16 mm.
// With zero coefficients this is the app's legacy CD formula exactly (r^2 = ri^2 + (ro^2 - ri^2) s / L,
// theta = 2 s / (r + ri)). With coefficients the app integrates the exact polar arc instead; that adds about
// 1e-4 mm of arc over the whole band (about 1e-6 rad), far below anything the probe needs.
sealed class PolyTrack : ITrack
{
    const int Panels = 512;
    static readonly double[] GlX, GlW;
    readonly double[] _f = [], _g = [];  // Int dr/q and Int r dr/q from ri to panel edge k
    readonly double _b;
    readonly bool _constant;

    static PolyTrack() => (GlX, GlW) = GaussLegendre(12);

    public PolyTrack(double ri, double ro, double lengthMm, double c1 = 0, double c2 = 0, double c3 = 0)
    {
        if (!(ri > 0 && ro > ri && lengthMm > ro - ri))
            throw new ArgumentException($"invalid track: need 0 < r0 < r1 (r0={ri}, r1={ro})");
        if (!ShapePositive(c1, c2, c3))
            throw new ArgumentException("1 + c1 x + c2 x^2 + c3 x^3 must stay positive on 0 <= x <= 1");
        Ri = ri;
        Ro = ro;
        LengthMm = lengthMm;
        C1 = c1;
        C2 = c2;
        C3 = c3;
        _constant = c1 == 0 && c2 == 0 && c3 == 0;
        if (_constant)
        {
            _b = (ro - ri) * (ro + ri) / (2 * lengthMm);
            return;
        }

        _f = new double[Panels + 1];
        _g = new double[Panels + 1];
        double h = (ro - ri) / Panels;
        for (int k = 0; k < Panels; k++)
        {
            (double f, double g) = Integrals(ri + k * h, ri + (k + 1) * h);
            _f[k + 1] = _f[k] + f;
            _g[k + 1] = _g[k] + g;
        }

        _b = _g[Panels] / lengthMm;
    }

    public double Ri { get; }
    public double Ro { get; }
    public double LengthMm { get; }
    public double C1 { get; }
    public double C2 { get; }
    public double C3 { get; }
    public bool IsConstant => _constant;

    public double Shape(double r)
    {
        double x = (r - Ri) / (Ro - Ri);
        return 1 + x * (C1 + x * (C2 + x * C3));
    }

    // Local track pitch (mm per turn) at radius r.
    public double PitchMm(double r) => 2 * Math.PI * _b * (_constant ? 1 : Shape(r));

    public double RadiusAtArc(double s)
    {
        s = Math.Clamp(s, 0, LengthMm);
        if (_constant) return Math.Sqrt(Ri * Ri + 2 * _b * s);
        double target = _b * s;
        int lo = 0, hi = Panels;
        while (hi - lo > 1)
        {
            int mid = (lo + hi) / 2;
            if (_g[mid] <= target) lo = mid; else hi = mid;
        }

        double h = (Ro - Ri) / Panels;
        double r = Ri + h * (lo + (target - _g[lo]) / (_g[lo + 1] - _g[lo]));
        for (int it = 0; it < 30; it++)
        {
            double step = (Cumulative(r).G - target) / (r / Shape(r));
            r = Math.Clamp(r - step, Ri, Ro);
            if (Math.Abs(step) <= 1e-14 * r) break;
        }

        return r;
    }

    public double ArcAtRadius(double r)
    {
        r = Math.Clamp(r, Ri, Ro);
        return _constant ? (r - Ri) * (r + Ri) / (2 * _b) : Cumulative(r).G / _b;
    }

    public double AngleAtArc(double s)
    {
        double r = RadiusAtArc(s);
        return _constant ? 2 * Math.Clamp(s, 0, LengthMm) / (r + Ri) : Cumulative(r).F / _b;
    }

    public double ThetaOfLba(int lba) => AngleAtArc(Geometry.SectorMm * (lba + 1.0));

    public double RadiusOfLba(int lba) => RadiusAtArc(Geometry.SectorMm * (lba + 1.0));

    (double F, double G) Cumulative(double r)
    {
        double h = (Ro - Ri) / Panels;
        int k = Math.Clamp((int)((r - Ri) / h), 0, Panels - 1);
        (double f, double g) = Integrals(Ri + k * h, r);
        return (_f[k] + f, _g[k] + g);
    }

    (double F, double G) Integrals(double a, double b)
    {
        double m = 0.5 * (a + b), h = 0.5 * (b - a), f = 0, g = 0;
        for (int i = 0; i < GlX.Length; i++)
        {
            double r = m + h * GlX[i];
            double inv = 1 / Shape(r);
            f += GlW[i] * inv;
            g += GlW[i] * r * inv;
        }

        return (h * f, h * g);
    }

    static bool ShapePositive(double c1, double c2, double c3)
    {
        List<double> xs = [.. Enumerable.Range(0, 257).Select(i => i / 256.0)];
        if (c3 != 0)
        {
            double disc = c2 * c2 - 3 * c1 * c3;
            if (disc >= 0)
            {
                xs.Add((-c2 + Math.Sqrt(disc)) / (3 * c3));
                xs.Add((-c2 - Math.Sqrt(disc)) / (3 * c3));
            }
        }
        else if (c2 != 0) xs.Add(-c1 / (2 * c2));

        return xs.Where(x => x >= 0 && x <= 1).All(x => 1 + x * (c1 + x * (c2 + x * c3)) > 0);
    }

    // n-point Gauss-Legendre nodes and weights on [-1, 1].
    static (double[] X, double[] W) GaussLegendre(int n)
    {
        double[] x = new double[n], w = new double[n];
        for (int i = 0; i < n; i++)
        {
            double z = Math.Cos(Math.PI * (i + 0.75) / (n + 0.5)), dp = 1;
            for (int it = 0; it < 100; it++)
            {
                double p0 = 1, p1 = z;
                for (int k = 1; k < n; k++) (p0, p1) = (p1, ((2 * k + 1) * z * p1 - k * p0) / (k + 1));
                dp = n * (z * p1 - p0) / (z * z - 1);
                double step = p1 / dp;
                z -= step;
                if (Math.Abs(step) < 1e-16) break;
            }

            x[i] = z;
            w[i] = 2 / ((1 - z * z) * dp * dp);
        }

        return (x, w);
    }
}

// The geometry the ladder assumes before it has measured anything, and the radius scale used to place test LBAs:
// either a generic 80-minute value scaled to the sector count, or given values (e.g. the burn values of the probe
// disc, which for a new disc model may be far off). Its uncertainty is deliberately broad: after the first few
// rungs pin the radius at the reference, the r0 prior sets the pitch uncertainty, and an over-confident prior would
// make the ladder step too far and lose a turn.
sealed class Prior
{
    public const double GenericR0 = 24.92, GenericPitchUm = 1.4865;
    public const double DefaultSigmaR0Mm = 0.5, DefaultSigmaPitch = 0.08;

    public Prior(double r0, double r1, double c1, double c2, double c3, int sectors, string source,
        double sigmaR0Mm = DefaultSigmaR0Mm, double sigmaPitch = DefaultSigmaPitch)
    {
        if (sectors < 1_000) throw new ArgumentException($"sector count {sectors} is too small");
        if (!(r0 > 15 && r0 < 35 && r1 > r0 + 5 && r1 < 62))
            throw new ArgumentException($"prior radii r0={r0} r1={r1} mm are not those of a CD (expected about 25 and 58 mm)");
        if (!(sigmaR0Mm > 0 && sigmaPitch > 0)) throw new ArgumentException("prior sigmas must be positive");
        Track = new PolyTrack(r0, r1, sectors * Geometry.SectorMm, c1, c2, c3);
        Sectors = sectors;
        Source = source;
        SigmaR0Mm = sigmaR0Mm;
        SigmaPitch = sigmaPitch;
    }

    public static Prior Generic(int sectors, double sigmaR0Mm = DefaultSigmaR0Mm, double sigmaPitch = DefaultSigmaPitch)
    {
        double r1 = Math.Sqrt(GenericR0 * GenericR0 + GenericPitchUm * 1e-3 * sectors * Geometry.SectorMm / Math.PI);
        return new Prior(GenericR0, r1, 0, 0, 0, sectors,
            $"generic 80-minute value scaled to {sectors} sectors (r0 {GenericR0} mm, pitch {GenericPitchUm} um)", sigmaR0Mm, sigmaPitch);
    }

    public PolyTrack Track { get; }
    public int Sectors { get; }
    public string Source { get; }
    public double SigmaR0Mm { get; }
    public double SigmaPitch { get; }
    public double R0 => Track.Ri;
    public double R1 => Track.Ro;
    public double MeanPitchUm => (R1 - R0) * 2 * Math.PI / Track.AngleAtArc(Track.LengthMm) * 1000;

    public double RadiusOfLba(int lba) => Track.RadiusOfLba(lba);

    // Radius at the end of the last sector.
    public double EndRadius => RadiusOfLba(Sectors - 1);

    // LBA whose completion byte lies nearest to radius r, clamped to the track.
    public int LbaAtRadius(double r) =>
        (int)Math.Clamp(Math.Round(Track.ArcAtRadius(r) / Geometry.SectorMm - 1), 0, Sectors - 1);

    // Constant-pitch spiral with the prior's radius and local pitch at LBA k: identical to the prior when it has
    // constant pitch, its tangent otherwise. The ladder starts from it and keeps it as a weak prior.
    public Geometry Tangent(int lba)
    {
        double r = RadiusOfLba(lba);
        double s = r / Geometry.ByteMm, w = Track.PitchMm(r) / Geometry.ByteMm, p = Geometry.SectorBytes * (lba + 1.0);
        double u2 = s * s - w * p / Math.PI;
        if (!(u2 > 0)) throw new ArgumentException("the prior has no constant-pitch tangent at the reference");
        return new Geometry(Math.Sqrt(u2), w);
    }

    public string Describe() =>
        $"r0={R0:R} r1={R1:R} c1={Track.C1:R} c2={Track.C2:R} c3={Track.C3:R} sectors={Sectors} "
        + $"(mean pitch {MeanPitchUm:F4} um; sigma r0 {SigmaR0Mm} mm, pitch {SigmaPitch * 100:F1} %; {Source})";
}

// --prior r0 r1 [c1 c2 c3] and --prior-sigma mm fraction, parsed and checked before the drive is opened.
sealed record PriorRequest(double[]? Values, double SigmaR0Mm, double SigmaPitch)
{
    public static PriorRequest From(Args a)
    {
        double[]? v = a.Numbers("prior", 2, 5);
        double[]? s = a.Numbers("prior-sigma", 2);
        PriorRequest request = new(v, s?[0] ?? Prior.DefaultSigmaR0Mm, s?[1] ?? Prior.DefaultSigmaPitch);
        request.Build(359_845);  // validates radii, shape and sigmas
        return request;
    }

    public Prior Build(int sectors) => Values is double[] v
        ? new Prior(v[0], v[1], v.Length == 5 ? v[2] : 0, v.Length == 5 ? v[3] : 0, v.Length == 5 ? v[4] : 0, sectors, "--prior", SigmaR0Mm, SigmaPitch)
        : Prior.Generic(sectors, SigmaR0Mm, SigmaPitch);
}
