#!/usr/bin/env python3
# Project file (.discproj) for the probe disc of a NEW CD-R model: one-disc calibration (README section
# "换新型号：一张盘完成标定", spec 6.6). It writes the project (and, with --make-pattern, a matching probe pattern);
# it never opens the drive.
#
#   python -I make_probe_project.py --sectors N [--radii RI RO] [--pitch C1 C2 C3]
#          [--pattern PNG [--allow-band-mismatch] | --make-pattern PNG [--no-gauge]] [--name NAME]
#          [--out FILE.discproj] [--audio FILE.wav] [--run-dir DIR] [--template FILE|none] [--force]
#   e.g. (README step 2): python -I analysis\make_probe_project.py --sectors 359845
#          --make-pattern patterns\probe_maxell80.png --name 探测盘_maxell80 --run-dir out\maxell80
#
#   --sectors N       the blank's ATIP capacity. "bin\Probe.exe <dir> inventory" on the blank prints
#                     "==> blank disc: burn the probe disc with the sector count N (ATIP capacity) ...".
#   --radii RI RO     nominal radii to burn with (mm). Default: the generic 80-minute value scaled to N, which is
#                     exactly the probe's default prior (src/Track.cs, Prior.Generic): ri = 24.92 mm, constant
#                     pitch 1.4865 um, ro = sqrt(ri^2 + 1.4865e-3 * 16 * N / pi) (57.8384 mm at 359845 sectors).
#                     With these values "Probe.exe ... calibrate" needs no --prior.
#   --pitch C1 C2 C3  optional relative pitch terms of the test build (default 0 0 0 = the app's legacy area formula).
#   --pattern PNG     the probe pattern to burn (default patterns/probe_pattern_4096.png). An app layer at 100 % spans
#                     +-ro (DesignLayerViewModel.LoadImage, ro = the project's CD outer radius), so a pattern written by
#                     make_probe_pattern.py must have been made for this band; otherwise the script stops.
#   --make-pattern PNG  first write a matching probe pattern (make_probe_pattern.py --band RI RO --gauge, same code),
#                     then use it. --no-gauge leaves the twist gauge out.
#
# Layout: the fields, their order and their JSON types are those of D:\CD\三次轨距验证.discproj, the valid project
# of the quadratic test disc (schemaVersion 2; the test build's ProjectJsonStore rejects unknown fields). Values: discFamily
# cd; geometry = radii, sectors and the three pitch fields; one layer (the pattern) at 100 %, offset 0, rotation 0;
# tone 2 levels, dither 0, brightness 0, no sRGB linearisation; interleave on, cue on, no data directory, volume label
# CD_IMAGE; output <name>.wav next to the project. Numbers are written as .NET writes them ("R": 0, 1, 1.5E-05).
# For the test build DiscImageStudio-v1.3.6-rawpw.1-cdcubic.1 (CD pitch terms). With all pitch terms 0, v1.3.6 opens it too.
import argparse, datetime, json, math, os, struct, sys, uuid

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
PROJECTS = os.path.dirname(REPO)                                   # D:\CD, where the user's projects live
TEMPLATE = os.path.join(REPO, 'templates', 'cd_cubic_template.discproj')   # contrib: a valid cdcubic project
DEFAULT_PATTERN = os.path.join(REPO, 'patterns', 'probe_pattern_4096.png')
PROBE_KEY = 'DiscImageStudio-probe-pattern'                        # make_probe_pattern.py TEXT_KEY
GENERIC_RI, GENERIC_PITCH_UM = 24.92, 1.4865                       # src/Track.cs Prior.GenericR0 / GenericPitchUm
SECTOR_MM = 1200.0 / 75.0                                          # track per sector at the app's 1200 mm/s
CANVAS_MM = 57.5                                                   # CdDiscParameters.StandardImageOuterRadiusMm
BAND_TOL_MM = 0.02


def generic_radii(sectors):
    """The probe's generic prior: ri 24.92 mm, constant pitch 1.4865 um, ro from the sector count (area formula)."""
    ri = GENERIC_RI
    return ri, math.sqrt(ri * ri + GENERIC_PITCH_UM * 1e-3 * sectors * SECTOR_MM / math.pi)


