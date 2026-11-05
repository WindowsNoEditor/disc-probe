using System.Diagnostics;

// Virtual drive: CAV spindle with slow period drift, seek delays, transport delay, jitter and cache hits, plus late
// host/USB outliers (2-3 ms) and rare sectors whose completion is shifted by a fixed angle (a local read anomaly, as
// seen at one LBA of disc 5). The truth is any track model, e.g. a polynomial pitch with a real S-bend.
sealed class SimReader(ITrack truth, double periodMs, double driftPerMinute, double jitterMs, double cacheRate, int seed,
    double outlierRate, double anomalyRate, double anomalyDeg) : ITimedReader
{
    readonly Random _rng = new(seed);
    readonly double _offset = 1.234;
    double _now;

    public double NowMs => _now;

    public bool IsAnomalous(int lba) => anomalyRate > 0 && Hash01(lba, seed) < anomalyRate;

    // Shift of an anomalous sector: anomalyDeg with a random sign (disc 5 showed -6 deg).
    double AnomalyRad(int lba) => !IsAnomalous(lba) ? 0 : (Hash01(lba, seed ^ 0x5BD1E995) < 0.5 ? -1 : 1) * anomalyDeg * Math.PI / 180;

    double SpindlePhase(double tMs)
    {
        double k = driftPerMinute / 60_000.0;
        return 2 * Math.PI * (tMs - 0.5 * k * tMs * tMs) / periodMs;
    }

    public (double, double, bool) Read(int lba, double waitMs)
    {
        _now += 150 + _rng.NextDouble() * 60 + waitMs;
        double start = _now;
        if (_rng.NextDouble() < cacheRate)
        {
            _now += 6.6;
            return (_now, 6.6, true);
        }

        double ready = start + 140 + _rng.NextDouble() * 60;
        double target = truth.ThetaOfLba(lba) + _offset + AnomalyRad(lba);
        double turns = Math.Ceiling((SpindlePhase(ready) - target) / (2 * Math.PI));
        double goal = target + 2 * Math.PI * turns;
        double t = ready;
        for (int i = 0; i < 30; i++)
        {
            double f = SpindlePhase(t) - goal;
            double slope = 2 * Math.PI / periodMs;
            t -= f / slope;
            if (Math.Abs(f) < 1e-12) break;
        }

        double late = _rng.NextDouble() < outlierRate ? 2 + _rng.NextDouble() : 0;
        double done = t + 6.8 + Gaussian() * jitterMs + late;
        _now = done;
        return (done, done - start, true);
    }

    double Gaussian()
    {
        double a = 1 - _rng.NextDouble(), b = _rng.NextDouble();
        return Math.Sqrt(-2 * Math.Log(a)) * Math.Cos(2 * Math.PI * b);
    }

    static double Hash01(int lba, int salt)
    {
        ulong z = (ulong)(uint)lba * 0x9E3779B97F4A7C15UL ^ (ulong)(uint)salt * 0xD1B54A32D192ED03UL;
        z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9UL;
        z = (z ^ (z >> 27)) * 0x94D049BB133111EBUL;
        z ^= z >> 31;
        return (z >> 11) * (1.0 / (1UL << 53));
    }
}

sealed record SimTruth(string Name, double R0, double R1, double C1, double C2, double C3)
{
    public PolyTrack Track(int sectors) => new(R0, R1, sectors * Geometry.SectorMm, C1, C2, C3);
}

sealed record SimOutcome(bool Completed, int Rungs, int Attempts, int Confirmed, int Remeasured, int Skipped, int WrongTurns, double MaxMissDeg,
    double MaxErrDeg, double FitErrDeg, double Minutes, double TwistInner, double TwistOuter, int AnomalousUsed, int Reference)
{
    // Wrong turn counts in a run that completed: the failure that would reach a calibration unnoticed.
    public int Silent => Completed ? WrongTurns : 0;
}

// Ladder settings the simulation can vary (defaults as on the drive).
sealed record LadderKnobs(double ConfirmAboveDeg = 1.0, double PlanFloorDeg = 0.5);

static partial class Program
{
    // 80-minute geometries of the original simulation: the Ritek preset and two candidates 0.088 mm off in r1.
    static readonly double[] RitekPreset = [24.911275, 57.931155], CandidateA = [24.908775, 58.019155], CandidateB = [24.913775, 57.843155];

