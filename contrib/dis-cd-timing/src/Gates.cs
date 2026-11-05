using System.Diagnostics;
using System.Numerics;

static partial class Program
{
    // Radius labels and test LBAs come from the prior of the disc in the drive (Disc), scaled to its sector count.
    static double RadiusOf(int lba) => Disc.RadiusOfLba(lba);
    static int LbaAt(double radius) => Disc.LbaAtRadius(radius);

    static int ReadCd(Drive d, int lba, int count = 1, bool c2 = false)
    {
        Span<byte> cdb = [0xBE, 0x04, (byte)(lba >> 24), (byte)(lba >> 16), (byte)(lba >> 8), (byte)lba,
            0, 0, (byte)count, (byte)(c2 ? 0x12 : 0x10), 0, 0];
        return d.Cmd(cdb, count * (c2 ? 2646 : 2352));
    }

    static void SpinWaitUs(double us)
    {
        long until = Stopwatch.GetTimestamp() + (long)(us / Drive.UsPerTick);
        while (Stopwatch.GetTimestamp() < until) Thread.SpinWait(20);
    }

    // P3: readability of the picture texture across the disc at the default speed.
    static void Scan(Drive d, int points)
    {
        List<string> rows = ["lba,radius_mm,us,status,c2_bits,frac_0D,frac_AA"];
        List<double> times = [];
        int failures = 0, c2Sectors = 0;
        for (int i = 0; i < points; i++)
        {
            int lba = (int)((long)LastLba * i / (points - 1));
            ReadCd(d, lba, 1, c2: true);
            double us = d.ElapsedUs;
            int c2 = 0;
            double f0d = 0, faa = 0;
            if (d.Ok)
            {
                ReadOnlySpan<byte> data = d.Data;
                for (int k = 0; k < 2352; k++)
                {
                    if (data[k] == 0x0D) f0d++;
                    else if (data[k] == 0xAA) faa++;
                }

                for (int k = 2352; k < 2646; k++) c2 += BitOperations.PopCount(data[k]);
                times.Add(us);
            }
            else failures++;

            if (c2 > 0) c2Sectors++;
            rows.Add($"{lba},{RadiusOf(lba):F3},{us:F0},{d.Status},{c2},{f0d / 2352:F3},{faa / 2352:F3}");
        }

        File.WriteAllLines(Path.Combine(OutDir, "scan.csv"), rows);
        Console.WriteLine($"scan: {points} points, failures={failures}, sectors with C2 errors={c2Sectors}");
        if (times.Count > 0) Console.WriteLine(Summary("read time", times.ToArray()));
        Console.WriteLine($"slow reads (>1 s): {times.Count(t => t > 1e6)}");
        foreach (string row in rows.Skip(1).Where((_, i) => i % 10 == 0)) Console.WriteLine("  " + row);
    }

    // Raw audio from the start of the track (framing offset s, diagnostic) and a content sample across the disc,
    // every 2 mm from r0 + 0.58 mm to 0.3 mm inside the end of the track (25.5 ... 57.5 mm on an 80-minute disc).
    // content_samples_lba.csv lists the LBA of each 4-sector block in content_samples.bin.
    static Framing.Result? Head(Drive d)
    {
        byte[] head = new byte[8 * 2352];
        bool complete = true;
        using (FileStream file = File.Create(Path.Combine(OutDir, "head_lba0-7.bin")))
        {
            for (int lba = 0; lba < 8; lba += 4)
            {
                ReadCd(d, lba, 4);
                Console.WriteLine($"READ CD LBA {lba}..{lba + 3}: {d.Status}, {d.Fetched} bytes");
                file.Write(d.Data);
                if (d.Ok && d.Fetched == 4 * 2352) d.Data.CopyTo(head.AsSpan(lba * 2352));
                else complete = false;
            }
        }

        int[] histogram = new int[256];
        List<string> index = ["radius_mm,lba,status"];
        using (FileStream sample = File.Create(Path.Combine(OutDir, "content_samples.bin")))
        {
            for (double r = Disc.R0 + 0.58; r <= Disc.EndRadius - 0.3; r += 2)
            {
                int lba = Math.Clamp(LbaAt(r), 0, LastLba - 3);
                ReadCd(d, lba, 4);
                index.Add($"{r:F3},{lba},{(d.Ok ? "ok" : d.Status)}");
                if (!d.Ok) { Console.WriteLine($"  r={r:F2}: {d.Status}"); continue; }
                sample.Write(d.Data);
                foreach (byte b in d.Data) histogram[b]++;
            }
        }

        File.WriteAllLines(Path.Combine(OutDir, "content_samples_lba.csv"), index);
        long total = histogram.Sum(v => (long)v);
        Console.WriteLine("content byte histogram (top values):");
        foreach ((int value, int count) in histogram.Select((c, v) => (v, c)).OrderByDescending(x => x.c).Take(8))
            Console.WriteLine($"  0x{value:X2}: {100.0 * count / Math.Max(1, total):F2}%");

        if (!complete)
        {
            Console.WriteLine("framing offset: LBA 0-7 not fully readable");
            return null;
        }

        Framing.Result s = Framing.Offset(head);
        Console.WriteLine($"framing offset (diagnostic): {s}");
        if (!s.Unique) Console.WriteLine("WARNING: staircase match is not unique enough; check that the disc was burned by the app with interleave on.");
        return s;
    }

