using System.Buffers.Binary;
using System.Diagnostics;
using System.Globalization;
using System.Text;

static partial class Program
{
    static string OutDir = "";

    // Sector count and prior geometry of the disc in the drive (or of a simulation): the radius scale used to place
    // test LBAs and the ladder's starting point. Set from the disc before any phase that reads it.
    static Prior Disc = Prior.Generic(359_845);
    static int Sectors => Disc.Sectors;
    static int LastLba => Disc.Sectors - 1;

    const string Usage = """
        usage: Probe <outdir> <phase> [arguments] [--options]
        drive phases (read-only, drive E:):
          inventory                                 drive, disc status, TOC, ATIP, capacity and the sector count to use
          calibrate [pairs] [speed] [ref] [period]  inventory + head + ladder in one run; writes summary.json
          autocal [--pairs N]                       for an unknown drive: find a CAV read speed and its period, then
                                                    calibrate with them (reference 41.5 mm on the prior)
          head                                      LBA 0-7 (framing offset s) and content samples
          ladder [pairs] [speed] [ref] [period]     timing ladder (default 24 pairs, speed 0583, ref near 40 mm, 48.35 ms)
          scan [points] | latency [n] | cache [lba] | rotation [far|back|none] [speeds] | gating [lba] [pairs] [speed] [period]
        options of the disc phases (after the positional arguments):
          --prior r0 r1 [c1 c2 c3]   prior geometry, e.g. the burn values of the probe disc; default r0 24.92 mm,
                                     pitch 1.4865 um and r1 from the sector count
          --prior-sigma mm frac      prior uncertainty of r0 (mm) and of the pitch (fraction); default 0.5 0.08
          --sectors N                sector count; default from the disc (TOC lead-out)
          --dry-run                  check the arguments and show the plan; the drive is not opened
          --drive X:                 the recorder to use (any drive phase); default: the only recorder IMAPI lists
        offline (no drive):
          laddersim [A|B|preset|box|box10|std74] [pairs] [--sectors N] [--truth r0 r1 [c1 c2 c3]]
                    [--prior r0 r1 [c1 c2 c3] | --prior-shift dr0 dr1] [--prior-sigma mm frac] [--ref LBA] [--seed S] [--runs K] [--anomaly rate deg] [--write]
          simsuite [--runs K] [--seed S] [--pairs P] [--anomaly rate deg] [--prior-sigma mm frac]
          framing <head_lba0-7.bin>                 framing offset s of a saved head file
        """;

    [STAThread]
    static int Main(string[] args)
    {
        if (args.Length < 2)
        {
            Console.WriteLine(Usage);
            return 2;
        }

        CultureInfo.DefaultThreadCurrentCulture = CultureInfo.InvariantCulture;
        OutDir = args[0];
        string phase = args[1].ToLowerInvariant();
        bool dryRun = args.Skip(2).Contains("--dry-run", StringComparer.OrdinalIgnoreCase);
        string? driveArg = null;
        List<string> rest = args.Skip(2).ToList();
        int di = rest.FindIndex(x => x.Equals("--drive", StringComparison.OrdinalIgnoreCase));
        if (di >= 0)
        {
            if (di + 1 >= rest.Count) { Console.WriteLine("error: --drive takes a drive letter, e.g. --drive D:"); return 2; }
            driveArg = rest[di + 1];
            rest.RemoveRange(di, 2);
        }
        Func<Drive, int> run;
        try
        {
            Args a = new(rest.Where(t => !t.Equals("--dry-run", StringComparison.OrdinalIgnoreCase)));
            switch (phase)
            {
                case "laddersim":
                    Directory.CreateDirectory(OutDir);
                    return LadderSim(a);
                case "simsuite":
                    Directory.CreateDirectory(OutDir);
                    return SimSuite(a);
                case "framing":
                    return FramingFile(a);
            }

            // Every argument is checked before the drive is opened.
            run = PlanDrivePhase(phase, a, string.Join(' ', args.Skip(1)));
            if (dryRun) return DryRun(phase, a);
        }
        catch (ArgumentException e)
        {
            Console.WriteLine($"error: {e.Message}");
            return 2;
        }

        Directory.CreateDirectory(OutDir);
        Process.GetCurrentProcess().PriorityClass = ProcessPriorityClass.High;
        Thread.CurrentThread.Priority = ThreadPriority.Highest;
        string volume;
        try { volume = PickRecorder(driveArg); }
        catch (InvalidOperationException e) { Console.WriteLine($"error: {e.Message}"); return 2; }
        using Drive drive = new(volume);
        Console.WriteLine($"drive: {drive.Model}");
        try
        {
            return run(drive);
        }
        catch (DiscException e)
        {
            Console.WriteLine($"STOP: {e.Message}");
            return 3;
        }
        catch (ArgumentException e)
        {
            Console.WriteLine($"error: {e.Message}");
            return 2;
        }
    }

