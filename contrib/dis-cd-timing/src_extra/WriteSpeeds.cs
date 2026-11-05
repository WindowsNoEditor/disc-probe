static partial class Program
{
    // Read-only: the write speeds and rotation control the drive offers for the loaded disc.
    static void WriteSpeeds(Drive d)
    {
        d.Cmd([0x5A, 0x08, 0x2A, 0, 0, 0, 0, 0x01, 0x00, 0], 256);
        if (d.Ok)
        {
            ReadOnlySpan<byte> m = d.Data;
            int p = 8 + Be16(m, 6);
            int n = Be16(m, p + 30);
            Console.WriteLine($"page 2A: rotation selected={m[p + 27] & 3} current write speed={Be16(m, p + 28)} kB/s, {n} write-speed descriptors");
            for (int i = 0; i < n && p + 32 + 4 * i + 4 <= m.Length; i++)
            {
                int o = p + 32 + 4 * i;
                int kbps = Be16(m, o + 2);
                string rot = (m[o + 1] & 3) switch { 0 => "CLV (or zoned/partial CAV)", 1 => "pure CAV", _ => "reserved" };
                Console.WriteLine($"  {kbps,5} kB/s = {kbps / 176.4,5:F1}x  rotation {rot}");
            }
        }
        else Console.WriteLine($"MODE SENSE 2A: {d.Status}");

        d.Cmd([0xAC, 0x00, 0, 0, 0, 0, 0, 0, 0x00, 0x20, 0x03, 0], 8 + 32 * 16);
        if (d.Ok)
        {
            ReadOnlySpan<byte> g = d.Data;
            int len = Be32(g, 0) + 4;
            Console.WriteLine("GET PERFORMANCE write-speed descriptors:");
            for (int o = 8; o + 16 <= len && o + 16 <= g.Length; o += 16)
            {
                int wrc = (g[o] >> 3) & 3;
                string rot = wrc switch { 0 => "default (CLV/Z-CLV)", 1 => "CAV", _ => "reserved" };
                Console.WriteLine($"  WRC {rot}  exact={(g[o] >> 1) & 1}  end LBA {Be32(g, o + 4)}  read {Be32(g, o + 8)} kB/s  write {Be32(g, o + 12)} kB/s ({Be32(g, o + 12) / 176.4:F1}x)");
            }
        }
        else Console.WriteLine($"GET PERFORMANCE type 3: {d.Status}");
    }
}