    // P5: which access patterns are answered from the drive cache vs read from the disc.
    static void Cache(Drive d, int r)
    {
        Random rng = new(1234);
        int far1 = Math.Min(r + 100_000, LastLba - 100), far2 = Math.Max(r - 100_000, 100), far3 = Math.Min(r + 180_000, LastLba - 100);
        (string Name, Action Pre, int Target)[] tests =
        [
            ("R,R", () => ReadCd(d, r), r),
            ("R,E,R", () => { ReadCd(d, r); ReadCd(d, far1); }, r),
            ("R,E1,E2,E3,R", () => { ReadCd(d, r); ReadCd(d, far1); ReadCd(d, far2); ReadCd(d, far3); }, r),
            ("R,R+5", () => ReadCd(d, r), r + 5),
            ("R,R+40", () => ReadCd(d, r), r + 40),
            ("R,R-5", () => ReadCd(d, r), r - 5),
            ("R,R-40", () => ReadCd(d, r), r - 40),
            ("R,flush,R", () =>
            {
                ReadCd(d, r);
                d.Cmd([0xA8, 0x08, (byte)(r >> 24), (byte)(r >> 16), (byte)(r >> 8), (byte)r, 0, 0, 0, 0, 0, 0], 0);
                Console.WriteLine($"    flush probe: {d.Status}");
            }, r),
            ("R,evict900,R", () =>
            {
                ReadCd(d, r);
                for (int s = 0; s < 900; s += 25) ReadCd(d, far1 + s, 25);
            }, r),
        ];

        List<string> rows = ["test,rep,target,us"];
        foreach ((string name, Action pre, int target) in tests)
        {
            List<double> times = [];
            for (int rep = 0; rep < 12; rep++)
            {
                pre();
                SpinWaitUs(rng.NextDouble() * 15_000);
                ReadCd(d, target);
                times.Add(d.Ok ? d.ElapsedUs : double.NaN);
                rows.Add($"{name},{rep},{target},{d.ElapsedUs:F0}");
            }

            double[] ok = times.Where(t => !double.IsNaN(t)).Order().ToArray();
            string spread = ok.Length > 3 ? $"min={ok[0] / 1000:F2} p25={Pct(ok, 0.25) / 1000:F2} median={Pct(ok, 0.5) / 1000:F2} p75={Pct(ok, 0.75) / 1000:F2} max={ok[^1] / 1000:F2} ms" : "n/a";
            Console.WriteLine($"{name,-14} {spread}  (<8.5 ms: {ok.Count(t => t < 8500)}/{ok.Length})");
        }

        File.WriteAllLines(Path.Combine(OutDir, "cache.csv"), rows);
    }