    // Current box (Lenovo Thinkplus 80 min, 359845 sectors), quadratic fit. Its S-bend gives the simulation a realistic
    // model error against the ladder's constant pitch.
    const double BoxR0 = 24.921551846562572, BoxR1 = 57.838950219991993, BoxC1 = -3.8950535120452173E-05, BoxC2 = 1.5748336087855265E-05;

    // Named truths. "box" keeps this box's r0, mean pitch and shape and takes r1 from the sector count; "std74" is a
    // plausible 74-minute disc in the app's frame (1.6 um at 1.211 m/s: r0 24.77 mm, pitch 1.585 um) with the same shape,
    // against which the generic prior is 0.15 mm and 6.6 % off. A, B and preset are the original 80-minute cases.
    static SimTruth NamedTruth(string name, int sectors)
    {
        double R1For(double r0, double pitchUm) => Math.Sqrt(r0 * r0 + pitchUm * 1e-3 * sectors * Geometry.SectorMm / Math.PI);
        double boxPitchUm = Math.PI * (BoxR1 * BoxR1 - BoxR0 * BoxR0) / (359_845 * Geometry.SectorMm) * 1000;
        string key = name.ToLowerInvariant();
        if (key is "a" or "b" or "preset" && sectors != 359_845)
            throw new ArgumentException($"truth {name} is an 80-minute geometry (359845 sectors); use box, std74 or --truth");
        return key switch
        {
            "a" => new SimTruth("A", CandidateA[0], CandidateA[1], 0, 0, 0),
            "b" => new SimTruth("B", CandidateB[0], CandidateB[1], 0, 0, 0),
            "preset" => new SimTruth("preset", RitekPreset[0], RitekPreset[1], 0, 0, 0),
            "box" => new SimTruth("box", BoxR0, R1For(BoxR0, boxPitchUm), BoxC1, BoxC2, 0),
            "box10" => new SimTruth("box10", BoxR0, R1For(BoxR0, boxPitchUm), 10 * BoxC1, 10 * BoxC2, 0),
            "std74" => new SimTruth("std74", 24.77, R1For(24.77, 1.585), BoxC1, BoxC2, 0),
            _ => throw new ArgumentException($"unknown truth '{name}' (A, B, preset, box, box10, std74 or --truth r0 r1 [c1 c2 c3])"),
        };
    }

    static SimOutcome SimulateOnce(SimTruth truth, Prior prior, int reference, int pairs, int seed, double anomalyRate, double anomalyDeg,
        LadderKnobs knobs, Action<string> log, Action<LadderRun>? report = null)
    {
        PolyTrack track = truth.Track(prior.Sectors);
        SimReader sim = new(track, 48.349, 2e-4, 0.065, 0.03, seed, 0.03, anomalyRate, anomalyDeg);
        LadderRun run = new(sim, prior, reference, 48.35, pairs, 11 + seed, log) { ConfirmAboveDeg = knobs.ConfirmAboveDeg, PlanFloorDeg = knobs.PlanFloorDeg };
        bool ok = run.Run();
        report?.Invoke(run);
        int wrong = 0, anomalous = 0;
        double maxErr = 0;
        foreach (Rung r in run.Rungs)
        {
            double err = r.Unwrapped - (track.ThetaOfLba(r.Target) - track.ThetaOfLba(reference));
            if (Math.Abs(err) > Math.PI) wrong++;
            if (sim.IsAnomalous(r.Target)) anomalous++;
            maxErr = Math.Max(maxErr, Math.Abs(err) * 180 / Math.PI);
        }

        // The ladder's constant-pitch fit (with its kappa) against the truth over the band, relative to the reference.
        double fitErr = 0;
        for (int i = 0; i <= 200; i++)
        {
            int k = run.InnerLimit + (int)((long)(run.OuterLimit - run.InnerLimit) * i / 200);
            fitErr = Math.Max(fitErr, Math.Abs(TwistTurns(run.Fit, track, reference, k) * 360 + run.Kappa * 180 / Math.PI));
        }

        return new SimOutcome(ok, run.Rungs.Count, run.Attempts, run.Confirmed, run.Remeasured, run.Skipped, wrong, run.MaxAbsMissDeg, maxErr, fitErr,
            sim.NowMs / 60_000, TwistTurns(track, prior.Track, reference, run.InnerLimit), TwistTurns(track, prior.Track, reference, run.OuterLimit),
            anomalous, reference);
    }

