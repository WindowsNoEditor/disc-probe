using System.Diagnostics;

// Spiral of the app's CD model in units of one app byte along the track (1.2 m/s, 75 sectors/s):
// S(p) = sqrt(u^2 + w p / pi) is the radius in bytes, Theta(p) = 2p / (S + u) the cumulative angle.
sealed record Geometry(double U, double W) : ITrack
{
    public const double ByteMm = 1200.0 / (75 * 2352);
    public const int SectorBytes = 2352;
    public const double SectorMm = 1200.0 / 75;  // 16 mm of track per sector

    public static Geometry FromRadii(double r0, double r1, double sectors)
    {
        double length = ByteMm * sectors * SectorBytes;
        double pitch = Math.PI * (r1 * r1 - r0 * r0) / length;
        return new Geometry(r0 / ByteMm, pitch / ByteMm);
    }

    double S(double p) => Math.Sqrt(U * U + W * p / Math.PI);
    public double Theta(double p) => 2 * p / (S(p) + U);
    public double ThetaOfLba(int lba) => Theta(SectorBytes * (lba + 1.0));
    public double RadiusMm(double p) => ByteMm * S(p);
    public double RadiusOfLba(int lba) => RadiusMm(SectorBytes * (lba + 1.0));
    public double R0 => U * ByteMm;
    public double R1(double sectors) => RadiusMm(sectors * SectorBytes);
    public double PitchUm => W * ByteMm * 1000;

    // d Theta / d(u, w) at byte p.
    public (double Du, double Dw) Grad(double p)
    {
        double s = S(p);
        return (-2 * p / (s * (s + U)), -p * p / (Math.PI * s * (s + U) * (s + U)));
    }

    public (double Du, double Dw) GradLba(int lba) => Grad(SectorBytes * (lba + 1.0));

    // Inverse of ThetaOfLba by bisection on [lo, hi].
    public int LbaForTheta(double theta, int lo, int hi)
    {
        while (hi - lo > 1)
        {
            int mid = (lo + hi) / 2;
            if (ThetaOfLba(mid) < theta) lo = mid; else hi = mid;
        }

        return lo;
    }

    // Largest LBA in [0, last] whose completion radius is below radiusMm.
    public int LbaAtRadius(double radiusMm, int last)
    {
        int lo = 0, hi = last;
        while (hi - lo > 1)
        {
            int mid = (lo + hi) / 2;
            if (RadiusOfLba(mid) < radiusMm) lo = mid; else hi = mid;
        }

        return lo;
    }
}

interface ITimedReader
{
    double NowMs { get; }

    // Cache-defeating far read, a wait, then one timed single-sector read of lba.
    (double CompletionMs, double DurationMs, bool Ok) Read(int lba, double waitMs);
}

static class Seek
{
    // Cache-defeating far read: a third of the track away, toward the middle (about 120 000 sectors on 80 minutes).
    public static int Far(int lba, int sectors) => lba < sectors / 2 ? lba + sectors / 3 : lba - sectors / 3;
}

sealed class DriveReader(Drive drive, int sectors) : ITimedReader
{
    public double NowMs => Stopwatch.GetTimestamp() * Drive.UsPerTick / 1000;

    public (double, double, bool) Read(int lba, double waitMs)
    {
        Program.ReadCdPublic(drive, Seek.Far(lba, sectors));
        Program.SpinWaitPublic(waitMs * 1000);
        Program.ReadCdPublic(drive, lba);
        return (drive.T1 * Drive.UsPerTick / 1000, drive.ElapsedUs / 1000, drive.Ok);
    }
}

sealed record Rung(int Index, int Target, double TurnsGuess, double DeltaWrapped, double Sigma, double Unwrapped,
    double Predicted, double Period, int Used, int Rejected);

sealed class LadderRun
{
    // Band limits as fractions of the sector count: LBA 4500 and 356500 of 359845 on an 80-minute disc (about 25.6 and
    // 57.7 mm). They scale with the capacity read from the disc and, being LBAs, do not depend on the prior.
    public const double InnerFraction = 4_500.0 / 359_845, OuterFraction = 356_500.0 / 359_845;
    public const double ReferenceRadiusMm = 40.0;
    const double MaxPredictedSigma = 25 * Math.PI / 180;

    // Prior width of the constant phase kappa of the fit. Every X - R difference carries the same constant: the model
    // error at the reference radius, or a read anomaly of the reference sector itself; without kappa it would bend
    // (u, w) and corrupt every prediction (spec 3.4).
    const double KappaPriorSigma = 10 * Math.PI / 180;

