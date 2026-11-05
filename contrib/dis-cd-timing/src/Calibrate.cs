using System.Text;
using System.Text.Encodings.Web;
using System.Text.Json;

// Writes everything to the console and to a file.
sealed class TeeWriter(TextWriter a, TextWriter b) : TextWriter
{
    public override Encoding Encoding => a.Encoding;

    public override void Write(char value)
    {
        a.Write(value);
        b.Write(value);
    }

    public override void Write(string? value)
    {
        a.Write(value);
        b.Write(value);
    }

    public override void WriteLine(string? value)
    {
        a.WriteLine(value);
        b.WriteLine(value);
    }

    public override void Flush()
    {
        a.Flush();
        b.Flush();
    }
}

static partial class Program
{
    // One run for a probe disc: inventory, head and ladder (all read-only), then summary.json. The console output is
    // also kept in calibrate_console.txt.
    static int Calibrate(Drive d, PriorRequest request, int? sectorsOption, int pairs, int speed, int? referenceArg, double period, string command)
    {
        TextWriter console = Console.Out;
        using StreamWriter file = new(Path.Combine(OutDir, "calibrate_console.txt"), false, new UTF8Encoding(false)) { AutoFlush = true };
        Console.SetOut(new TeeWriter(console, file));
        try
        {
            return CalibrateCore(d, request, sectorsOption, pairs, speed, referenceArg, period, command);
        }
        finally
        {
            Console.SetOut(console);
        }
    }

    static int CalibrateCore(Drive d, PriorRequest request, int? sectorsOption, int pairs, int speed, int? referenceArg, double period, string command)
    {
        Console.WriteLine($"calibrate {DateTime.Now:yyyy-MM-dd HH:mm:ss}: {Path.GetFullPath(OutDir)}");
        Console.WriteLine($"drive: {d.Model}");
        Console.WriteLine("=== 1/3 inventory");
        DiscInfo info = Inventory(d);
        if (info.IsBlank || info.Sectors is not int discSectors)
        {
            Console.WriteLine("STOP: no burned track to measure. Burn the probe disc first (sector count as printed above), then run calibrate again.");
            WriteSummary("calibrate", command, d.Model, info, null, null, null);
            return 3;
        }

        if (!info.IsAppBurn)
        {
            Console.WriteLine("STOP: the disc is not one audio track starting at LBA 0, so it was not burned by the app; the ladder would be meaningless.");
            WriteSummary("calibrate", command, d.Model, info, null, null, null);
            return 3;
        }

        int sectors = sectorsOption ?? discSectors;
        if (sectors != discSectors) Console.WriteLine($"note: --sectors {sectors} overrides the disc's {discSectors}");
        Disc = request.Build(sectors);
        int reference = referenceArg ?? LadderRun.DefaultReference(Disc);
        LadderRun.CheckReference(reference, sectors);
        Console.WriteLine($"prior: {Disc.Describe()}");
        Console.WriteLine($"reference LBA {reference} ({(referenceArg is null ? "40 mm on the prior" : "given")}, prior radius {Disc.RadiusOfLba(reference):F3} mm); "
            + $"band LBA {LadderRun.InnerLimitFor(sectors)}..{LadderRun.OuterLimitFor(sectors)}; {pairs} pairs at speed 0x{speed:X4}");

        Console.WriteLine("=== 2/3 head");
        Framing.Result? s = Head(d);

        Console.WriteLine("=== 3/3 ladder (about 14 minutes: do not open the drive in Explorer and do not stop the program)");
        LadderOutcome outcome = LadderReal(d, pairs, speed, reference, period);
        WriteSummary("calibrate", command, d.Model, info, referenceArg is null ? "40 mm on the prior" : "given", s, outcome);

        string dir = Path.GetFullPath(OutDir);
        Console.WriteLine();
        if (outcome.Completed)
        {
            Console.WriteLine($"done: {outcome.Run!.Rungs.Count} rungs in {outcome.Minutes:F1} min; summary.json written. Next (no drive needed):");
            Console.WriteLine($"  python -I analysis\\calibrate.py --head \"{Path.Combine(dir, "head_lba0-7.bin")}\" --sectors {sectors} \"{dir}\"");
            Console.WriteLine("  (--sectors is the sector count of the burn the radii are for; constant, quadratic and cubic fits use ladder_raw.csv and ladder_rungs.csv)");
            return 0;
        }

        Console.WriteLine($"the ladder did not complete ({outcome.Status}); see ladder_log.txt. Do not use these files for a calibration; run calibrate again.");
        return 1;
    }

