// What the disc says about itself (read-only): READ DISC INFORMATION, READ TOC, ATIP and READ CAPACITY.
sealed record Msf(int M, int S, int F)
{
    // MMC addressing: LBA 0 = 00:02:00; lead-in times are given as minutes >= 90 (negative LBA).
    public int Lba => (M * 60 + S) * 75 + F - (M >= 90 ? 450_150 : 150);

    public override string ToString() => $"{M:D2}:{S:D2}:{F:D2}";
}

sealed record TocEntry(int Track, int Control, int Adr, int Lba)
{
    public bool IsAudio => (Control & 0x4) == 0;
}

sealed class DiscException(string message) : Exception(message);

sealed class DiscInfo
{
    public int? DiscStatus, Sessions, FirstTrackNumber, LastTrackLastSession, TocFirst, TocLast;
    public List<TocEntry> Toc { get; } = [];
    public string? TocStatus;
    public Msf? AtipLeadIn, AtipLeadOut;
    public bool? Rewritable;
    public int? ReadCapacityLastLba, BlockLength;

    public TocEntry? FirstTrack => Toc.FirstOrDefault(t => t.Track != 0xAA);
    public int TrackCount => Toc.Count(t => t.Track != 0xAA);
    public int? TocLeadOut => Toc.FirstOrDefault(t => t.Track == 0xAA)?.Lba;

    // The ATIP's last possible lead-out start is the capacity of the blank in sectors (79:59:70 = LBA 359845).
    public int? AtipCapacity => AtipLeadOut?.Lba;
    public bool IsBlank => DiscStatus == 0 || (TrackCount == 0 && ReadCapacityLastLba is not > 0);

    // Sector count of the burned track: the TOC lead-out (one track from LBA 0), else READ CAPACITY.
    public int? Sectors => TocLeadOut is int t && t > 0 ? t : ReadCapacityLastLba is int l && l > 0 ? l + 1 : null;
    public string SectorsSource => TocLeadOut is int t && t > 0 ? "TOC lead-out" : "READ CAPACITY";
    public bool IsAppBurn => TrackCount == 1 && FirstTrack is { Lba: 0, IsAudio: true };
}

static partial class Program
{
    static DiscInfo? DiscRead;

    static DiscInfo ReadDiscInfo(Drive d)
    {
        DiscInfo i = new();
        d.Cmd([0x51, 0, 0, 0, 0, 0, 0, 0, 34, 0], 34);
        if (d.Ok && d.Fetched >= 7)
        {
            i.DiscStatus = d.Data[2] & 3;
            i.FirstTrackNumber = d.Data[3];
            i.Sessions = d.Data[4];
            i.LastTrackLastSession = d.Data[6];
        }

        d.Cmd([0x43, 0, 0, 0, 0, 0, 1, 0x03, 0x24, 0], 804);
        if (d.Ok && d.Fetched >= 4)
        {
            ReadOnlySpan<byte> t = d.Data;
            int len = Be16(t, 0) + 2;
            i.TocFirst = t[2];
            i.TocLast = t[3];
            for (int o = 4; o + 8 <= len && o + 8 <= t.Length; o += 8)
                i.Toc.Add(new TocEntry(t[o + 2], t[o + 1] & 0xF, t[o + 1] >> 4, Be32(t, o + 4)));
        }
        else i.TocStatus = d.Status;

        d.Cmd([0x43, 0x02, 0x04, 0, 0, 0, 0, 0, 0x20, 0], 32);
        if (d.Ok && d.Fetched >= 15)
        {
            ReadOnlySpan<byte> a = d.Data;
            i.AtipLeadIn = new Msf(a[8], a[9], a[10]);
            i.AtipLeadOut = new Msf(a[12], a[13], a[14]);
            i.Rewritable = ((a[6] >> 6) & 1) == 1;
        }

        d.Cmd([0x25, 0, 0, 0, 0, 0, 0, 0, 0, 0], 8);
        if (d.Ok && d.Fetched >= 8)
        {
            i.ReadCapacityLastLba = Be32(d.Data, 0);
            i.BlockLength = Be32(d.Data, 4);
        }

        DiscRead = i;
        return i;
    }

    static string DescribeCapacity(DiscInfo i) =>
        $"TOC lead-out {(i.TocLeadOut is int t ? $"LBA {t}" : "none")}, "
        + $"READ CAPACITY {(i.ReadCapacityLastLba is int l ? $"{l + 1} sectors (last LBA {l})" : "n/a")}, "
        + $"ATIP capacity {(i.AtipCapacity is int c ? $"{c} sectors ({i.AtipLeadOut})" : "n/a")}"
        + (i.Sectors is int n ? $" -> {n} sectors ({n / 4500.0:F2} min, {i.SectorsSource})" : "");

    // The capacity part of the inventory: what to burn and what the ladder will use.
    static void PrintCapacity(DiscInfo i)
    {
        if (i.AtipLeadIn is Msf li && i.AtipLeadOut is Msf lo)
            Console.WriteLine($"ATIP: lead-in start {li} (LBA {li.Lba}), last possible lead-out start {lo} (LBA {lo.Lba}) "
                + $"= capacity {lo.Lba} sectors ({lo.Lba / 4500.0:F2} min), {(i.Rewritable == true ? "CD-RW" : "CD-R")}");
        else Console.WriteLine("ATIP: not available (pressed disc or drive without ATIP)");
        Console.WriteLine($"capacity: {DescribeCapacity(i)}");
        if (i.IsBlank)
        {
            Console.WriteLine(i.AtipCapacity is int c
                ? $"==> blank disc: burn the probe disc with the sector count {c} (ATIP capacity) in the project settings"
                : "==> blank disc without ATIP: the capacity is unknown");
            return;
        }

        if (!i.IsAppBurn)
            Console.WriteLine($"warning: {i.TrackCount} track(s), first at LBA {i.FirstTrack?.Lba} ({(i.FirstTrack?.IsAudio == true ? "audio" : "data")}); "
                + "the ladder expects one audio track at LBA 0 as the app burns it");
        if (i.Sectors is int n)
        {
            Console.WriteLine($"==> sector count to use: {n} ({i.SectorsSource} of the burned track)");
            if (i.AtipCapacity is int c && c != n)
                Console.WriteLine($"note: the blank holds {c} sectors (ATIP) but this disc was burned with {n}; "
                    + "give calibrate.py --sectors the sector count of the final burns");
            if (i.ReadCapacityLastLba is int l && i.TocLeadOut is int t && l + 1 != t)
                Console.WriteLine($"note: READ CAPACITY ({l + 1} sectors) and the TOC lead-out ({t}) differ; the TOC lead-out is used");
        }
    }
}