    static Func<Drive, int> PlanDrivePhase(string phase, Args a, string command)
    {
        switch (phase)
        {
            case "inventory":
                a.AllowOnly(0);
                return d => { Inventory(d); return 0; };
            case "latency":
            {
                a.AllowOnly(1);
                int n = Positive(a.PosInt(0, 2000), 10, 1_000_000, "n");
                return d => { Latency(d, n); return 0; };
            }
        }

        string[] discOptions = ["prior", "prior-sigma", "sectors"];
        PriorRequest prior = PriorRequest.From(a);
        int? sectors = a.Int("sectors", 10_000, 450_000);
        switch (phase)
        {
            case "scan":
            {
                a.AllowOnly(1, discOptions);
                int points = Positive(a.PosInt(0, 100), 2, 100_000, "points");
                return d => { UseDisc(d, prior, sectors); Scan(d, points); return 0; };
            }
            case "head":
                a.AllowOnly(0, discOptions);
                return d => { UseDisc(d, prior, sectors); Head(d); return 0; };
            case "cache":
            {
                a.AllowOnly(1, discOptions);
                int? lba = a.PosIntOrNull(0);
                return d => { UseDisc(d, prior, sectors); Cache(d, CheckLba(lba ?? LadderRun.DefaultReference(Disc))); return 0; };
            }
            case "rotation":
            {
                a.AllowOnly(2, discOptions);
                string strategy = a.Pos(0) ?? "far";
                if (strategy is not ("far" or "back" or "none")) throw new ArgumentException($"rotation strategy '{strategy}' is not far, back or none");
                string speeds = a.Pos(1) ?? "FFFF,108A,0B06,06E4,0583,02C2";
                foreach (string s in speeds.Split(',')) ParseSpeed(s);
                return d => { UseDisc(d, prior, sectors); Rotation(d, strategy, speeds); return 0; };
            }
            case "gating":
            {
                a.AllowOnly(4, discOptions);
                int? lba = a.PosIntOrNull(0);
                int pairs = Positive(a.PosInt(1, 24), 6, 1_000, "pairs");
                int speed = Positive(a.PosHex(2, 0x0583), 1, 0xFFFF, "speed");
                double period = PeriodGuess(a.PosDouble(3, 48.35));
                return d =>
                {
                    UseDisc(d, prior, sectors);
                    Gating(d, CheckLba(lba ?? LadderRun.DefaultReference(Disc)), pairs, speed, period);
                    return 0;
                };
            }
            case "autocal":
            {
                a.AllowOnly(0, [.. discOptions, "pairs"]);
                int pairs = a.Int("pairs", 6, 1_000) ?? 24;
                return d => AutoCal(d, prior, sectors, pairs, command);
            }
            case "ladder":
            case "calibrate":
            {
                a.AllowOnly(4, discOptions);
                int pairs = Positive(a.PosInt(0, 24), 6, 1_000, "pairs");
                int speed = Positive(a.PosHex(1, 0x0583), 1, 0xFFFF, "speed");
                int? reference = a.PosIntOrNull(2);
                double period = PeriodGuess(a.PosDouble(3, 48.35));
                if (phase == "calibrate") return d => Calibrate(d, prior, sectors, pairs, speed, reference, period, command);
                return d =>
                {
                    UseDisc(d, prior, sectors);
                    int r = reference ?? LadderRun.DefaultReference(Disc);
                    LadderRun.CheckReference(r, Sectors);
                    Framing.Result? s = FramingFromSavedHead();
                    LadderOutcome outcome = LadderReal(d, pairs, speed, r, period);
                    WriteSummary("ladder", command, d.Model, DiscRead, reference is null ? "40 mm on the prior" : "given", s, outcome);
                    return outcome.Completed ? 0 : 1;
                };
            }
            default:
                throw new ArgumentException($"unknown phase '{phase}'\n{Usage}");
        }
    }

