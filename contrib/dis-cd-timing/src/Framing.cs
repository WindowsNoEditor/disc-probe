// Framing offset s from the app's interleaver zero staircase at the start of the track; a port of
// analysis\calibrate.py framing_offset (same expected pattern, span, search range and tie order). READ CD of LBA k
// returns file bytes 2352 k + j + s. Diagnostic only: it shows an app burn with interleave on and fingerprints the
// drive pair; it is never applied to r0/r1 (spec, Erratum).
static class Framing
{
    const int Fpc = 112, Bpf = 24;

    public sealed record Result(int S, int Mismatches, int RunnerUp)
    {
        public int Margin => RunnerUp - Mismatches;
        public bool Unique => Mismatches <= 2 && Margin >= 20;

        public override string ToString() =>
            $"s = {S} bytes ({S / 4.0:F2} samples, {S / 24.0:F3} frames); {Mismatches} mismatches, runner-up {RunnerUp} (margin {Margin})";
    }

    static int[] Delays()
    {
        int[] k0e = [0, 8, 16, 2, 10, 18], k0o = [4, 12, 20, 6, 14, 22];
        int[] d = new int[24];
        for (int i = 0; i < 12; i++)
        {
            int odd = i & 1;
            d[i] = odd - 24 * (i * 4 + (odd == 1 ? 2 : 3)) + k0e[i / 2];
        }

        for (int i = 12; i < 24; i++)
        {
            int odd = (i - 12) & 1;
            d[i] = odd - 24 * ((i + 4) * 4 + (odd == 1 ? 0 : 1)) + k0o[(i - 12) / 2];
        }

        return d;
    }

    // Zero bytes the interleaver emits for 12 sectors of 0xAA input (its delay line starts with zeros).
    static bool[] ExpectedZeros()
    {
        int[] delay = Delays();
        byte[] seq = new byte[Fpc * Bpf], sector = new byte[2352];
        List<bool> zeros = new(2352 * 12);
        int head = Fpc - 1, pos = 0, fill = 0;
        for (int n = 0; n < 2352 * 12; n++)
        {
            int idx = head * Bpf + delay[pos];
            if (idx >= seq.Length) idx -= seq.Length;
            else if (idx < 0) idx += seq.Length;
            seq[idx] = 0xAA;
            if (++pos < Bpf) continue;
            pos = 0;
            head = head + 1 >= Fpc ? 0 : head + 1;
            for (int j = 0; j < Bpf; j++) sector[fill++] = seq[head * Bpf + j];
            if (fill < sector.Length) continue;
            for (int i = 0; i < sector.Length; i += 2) (sector[i], sector[i + 1]) = (sector[i + 1], sector[i]);
            foreach (byte b in sector) zeros.Add(b == 0);
            fill = 0;
        }

        return [.. zeros];
    }

    public static Result Offset(ReadOnlySpan<byte> head, int span = 6000, int search = 6000)
    {
        if (head.Length < span) throw new ArgumentException($"need at least {span} bytes from LBA 0, got {head.Length}");
        bool[] expected = ExpectedZeros();
        bool[] obs = new bool[span];
        for (int j = 0; j < span; j++) obs[j] = head[j] == 0;
        int best = int.MaxValue, bestS = 0, second = int.MaxValue;
        for (int s = -search; s <= search; s++)
        {
            int bad = 0;
            for (int j = 0; j < span; j++)
            {
                int f = j + s;
                bool e = f < 0 || (f < expected.Length && expected[f]);
                if (e != obs[j]) bad++;
            }

            if (bad < best)
            {
                second = best;
                best = bad;
                bestS = s;
            }
            else if (bad < second) second = bad;
        }

        return new Result(bestS, best, second);
    }
}