    readonly ITimedReader _reader;
    readonly Random _rng;
    readonly int _pairs;
    readonly Geometry _prior;
    readonly double _priorSigmaU, _priorSigmaW;
    readonly List<string> _raw = ["rung,role,lba,completion_ms,duration_ms,ok"];
    readonly List<string> _rejected = ["attempt,target,reason,role,lba,completion_ms,duration_ms,ok"];
    readonly Action<string> _log;
    readonly double[,] _planCov = new double[3, 3];
    double _period;
    int _attempts;

    public LadderRun(ITimedReader reader, Prior prior, int reference, double periodGuessMs, int pairs, int seed, Action<string> log)
    {
        Sectors = prior.Sectors;
        InnerLimit = InnerLimitFor(Sectors);
        OuterLimit = OuterLimitFor(Sectors);
        CheckReference(reference, Sectors);
        Reference = reference;
        Prior = prior;
        _prior = prior.Tangent(reference);
        _priorSigmaU = prior.SigmaR0Mm / Geometry.ByteMm;
        _priorSigmaW = prior.SigmaPitch * _prior.W;
        _reader = reader;
        Fit = _prior;
        _period = periodGuessMs;
        _pairs = pairs;
        ConfirmPairs = Math.Max(8, pairs / 2);
        _rng = new Random(seed);
        _log = log;
        Covariance[0, 0] = _planCov[0, 0] = _priorSigmaU * _priorSigmaU;
        Covariance[1, 1] = _planCov[1, 1] = _priorSigmaW * _priorSigmaW;
        Covariance[2, 2] = _planCov[2, 2] = KappaPriorSigma * KappaPriorSigma;
    }

    // A rung whose prediction is looser than this (deg) is confirmed by the next sector before it is used: the
    // prediction cannot tell a local read anomaly from its own error there, and such a rung (the first one, the
    // extension rungs) steers the next long step, where a few degrees of error grow into a lost turn.
    public double ConfirmAboveDeg { get; init; } = 1.0;

    // Per-rung systematic allowance (deg) in the covariance the planner steps with (not in the fit): small undetected
    // errors (model error, anomalies below the confirmation tolerance) cannot then be amplified into a lost turn.
    public double PlanFloorDeg { get; init; } = 0.5;

    // Pairs for the confirming sectors (the second to fourth of a rung): enough to see a 1 deg disagreement at half the cost.
    public int ConfirmPairs { get; init; }

    public static int InnerLimitFor(int sectors) => (int)Math.Round(sectors * InnerFraction);
    public static int OuterLimitFor(int sectors) => (int)Math.Round(sectors * OuterFraction);

    public static void CheckReference(int reference, int sectors)
    {
        if (reference < InnerLimitFor(sectors) + 1_000 || reference > OuterLimitFor(sectors) - 1_000)
            throw new ArgumentException($"reference LBA {reference} is outside the ladder band {InnerLimitFor(sectors)}..{OuterLimitFor(sectors)} of {sectors} sectors");
    }

    // Reference near 40 mm on the prior's radius scale.
    public static int DefaultReference(Prior prior) => prior.LbaAtRadius(ReferenceRadiusMm);

    public int Reference { get; }
    public int Sectors { get; }
    public int InnerLimit { get; }
    public int OuterLimit { get; }
    public Prior Prior { get; }
    public Geometry Start => _prior;
    public List<Rung> Rungs { get; } = [];
    public Geometry Fit { get; private set; }
    public double Kappa { get; private set; }

    // Covariance of (u, w, kappa) of the fit.
    public double[,] Covariance { get; private set; } = new double[3, 3];
    public int Attempts => _attempts;
    public int Confirmed { get; private set; }
    public int Remeasured { get; private set; }
    public int Skipped { get; private set; }
    public double MaxAbsMissDeg { get; private set; }
    public double Period => _period;
    public IReadOnlyList<string> Raw => _raw;
    public IReadOnlyList<string> RejectedRaw => _rejected;