    // --dry-run: the arguments are valid; show what the phase would use without opening the drive. The sector count
    // normally comes from the disc, so the prior, reference and band are shown only with --sectors.
    static int DryRun(string phase, Args a)
    {
        Console.WriteLine($"dry run: the arguments of '{phase}' are valid; the drive was not opened.");
        if (phase is "inventory" or "latency") return 0;
        PriorRequest request = PriorRequest.From(a);
        if (a.Int("sectors", 10_000, 450_000) is not int sectors)
        {
            Console.WriteLine(request.Values is double[] v ? $"prior: --prior {string.Join(' ', v.Select(x => x.ToString("R")))}" : "prior: generic (r0 24.92 mm, pitch 1.4865 um, r1 from the sector count)");
            Console.WriteLine("sector count: from the disc (TOC lead-out); add --sectors N to see the prior, reference and band here");
            return 0;
        }

        Disc = request.Build(sectors);
        Console.WriteLine($"prior: {Disc.Describe()}");
        int? given = phase is "ladder" or "calibrate" ? a.PosIntOrNull(2) : phase is "gating" or "cache" ? a.PosIntOrNull(0) : null;
        if (phase == "autocal")
        {
            int r = Disc.LbaAtRadius(41.5);
            LadderRun.CheckReference(r, sectors);
            Console.WriteLine($"autocal: tries read speeds {string.Join(", ", AutoSpeeds.Select(x => "0x" + x.ToString("X4")))} until one is CAV "
                + $"(periods at {Disc.R0 + 1.08:F2}, 41.50 and {Disc.EndRadius - 0.34:F2} mm agree to {100 * CavTolerance:F1} %), then calibrates with reference LBA {r} (41.5 mm)");
            return 0;
        }
        int lba = given ?? LadderRun.DefaultReference(Disc);
        if (phase is "ladder" or "calibrate") LadderRun.CheckReference(lba, sectors);
        Console.WriteLine($"{(phase is "ladder" or "calibrate" ? "reference " : "")}LBA {lba} ({(given is null ? "40 mm on the prior" : "given")}, prior radius {Disc.RadiusOfLba(lba):F3} mm); "
            + $"band LBA {LadderRun.InnerLimitFor(sectors)}..{LadderRun.OuterLimitFor(sectors)} "
            + $"(prior {Disc.RadiusOfLba(LadderRun.InnerLimitFor(sectors)):F2}..{Disc.RadiusOfLba(LadderRun.OuterLimitFor(sectors)):F2} mm); end of track {Disc.EndRadius:F3} mm");
        return 0;
    }

    static int Positive(int v, int min, int max, string what) =>
        v >= min && v <= max ? v : throw new ArgumentException($"{what} {v} is outside {min}..{max}");

    static int ParseSpeed(string s)
    {
        try { return Positive(Convert.ToInt32(s, 16), 1, 0xFFFF, "speed"); }
        catch (FormatException) { throw new ArgumentException($"speed '{s}' is not hexadecimal"); }
    }

    static double PeriodGuess(double ms) => ms is >= 5 and <= 200 ? ms : throw new ArgumentException($"period guess {ms} ms is outside 5..200 ms");

    static int CheckLba(int lba) => lba >= 1 && lba < LastLba - 1 ? lba : throw new ArgumentException($"LBA {lba} is outside the disc (0..{LastLba})");

