using System.Numerics;

static partial class Program
{
    // Read-only search for a write link: every sector in [start, end) with C2 error flags and raw P-W
    // subcode. A link usually leaves damaged frames (C2) or broken Q subcode (CRC / address) at the spot.
    static void LinkScan(Drive d, int start, int end)
    {
        const int Per = 2352 + 294 + 96;
        const int Chunk = 16;
        List<string> rows = ["lba,c2_bits,q_crc_ok,q_adr,q_abs_lba,status"];
        int bad = 0, c2Sectors = 0, qBad = 0;
        Span<byte> q = stackalloc byte[12];
        for (int lba = start; lba < end; lba += Chunk)
        {
            int n = Math.Min(Chunk, end - lba);
            Span<byte> cdb = [0xBE, 0x04, (byte)(lba >> 24), (byte)(lba >> 16), (byte)(lba >> 8), (byte)lba,
                0, 0, (byte)n, 0x12, 0x01, 0];
            d.Cmd(cdb, n * Per);
            if (!d.Ok || d.Fetched < n * Per)
            {
                bad++;
                rows.Add($"{lba},,,,,\"{d.Status}\"");
                continue;
            }

            ReadOnlySpan<byte> data = d.Data;
            for (int i = 0; i < n; i++)
            {
                ReadOnlySpan<byte> s = data.Slice(i * Per, Per);
                int c2 = 0;
                foreach (byte b in s.Slice(2352, 294)) c2 += BitOperations.PopCount(b);
                q.Clear();
                ReadOnlySpan<byte> pw = s.Slice(2352 + 294, 96);
                for (int bit = 0; bit < 96; bit++)
                    if ((pw[bit] & 0x40) != 0) q[bit >> 3] |= (byte)(0x80 >> (bit & 7));
                ushort crc = Crc16Ccitt(q[..10]);
                bool crcOk = (ushort)~crc == (ushort)((q[10] << 8) | q[11]);
                int adr = q[0] & 0x0F;
                int absLba = adr == 1 ? (Bcd(q[7]) * 60 + Bcd(q[8])) * 75 + Bcd(q[9]) - 150 : -1;
                if (c2 > 0) c2Sectors++;
                if (!crcOk || (adr == 1 && absLba != lba + i)) qBad++;
                rows.Add($"{lba + i},{c2},{(crcOk ? 1 : 0)},{adr},{absLba},ok");
            }
        }

        File.WriteAllLines(Path.Combine(OutDir, $"linkscan_{start}_{end}.csv"), rows);
        Console.WriteLine($"linkscan {start}..{end}: {end - start} sectors, failed commands {bad}, sectors with C2 {c2Sectors}, "
            + $"sectors with bad/unexpected Q {qBad}");
        foreach (string row in rows.Skip(1).Where(r => !r.Contains(",0,1,1,") || r.EndsWith(",ok") == false).Take(60))
            Console.WriteLine("  " + row);
    }

    static int Bcd(byte b) => (b >> 4) * 10 + (b & 0x0F);

    static ushort Crc16Ccitt(ReadOnlySpan<byte> bytes)
    {
        ushort crc = 0;
        foreach (byte b in bytes)
        {
            crc ^= (ushort)(b << 8);
            for (int k = 0; k < 8; k++) crc = (crc & 0x8000) != 0 ? (ushort)((crc << 1) ^ 0x1021) : (ushort)(crc << 1);
        }

        return crc;
    }

    // Phase of each target relative to one reference, against a prior spiral (for unwrapping only).
    // Neighbouring targets on either side of a write link differ by the link's along-track step.
    static void LocalSteps(Drive d, int reference, int pairs, int speedHex, Geometry prior, int[] targets)
    {
        d.SetReadSpeed(speedHex);
        Console.WriteLine($"SET CD SPEED 0x{speedHex:X4}: {d.Status}; prior r0={prior.R0:F7}");
        DriveReader reader = new(d);
        Random rng = new(7);
        List<double> settle = [];
        for (int i = 0; i < 40; i++)
        {
            (double tc, double dur, bool ok) = reader.Read(reference, rng.NextDouble() * 60);
            if (ok && dur > 8.5) settle.Add(tc);
        }

        (double period, double coherence, double scatter, _) = BestPeriodNear(settle, 48.35);
        Console.WriteLine($"settle: period={period:F5} ms coherence={coherence:F3} scatter={scatter:F2} deg; reference {reference}");
        List<string> rows = ["target,radius_mm,bytes_per_deg,measured_minus_prior_deg,sigma_deg,used"];
        foreach (int target in targets)
        {
            List<double> refs = [], xs = [];
            for (int k = 0; k < pairs; k++)
            {
                (double a, double da, bool oka) = reader.Read(reference, rng.NextDouble() * 1.2 * period);
                if (oka && da > 8.5) refs.Add(a);
                (double x, double dx, bool okx) = reader.Read(target, rng.NextDouble() * 1.2 * period);
                if (okx && dx > 8.5) xs.Add(x);
            }

            if (refs.Count < 6 || xs.Count < 6) { Console.WriteLine($"  {target}: unusable"); continue; }
            (double delta, double sigma, int used) = PhaseDelta(refs, xs, period);
            double predicted = prior.ThetaOfLba(target) - prior.ThetaOfLba(reference);
            double wraps = Math.Round((predicted - delta) / (2 * Math.PI));
            double miss = (delta + 2 * Math.PI * wraps - predicted) * 180 / Math.PI;
            double r = prior.RadiusMm(Geometry.SectorBytes * (target + 1.0));
            double bytesPerDeg = Math.PI / 180 * r / Geometry.ByteMm;
            Console.WriteLine($"  target {target,6} r={r:F3} mm: measured-prior {miss,8:F3} deg +- {sigma * 180 / Math.PI:F3}"
                + $"  ({miss * bytesPerDeg,7:F0} bytes)  used {used}/{pairs}");
            rows.Add($"{target},{r:F4},{bytesPerDeg:F2},{miss:F4},{sigma * 180 / Math.PI:F4},{used}");
        }

        File.WriteAllLines(Path.Combine(OutDir, $"localsteps_{reference}.csv"), rows);
    }
}
