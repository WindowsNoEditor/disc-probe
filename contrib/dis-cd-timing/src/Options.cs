using System.Globalization;

// Command line after "<outdir> <phase>": positional arguments first, then options. An option starts with "--" and
// takes the values up to the next "--" token, so negative numbers ("-0.1") are values, not options.
sealed class Args
{
    readonly List<string> _positional = [];
    readonly Dictionary<string, List<string>> _options = new(StringComparer.Ordinal);

    public Args(IEnumerable<string> tokens)
    {
        List<string>? current = null;
        foreach (string t in tokens)
        {
            if (t.StartsWith("--", StringComparison.Ordinal))
            {
                string name = t[2..].ToLowerInvariant();
                if (name.Length == 0) throw new ArgumentException("empty option name '--'");
                if (_options.ContainsKey(name)) throw new ArgumentException($"option --{name} is given twice");
                current = [];
                _options[name] = current;
            }
            else if (current is null) _positional.Add(t);
            else current.Add(t);
        }
    }

    public IReadOnlyList<string> Positional => _positional;

    public void AllowOnly(int maxPositional, params string[] options)
    {
        if (_positional.Count > maxPositional)
            throw new ArgumentException($"too many arguments: '{string.Join(' ', _positional.Skip(maxPositional))}' (options go after the positional arguments)");
        foreach (string name in _options.Keys)
        {
            if (!options.Contains(name))
                throw new ArgumentException($"unknown option --{name} for this phase" + (options.Length > 0 ? $" (allowed: {string.Join(", ", options.Select(o => "--" + o))})" : ""));
        }
    }

    public bool Has(string name) => _options.ContainsKey(name);

    public string? Pos(int i) => i < _positional.Count ? _positional[i] : null;

    public int PosInt(int i, int fallback) => Pos(i) is string s ? ParseInt(s, $"argument {i + 1}") : fallback;

    public int? PosIntOrNull(int i) => Pos(i) is string s ? ParseInt(s, $"argument {i + 1}") : null;

    public int PosHex(int i, int fallback)
    {
        if (Pos(i) is not string s) return fallback;
        try { return Convert.ToInt32(s, 16); }
        catch (FormatException) { throw new ArgumentException($"argument {i + 1} '{s}' is not a hexadecimal speed code (e.g. 0583)"); }
        catch (OverflowException) { throw new ArgumentException($"argument {i + 1} '{s}' is out of range"); }
    }

    public double PosDouble(int i, double fallback) => Pos(i) is string s ? ParseDouble(s, $"argument {i + 1}") : fallback;

    // Values of --name as numbers; the count must be one of the allowed counts. Null when the option is absent.
    public double[]? Numbers(string name, params int[] counts)
    {
        if (!_options.TryGetValue(name, out List<string>? values)) return null;
        if (!counts.Contains(values.Count))
            throw new ArgumentException($"--{name} takes {string.Join(" or ", counts)} numbers, got {values.Count}" + (values.Count > 0 ? $" ('{string.Join(' ', values)}')" : "")
                + (values.Count > counts.Max() ? "; positional arguments go before the options" : ""));
        return values.Select(v => ParseDouble(v, "--" + name)).ToArray();
    }

    public int? Int(string name, int min, int max)
    {
        if (!_options.TryGetValue(name, out List<string>? values)) return null;
        if (values.Count != 1) throw new ArgumentException($"--{name} takes one integer");
        int v = ParseInt(values[0], "--" + name);
        if (v < min || v > max) throw new ArgumentException($"--{name} {v} is outside {min}..{max}");
        return v;
    }

    public bool Flag(string name)
    {
        if (!_options.TryGetValue(name, out List<string>? values)) return false;
        if (values.Count != 0) throw new ArgumentException($"--{name} takes no value");
        return true;
    }

    static int ParseInt(string s, string what) =>
        int.TryParse(s, NumberStyles.Integer, CultureInfo.InvariantCulture, out int v) ? v : throw new ArgumentException($"{what} '{s}' is not an integer");

    static double ParseDouble(string s, string what) =>
        double.TryParse(s, NumberStyles.Float, CultureInfo.InvariantCulture, out double v) && double.IsFinite(v)
            ? v : throw new ArgumentException($"{what} '{s}' is not a number (use a dot as the decimal separator)");
}
