using System.Diagnostics;
using System.Runtime.InteropServices;

// Read-only MMC access through IMAPI2 (works without administrator rights).
// The probe only ever sends commands from AllowedOpcodes; anything else throws.
[ComImport, Guid("27354132-7F64-5B0F-8F00-5D77AFBE261E"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IDiscRecorder2Ex
{
    [PreserveSig] int SendCommandNoData(IntPtr cdb, uint cdbSize, IntPtr sense, uint timeout);
    [PreserveSig] int SendCommandSendDataToDevice(IntPtr cdb, uint cdbSize, IntPtr sense, uint timeout, IntPtr buffer, uint bufferSize);
    [PreserveSig] int SendCommandGetDataFromDevice(IntPtr cdb, uint cdbSize, IntPtr sense, uint timeout, IntPtr buffer, uint bufferSize, out uint fetched);
}

sealed unsafe class Drive : IDisposable
{
    public const int BufferBytes = 1 << 16;
    public static readonly double UsPerTick = 1e6 / Stopwatch.Frequency;

    // TUR, INQUIRY, READ CAPACITY, READ TOC/ATIP, GET CONFIGURATION, READ DISC INFO,
    // MODE SENSE(10), GET PERFORMANCE, READ(12), SET CD SPEED, READ CD.
    static readonly HashSet<byte> AllowedOpcodes = [0x00, 0x12, 0x25, 0x43, 0x46, 0x51, 0x5A, 0xAC, 0xA8, 0xBB, 0xBE];

    readonly dynamic _recorder;
    readonly IDiscRecorder2Ex _ex;
    readonly byte* _cdb;
    readonly byte* _sense;
    readonly byte* _buffer;
    bool _locked;
    bool _mcnDisabled;
    bool _disposed;

    public long T0;
    public long T1;
    public int Hr;
    public uint Fetched;

    public Drive(string volume)
    {
        dynamic master = Activator.CreateInstance(Type.GetTypeFromProgID("IMAPI2.MsftDiscMaster2", true)!)!;
        dynamic? found = null;
        int count = master.Count;
        for (int i = 0; i < count && found is null; i++)
        {
            string id = master.Item(i);
            dynamic recorder = Activator.CreateInstance(Type.GetTypeFromProgID("IMAPI2.MsftDiscRecorder2", true)!)!;
            recorder.InitializeDiscRecorder(id);
            foreach (object? path in (Array)recorder.VolumePathNames)
            {
                if (string.Equals(path as string, volume, StringComparison.OrdinalIgnoreCase))
                    found = recorder;
            }
        }

        _recorder = found ?? throw new InvalidOperationException($"No recorder at {volume}");
        _recorder.AcquireExclusiveAccess(false, "DISProbe");
        _locked = true;
        _recorder.DisableMcn();
        _mcnDisabled = true;
        _ex = (IDiscRecorder2Ex)(object)_recorder;
        _cdb = (byte*)NativeMemory.AllocZeroed(16);
        _sense = (byte*)NativeMemory.AllocZeroed(18);
        _buffer = (byte*)NativeMemory.AlignedAlloc(BufferBytes, 4096);
    }

    public string Model => $"{((string)_recorder.VendorId).Trim()} {((string)_recorder.ProductId).Trim()} {((string)_recorder.ProductRevision).Trim()}";

    public int Cmd(ReadOnlySpan<byte> cdb, int dataIn, uint timeoutSeconds = 30)
    {
        if (cdb.Length is 0 or > 16)
            throw new InvalidOperationException($"CDB length {cdb.Length} is outside 1..16.");
        if (!AllowedOpcodes.Contains(cdb[0]))
            throw new InvalidOperationException($"Opcode 0x{cdb[0]:X2} is not on the read-only allow list.");
        if (cdb[0] == 0xA8 && (cdb[6] | cdb[7] | cdb[8] | cdb[9]) != 0 && dataIn == 0)
            throw new InvalidOperationException("READ(12) with data must use the data-in path.");
        for (int i = 0; i < 16; i++) _cdb[i] = i < cdb.Length ? cdb[i] : (byte)0;
        for (int i = 0; i < 18; i++) _sense[i] = 0;
        uint fetched = 0;
        T0 = Stopwatch.GetTimestamp();
        Hr = dataIn > 0
            ? _ex.SendCommandGetDataFromDevice((IntPtr)_cdb, (uint)cdb.Length, (IntPtr)_sense, timeoutSeconds, (IntPtr)_buffer, (uint)dataIn, out fetched)
            : _ex.SendCommandNoData((IntPtr)_cdb, (uint)cdb.Length, (IntPtr)_sense, timeoutSeconds);
        T1 = Stopwatch.GetTimestamp();
        Fetched = fetched;
        return Hr;
    }

    public ReadOnlySpan<byte> Data => new(_buffer, (int)Fetched);
    public ReadOnlySpan<byte> Sense => new(_sense, 18);
    public bool Ok => Hr == 0;
    public double ElapsedUs => (T1 - T0) * UsPerTick;
    public string Status => Hr == 0 ? "ok" : $"hr=0x{Hr:X8} sense={Sense[2] & 0xF:X}/{Sense[12]:X2}/{Sense[13]:X2}";

    // SET CD SPEED: read speed in kB/s (0xFFFF = maximum), write speed left at maximum.
    public int SetReadSpeed(int kbps, bool pureCav = false)
    {
        Span<byte> cdb = [0xBB, (byte)(pureCav ? 1 : 0), (byte)(kbps >> 8), (byte)kbps, 0xFF, 0xFF, 0, 0, 0, 0, 0, 0];
        return Cmd(cdb, 0);
    }

    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        try { SetReadSpeed(0xFFFF); } catch { }
        try { if (_mcnDisabled) _recorder.EnableMcn(); } catch { }
        try { if (_locked) _recorder.ReleaseExclusiveAccess(); } catch { }
        NativeMemory.Free(_cdb);
        NativeMemory.Free(_sense);
        NativeMemory.AlignedFree(_buffer);
    }
}