def geometry_report(ri, ro, sectors, c):
    """Checks the values as the test build and the probe do; returns (turns, mean pitch um, note)."""
    errors = []
    if not (10_000 <= sectors <= 450_000):
        errors.append(f'--sectors {sectors} is outside 10000..450000 (the probe\'s range)')
    if not all(math.isfinite(v) for v in (ri, ro) + tuple(c)):
        errors.append('radii and pitch terms must be finite')
    elif not (15 < ri < 35 and ro > ri + 5 and ro < 62):
        errors.append(f'radii ri={ri!r} ro={ro!r} mm are not those of a CD (the probe\'s --prior accepts '
                      '15 < ri < 35, ro > ri + 5, ro < 62)')
    if errors:
        raise SystemExit('error: ' + '; '.join(errors))
    track = sectors * SECTOR_MM                                    # CalibrationParameters.TrackLengthMm for CD
    if any(v != 0.0 for v in c):
        sys.path.insert(0, os.path.join(HERE, 'pitchfit'))
        from spiral import SpiralGeometry                          # validated copy of the app's DvdTrackGeometry
        try:
            geo = SpiralGeometry(ri, ro, track, *c)
        except ValueError as e:
            raise SystemExit(f'error: the test build would reject these pitch terms ({e})')
        total = geo.total_angle
        note = f'cubic pitch (test build), b = {geo.b * 1000:.6f} um/rad'
    else:
        total = 2.0 * track / (ro + ri)                            # area formula: theta = 2 s / (r + ri)
        note = 'constant pitch (area formula)'
    turns = total / (2 * math.pi)
    return turns, (ro - ri) / turns * 1000.0, note


# ---------------------------------------------------------------------------------------------------- pattern
def png_info(path):
    """(width, height, bit depth, colour type, tEXt chunks) of a PNG file; no pixel decoding."""
    try:
        with open(path, 'rb') as fh:
            data = fh.read()
    except OSError as e:
        raise SystemExit(f'error: cannot read the pattern {path}: {e}')
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        raise SystemExit(f'error: {path} is not a PNG file')
    pos, ihdr, texts = 8, None, {}
    while pos + 8 <= len(data):
        n = int.from_bytes(data[pos:pos + 4], 'big')
        kind, body = data[pos + 4:pos + 8], data[pos + 8:pos + 8 + n]
        if kind == b'IHDR':
            ihdr = struct.unpack('>IIBB', body[:10])
        elif kind == b'tEXt':
            key, _, value = body.partition(b'\x00')
            texts[key.decode('latin-1')] = value.decode('latin-1')
        elif kind == b'IEND':
            break
        pos += 12 + n
    if ihdr is None:
        raise SystemExit(f'error: {path} has no IHDR chunk')
    return ihdr + (texts,)


