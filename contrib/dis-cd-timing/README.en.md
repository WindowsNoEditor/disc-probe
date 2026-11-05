# DiscImageStudio CD-DA read-timing calibration (HP BU20N, reference implementation)

[中文](README.md)

A standalone prototype that measures the spiral of CD-R discs burned by DiscImageStudio (DIS) as a **CD-DA audio track**. The principle is the same as disc-probe's: under constant rotation (CAV), the completion time of a read modulo the revolution period gives the sector's angle; a ladder of rungs fixes the whole turns, and the spiral is fitted. It complements disc-probe:

| | disc-probe | this folder |
|---|---|---|
| Disc | random-data disc (Mode 1 / DVD), READ(12) with FUA | DIS-burned CD-DA disc, single-sector READ CD after a far read that evicts the cache |
| Command path | SPTI | IMAPI2 `IDiscRecorder2Ex` (standard user) |
| Fit | u/v constant pitch plus `geo_polyfit.py` | the DIS test build's pitch model (constant, quadratic, cubic), chosen by F-test and leave-one-out prediction; a free constant κ per run; an optional step term for a write seam |
| Output | a DIS preset (`disexport`) | the five DIS project values (inner and outer radius, c1/c2/c3) and the sector count |

Licence: GPL-3.0-or-later (as DIS; compatible with disc-probe's GPL-3.0).

## Results

**Lenovo Thinkplus CD-R 80 min (359845 sectors)**
- Two discs, 4 ladders (one at twice the speed), 99 points over 25.6–57.6 mm (`analysis/rungs_all_runs.csv`).
- Constant pitch fails (χ²/ν 14.7); quadratic is enough (1.72). The residual is a smooth S of about 1.8° peak to peak. At twice the speed its amplitude ratio is 0.87 ± 0.11; a timing artefact would give 2, so it is disc geometry.
- Quadratic values: ri 24.921551846562572, ro 57.838950219991993, c1 −3.8950535120452173e−05, c2 1.5748336087855265e−05, c3 0. Disc 5, burned with them, has straight solid spokes.
- Disc 5 has an along-track step of about +0.20 ± 0.05 mm near sector 65 600 (r ≈ 33.4 mm). It shows both in a photo and in the timing; the read-back data are continuous. See `docs/seam_disc5_zh.md`, `docs/jog_photo_annotated.png` and `results/disc5_jog*`. The new disc below has no step at that sector.

**New CD-R type (ATIP lead-in 97:27:18, 359849 sectors), one probe disc**
- The fit chose constant pitch: ri 24.911761984709965, ro 57.93170828230436, all coefficients 0 (`out/newmodel_fit_final.json`).
- Two runs on the HP BU20N, fitted separately, agree within about 1 nm.
- No step around sector 65 500: g = −0.01 ± 0.04 mm (`out/newmodel_seam`).
- A final disc burned with these values on the other PC's PLDS DU-8A5LH (not the BU20N that measured them) shows the design undistorted (by eye; not yet checked with a ruler).
- Its mean pitch is about 0.4 % larger than the Lenovo disc's.

**Same disc, second drive (PLDS DVD±RW DU-8A5LH on another PC)**
- `autocal` found the drive was not CAV at 0x0583 (108 ms period at 41.5 mm, 29.5 ms at the inner and outer edge). It switched to 0x06E4: 29.53 ms (2032 rpm) at all three radii.
- The ladder had 36 rungs and took 9.3 minutes. It chose constant pitch too.
- Everything agrees except the along-track constant x. With x = 0 for both drives the ruler reading B differs by 8.2 mm, which is x ≈ −603 bytes for this reader. With that x the radii agree within a few nm.
- The read offsets also differ (−144 vs −532 bytes), but x cannot be derived from s.

## The along-track constant x

Timing cannot see a constant along-track shift of the pattern: it is equivalent to moving both radii slightly. x belongs to the (burner, reader) pair and is checked once per pair with a burned straight line. On this drive, burning and reading itself, x ≈ 0 (ruler estimate −45 bytes, 68 % interval −152…+64).

## Contents and reproduction

See the table and the commands in [README.md](README.md). Only the Python standard library is needed. The C# probe builds with `dotnet build src/Probe.csproj -c Release -o bin` (.NET 10) and only sends query and read commands plus SET CD SPEED.