    public bool Run()
    {
        _log($"band LBA {InnerLimit}..{OuterLimit} of {Sectors} (prior {Prior.RadiusOfLba(InnerLimit):F2}..{Prior.RadiusOfLba(OuterLimit):F2} mm), "
            + $"reference LBA {Reference} (prior {Prior.RadiusOfLba(Reference):F3} mm); start r0={Fit.R0:F6} r1={Fit.R1(Sectors):F6} "
            + $"(prior sigma r0 {Prior.SigmaR0Mm} mm, pitch {Prior.SigmaPitch * 100:F1} %)");
        double sectorsPerTurn = 2 * Math.PI * Fit.RadiusOfLba(Reference) / Geometry.SectorMm;
        foreach (double turns in new[] { 0.5, -0.5, 1.5, -1.5, 4, -4 })
        {
            if (!Measure((int)Math.Round(Reference + turns * sectorsPerTurn), turns)) return false;
        }

        if (Rungs.Count < 4)
        {
            _log($"ABORT: only {Rungs.Count} of the 6 bootstrap rungs are usable.");
            return false;
        }

        // Extend outward and inward while the predicted angle uncertainty stays below 25 deg.
        int outer = Rungs.Max(r => r.Target), inner = Rungs.Min(r => r.Target);
        while (outer < OuterLimit || inner > InnerLimit)
        {
            if (outer < OuterLimit)
            {
                outer = FarthestSafe(outer, OuterLimit);
                if (!Measure(outer, double.NaN)) return false;
            }

            if (inner > InnerLimit)
            {
                inner = FarthestSafe(inner, InnerLimit);
                if (!Measure(inner, double.NaN)) return false;
            }
        }

        // Fill the band every 2 mm for residual structure (26 ... 56 mm on an 80-minute disc).
        double last = Fit.RadiusOfLba(OuterLimit) - 1.0;
        for (double r = Math.Ceiling(Fit.RadiusOfLba(InnerLimit)); r <= last; r += 2)
        {
            int lba = Fit.LbaAtRadius(r, Sectors - 1);
            if (Rungs.Any(x => Math.Abs(x.Target - lba) < 2000)) continue;
            if (!Measure(lba, double.NaN)) return false;
        }

        return true;
    }

    int FarthestSafe(int from, int limit)
    {
        // Largest step (in the direction of limit) whose predicted sigma stays below the bound.
        int dir = Math.Sign(limit - from);
        int best = from + dir * 50;
        for (double frac = 1.0; frac > 0.0005; frac *= 0.8)
        {
            int candidate = from + (int)Math.Round((limit - from) * frac);
            if (PredictedSigma(candidate) < MaxPredictedSigma)
            {
                best = candidate;
                break;
            }
        }

        return Math.Clamp(best, Math.Min(from, limit), Math.Max(from, limit));
    }

    // Prediction uncertainty the planner steps with: planning covariance plus a 0.5 deg model floor.
    double PredictedSigma(int target) => Math.Sqrt(Variance(_planCov, target) + Math.Pow(0.5 * Math.PI / 180, 2));

    // Statistical prediction uncertainty of the fit alone.
    double PredictedSigmaStat(int target) => Math.Sqrt(Variance(Covariance, target));

    double Variance(double[,] c, int target)
    {
        (double du, double dw) = Diff(Fit, target);
        double[] j = [du, dw, 1];
        double var = 0;
        for (int p = 0; p < 3; p++)
            for (int q = 0; q < 3; q++) var += j[p] * c[p, q] * j[q];
        return Math.Max(var, 0);
    }

    (double Du, double Dw) Diff(Geometry g, int target)
    {
        (double xu, double xw) = g.GradLba(target);
        (double ru, double rw) = g.GradLba(Reference);
        return (xu - ru, xw - rw);
    }

    sealed record Attempt(int Number, int Target, double Delta, double Sigma, double Period, int Used, int Rejected,
        double Predicted, double Unwrapped, double MissDeg, List<string> Rows);

    // A sector whose own phase is this uncertain cannot vote: a wide sigma would make anything look consistent.
    const double PreciseSigma = 0.6 * Math.PI / 180;
    const int MaxSectorsPerRung = 4;

    static bool Precise(Attempt a) => a.Sigma <= PreciseSigma;

    static bool Consistent(Attempt a, Attempt b) =>
        Precise(a) && Precise(b)
        && Math.Abs(a.MissDeg - b.MissDeg) <= Math.Max(4 * Math.Sqrt(a.Sigma * a.Sigma + b.Sigma * b.Sigma) * 180 / Math.PI, 1.0);