def check_pattern(path, ri, ro, allow_mismatch):
    """Pattern placement as the app does it: larger side = 2 ro at 100 %. Returns (feature list or None, notes)."""
    w, h, depth, ctype, texts = png_info(path)
    notes = [f'{w} x {h} px, {depth}-bit, colour type {ctype}; at 100 % the larger side spans 2 x {ro:.6f} mm '
             f'({2 * ro / max(w, h) * 1000:.4f} um/px)']
    if w != h:
        notes.append('warning: not square; the app fits the larger side to the disc diameter 2 ro')
    if PROBE_KEY not in texts:
        notes.append('warning: no probe feature list in this PNG (not written by make_probe_pattern.py): '
                     'predict_disc.py cannot predict it as a probe pattern, so the same-disc check of the README needs '
                     'a probe pattern (use --make-pattern)')
        return None, notes
    feat = json.loads(texts[PROBE_KEY])
    b0, b1 = (float(v) for v in feat['band'])
    k = ro / float(feat['span_mm'])
    inner, outer = b0 * k, b1 * k
    notes.append(f'probe pattern made for the band {b0:g} .. {b1:g} mm (span +-{feat["span_mm"]:g}); in this project its '
                 f'band lands at {inner:.5f} .. {outer:.5f} mm (scale {k:.6f})')
    if abs(inner - ri) > BAND_TOL_MM or abs(outer - ro) > BAND_TOL_MM:
        msg = (f'the pattern\'s band does not match the radii {ri!r} / {ro!r} (tolerance {BAND_TOL_MM} mm): '
               f'make one for this band with --make-pattern PNG, or run\n'
               f'  python -I analysis\\make_probe_pattern.py --band {ri!r} {ro!r} --gauge --out <PNG>')
        if not allow_mismatch:
            raise SystemExit('error: ' + msg)
        notes.append('warning (--allow-band-mismatch): ' + msg)
    elif abs(k - 1) > 1e-4:
        notes.append(f'note: features land at {k:.6f} x their design radii (rings at '
                     + ', '.join(f'{r["r"] * k:.2f}' for r in feat['rings']) + ' mm); predict_disc.py accounts for it')
    if 'gauge' not in feat:
        notes.append('note: no twist gauge. With nominal radii more than about 1 um off the truth the thin spokes become '
                     'invisible hairlines; for a new model use --make-pattern (it adds the gauge) [P]')
    if outer > CANVAS_MM:
        half = math.degrees(math.acos(CANVAS_MM / outer))
        notes.append(f'note: the app composes a CD design on a canvas of +-{CANVAS_MM} mm (CdDiscParameters.Standard'
                     f'ImageOuterRadiusMm) and samples white outside it. Beyond {CANVAS_MM} mm the pattern survives only '
                     f'away from the image axes: the outer edge ring and the ends of the 0/90/180/270 deg spokes are cut '
                     f'within +-{half:.1f} deg of those spokes (at {outer:.2f} mm). Expected on the disc; '
                     f'predict_disc.py draws these gaps (its --canvas, default 57.5)')
    return feat, notes


def make_pattern(path, ri, ro, gauge, force):
    if os.path.exists(path) and not force:
        raise SystemExit(f'error: {path} exists (pass --force to overwrite it)')
    sys.path.insert(0, HERE)
    import make_probe_pattern as mpp                               # same code as the command line tool
    feat = mpp.design(ri, ro, gauge=gauge)
    feat['size_px'] = 4096
    ras = mpp.render(feat, 4096)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'wb') as fh:
        fh.write(mpp.png_bytes(4096, 4096, ras.rows(), {mpp.TEXT_KEY: json.dumps(feat, separators=(',', ':'))}))
    return feat


# ---------------------------------------------------------------------------------------------------- JSON
def number(v):
    """A double as System.Text.Json writes it: shortest round trip, integral values without a fraction, E exponent."""
    v = float(v)
    if not math.isfinite(v):
        raise ValueError('non-finite number')
    if v == int(v) and abs(v) < 1e15:
        return str(int(v))
    return repr(v).replace('e', 'E')