    // Sector count from the disc (or --sectors) and the prior scaled to it.
    // The recorder's volume path: --drive as given ("D", "D:" or "D:\\"); else the only recorder IMAPI lists.
    static string PickRecorder(string? driveArg)
    {
        if (driveArg is string g)
        {
            string v = g.TrimEnd('\\', ':');
            if (v.Length != 1 || !char.IsLetter(v[0])) throw new InvalidOperationException($"--drive '{g}' is not a drive letter such as D:");
            return char.ToUpperInvariant(v[0]) + ":\\";
        }

        List<string> found = [];
        dynamic master = Activator.CreateInstance(Type.GetTypeFromProgID("IMAPI2.MsftDiscMaster2", true)!)!;
        int count = master.Count;
        for (int i = 0; i < count; i++)
        {
            dynamic recorder = Activator.CreateInstance(Type.GetTypeFromProgID("IMAPI2.MsftDiscRecorder2", true)!)!;
            recorder.InitializeDiscRecorder((string)master.Item(i));
            foreach (object? path in (Array)recorder.VolumePathNames)
                if (path is string s) { found.Add(s); break; }
        }

        if (found.Count == 1) { Console.WriteLine($"recorder: {found[0]} (the only one)"); return found[0]; }
        if (found.Count == 0) throw new InvalidOperationException("no optical recorder found (IMAPI lists none)");
        throw new InvalidOperationException($"several recorders ({string.Join(", ", found)}); choose one with --drive X:");
    }

    static void UseDisc(Drive d, PriorRequest request, int? sectorsOption)
    {
        int sectors;
        if (sectorsOption is int n)
        {
            sectors = n;
            Console.WriteLine($"sectors: {n} (--sectors)");
        }
        else
        {
            DiscInfo info = ReadDiscInfo(d);
            Console.WriteLine($"disc: {DescribeCapacity(info)}");
            if (info.IsBlank || info.Sectors is not int s)
                throw new DiscException("no burned track on this disc (blank?); 'inventory' prints its capacity");
            if (!info.IsAppBurn) Console.WriteLine("warning: not one audio track at LBA 0; the ladder expects a disc burned by the app");
            sectors = s;
        }

        Disc = request.Build(sectors);
        Console.WriteLine($"prior: {Disc.Describe()}");
    }

    static int FramingFile(Args a)
    {
        a.AllowOnly(1);
        string path = a.Pos(0) ?? throw new ArgumentException("framing needs the path of a head_lba0-7.bin");
        if (!File.Exists(path)) throw new ArgumentException($"file not found: {path}");
        Framing.Result r = Framing.Offset(File.ReadAllBytes(path));
        Console.WriteLine($"framing offset (diagnostic): {r}");
        if (!r.Unique) Console.WriteLine("WARNING: staircase match is not unique enough; check that the disc was burned by the app with interleave on.");
        return 0;
    }

    static Framing.Result? FramingFromSavedHead()
    {
        string path = Path.Combine(OutDir, "head_lba0-7.bin");
        if (!File.Exists(path)) return null;
        byte[] head = File.ReadAllBytes(path);
        return head.Length >= 6000 ? Framing.Offset(head) : null;
    }

    static int Be16(ReadOnlySpan<byte> b, int o) => BinaryPrimitives.ReadUInt16BigEndian(b[o..]);
    static int Be32(ReadOnlySpan<byte> b, int o) => BinaryPrimitives.ReadInt32BigEndian(b[o..]);