    static Prior ShiftedPrior(SimTruth truth, int sectors, double dr0, double dr1, double sigmaR0, double sigmaPitch) =>
        new(truth.R0 + dr0, truth.R1 + dr1, 0, 0, 0, sectors, $"truth {truth.Name} with r0 {dr0:+0.###;-0.###;0} mm, r1 {dr1:+0.###;-0.###;0} mm, constant pitch", sigmaR0, sigmaPitch);

    static string Minutes(int sectors) => $"{sectors / 4500.0:F1} min";

    // laddersim [A|B|preset|box|box10|std74] [pairs] [--sectors N] [--truth r0 r1 [c1 c2 c3]]
    //           [--prior r0 r1 [c1 c2 c3] | --prior-shift dr0 dr1] [--prior-sigma mm frac] [--ref LBA] [--seed S] [--runs K] [--anomaly rate deg] [--write]
    static int LadderSim(Args a)
    {
        a.AllowOnly(2, "sectors", "truth", "prior", "prior-shift", "prior-sigma", "ref", "seed", "runs", "anomaly", "confirm-above", "plan-floor", "write");
        bool write = a.Flag("write");
        LadderKnobs knobs = Knobs(a);
        string truthName = a.Pos(0) ?? "A";
        int pairs = a.PosInt(1, 24);
        int sectors = a.Int("sectors", 100_000, 450_000) ?? 359_845;
        double[]? tv = a.Numbers("truth", 2, 5);
        SimTruth truth = tv is not null
            ? new SimTruth("--truth", tv[0], tv[1], tv.Length == 5 ? tv[2] : 0, tv.Length == 5 ? tv[3] : 0, tv.Length == 5 ? tv[4] : 0)
            : NamedTruth(truthName, sectors);
        PriorRequest request = PriorRequest.From(a);
        double[]? shift = a.Numbers("prior-shift", 2);
        if (shift is not null && a.Has("prior")) throw new ArgumentException("use either --prior or --prior-shift");
        bool legacy = tv is null && truthName.ToLowerInvariant() is "a" or "b" or "preset";
        Prior prior = shift is not null ? ShiftedPrior(truth, sectors, shift[0], shift[1], request.SigmaR0Mm, request.SigmaPitch)
            : request.Values is null && legacy ? new Prior(RitekPreset[0], RitekPreset[1], 0, 0, 0, sectors, "Ritek preset (original simulation)", request.SigmaR0Mm, request.SigmaPitch)
            : request.Build(sectors);
        int seed = a.Int("seed", 0, 1_000_000) ?? 7;
        int runs = a.Int("runs", 1, 10_000) ?? 1;
        double[] anomaly = a.Numbers("anomaly", 2) ?? [0.01, -6];
        int reference = a.Int("ref", 0, sectors - 1) ?? LadderRun.DefaultReference(prior);
        LadderRun.CheckReference(reference, sectors);
        PolyTrack track = truth.Track(sectors);
        Process.GetCurrentProcess().PriorityClass = ProcessPriorityClass.BelowNormal;

        Console.WriteLine($"truth {truth.Name}: r0={truth.R0:R} r1={truth.R1:R} c1={truth.C1:R} c2={truth.C2:R} c3={truth.C3:R} ({sectors} sectors, {Minutes(sectors)})");
        Console.WriteLine($"prior: {prior.Describe()}");
        Console.WriteLine($"reference LBA {reference}: prior {prior.RadiusOfLba(reference):F3} mm, truth {track.RadiusOfLba(reference):F3} mm; "
            + $"band LBA {LadderRun.InnerLimitFor(sectors)}..{LadderRun.OuterLimitFor(sectors)}; anomalies {anomaly[0] * 100:F1} % of sectors at {anomaly[1]:F1} deg; {pairs} pairs");
        List<SimOutcome> results = [];
        for (int i = 0; i < runs; i++)
        {
            SimOutcome o = runs == 1
                ? SimulateOnce(truth, prior, reference, pairs, seed + i, anomaly[0], anomaly[1], knobs, Console.WriteLine, r =>
                {
                    ReportFit(r, "sim");
                    if (write) WriteLadderFiles(r);
                })
                : SimulateOnce(truth, prior, reference, pairs, seed + i, anomaly[0], anomaly[1], knobs, _ => { });
            results.Add(o);
            Console.WriteLine($"seed {seed + i}: completed={o.Completed} rungs={o.Rungs} attempts={o.Attempts} confirmed={o.Confirmed} re-measured={o.Remeasured} skipped={o.Skipped} "
                + $"wrong turns={o.WrongTurns} max|miss|={o.MaxMissDeg:F2} deg max|rung-truth|={o.MaxErrDeg:F2} deg anomalous rungs used={o.AnomalousUsed} "
                + $"fit-truth={o.FitErrDeg:F2} deg virtual {o.Minutes:F1} min");
        }

        SimOutcome f = results[0];
        Console.WriteLine($"twist of the truth against the prior from the reference: inner limit {f.TwistInner:F2} turns, outer limit {f.TwistOuter:F2} turns");
        if (runs > 1) Console.WriteLine(SuiteLine($"{truth.Name}, {prior.Source}", results));
        return results.All(o => o.Completed && o.WrongTurns == 0) ? 0 : 1;
    }