def dump(v, depth=0):
    pad = '  ' * depth
    if isinstance(v, dict):
        items = [f'{pad}  {json.dumps(k, ensure_ascii=False)}: {dump(x, depth + 1)}' for k, x in v.items()]
        return '{\n' + ',\n'.join(items) + '\n' + pad + '}' if items else '{}'
    if isinstance(v, list):
        items = [f'{pad}  {dump(x, depth + 1)}' for x in v]
        return '[\n' + ',\n'.join(items) + '\n' + pad + ']' if items else '[]'
    if v is None:
        return 'null'
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, (int, float)):
        return number(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    raise TypeError(type(v))


def shape(v):
    """Field names in order and JSON types, for the layout check against the template."""
    if isinstance(v, dict):
        return [(k, shape(x)) for k, x in v.items()]
    if isinstance(v, list):
        return ['array', shape(v[0])] if v else ['array']
    if v is None:
        return 'null'
    if isinstance(v, bool):
        return 'bool'
    if isinstance(v, (int, float)):
        return 'number'
    return 'string'


def windows_path(p):
    return os.path.abspath(p).replace('/', '\\')


def project(name, ri, ro, sectors, c, pattern, audio):
    now = datetime.datetime.now().astimezone().isoformat(timespec='seconds')
    return {
        'schemaVersion': 2,
        'name': name,
        'discFamily': 'cd',
        'geometry': {
            'innerRadiusMm': float(ri),
            'outerRadiusMm': float(ro),
            'sectors': int(sectors),
            'pitchLinear': float(c[0]),
            'pitchQuadratic': float(c[1]),
            'pitchCubic': float(c[2]),
        },
        'layers': [{
            'id': uuid.uuid4().hex,
            'name': os.path.basename(pattern),
            'imagePath': windows_path(pattern),
            'visible': True,
            'translateXMm': 0,
            'translateYMm': 0,
            'rotationDeg': 0,
            'scale': 1,
        }],
        'outputs': {
            'outputPath': windows_path(audio),
            'writeCue': True,
            'dataDirectory': '',
            'volumeLabel': 'CD_IMAGE',
            'interleave': True,
        },
        'calibrationSessionPath': None,
        'thumbnailPngBase64': None,
        'createdUtc': now,
        'modifiedUtc': now,
        'tone': {
            'ditherStrength': 0,
            'levels': 2,
            'brightness': 0,
            'srgbLinearization': False,
        },
        'bluRay': None,
    }


def quote(p):
    return f'"{p}"' if (' ' in p or not p) else p


def main(argv=None):
    try:
        sys.stdout.reconfigure(errors='backslashreplace')
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(allow_abbrev=False, description='Write the .discproj of a probe disc for a new CD-R model '
                                 '(one-disc calibration, README "换新型号：一张盘完成标定").')
    ap.add_argument('--sectors', type=int, required=True, metavar='N', help='sector count = the blank\'s ATIP capacity')
    ap.add_argument('--radii', nargs=2, type=float, metavar=('RI', 'RO'),
                    help='nominal radii in mm (default: generic 80-minute value scaled to N = the probe\'s default prior)')
    ap.add_argument('--pitch', nargs=3, type=float, metavar=('C1', 'C2', 'C3'), default=[0.0, 0.0, 0.0],
                    help='relative pitch terms of the test build (default 0 0 0)')
    g = ap.add_mutually_exclusive_group()
    g.add_argument('--pattern', help='probe pattern PNG (default patterns/probe_pattern_4096.png)')
    g.add_argument('--make-pattern', metavar='PNG', help='write a matching probe pattern (with the twist gauge) and use it')
    ap.add_argument('--no-gauge', action='store_true', help='with --make-pattern: leave the twist gauge out')
    ap.add_argument('--allow-band-mismatch', action='store_true', help='use a probe pattern made for another band anyway')
    ap.add_argument('--name', help='project name (default 探测盘_<N>)')
    ap.add_argument('--out', help='project file (default <name>.discproj in D:\\CD, next to the other projects)')
    ap.add_argument('--audio', help='generated track (default <name>.wav next to the project)')
    ap.add_argument('--run-dir', default=None, help='probe output folder used in the printed commands '
                                                    '(default out\\newmodel_<N>, relative to the probe folder)')
    ap.add_argument('--template', default=TEMPLATE, help='project whose layout is checked, or "none" '
                                                         '(default %(default)s)')
    ap.add_argument('--force', action='store_true', help='overwrite existing files')
    a = ap.parse_args(argv)
    if a.no_gauge and not a.make_pattern:
        ap.error('--no-gauge only applies to --make-pattern')

    n = a.sectors
    generic = a.radii is None
    ri, ro = generic_radii(n) if generic else (float(a.radii[0]), float(a.radii[1]))
    c = tuple(float(v) for v in a.pitch)
    turns, pitch_um, model = geometry_report(ri, ro, n, c)
    name = a.name or f'探测盘_{n}'
    out = os.path.abspath(a.out or os.path.join(PROJECTS, name + '.discproj'))
    if not out.lower().endswith('.discproj'):
        raise SystemExit('error: --out must end in .discproj')
    if os.path.exists(out) and not a.force:
        raise SystemExit(f'error: {out} exists (pass --force to overwrite it)')
    audio = a.audio or os.path.splitext(out)[0] + '.wav'

    made = None
    if a.make_pattern:
        pattern = os.path.abspath(a.make_pattern)
        made = make_pattern(pattern, ri, ro, not a.no_gauge, a.force)
    else:
        pattern = os.path.abspath(a.pattern or DEFAULT_PATTERN)
    feat, pattern_notes = check_pattern(pattern, ri, ro, a.allow_band_mismatch)

    doc = project(name, ri, ro, n, c, pattern, audio)
    text = dump(doc) + '\n'
    if a.template.lower() == 'none':
        layout = 'not checked (--template none)'
    elif not os.path.isfile(a.template):
        layout = f'not checked (template not found: {a.template})'
    else:
        with open(a.template, encoding='utf-8-sig') as fh:
            tmpl = json.load(fh)
        want, got = shape(tmpl), shape(json.loads(text))
        if want != got:
            raise SystemExit(f'error: the generated layout differs from the template {a.template}\n'
                             f'  template:  {want}\n  generated: {got}\n'
                             'If the template was re-saved by a newer app, update this script first '
                             '(or pass --template none to skip the check).')
        layout = f'same fields, order and JSON types as {a.template}'
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(text)

    pitched = any(v != 0.0 for v in c)
    burn = [ri, ro] + (list(c) if pitched else [])
    print(f'wrote {out}')
    print(f'  geometry: ri {ri!r} mm, ro {ro!r} mm, sectors {n}, c1 {c[0]!r}, c2 {c[1]!r}, c3 {c[2]!r}')
    print(f'            {model}; {turns:.1f} turns, mean pitch {pitch_um:.4f} um'
          + (f'; generic 80-minute value scaled to {n} sectors (ri {GENERIC_RI} mm, pitch {GENERIC_PITCH_UM} um)'
             if generic and not pitched else ''))
    if ro > 58.5:
        print('  warning: ro is beyond 58.5 mm, outside the usual program area'
              + ('; the generic 80-minute pitch does not fit a blank this long: pass --radii' if generic else ''))
    if made is not None:
        print(f'  made the pattern {pattern} (band {ri!r} .. {ro!r} mm, twist gauge {"on" if "gauge" in made else "off"})')
    print(f'  layer: {pattern}, 100 %, offset 0 / 0, rotation 0 (the only layer)')
    for note in pattern_notes:
        print('    ' + note)
    print(f'  tone 2 levels, dither 0; interleave on; output {windows_path(audio)}')
    print(f'  layout: {layout}')

    run = a.run_dir or f'out\\newmodel_{n}'
    prior = '' if generic and not pitched else ' --prior ' + ' '.join(repr(v) for v in burn)
    print()
    print('burn: open the project in DiscImageStudio-v1.3.6-rawpw.1-cdcubic.1 and burn it on this drive (full length). The burn')
    print(f'  confirmation must show ri {ri!r}, ro {ro!r}, {n} sectors' + (', and the c1/c2/c3 above' if pitched else '')
          + '; do not open old tracks in the read-back preview first.')
    print('then, in the probe folder (read-only, about 12-14 minutes; x = 0 holds for the HP BU20N only):')
    print(f'  bin\\Probe.exe {run} calibrate{prior}')
    print(f'  python -I analysis\\calibrate_pitch.py --sectors {n} --burn {",".join(repr(v) for v in burn)} '
          f'--json {run}\\fit.json {run}')
    print(f'  python -I analysis\\predict_disc.py --burn {" ".join(repr(v) for v in burn)} --true <ri ro c1 c2 c3 of the '
          f'recommended model> --x 0 --sectors {n} --pattern {quote(pattern)} --out {run}\\predicted.png '
          f'--report {run}\\predicted.txt')
    if feat is None:
        print('  (predict_disc.py needs a probe pattern; see the warning above)')


if __name__ == '__main__':
    main()