    // summary.json: capacity, ATIP, framing offset s, period, reference, prior and the ladder outcome.
    static void WriteSummary(string phase, string command, string drive, DiscInfo? info, string? referenceChoice, Framing.Result? s, LadderOutcome? outcome)
    {
        using FileStream fs = File.Create(Path.Combine(OutDir, "summary.json"));
        using Utf8JsonWriter j = new(fs, new JsonWriterOptions { Indented = true, Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping });
        void Num(string name, double? v)
        {
            if (v is double x && double.IsFinite(x)) j.WriteNumber(name, x);
            else j.WriteNull(name);
        }

        void Int(string name, int? v)
        {
            if (v is int x) j.WriteNumber(name, x);
            else j.WriteNull(name);
        }

        j.WriteStartObject();
        j.WriteString("probe", "cd-timing-probe, capacity-aware (2026-11-04)");
        j.WriteString("phase", phase);
        j.WriteString("command", command);
        j.WriteString("created", DateTimeOffset.Now.ToString("yyyy-MM-ddTHH:mm:sszzz"));
        j.WriteString("drive", drive);
        bool measured = outcome is not null;

        j.WriteStartObject("capacity");
        Int("sectors_used", measured ? Sectors : null);
        j.WriteString("sectors_source", !measured ? "not measured" : info is not null && info.Sectors == Sectors ? info.SectorsSource : "--sectors");
        Int("toc_lead_out_lba", info?.TocLeadOut);
        Int("read_capacity_last_lba", info?.ReadCapacityLastLba);
        Int("atip_capacity_sectors", info?.AtipCapacity);
        Int("disc_status", info?.DiscStatus);
        Int("tracks", info?.TrackCount);
        Int("first_track_lba", info?.FirstTrack?.Lba);
        if (info?.FirstTrack is TocEntry first) j.WriteBoolean("first_track_audio", first.IsAudio);
        else j.WriteNull("first_track_audio");
        j.WriteEndObject();

        if (info?.AtipLeadIn is Msf li && info.AtipLeadOut is Msf lo)
        {
            j.WriteStartObject("atip");
            j.WriteString("lead_in_start", li.ToString());
            j.WriteNumber("lead_in_start_lba", li.Lba);
            j.WriteString("last_lead_out_start", lo.ToString());
            j.WriteNumber("last_lead_out_start_lba", lo.Lba);
            j.WriteString("disc_type", info.Rewritable == true ? "CD-RW" : "CD-R");
            j.WriteEndObject();
        }
        else j.WriteNull("atip");

        if (s is not null)
        {
            j.WriteStartObject("framing_offset_s");
            j.WriteNumber("bytes", s.S);
            j.WriteNumber("mismatches", s.Mismatches);
            j.WriteNumber("runner_up", s.RunnerUp);
            j.WriteBoolean("unique", s.Unique);
            j.WriteString("note", "diagnostic only, never applied to r0/r1 (HP BU20N app burns: -532)");
            j.WriteEndObject();
        }
        else j.WriteNull("framing_offset_s");

        if (!measured)
        {
            j.WriteNull("prior");
            j.WriteNull("reference");
            j.WriteNull("period");
            j.WriteNull("ladder");
            j.WriteEndObject();
            return;
        }

        LadderRun? run = outcome!.Run;
        j.WriteStartObject("prior");
        j.WriteString("source", Disc.Source);
        j.WriteNumber("r0_mm", Disc.R0);
        j.WriteNumber("r1_mm", Disc.R1);
        j.WriteNumber("c1", Disc.Track.C1);
        j.WriteNumber("c2", Disc.Track.C2);
        j.WriteNumber("c3", Disc.Track.C3);
        j.WriteNumber("sectors", Disc.Sectors);
        j.WriteNumber("mean_pitch_um", Disc.MeanPitchUm);
        j.WriteNumber("sigma_r0_mm", Disc.SigmaR0Mm);
        j.WriteNumber("sigma_pitch_fraction", Disc.SigmaPitch);
        Geometry start = Disc.Tangent(outcome.Reference);
        j.WriteStartObject("ladder_start_constant_pitch");
        j.WriteNumber("r0_mm", start.R0);
        j.WriteNumber("r1_mm", start.R1(Disc.Sectors));
        j.WriteNumber("pitch_um", start.PitchUm);
        j.WriteEndObject();
        j.WriteEndObject();

        j.WriteStartObject("reference");
        j.WriteNumber("lba", outcome.Reference);
        j.WriteString("choice", referenceChoice ?? "given");
        j.WriteNumber("prior_radius_mm", Disc.RadiusOfLba(outcome.Reference));
        Num("fit_radius_mm", run?.Fit.RadiusOfLba(outcome.Reference));
        j.WriteNumber("band_inner_lba", LadderRun.InnerLimitFor(Sectors));
        j.WriteNumber("band_outer_lba", LadderRun.OuterLimitFor(Sectors));
        j.WriteEndObject();

        j.WriteStartObject("period");
        j.WriteString("speed", $"{outcome.SpeedHex:X4}");
        Num("settle_ms", outcome.SettlePeriodMs);
        Num("settle_coherence", outcome.SettleCoherence);
        Num("settle_scatter_deg", outcome.SettleScatterDeg);
        Num("last_rung_ms", run?.Period);
        j.WriteEndObject();

        j.WriteStartObject("ladder");
        j.WriteBoolean("completed", outcome.Completed);
        j.WriteString("status", outcome.Status);
        j.WriteNumber("pairs", outcome.Pairs);
        Num("minutes", outcome.Minutes);
        if (run is not null)
        {
            j.WriteNumber("rungs", run.Rungs.Count);
            j.WriteNumber("attempts", run.Attempts);
            j.WriteNumber("confirmed", run.Confirmed);
            j.WriteNumber("remeasured", run.Remeasured);
            j.WriteNumber("skipped", run.Skipped);
            j.WriteNumber("max_abs_miss_deg", run.MaxAbsMissDeg);
            j.WriteStartObject("fit_constant_pitch");
            j.WriteString("note", "the probe's own unwrapping fit; use calibrate.py and the cubic tools for the burn values");
            j.WriteNumber("r0_mm", run.Fit.R0);
            j.WriteNumber("r1_mm", run.Fit.R1(Sectors));
            j.WriteNumber("pitch_um", run.Fit.PitchUm);
            j.WriteNumber("kappa_deg", run.Kappa * 180 / Math.PI);
            Num("chi2_dof", run.Rungs.Count > 3 ? run.ChiSquarePerDof() : null);
            Num("residual_rms_deg", run.Rungs.Count > 0 ? Math.Sqrt(run.Rungs.Average(r => Math.Pow(run.Residual(r), 2))) * 180 / Math.PI : null);
            Num("residual_max_deg", run.Rungs.Count > 0 ? run.Rungs.Max(r => Math.Abs(run.Residual(r))) * 180 / Math.PI : null);
            j.WriteEndObject();
            j.WriteStartObject("twist_fit_vs_prior_turns");
            j.WriteString("note", "turns a straight spoke burned with the prior winds from the reference to this LBA, on the constant-pitch fit");
            foreach ((string name, int lba) in new[] { ("lba_0", 0), ("band_inner", run.InnerLimit), ("band_outer", run.OuterLimit), ("last_sector", Sectors - 1) })
                j.WriteNumber(name, TwistTurns(run.Fit, Disc.Track, outcome.Reference, lba));
            j.WriteEndObject();
        }

        j.WriteEndObject();
        j.WriteStartArray("files");
        foreach (string f in new[] { "calibrate_console.txt", "head_lba0-7.bin", "content_samples.bin", "content_samples_lba.csv", "ladder_raw.csv",
                     "ladder_rungs.csv", "ladder_rejected.csv", "ladder_log.txt" })
        {
            if (File.Exists(Path.Combine(OutDir, f))) j.WriteStringValue(f);
        }

        j.WriteEndArray();
        j.WriteEndObject();
    }
}