    // --write: the ladder files of a single simulated run, in the drive's format, for the analysis tools.
    static void WriteLadderFiles(LadderRun run)
    {
        File.WriteAllLines(Path.Combine(OutDir, "ladder_raw.csv"), run.Raw);
        File.WriteAllLines(Path.Combine(OutDir, "ladder_rejected.csv"), run.RejectedRaw);
        File.WriteAllLines(Path.Combine(OutDir, "ladder_rungs.csv"), LadderRungRows(run));
        Console.WriteLine($"wrote ladder_raw.csv, ladder_rungs.csv and ladder_rejected.csv to {Path.GetFullPath(OutDir)}");
    }

    static string SuiteLine(string name, List<SimOutcome> r) =>
        $"{name,-56} {r.Count(o => o.Completed),3}/{r.Count,-3} {r.Sum(o => o.WrongTurns),5} {r.Sum(o => o.Silent),6} {r.Average(o => o.Rungs),6:F1} {r.Average(o => o.Attempts),6:F1} "
        + $"{r.Sum(o => o.Confirmed),5} {r.Sum(o => o.Remeasured),5} {r.Sum(o => o.Skipped),4} {r.Max(o => o.MaxMissDeg),7:F1} {r.Max(o => o.MaxErrDeg),6:F1} {r.Sum(o => o.AnomalousUsed),4} "
        + $"{r.Max(o => o.FitErrDeg),6:F2} {r.Average(o => o.Minutes),5:F1} {r[0].TwistInner,8:F2} {r[0].TwistOuter,8:F2}";

    static LadderKnobs Knobs(Args a)
    {
        double[]? c = a.Numbers("confirm-above", 1), f = a.Numbers("plan-floor", 1);
        LadderKnobs k = new();
        return k with { ConfirmAboveDeg = c?[0] ?? k.ConfirmAboveDeg, PlanFloorDeg = f?[0] ?? k.PlanFloorDeg };
    }