    // P4: revolution period at three radii for each read speed, using a far read before each timed read.
    // Radii r0 + 1.08 mm, 40 mm and 0.34 mm inside the end of the track (26, 40 and 57.5 mm on an 80-minute disc).
    static void Rotation(Drive d, string strategy, string speedList)
    {
        Random rng = new(4321);
        List<string> rows = ["speed,radius_mm,lba,rep,t_ms,us"];
        int[] radiiLba = [LbaAt(Disc.R0 + 1.08), LbaAt(40), LbaAt(Disc.EndRadius - 0.34)];
        foreach (string hex in speedList.Split(','))
        {
            int speed = Convert.ToInt32(hex, 16);
            d.SetReadSpeed(speed);
            Console.WriteLine($"=== SET CD SPEED 0x{speed:X4} ({(speed == 0xFFFF ? "max" : (speed / 176.4).ToString("F1") + "x")}): {d.Status}");
            long settleUntil = Stopwatch.GetTimestamp() + (long)(4e6 / Drive.UsPerTick);
            while (Stopwatch.GetTimestamp() < settleUntil) ReadCd(d, radiiLba[0] + rng.Next(0, 2000));

            foreach (int lba in radiiLba)
            {
                List<double> t = [];
                int far = Seek.Far(lba, Sectors);
                for (int rep = 0; rep < 40; rep++)
                {
                    if (strategy == "far") ReadCd(d, far);
                    else if (strategy == "back") ReadCd(d, lba + 40);
                    SpinWaitUs(rng.NextDouble() * 20_000);
                    ReadCd(d, lba);
                    if (!d.Ok) { Console.WriteLine($"  read failed: {d.Status}"); continue; }
                    double tMs = d.T1 * Drive.UsPerTick / 1000;
                    t.Add(tMs);
                    rows.Add($"{speed:X4},{RadiusOf(lba):F2},{lba},{rep},{tMs:F4},{d.ElapsedUs:F0}");
                }

                (double period, double coherence, double scatterDeg, string alternatives) = BestPeriod(t);
                Console.WriteLine($"  r={RadiusOf(lba):F1} mm: period={period:F4} ms ({60_000 / period:F0} rpm) coherence={coherence:F3} "
                    + $"phase scatter={scatterDeg:F1} deg  next: {alternatives}");
            }
        }

        File.WriteAllLines(Path.Combine(OutDir, $"rotation_{strategy}.csv"), rows);
    }

    // Completion times of reads of one sector are congruent modulo the revolution period.
    static (double Period, double Coherence, double ScatterDeg, string Alternatives) BestPeriod(List<double> tMs)
    {
        if (tMs.Count < 8) return (double.NaN, 0, double.NaN, "");
        double t0 = tMs[0];
        double[] t = tMs.Select(v => v - t0).ToArray();
        List<(double P, double C)> peaks = [];
        double bestP = 0, bestC = 0;
        double prevC = 0, prevP = 0;
        bool rising = false;
        for (double p = 5.0; p <= 160.0; p *= 1.00005)
        {
            double c = Coherence(t, p);
            if (c > bestC) { bestC = c; bestP = p; }
            if (c < prevC && rising && prevC > 0.5) peaks.Add((prevP, prevC));
            rising = c > prevC;
            prevC = c;
            prevP = p;
        }

        for (double p = bestP * 0.9995; p <= bestP * 1.0005; p *= 1.000001)
        {
            double c = Coherence(t, p);
            if (c > bestC) { bestC = c; bestP = p; }
        }

        double scatter = Math.Sqrt(-2 * Math.Log(Math.Max(bestC, 1e-9))) * 180 / Math.PI;
        string alt = string.Join(" ", peaks.OrderByDescending(x => x.C).Where(x => Math.Abs(x.P / bestP - 1) > 0.01)
            .Take(2).Select(x => $"{x.P:F3}ms/{x.C:F2}"));
        return (bestP, bestC, scatter, alt);
    }

    static double Coherence(double[] t, double period)
    {
        double sx = 0, sy = 0;
        foreach (double v in t)
        {
            double a = 2 * Math.PI * v / period;
            sx += Math.Cos(a);
            sy += Math.Sin(a);
        }

        return Math.Sqrt(sx * sx + sy * sy) / t.Length;
    }
}