    // One rung, checked before anything of it can enter the fit (spec 4.4, A4/A5). Every sector's miss is taken against
    // the same fit.
    // - |miss| > 90 deg on any sector: abort (turn ambiguity); nothing of the rung is used.
    // - Tight prediction (sigma_pred <= ConfirmAboveDeg) and |miss| within the limit: used. The limit is
    //   max(5 sigma_pred, 3 deg); for the bootstrap rungs, within 4 turns of the reference where the model error is
    //   negligible, max(4 sqrt(sigma_fit^2 + sigma_rung^2), 1 deg), because their short lever turns a few degrees into
    //   a large radius error at the reference.
    // - Otherwise the next sectors are measured (up to 4 sectors in all, the extra ones with ConfirmPairs) until two
    //   precise sectors agree with each other: both are used. Under a loose prediction this is the confirmation; under a
    //   tight one it means the prediction was off (model or prior), and skipping would starve the fit where it needs
    //   data. Under a tight prediction a precise sector that meets it also settles the rung (the sectors before it were
    //   local read anomalies; seen: -6 deg at one LBA of disc 5). With no such outcome the rung is skipped.
    // Rows of sectors that are not used go to ladder_rejected.csv, so ladder_raw.csv holds exactly the rungs of
    // ladder_rungs.csv.
    bool Measure(int target, double turnsGuess)
    {
        bool bootstrap = !double.IsNaN(turnsGuess);
        double sigmaPred = PredictedSigma(target) * 180 / Math.PI, sigmaStat = PredictedSigmaStat(target) * 180 / Math.PI;
        double Limit(Attempt a) => bootstrap
            ? Math.Max(4 * Math.Sqrt(sigmaStat * sigmaStat + Math.Pow(a.Sigma * 180 / Math.PI, 2)), 1.0)
            : Math.Max(5 * sigmaPred, 3.0);
        bool loose = (bootstrap ? sigmaStat : sigmaPred) > ConfirmAboveDeg;
        List<Attempt> got = [];
        for (int k = 0; k < MaxSectorsPerRung; k++)
        {
            Attempt? a = Sample(target + k, k == 0 ? 0 : ConfirmPairs);
            if (a is null || Math.Abs(a.MissDeg) > 90)
            {
                foreach (Attempt g in got) Reject(g, "superseded");
                return a is null ? Unusable(target + k) : Ambiguous(a);
            }

            got.Add(a);
            if (k == 0)
            {
                bool outlier = Math.Abs(a.MissDeg) > Limit(a);
                if (!loose && !outlier) return Accept([a], turnsGuess, "");
                if (outlier)
                {
                    Remeasured++;
                    _log($"rung {Rungs.Count}: lba {target} misses the prediction by {a.MissDeg:F2} deg (limit {Limit(a):F2}); measuring lba {target + 1}");
                }
                else Confirmed++;
                continue;
            }

            for (int i = 0; i < got.Count - 1; i++)
            {
                if (!Consistent(got[i], a)) continue;
                string note = loose ? "  [confirmed by the next sector]" : "  [the sectors agree: the prediction was off]";
                Attempt keep = got[i];
                foreach (Attempt g in got.Where(g => !ReferenceEquals(g, keep) && !ReferenceEquals(g, a)))
                {
                    Reject(g, "local-anomaly");
                    note += $"  [lba {g.Target} ({g.MissDeg:F2} deg, sigma {g.Sigma * 180 / Math.PI:F2}) disagreed: not used]";
                }

                return Accept([keep, a], turnsGuess, note);
            }

            if (!loose && Precise(a) && Math.Abs(a.MissDeg) <= Limit(a))
            {
                foreach (Attempt g in got.Take(got.Count - 1)) Reject(g, "local-anomaly");
                return Accept([a], turnsGuess, $"  [lba {target}..{a.Target - 1} missed the prediction: local read anomaly, not used]");
            }

            if (k < MaxSectorsPerRung - 1)
                _log($"rung {Rungs.Count}: no agreeing pair yet ({string.Join(", ", got.Select(g => $"lba {g.Target} {g.MissDeg:F2} +- {g.Sigma * 180 / Math.PI:F2} deg"))}); measuring lba {target + k + 1}");
        }

        Skipped++;
        foreach (Attempt g in got) Reject(g, "inconsistent");
        _log($"rung {Rungs.Count}: lba {target}..{target + MaxSectorsPerRung - 1} found no agreeing pair; skipped");
        return true;
    }

    Attempt? Sample(int target, int pairs = 0)
    {
        int number = _attempts++;
        List<(bool IsRef, double Tc, double Dur, bool Ok)> samples = [];
        List<string> rows = [];
        for (int k = 0; k < (pairs > 0 ? pairs : _pairs); k++)
        {
            foreach (bool isRef in new[] { true, false })
            {
                int lba = isRef ? Reference : target;
                (double tc, double dur, bool ok) = _reader.Read(lba, _rng.NextDouble() * 1.2 * _period);
                samples.Add((isRef, tc, dur, ok));
                rows.Add($"{(isRef ? "R" : "X")},{lba},{tc:F5},{dur:F4},{(ok ? 1 : 0)}");
            }
        }

        (double delta, double sigma, double period, int used, int rejected) = EstimateDelta(samples);
        if (double.IsNaN(delta))
        {
            foreach (string row in rows) _rejected.Add($"{number},{target},unusable,{row}");
            return null;
        }

        _period = period;
        double predicted = Fit.ThetaOfLba(target) - Fit.ThetaOfLba(Reference) + Kappa;
        double wraps = Math.Round((predicted - delta) / (2 * Math.PI));
        double unwrapped = delta + 2 * Math.PI * wraps;
        return new Attempt(number, target, delta, sigma, period, used, rejected, predicted, unwrapped, (unwrapped - predicted) * 180 / Math.PI, rows);
    }