    // The verification matrix: 80 and 74 minutes, priors right and off by 0.1 mm in r0, r1 or both, a realistic 74-minute
    // disc against the generic prior, and two stress cases.
    static int SimSuite(Args a)
    {
        a.AllowOnly(0, "runs", "seed", "anomaly", "prior-sigma", "pairs", "confirm-above", "plan-floor");
        LadderKnobs knobs = Knobs(a);
        int runs = a.Int("runs", 1, 1_000) ?? 8;
        int seed = a.Int("seed", 0, 1_000_000) ?? 100;
        int pairs = a.Int("pairs", 8, 96) ?? 24;
        double[] anomaly = a.Numbers("anomaly", 2) ?? [0.02, -6];
        double[] sig = a.Numbers("prior-sigma", 2) ?? [Prior.DefaultSigmaR0Mm, Prior.DefaultSigmaPitch];
        Process.GetCurrentProcess().PriorityClass = ProcessPriorityClass.BelowNormal;

        List<(string Name, SimTruth Truth, Prior Prior)> cases = [];
        (double, double)[] shifts = [(0.1, 0.1), (-0.1, -0.1), (0.1, 0), (-0.1, 0), (0, 0.1), (0, -0.1), (0.1, -0.1), (-0.1, 0.1)];
        foreach (int n in new[] { 359_845, 333_000 })
        {
            SimTruth box = NamedTruth("box", n);
            cases.Add(($"{Minutes(n)} box, generic prior", box, Prior.Generic(n, sig[0], sig[1])));
            foreach ((double d0, double d1) in shifts)
                cases.Add(($"{Minutes(n)} box, prior r0 {d0:+0.0;-0.0;0} r1 {d1:+0.0;-0.0;0} mm", box, ShiftedPrior(box, n, d0, d1, sig[0], sig[1])));
        }

        SimTruth std74 = NamedTruth("std74", 333_000);
        cases.Add(("74.0 min std74, generic prior (0.15 mm, 6.6 % off)", std74, Prior.Generic(333_000, sig[0], sig[1])));
        cases.Add(("74.0 min std74, prior r0 +0.1 r1 +0.1 mm", std74, ShiftedPrior(std74, 333_000, 0.1, 0.1, sig[0], sig[1])));
        cases.Add(("74.0 min std74, prior r0 -0.1 r1 -0.1 mm", std74, ShiftedPrior(std74, 333_000, -0.1, -0.1, sig[0], sig[1])));
        cases.Add(("80.0 min box x10 shape (stress), generic prior", NamedTruth("box10", 359_845), Prior.Generic(359_845, sig[0], sig[1])));
        cases.Add(("80.0 min box, prior r0 -0.5 r1 -0.5 mm (stress)", NamedTruth("box", 359_845), ShiftedPrior(NamedTruth("box", 359_845), 359_845, -0.5, -0.5, sig[0], sig[1])));

        Console.WriteLine($"{runs} seeds per case from {seed}; {pairs} pairs; anomalies {anomaly[0] * 100:F1} % of sectors at {anomaly[1]:F1} deg; "
            + $"late outliers 3 %, cache hits 3 %; prior sigma r0 {sig[0]} mm, pitch {sig[1] * 100:F1} %; confirm above {knobs.ConfirmAboveDeg} deg, plan floor {knobs.PlanFloorDeg} deg");
        Console.WriteLine($"{"case",-56} {"done",7} {"wrong",5} {"silent",6} {"rungs",6} {"tries",6} {"conf",5} {"remea",5} {"skip",4} {"|miss|",7} {"|err|",6} {"anom",4} {"fit",6} {"min",5} {"twistIn",8} {"twistOut",8}");
        bool allGood = true;
        foreach ((string name, SimTruth truth, Prior prior) in cases)
        {
            int reference = LadderRun.DefaultReference(prior);
            List<SimOutcome> results = [];
            for (int i = 0; i < runs; i++) results.Add(SimulateOnce(truth, prior, reference, pairs, seed + i, anomaly[0], anomaly[1], knobs, _ => { }));
            Console.WriteLine(SuiteLine(name, results));
            allGood &= results.All(o => o.Completed && o.WrongTurns == 0);
        }

        Console.WriteLine("columns: done = completed runs; wrong = rungs with a wrong turn count (all runs); silent = wrong turns in completed runs;");
        Console.WriteLine("rungs/tries = mean accepted rungs / sector measurements; conf/remea/skip = confirmed / re-measured / skipped rungs (all runs);");
        Console.WriteLine("|miss| = max miss vs prediction (deg); |err| = max |rung - truth| (deg);");
        Console.WriteLine("anom = anomalous sectors among accepted rungs; fit = max |fit - truth| over the band (deg); min = mean virtual minutes;");
        Console.WriteLine("twistIn/Out = turns a spoke burned with the prior winds between the reference and the inner / outer limit.");
        Console.WriteLine(allGood ? "ALL RUNS COMPLETED WITH CORRECT TURN COUNTS" : "SOME RUNS FAILED");
        return allGood ? 0 : 1;
    }
}
