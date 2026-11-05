using System.Diagnostics;

static partial class Program
{
    // autocal: calibrate on an unknown drive. The timing method needs a speed at which the drive spins at constant
    // angular velocity (CAV): one revolution period, the same at every radius. This phase looks for such a speed
    // (reads of one sector repeat modulo the revolution, at an inner, a middle and an outer radius), then runs the
    // normal calibrate (inventory, head, ladder) with that speed and period and a reference at 41.5 mm on the prior,
    // clear of the probe pattern's 40 mm ring. Read-only, like every other phase.
    static readonly int[] AutoSpeeds = [0x0583, 0x06E4, 0x0B06, 0x02C2, 0x108A, 0xFFFF];
    const double CavTolerance = 0.003;   // the three periods must agree to 0.3 %
    const double MinCoherence = 0.90;

    static int AutoCal(Drive d, PriorRequest prior, int? sectorsOption, int pairs, string command)
    {
        Console.WriteLine($"autocal {DateTime.Now:yyyy-MM-dd HH:mm:ss}: {Path.GetFullPath(OutDir)}");
        UseDisc(d, prior, sectorsOption);
        int reference = LbaAt(41.5);
        LadderRun.CheckReference(reference, Sectors);
        int[] lbas = [LbaAt(Disc.R0 + 1.08), reference, LbaAt(Disc.EndRadius - 0.34)];
        Random rng = new(4321);
        List<string> rows = ["speed,radius_mm,lba,period_ms,coherence,scatter_deg,reads"];
        (int Speed, double Period)? chosen = null;
        Console.WriteLine("=== 0/3 looking for a constant-angular-velocity read speed");
        foreach (int speed in AutoSpeeds)
        {
            d.SetReadSpeed(speed);
            Console.WriteLine($"SET CD SPEED 0x{speed:X4} ({(speed == 0xFFFF ? "max" : (speed / 176.4).ToString("F1") + "x")}): {d.Status}");
            long settleUntil = Stopwatch.GetTimestamp() + (long)(4e6 / Drive.UsPerTick);
            while (Stopwatch.GetTimestamp() < settleUntil) ReadCd(d, lbas[0] + rng.Next(0, 2000));

            List<(double Period, double Coherence)> found = [];
            foreach (int lba in lbas)
            {
                List<double> t = [];
                int far = Seek.Far(lba, Sectors);
                for (int rep = 0; rep < 40; rep++)
                {
                    ReadCd(d, far);
                    SpinWaitUs(rng.NextDouble() * 20_000);
                    ReadCd(d, lba);
                    if (d.Ok) t.Add(d.T1 * Drive.UsPerTick / 1000);
                }

                (double period, double coherence, double scatter, _) = BestPeriod(t);
                found.Add((period, coherence));
                rows.Add($"{speed:X4},{RadiusOf(lba):F2},{lba},{period:F5},{coherence:F4},{scatter:F2},{t.Count}");
                Console.WriteLine($"  r={RadiusOf(lba):F2} mm: period {period:F4} ms ({60_000 / period:F0} rpm), coherence {coherence:F3}, {t.Count} reads");
            }

            bool coherent = found.All(f => f.Coherence >= MinCoherence && double.IsFinite(f.Period));
            double pMin = found.Min(f => f.Period), pMax = found.Max(f => f.Period);
            bool cav = coherent && pMax / pMin - 1 <= CavTolerance;
            Console.WriteLine(cav
                ? $"  -> CAV: the three periods agree to {100 * (pMax / pMin - 1):F3} %"
                : coherent ? $"  -> not CAV: periods differ by {100 * (pMax / pMin - 1):F2} % (the drive changes speed with radius)"
                           : "  -> no stable period at every radius");
            if (cav)
            {
                chosen = (speed, found[1].Period);
                break;
            }
        }

        File.WriteAllLines(Path.Combine(OutDir, "autocal_speeds.csv"), rows);
        if (chosen is not (int s, double p))
        {
            Console.WriteLine("STOP: this drive spins at no tested speed with one period at every radius, so the timing method cannot run on it.");
            Console.WriteLine("      Send the output folder to the maintainer.");
            return 3;
        }

        Console.WriteLine($"=== using speed 0x{s:X4}, period {p:F4} ms, reference LBA {reference} (41.5 mm on the prior)");
        return Calibrate(d, prior, sectorsOption, pairs, s, reference, p, command);
    }
}