    bool Accept(Attempt[] attempts, double turnsGuess, string note)
    {
        int first = Rungs.Count;
        foreach (Attempt a in attempts)
        {
            int index = Rungs.Count;
            Rungs.Add(new Rung(index, a.Target, turnsGuess, a.Delta, a.Sigma, a.Unwrapped, a.Predicted, a.Period, a.Used, a.Rejected));
            foreach (string row in a.Rows) _raw.Add($"{index},{row}");
            MaxAbsMissDeg = Math.Max(MaxAbsMissDeg, Math.Abs(a.MissDeg));
        }

        Refit();
        for (int i = 0; i < attempts.Length; i++)
        {
            Attempt a = attempts[i];
            _log($"rung {first + i,2}: lba {a.Target,6} r={Fit.RadiusOfLba(a.Target):F2} mm turns={a.Unwrapped / (2 * Math.PI),10:F3} "
                + $"sigma={a.Sigma * 180 / Math.PI:F3} deg miss-vs-prediction={a.MissDeg,8:F2} deg used={a.Used} rejected={a.Rejected} period={a.Period:F5} ms "
                + $"-> r0={Fit.R0:F6} r1={Fit.R1(Sectors):F6}{(i == attempts.Length - 1 ? note : "")}");
        }

        return true;
    }

    void Reject(Attempt a, string reason)
    {
        foreach (string row in a.Rows) _rejected.Add($"{a.Number},{a.Target},{reason},{row}");
    }

    bool Ambiguous(Attempt a)
    {
        Reject(a, "ambiguous");
        MaxAbsMissDeg = Math.Max(MaxAbsMissDeg, Math.Abs(a.MissDeg));
        _log($"rung {Rungs.Count}: lba {a.Target} r={Fit.RadiusOfLba(a.Target):F2} mm misses the prediction by {a.MissDeg:F2} deg (not used)");
        _log("ABORT: measurement disagrees with the prediction by more than 90 deg (turn ambiguity).");
        return false;
    }

    bool Unusable(int target)
    {
        _log($"rung {Rungs.Count}: target {target} unusable");
        return false;
    }

    (double Delta, double Sigma, double Period, int Used, int Rejected) EstimateDelta(List<(bool IsRef, double Tc, double Dur, bool Ok)> samples)
    {
        var refs = samples.Where(s => s.IsRef && s.Ok && s.Dur > 8.5).Select(s => s.Tc).ToList();
        var xs = samples.Where(s => !s.IsRef && s.Ok && s.Dur > 8.5).Select(s => s.Tc).ToList();
        int cacheLike = samples.Count(s => s.Ok && s.Dur <= 8.5);
        if (refs.Count < 6 || xs.Count < 6) return (double.NaN, 0, _period, 0, cacheLike);

        // Refine the period from the reference completions (all congruent modulo one revolution),
        // dropping late outliers (sporadic 2-3 ms host/USB delays) from the reference set too.
        double period = _period, mean = 0;
        List<double> allRefs = refs;
        for (int pass = 0; pass < 3; pass++)
        {
            double best = -1;
            for (double p = _period * 0.999; p <= _period * 1.001; p += _period * 2e-6)
            {
                double c = Coherence(refs, p);
                if (c > best) { best = c; period = p; }
            }

            // Centre on the median so late outliers cannot pull the centre or inflate the spread.
            double m0 = CircularMean(allRefs.Select(t => 2 * Math.PI * t / period));
            double[] off0 = allRefs.Select(t => Wrap(2 * Math.PI * t / period - m0)).Order().ToArray();
            m0 += off0[off0.Length / 2];
            double[] dev0 = allRefs.Select(t => Math.Abs(Wrap(2 * Math.PI * t / period - m0))).Order().ToArray();
            double lim = Math.Max(4 * Math.Max(dev0[dev0.Length / 2] * 1.4826, 0.15 * Math.PI / 180), 1.5 * Math.PI / 180);
            refs = allRefs.Where(t => Math.Abs(Wrap(2 * Math.PI * t / period - m0)) <= lim).ToList();
            mean = CircularMean(refs.Select(t => 2 * Math.PI * t / period));
        }

        cacheLike += allRefs.Count - refs.Count;
        // Reference phase residuals with a linear trend absorb slow spindle drift inside the rung.
        double tMid = refs.Average();
        double[] resid = refs.Select(t => Wrap(2 * Math.PI * t / period - mean)).ToArray();
        double[] dt = refs.Select(t => t - tMid).ToArray();
        double sxx = dt.Sum(v => v * v), sxy = dt.Zip(resid, (a, b) => a * b).Sum();
        double slope = sxx > 0 ? sxy / sxx : 0, intercept = resid.Average();

        List<double> deltas = xs.Select(t => Wrap(2 * Math.PI * t / period - (mean + intercept + slope * (t - tMid)))).ToList();
        double d = CircularMean(deltas);
        double[] offsets = deltas.Select(v => Wrap(v - d)).Order().ToArray();
        d += offsets[offsets.Length / 2];
        List<double> dev = deltas.Select(v => Math.Abs(Wrap(v - d))).Order().ToList();
        double robust = Math.Max(dev[dev.Count / 2] * 1.4826, 0.2 * Math.PI / 180);
        List<double> kept = deltas.Where(v => Math.Abs(Wrap(v - d)) <= 4 * robust).ToList();
        d = CircularMean(kept);
        double sd = Math.Sqrt(kept.Sum(v => Math.Pow(Wrap(v - d), 2)) / Math.Max(1, kept.Count - 1));
        double refSd = Math.Sqrt(resid.Zip(dt, (r, x) => Math.Pow(r - intercept - slope * x, 2)).Sum() / Math.Max(1, resid.Length - 2));
        double sigma = Math.Sqrt(sd * sd / kept.Count + refSd * refSd / resid.Length);
        return (d, sigma, period, kept.Count, cacheLike + deltas.Count - kept.Count);
    }