    static DiscInfo Inventory(Drive d)
    {
        d.Cmd([0x12, 0, 0, 0, 0x60, 0], 0x60);
        if (d.Ok)
        {
            ReadOnlySpan<byte> q = d.Data;
            Console.WriteLine($"INQUIRY: '{Encoding.ASCII.GetString(q[8..36])}'");
        }

        d.Cmd([0x46, 0, 0, 0, 0, 0, 0, 0, 8, 0], 8);
        Console.WriteLine(d.Ok ? $"current profile: 0x{Be16(d.Data, 6):X4}" : $"GET CONFIGURATION: {d.Status}");

        d.Cmd([0x46, 2, 0x00, 0x1E, 0, 0, 0, 0, 16, 0], 16);
        if (d.Ok && d.Fetched >= 13)
        {
            byte f = d.Data[12];
            Console.WriteLine($"CD Read feature 001E: current={(d.Data[10] & 1)} CD-Text={(f & 1)} C2={(f >> 1) & 1} DAP={(f >> 7) & 1}");
        }

        d.Cmd([0x46, 2, 0x01, 0x07, 0, 0, 0, 0, 16, 0], 16);
        if (d.Ok && d.Fetched >= 13)
            Console.WriteLine($"Real-time streaming 0107: current={(d.Data[10] & 1)} flags=0x{d.Data[12]:X2}");

        d.Cmd([0x5A, 0x08, 0x2A, 0, 0, 0, 0, 0x01, 0x00, 0], 256);
        if (d.Ok)
        {
            ReadOnlySpan<byte> m = d.Data;
            int p = 8 + Be16(m, 6);
            Console.WriteLine($"page 2A: maxRead={Be16(m, p + 8)} kB/s curRead={Be16(m, p + 14)} kB/s buffer={Be16(m, p + 12)} KiB "
                + $"rotationSelected={m[p + 27] & 3} streamAccurate={(m[p + 5] >> 1) & 1} curWriteSel={Be16(m, p + 28)}");
        }

        DiscInfo info = ReadDiscInfo(d);
        if (info.DiscStatus is int status)
            Console.WriteLine($"disc status={status} (0=blank, 2=complete) sessions={info.Sessions} firstTrack={info.FirstTrackNumber} lastTrackLastSession={info.LastTrackLastSession}");
        if (info.TocStatus is null)
        {
            Console.WriteLine($"TOC: tracks {info.TocFirst}..{info.TocLast}");
            foreach (TocEntry e in info.Toc)
                Console.WriteLine($"  track {(e.Track == 0xAA ? "lead-out" : e.Track.ToString())}: ctrl=0x{e.Control:X} adr={e.Adr} lba={e.Lba}");
        }
        else Console.WriteLine($"READ TOC: {info.TocStatus}");

        if (info.AtipLeadIn is Msf li && info.AtipLeadOut is Msf lo) Console.WriteLine($"ATIP: lead-in {li} last lead-out {lo}");
        if (info.ReadCapacityLastLba is int last) Console.WriteLine($"READ CAPACITY: last LBA {last}, block {info.BlockLength}");

        d.Cmd([0xAC, 0x10, 0, 0, 0, 0, 0, 0, 0x00, 0x10, 0x00, 0], 8 + 16 * 16);
        if (d.Ok)
        {
            ReadOnlySpan<byte> g = d.Data;
            int len = Be32(g, 0) + 4;
            Console.WriteLine($"GET PERFORMANCE (read, nominal): write={(g[4] >> 1) & 1} except={g[4] & 1}");
            for (int o = 8; o + 16 <= len && o + 16 <= g.Length; o += 16)
                Console.WriteLine($"  start LBA {Be32(g, o)} @ {Be32(g, o + 4)} kB/s -> end LBA {Be32(g, o + 8)} @ {Be32(g, o + 12)} kB/s");
        }
        else Console.WriteLine($"GET PERFORMANCE: {d.Status}");

        PrintCapacity(info);
        return info;
    }

    static void Latency(Drive d, int n)
    {
        double[] tur = new double[n];
        double[] inquiry = new double[n];
        for (int i = 0; i < n; i++)
        {
            d.Cmd([0, 0, 0, 0, 0, 0], 0);
            tur[i] = d.ElapsedUs;
        }

        for (int i = 0; i < n; i++)
        {
            d.Cmd([0x12, 0, 0, 0, 0x24, 0], 0x24);
            inquiry[i] = d.ElapsedUs;
        }

        Console.WriteLine(Summary("TEST UNIT READY", tur));
        Console.WriteLine(Summary("INQUIRY 36B", inquiry));
        File.WriteAllLines(Path.Combine(OutDir, "latency.csv"),
            Enumerable.Range(0, n).Select(i => $"{tur[i]:F2},{inquiry[i]:F2}").Prepend("tur_us,inquiry_us"));
    }

    static string Summary(string name, double[] values)
    {
        double[] s = values.Order().ToArray();
        double median = Pct(s, 0.5);
        double mad = values.Select(v => Math.Abs(v - median)).Order().ElementAt(values.Length / 2) * 1.4826;
        return $"{name}: n={s.Length} median={median:F1} us robustSigma={mad:F1} us p1={Pct(s, 0.01):F1} p5={Pct(s, 0.05):F1} "
            + $"p95={Pct(s, 0.95):F1} p99={Pct(s, 0.99):F1} max={s[^1]:F1}";
    }

    static double Pct(double[] sorted, double q) => sorted[Math.Clamp((int)Math.Round(q * (sorted.Length - 1)), 0, sorted.Length - 1)];
}
