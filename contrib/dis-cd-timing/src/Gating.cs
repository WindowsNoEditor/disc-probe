static partial class Program
{
    static byte[] ReadCdCdb(int lba, int count, byte mainFlags, byte subSelect) =>
        [0xBE, 0x04, (byte)(lba >> 24), (byte)(lba >> 16), (byte)(lba >> 8), (byte)lba, 0, 0, (byte)count, mainFlags, subSelect, 0];

    // Completion-gating experiment (read-only). Does READ CD complete at the same disc angle for
    // different channel selections and transfer shapes? Each pair alternates the baseline (one audio
    // sector at L) with one variant; every timed read follows an untimed far read (cache defeat) and a
    // random wait. A phase difference converts to bytes along the track at the radius of L.
    static void Gating(Drive d, int lba, int pairs, int speedHex, double periodGuessMs)
    {
        d.SetReadSpeed(speedHex);
        Console.WriteLine($"SET CD SPEED 0x{speedHex:X4}: {d.Status}");
        Random rng = new(4242);
        int far = Seek.Far(lba, Sectors);

        (double Tc, double Dur, bool Ok, string Status) Timed(byte[] cdb, int length, double waitMs)
        {
            ReadCd(d, far);
            SpinWaitUs(waitMs * 1000);
            d.Cmd(cdb, length);
            return (d.T1 * Drive.UsPerTick / 1000, d.ElapsedUs / 1000, d.Ok, d.Status);
        }

        byte[] baseline = ReadCdCdb(lba, 1, 0x10, 0x00);
        List<double> settle = [];
        for (int i = 0; i < 40; i++)
        {
            var r = Timed(baseline, 2352, rng.NextDouble() * 60);
            if (r.Ok && r.Dur > 8.5) settle.Add(r.Tc);
        }

        (double period, double coherence, double scatter, _) = BestPeriodNear(settle, periodGuessMs);
        Console.WriteLine($"settle: period={period:F5} ms coherence={coherence:F3} scatter={scatter:F2} deg; LBA {lba}");
        if (coherence < 0.9)
        {
            Console.WriteLine("ABORT: no stable spindle period.");
            return;
        }

        // Radius on the prior's scale (--prior; default the generic 80-minute value scaled to the disc).
        double rMm = Disc.RadiusOfLba(lba);
        double bytesPerDeg = Math.PI / 180 * rMm / Geometry.ByteMm;
        Console.WriteLine($"radius {rMm:F3} mm (prior): 1 deg = {bytesPerDeg:F1} bytes along the track; one sector = {Geometry.SectorBytes / bytesPerDeg:F2} deg");

        (string Name, byte[] Cdb, int Length)[] variants =
        [
            ("A baseline vs itself (null test)", baseline, 2352),
            ("F next sector L+1 (scale check, expect +1 sector)", ReadCdCdb(lba + 1, 1, 0x10, 0x00), 2352),
            ("B sub-channel Q only, no audio", ReadCdCdb(lba, 1, 0x00, 0x02), 16),
            ("G nothing selected (no transfer)", ReadCdCdb(lba, 1, 0x00, 0x00), 0),
            ("C audio + raw P-W", ReadCdCdb(lba, 1, 0x10, 0x01), 2448),
            ("H audio + formatted Q", ReadCdCdb(lba, 1, 0x10, 0x02), 2368),
            ("E audio + C2 error flags", ReadCdCdb(lba, 1, 0x12, 0x00), 2646),
            ("D two sectors L-1..L", ReadCdCdb(lba - 1, 2, 0x10, 0x00), 4704),
        ];

        List<string> rows = ["variant,role,completion_ms,duration_ms,ok,status"];
        foreach ((string name, byte[] cdb, int length) in variants)
        {
            List<double> refs = [], xs = [];
            List<double> xDur = [];
            int fails = 0;
            string lastStatus = "ok";
            for (int k = 0; k < pairs; k++)
            {
                var a = Timed(baseline, 2352, rng.NextDouble() * 1.2 * period);
                rows.Add($"\"{name}\",R,{a.Tc:F5},{a.Dur:F4},{(a.Ok ? 1 : 0)},\"{a.Status}\"");
                if (a.Ok && a.Dur > 8.5) refs.Add(a.Tc);
                var x = Timed(cdb, length, rng.NextDouble() * 1.2 * period);
                rows.Add($"\"{name}\",X,{x.Tc:F5},{x.Dur:F4},{(x.Ok ? 1 : 0)},\"{x.Status}\"");
                if (x.Ok && x.Dur > 8.5) { xs.Add(x.Tc); xDur.Add(x.Dur); }
                else { fails++; lastStatus = x.Ok ? $"fast {x.Dur:F1} ms" : x.Status; }
            }

            if (refs.Count < 6 || xs.Count < 6)
            {
                Console.WriteLine($"{name}: unusable ({xs.Count}/{pairs} usable; last: {lastStatus})");
                continue;
            }

            (double delta, double sigma, int used) = PhaseDelta(refs, xs, period);
            double deg = delta * 180 / Math.PI, sdeg = sigma * 180 / Math.PI;
            xDur.Sort();
            Console.WriteLine($"{name}: delta = {deg,8:F3} deg +- {sdeg:F3}  = {deg * bytesPerDeg,8:F0} bytes ({deg * bytesPerDeg / 24,7:F1} frames)"
                + $"  used {used}/{pairs}, failed/fast {fails}, median duration {xDur[xDur.Count / 2]:F1} ms");
        }

        File.WriteAllLines(Path.Combine(OutDir, $"gating_{lba}.csv"), rows);
    }

    // Robust phase of xs relative to refs (median-centred clipping on both sides, linear drift from refs).
    static (double Delta, double Sigma, int Used) PhaseDelta(List<double> refsIn, List<double> xs, double period)
    {
        static double Wrap(double a) => Math.IEEERemainder(a, 2 * Math.PI);
        static double CMean(IEnumerable<double> v)
        {
            double sx = 0, sy = 0;
            foreach (double a in v) { sx += Math.Cos(a); sy += Math.Sin(a); }
            return Math.Atan2(sy, sx);
        }

        double m0 = CMean(refsIn.Select(t => 2 * Math.PI * t / period));
        double[] off0 = refsIn.Select(t => Wrap(2 * Math.PI * t / period - m0)).Order().ToArray();
        m0 += off0[off0.Length / 2];
        double[] dev0 = refsIn.Select(t => Math.Abs(Wrap(2 * Math.PI * t / period - m0))).Order().ToArray();
        double lim = Math.Max(4 * Math.Max(dev0[dev0.Length / 2] * 1.4826, 0.15 * Math.PI / 180), 1.5 * Math.PI / 180);
        List<double> refs = refsIn.Where(t => Math.Abs(Wrap(2 * Math.PI * t / period - m0)) <= lim).ToList();
        double mean = CMean(refs.Select(t => 2 * Math.PI * t / period));
        double tMid = refs.Average();
        double[] resid = refs.Select(t => Wrap(2 * Math.PI * t / period - mean)).ToArray();
        double[] dt = refs.Select(t => t - tMid).ToArray();
        double sxx = dt.Sum(v => v * v), sxy = dt.Zip(resid, (a, b) => a * b).Sum();
        double slope = sxx > 0 ? sxy / sxx : 0, icpt = resid.Average();
        List<double> deltas = xs.Select(t => Wrap(2 * Math.PI * t / period - (mean + icpt + slope * (t - tMid)))).ToList();
        double d = CMean(deltas);
        double[] offs = deltas.Select(v => Wrap(v - d)).Order().ToArray();
        d += offs[offs.Length / 2];
        List<double> dev = deltas.Select(v => Math.Abs(Wrap(v - d))).Order().ToList();
        double robust = Math.Max(dev[dev.Count / 2] * 1.4826, 0.2 * Math.PI / 180);
        List<double> kept = deltas.Where(v => Math.Abs(Wrap(v - d)) <= Math.Max(4 * robust, 1.5 * Math.PI / 180)).ToList();
        d = d + Wrap(CMean(kept.Select(v => Wrap(v - d))));
        double sd = Math.Sqrt(kept.Sum(v => Math.Pow(Wrap(v - d), 2)) / Math.Max(1, kept.Count - 1));
        double refSd = Math.Sqrt(resid.Zip(dt, (r, x) => Math.Pow(r - icpt - slope * x, 2)).Sum() / Math.Max(1, resid.Length - 2));
        return (Wrap(d), Math.Sqrt(sd * sd / kept.Count + refSd * refSd / resid.Length), kept.Count);
    }
}