    void Refit()
    {
        double u = Fit.U, w = Fit.W, kappa = Kappa;
        for (int iter = 0; iter < 30; iter++)
        {
            Geometry g = new(u, w);
            // Normal equations in (u, w, kappa) with a weak prior around the starting geometry and kappa = 0.
            double[,] a = PriorInformation();
            double[] b = [(_prior.U - u) * a[0, 0], (_prior.W - w) * a[1, 1], -kappa * a[2, 2]];
            foreach (Rung r in Rungs)
            {
                (double ju, double jw) = Diff(g, r.Target);
                double wt = 1 / (r.Sigma * r.Sigma + Math.Pow(0.05 * Math.PI / 180, 2));
                double res = r.Unwrapped - (g.ThetaOfLba(r.Target) - g.ThetaOfLba(Reference) + kappa);
                Accumulate(a, b, ju, jw, wt, res);
            }

            double[,] inv = InvertSym3(a);
            double du = inv[0, 0] * b[0] + inv[0, 1] * b[1] + inv[0, 2] * b[2];
            double dw = inv[1, 0] * b[0] + inv[1, 1] * b[1] + inv[1, 2] * b[2];
            double dk = inv[2, 0] * b[0] + inv[2, 1] * b[1] + inv[2, 2] * b[2];
            u += du;
            w += dw;
            kappa += dk;
            Covariance = inv;
            if (Math.Abs(du) < 1e-10 && Math.Abs(dw) < 1e-13 && Math.Abs(dk) < 1e-12) break;
        }

        Fit = new Geometry(u, w);
        Kappa = kappa;

        // The planner's covariance: the same normal equations with the per-rung allowance PlanFloorDeg.
        double floor = Math.Max(PlanFloorDeg, 0.05) * Math.PI / 180;
        double[,] pa = PriorInformation();
        foreach (Rung r in Rungs)
        {
            (double ju, double jw) = Diff(Fit, r.Target);
            Accumulate(pa, null, ju, jw, 1 / (r.Sigma * r.Sigma + floor * floor), 0);
        }

        double[,] pinv = InvertSym3(pa);
        for (int i = 0; i < 3; i++)
            for (int j = 0; j < 3; j++) _planCov[i, j] = pinv[i, j];
    }

    double[,] PriorInformation()
    {
        double[,] a = new double[3, 3];
        a[0, 0] = 1 / (_priorSigmaU * _priorSigmaU);
        a[1, 1] = 1 / (_priorSigmaW * _priorSigmaW);
        a[2, 2] = 1 / (KappaPriorSigma * KappaPriorSigma);
        return a;
    }

    static void Accumulate(double[,] a, double[]? b, double ju, double jw, double wt, double res)
    {
        double[] j = [ju, jw, 1];
        for (int p = 0; p < 3; p++)
        {
            if (b is not null) b[p] += wt * j[p] * res;
            for (int q = 0; q < 3; q++) a[p, q] += wt * j[p] * j[q];
        }
    }

    // Inverse of a symmetric positive definite 3x3 matrix, by cofactors after scaling to a unit diagonal.
    static double[,] InvertSym3(double[,] a)
    {
        double[] d = [1 / Math.Sqrt(a[0, 0]), 1 / Math.Sqrt(a[1, 1]), 1 / Math.Sqrt(a[2, 2])];
        double s01 = a[0, 1] * d[0] * d[1], s02 = a[0, 2] * d[0] * d[2], s12 = a[1, 2] * d[1] * d[2];
        double[,] c =
        {
            { 1 - s12 * s12, s02 * s12 - s01, s01 * s12 - s02 },
            { s02 * s12 - s01, 1 - s02 * s02, s01 * s02 - s12 },
            { s01 * s12 - s02, s01 * s02 - s12, 1 - s01 * s01 },
        };
        double det = c[0, 0] + s01 * c[0, 1] + s02 * c[0, 2];
        double[,] inv = new double[3, 3];
        for (int i = 0; i < 3; i++)
            for (int j = 0; j < 3; j++) inv[i, j] = c[i, j] / det * d[i] * d[j];
        return inv;
    }

    public double ChiSquarePerDof() => Rungs.Sum(r => Math.Pow(Residual(r) / r.Sigma, 2)) / Math.Max(1, Rungs.Count - 3);

    // Residual against the fit, kappa included.
    public double Residual(Rung r) => r.Unwrapped - (Fit.ThetaOfLba(r.Target) - Fit.ThetaOfLba(Reference) + Kappa);

    static double Coherence(List<double> t, double period)
    {
        double sx = 0, sy = 0;
        foreach (double v in t)
        {
            double a = 2 * Math.PI * v / period;
            sx += Math.Cos(a);
            sy += Math.Sin(a);
        }

        return Math.Sqrt(sx * sx + sy * sy) / t.Count;
    }

    static double CircularMean(IEnumerable<double> angles)
    {
        double sx = 0, sy = 0;
        foreach (double a in angles) { sx += Math.Cos(a); sy += Math.Sin(a); }
        return Math.Atan2(sy, sx);
    }

    static double Wrap(double a) => Math.IEEERemainder(a, 2 * Math.PI);
}

sealed record LadderOutcome(bool Completed, LadderRun? Run, int Reference, int SpeedHex, int Pairs, double SettlePeriodMs,
    double SettleCoherence, double SettleScatterDeg, double Minutes, string Status);

static partial class Program
{
    public static int ReadCdPublic(Drive d, int lba) => ReadCd(d, lba);
    public static void SpinWaitPublic(double us) => SpinWaitUs(us);

    // Turns that a straight spoke burned with the 'burn' model winds between the reference and LBA k, if 'disc' is
    // where the sectors really are (fit minus prior, both taken relative to the reference).
    static double TwistTurns(ITrack disc, ITrack burn, int reference, int lba) =>
        (disc.ThetaOfLba(lba) - disc.ThetaOfLba(reference) - (burn.ThetaOfLba(lba) - burn.ThetaOfLba(reference))) / (2 * Math.PI);

    static void ReportFit(LadderRun run, string name)
    {
        Geometry g = run.Fit;
        int n = run.Sectors;
        double sigR0 = Math.Sqrt(run.Covariance[0, 0]) * Geometry.ByteMm;
        Console.WriteLine($"[{name}] fitted r0={g.R0:F6} mm  r1={g.R1(n):F6} mm  (u={g.U:F4}, w={g.W:F8}, pitch {g.PitchUm:F5} um, {n} sectors)  "
            + $"chi2/dof={run.ChiSquarePerDof():F2}  rungs={run.Rungs.Count}");
        Console.WriteLine($"[{name}] sigma(u)={Math.Sqrt(run.Covariance[0, 0]):F4} (r0 {sigR0 * 1e6:F1} nm), sigma(w)={Math.Sqrt(run.Covariance[1, 1]):E2}, "
            + $"kappa={run.Kappa * 180 / Math.PI:F3} +- {Math.Sqrt(run.Covariance[2, 2]) * 180 / Math.PI:F3} deg");
        Console.WriteLine($"[{name}] prior r0={run.Prior.R0:F6} r1={run.Prior.R1:F6}: twist of the fit against the prior from the reference: "
            + $"LBA 0 {TwistTurns(g, run.Prior.Track, run.Reference, 0):F2}, inner limit {TwistTurns(g, run.Prior.Track, run.Reference, run.InnerLimit):F2}, "
            + $"outer limit {TwistTurns(g, run.Prior.Track, run.Reference, run.OuterLimit):F2}, last sector {TwistTurns(g, run.Prior.Track, run.Reference, n - 1):F2} turns");
        if (run.Rungs.Count == 0) return;
        double maxRes = run.Rungs.Max(r => Math.Abs(run.Residual(r))) * 180 / Math.PI;
        double rms = Math.Sqrt(run.Rungs.Average(r => Math.Pow(run.Residual(r), 2))) * 180 / Math.PI;
        Console.WriteLine($"[{name}] residuals: rms={rms:F3} deg, max={maxRes:F3} deg; sector measurements {run.Attempts}, confirmed {run.Confirmed}, "
            + $"re-measured {run.Remeasured}, skipped {run.Skipped}");
    }

    static LadderOutcome LadderReal(Drive d, int pairs, int speedHex, int reference, double periodGuessMs)
    {
        List<string> log = [];
        void Log(string line)
        {
            Console.WriteLine(line);
            log.Add(line);
        }

        log.Add($"prior: {Disc.Describe()}");
        d.SetReadSpeed(speedHex);
        Log($"SET CD SPEED 0x{speedHex:X4}: {d.Status}");
        DriveReader reader = new(d, Sectors);
        // Settle and measure the spindle period from repeated reference reads.
        Random rng = new(99);
        List<double> t = [];
        for (int i = 0; i < 40; i++)
        {
            (double tc, double dur, bool ok) = reader.Read(reference, rng.NextDouble() * 60);
            if (ok && dur > 8.5) t.Add(tc);
        }

        (double period, double coherence, double scatter, _) = t.Count >= 8 ? BestPeriodNear(t, periodGuessMs) : (double.NaN, 0.0, double.NaN, t.Count);
        LadderOutcome outcome;
        if (coherence < 0.9)
        {
            Log($"ABORT: no stable spindle period near {periodGuessMs} ms (coherence {coherence:F3}, {t.Count} usable settle reads).");
            outcome = new(false, null, reference, speedHex, pairs, period, coherence, scatter, 0, "no stable spindle period");
        }
        else
        {
            Log($"settle: period={period:F5} ms coherence={coherence:F3} scatter={scatter:F2} deg; reference LBA {reference}");
            LadderRun run = new(reader, Disc, reference, period, pairs, 2024 + reference, Log);
            Stopwatch sw = Stopwatch.StartNew();
            bool okRun = run.Run();
            Log($"ladder completed={okRun} in {sw.Elapsed.TotalMinutes:F1} min");
            ReportFit(run, "disc");
            File.WriteAllLines(Path.Combine(OutDir, "ladder_raw.csv"), run.Raw);
            File.WriteAllLines(Path.Combine(OutDir, "ladder_rejected.csv"), run.RejectedRaw);
            File.WriteAllLines(Path.Combine(OutDir, "ladder_rungs.csv"), LadderRungRows(run));
            outcome = new(okRun, run, reference, speedHex, pairs, period, coherence, scatter, sw.Elapsed.TotalMinutes, okRun ? "completed" : "aborted");
        }

        File.WriteAllLines(Path.Combine(OutDir, "ladder_log.txt"), log);
        return outcome;
    }

    static IEnumerable<string> LadderRungRows(LadderRun run) =>
        run.Rungs.Select(r => $"{r.Index},{r.Target},{r.DeltaWrapped:F6},{r.Sigma:F6},{r.Unwrapped:F6},{r.Predicted:F6},{r.Period:F6},{r.Used},{r.Rejected},{run.Residual(r):F6}")
            .Prepend("rung,target,delta_wrapped,sigma,unwrapped,predicted_before,period_ms,used,rejected,residual_final");

    static (double Period, double Coherence, double ScatterDeg, int N) BestPeriodNear(List<double> t, double guess)
    {
        double best = -1, period = guess;
        for (double p = guess * 0.99; p <= guess * 1.01; p *= 1.000001)
        {
            double sx = 0, sy = 0;
            foreach (double v in t) { double a = 2 * Math.PI * v / p; sx += Math.Cos(a); sy += Math.Sin(a); }
            double c = Math.Sqrt(sx * sx + sy * sy) / t.Count;
            if (c > best) { best = c; period = p; }
        }

        return (period, best, Math.Sqrt(-2 * Math.Log(Math.Max(best, 1e-9))) * 180 / Math.PI, t.Count);
    }
}
