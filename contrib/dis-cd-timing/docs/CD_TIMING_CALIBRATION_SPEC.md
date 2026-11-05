# CD read-timing calibration with 1–2 discs per box: technical specification

Status: draft for discussion (technical core of a Draft PR to DiscImageStudio). Nothing here changes the app yet. Revised 2026-11-04 after the physical results of discs 3 and 4: the framing correction of the previous version is withdrawn (see Erratum). Revised again the same day after two reviews: estimator dependence (§3.3, §3.6 row 12), evidence tags of the x interval, the reader-only invariant x + s (§2.5), CIRC lane scatter and the AccurateRip arithmetic (§2.5), the v2 readout (§6.5), and evidence paths (now under `analysis\review\`).
Measurements: HP BD-RE BU20N on USB (firmware 0403), Windows 11, IMAPI2, no administrator rights; one box of Lenovo Thinkplus CD-R 700MB/80min; discs 1, 3 and 4 of that box.

Evidence tags used throughout:

- **[V]** verified in this work. Either measured on the user's hardware (raw files are named), recomputed here from raw data or repository source, or, marked "[V, user]", measured by the user on a burned disc, with the stated precision.
- **[I]** inference or modelling assumption, not yet tested independently.
- **[P]** proposal or design choice for the maintainer to accept or change.

---

## Erratum (2026-11-04): the s correction is withdrawn

- **The wrong correction.** The previous version assumed that READ CD completes when the *returned* data (file bytes up to 2352(k+1) + s) have been decoded, and that the app's 111-frame CIRC pre-compensation cancels a 111-frame decoder latency. It therefore shifted the fit by d = −s = +532 bytes (u_app² = u_fit² + w·532/π) and recommended r0 = 24.9216646, r1 = 57.8390395 mm. A verifier confirmed the sign under the same assumption, so that check was not independent.
- **What the discs showed [V, user].** Both discs carry a half-plane design with one straight diameter edge (2 tone levels, interleave on). A ruler laid on one half of the edge is extended across the hub:
  - Disc 3, burned with the uncorrected 24.921633 / 57.839017: the other half lines up ("symmetric"; legend panel "residual only").
  - Disc 4, burned with the corrected 24.9216646 / 57.8390395: the halves are offset by "about 1 cm (may be inaccurate, the lines are faint)"; legend panel "offset + S-bend" (pinwheel). Its content read back confirms the burn values [V]: s = −532 as on disc 3, and 6 of 159,936 sampled bytes differ from a regeneration with its own values, against 2,901 for disc 3's values.
- **What the model predicts [V computation].** Ruler reading B (§6.4): at x = 0 (no along-track constant), disc 3 −0.33 mm and disc 4 −8.49 mm, matching the user's descriptions. At x = +532 (the withdrawn correction), disc 3 +6.88 mm and disc 4 −1.30 mm; neither disc looks like that.
- **What the readings imply [I, model-dependent].** The readings are qualitative, and the ruler's contact radii are unknown. Reading "symmetric" as |B3| ≲ 1–1.5 mm and "about 1 cm" as |B4| = 10 ± 2.5 mm gives x = −45 B, 68 % [−152, +64]. Variants of these assumptions move the median between −70 and −20 B and the 68 % bounds between −177 and +88 B. Other readings of "symmetric" (a least-squares ruler, a ruler through the edge ends) give −88 or +127 B (§6.4; `analysis\review\offset_model_out.txt` §3, §3b). x = 0 is fully consistent. Under this reading model each disc excludes x = +532 on its own; disc 3 alone excludes it qualitatively, since +532 predicts a 6.9 mm offset where the user saw the halves line up.
- **Outcome of the mechanism analysis.**
  - [V; x ≈ 0 from the user's readings, its interval I] The measurements fix only two combinations: the drive completes a read where it also writes (x = W − U ≈ 0), and the returned bytes start 532 B earlier (s = Rd − W = −532 B, §2.5).
  - [V] The completion-gating experiment shows that a read completes at the end of the last requested sector, whatever fields are returned (§2.6).
  - [I] Whether s arises on the read or the write side is open. An external read-offset value for this model favours the write side, although read literally it implies an off-grid write framing (§2.5). Either way s alone does not determine x. But x + s depends only on the reader, so after one physical check per reader, s′ predicts x′ for discs from other burners (§2.5).
- **Consequences [P].**
  - Burn values = fit-frame values plus a per-drive along-track constant x, applied through the exact identity. x is determined once per drive with a ruler or photo (§6.3).
  - For this box and drive x = 0: r0 = 24.9216305 mm, r1 = 57.8390244 mm, N = 359,845 (§5).
  - s stays only as gate G5, a diagnostic.
  - Sections 1, 2.3–2.5, 3.2, 3.4–3.7, 4.2, 4.4, 5, 6, 7, 9–13 are revised accordingly; §2.6 (completion gating) is new.

---

## 1. Summary

The drive itself measures the burned spiral, so no camera is needed for the spiral itself. Under constant angular velocity (CAV), the time at which a single-sector READ CD completes, taken modulo the revolution period, equals the disc angle at which that sector's data finished passing the pickup, plus a constant. A "ladder" of target sectors, from close to the reference out to both edges of the band, resolves the whole-turn ambiguity. This gives the app's spiral (r0, r1 at its fixed 1200 mm/s) to a few nanometres in about 12 minutes of reading.

Timing alone cannot see a constant along-track offset: a shift of x bytes is exactly the same as a different r0/r1 pair (§3.5). That constant belongs to the drive, more precisely to the (burner, reader) pair, not to the box [I: follows from x = W − U (§2.5); observed on one box and one drive only]. The sum x + s depends only on the reader, so for a fixed reader a change of burner shows up in s (§2.5) [I]. x is determined once per drive with a ruler or photo of a burned straight radial edge, best with the v2 verification pattern (§6.3). The framing offset s that the zero staircase gives to the byte (§2.4) is a diagnostic only. It says which bytes a read returns, not where the drive writes or where a read completes. On this drive s = −532 bytes while x ≈ 0. Applying d = −s, as the previous version did, made disc 4 worse (Erratum).

On this setup:

- s = −532 bytes on discs 3 and 4 [V]; diagnostic only (G5).
- x ≈ 0 for the BU20N burning and reading its own discs. The user's ruler readings of discs 3 and 4 match the x = 0 predictions [V, user]. Translated into x with an assumed reading model, x = 0 ± ~100 bytes, estimate −45 B, 68 % [−152, +64] [I, model-dependent] (§6.4).
- Four ladders on two discs agree in the fit frame, with one phase constant κ per run [V]: joint r0 = 24.9216305 mm, r1 = 57.8390244 mm, statistical σ ≈ 3.7 nm each (§5, §9). The choice of per-rung estimator moves them by about ±2 nm (ruler B ≤ 0.17 mm; §3.3, §3.6 row 12) [V].
- A constant-pitch spiral leaves a reproducible smooth residual E(r): 1.83° p-p, about ±1 mm tangential; residual rms 0.49–0.58° per run in the joint fit [V]. It does not change when the spindle speed doubles (k = 0.87 ± 0.11, §3.7), so it is track structure, not a timing artefact [V].
  - Two pitch-polynomial terms, the form the app already uses for DVD, reduce the joint rms from 0.54° to 0.19° [V].
  - A pre-warp of the design (`analysis\prewarp.py`) cancels it today with no app change [V on synthetic and app images, §3.7].
- Recommended burn values for this box and drive: **r0 = 24.9216305 mm, r1 = 57.8390244 mm, N = 359,845** (x = 0, §5). `analysis\calibrate.py` reproduces them from the raw files (`analysis\calibrate_x0_out.txt`).

---

## 2. Principle

### 2.1 Rotational-latency phase under CAV

A timed read has three parts. First a seek and settle. Then the drive waits until the needed track position rotates under the pickup. Finally it decodes and transfers. Under CAV with period T, the completion time `t_c` therefore satisfies

`2π t_c / T ≡ θ_disc(x_done) + φ0   (mod 2π)`

where `x_done` is the along-track position whose passage releases the data, and φ0 collects every constant: the pickup angle, the decode and transfer time, and the USB/IMAPI latency. Taking differences between a target X and a fixed reference R, read alternately, removes φ0 and slow spindle drift. [V for this drive: completion phases are coherent to a per-read σ of 0.060 ms (0.45°) at 1241 rpm.]

### 2.2 Ladder unwrapping

Each rung measures only the fractional turn of `Θ(X) − Θ(R)`. Between LBA 4,500 and 128,842 lie −9,661 turns [V]. The integer number of turns is taken from the current model:

`n = round((P − Δ)/2π)`

This is correct if the prediction error stays below ±180°. Rungs therefore start very close to R, at ±0.5, ±1.5 and ±4 turns. After each refit the ladder jumps to the farthest target whose predicted σ is under 25°, and finally fills the band.

[V] On run 1, changing any single turn count by ±1 raised χ² by at least 8,809. The largest residual was 0.0032 turn, so the margin to an ambiguity is 0.497 turn. The opposite rotation sign fails by the sixth rung (`D:\CD\cd-timing-probe\analysis\independent_run1.txt`).

### 2.3 What timing cannot see

1. **Along-track offset.** It is exactly degenerate with r0/r1 (§3.5). It is the per-drive constant x of §2.5, determined physically (§6.3).
2. **Absolute radial scale.** This is the true scanning velocity, 1.20–1.40 m/s per ECMA-130. It produces a uniform magnification about the centre, so it never bends straight lines [I]. The fitted radii are exact app equivalents at 1200 mm/s, which is all the generator uses.
3. **Global rotation.** It is irrelevant for straightness.

### 2.4 Framing offset s from the interleaver zero staircase (diagnostic)

`CddaInterleaver` starts with a zeroed 112-frame ring. The first emitted file bytes whose target index would be negative are therefore zero placeholders: 1,332 bytes in a column-wise staircase, the last at file index 2,569 [V, regenerated with the app's delay table and little-endian swap].

The app's palettes are `0D/AA` and `0D/10/63/AA` (`CdToneMapping.cs`). Content never contains `0x00`, and the pregap is silence. So the zero mask of READ CD output for LBA 0–7 identifies

`returned(k, j) = file(2352·k + j + s)`

uniquely. On disc 3 the result is s = −532 bytes: −133 samples, −22.17 frames. There were 0 mismatches over 6,000 bytes. The runner-ups at ±24 bytes (one frame) have 24 mismatches. The observed zero count is 1,864 = 1,332 + 532 pregap bytes, and the content bytes are only 0x0D and 0xAA [V; `analysis\staircase.py` on `results\disc3\head_lba0-7.bin`, rerun in this revision]. Disc 4 gives the same s with the same margin [V; `results\drive_now\head_lba0-7.bin`, recomputed with `calibrate.py`'s detector]. Because the expected mask includes the little-endian pair swap, the match also confirms that the drive received the stream in the modelled byte order. It says nothing about the physical CIRC lane placement, since decoding is transparent.

Two cross-checks by another analysis in this workflow [V, `fv\staircase_alt_out.txt`]:

- De-interleaving content samples at 16 radii is smoothest at −532 wherever the content has edges, so s is constant across the disc.
- "532 zero bytes prepended, s = 0" fits the staircase equally well. The staircase therefore locates file byte 0 in the returned data, but cannot tell whether s arises on the read side or the write side (§2.5).

**What s is and is not.** s is the combined read/write framing offset of the drive pair: a data-alignment property. In EAC terms it is a combined offset correction of +133 samples [I, sign convention from the EAC documentation]. It is measured to the byte in seconds and serves as gate G5: it shows an app burn with interleave on, confirms the byte order and fingerprints the drive pair. It is **not** an along-track geometry correction. On this drive s = −532 B while the physical along-track constant is x ≈ 0 [V, §2.5].

### 2.5 Along-track constant x: what is established and what is inferred

**Definition.** The content of file byte q lands at the fit-frame angle of q + x:

`Θ_true(q) = Θ_F(q + x) + E(r) + const`

Equivalently, the READ CD completion of LBA k sits at the physical position of file byte `q_k = 2352(k+1) − x`. x belongs to the (burner, reader) pair and to the app's pre-compensation. It is exactly degenerate with r0/r1 (§3.5).

**Bookkeeping [V algebra].** Positions are in bytes on the physical subcode grid; subcode block k is [2352k, 2352(k+1)).

| Symbol | Meaning |
|---|---|
| W | write framing: file byte h enters the CIRC encoder at encoder-input position h + W |
| Rd | read framing: READ CD of LBA k returns encoder-input bytes [2352k + Rd, 2352(k+1) + Rd) |
| U | completion framing: READ CD of LBA k completes when the pickup passes P(k) + 2664 + U, with P(k) = 2352(k+1); constant times go into κ |

The app's pre-compensation plus a standard encoder places design byte q at physical position q + W + 2664, for all 24 byte lanes [V: app lead + encoder delay = 111 frames for every lane; the 1,332 placeholders are the sum of the leads; `fv\circ_chain_out.txt`, rechecked in `analysis\review\circ_timing_out.txt`]. Hence:

- x = W − U, ± e/b for a pickup travel line off the centre by e (|e/b| ≤ 73 B for e ≤ 0.5 mm);
- s = Rd − W;
- s + x = Rd − U.

If the app's pre-compensation depth ever changes from 111 frames to D, x changes by 24·(D − 111) bytes, so x must be re-checked [I: assumes U does not depend on the content].

**Established [V].**

1. s = −532 B on discs 3 and 4 (§2.4).
2. The previous assumption U = Rd ("the read completes when the returned bytes have been decoded, 111 frames after they pass") gives x = −s = +532 B. The discs refute it [V, user]: at x = +532 the halves of disc 3 would be 6.9 mm apart, and the user saw them line up. Under the reading model of §6.4 each disc excludes it on its own [I].
3. Completion is gated by the last requested sector, advances exactly one sector per LBA, and does not move along the track when sub-channel or C2 data are returned with the audio (§2.6).

**From the user's readings [V, user; interval I].** The ruler readings of discs 3 and 4 match the x = 0 predictions. With the reading model of §6.4 they give x = 0 ± ~100 B for discs this drive burns and reads [I, model-dependent]. So s + x = Rd − U ≈ −532 B: the window of returned bytes lies 532 B before the sector unit whose end gates the completion.

**Inferred [I].**

- Completion is tied to the drive's own sector unit on the grid it also writes on (U ≈ W), not to the returned bytes.
- s is not a whole number of frames (s = −22 frames −4 bytes), so W and Rd cannot both lie on the 24-byte frame grid. A write framing off the grid scatters the 24 byte lanes along the track [V, `fv\circ_chain_out.txt`; `analysis\review\circ_timing_out.txt`, `lane_scatter_out.txt`]:
  - by ±4 B (W ≡ +4 if Rd is on the grid): three partial-contrast copies of every edge (4, 8 and 12 lanes), 8.8–12.6 mm from the nominal position and 3.8, 18.9 and 22.7 mm apart, with nothing at the nominal position;
  - by 12 B: four copies, 7.5–11.4 mm from the nominal position;
  - by ±8 B: two copies only 3.8 mm apart, 1.3 and 2.5 mm from the nominal position.
- The user matched single-edge legend panels, so W ≡ 0 (mod 24) is likely, which puts the 4-byte remainder of s on the read side [I]. This is not firm. The user did not look for copies and reported faint lines, which partial-contrast copies would also produce, and a ±8 B framing would hardly show at ruler precision. A zero-cost look at discs 3 and 4 for fainter parallel copies of the edge 4–23 mm along the track would settle the ±4 and 12 B cases (§6.4).
- Where the bulk of s arises is open. Two classes of explanation fit every measurement here, and give the same x ≈ 0 for discs this drive burns and reads:
  - read side (RS): W ≈ U ≈ 0 and Rd ≈ −532 B, from a read-pointer shift or an uncompensated read latency;
  - write side (WS): the drive's data path lags its subcode by about 22 frames. Reads are re-aligned and writes are not, so W ≈ U ≈ +528 B and Rd ≈ −4 B. In WS the old rule "the read completes when the returned audio has been decoded" is literally true; the error was the 111-frame decode time.
- External value: AccurateRip lists a read-offset correction of +6 samples for the BU20N (three listings, 106 submissions, 93–100 % agreement) [I, external, not measured on this unit]. It favours WS: s would be mostly a write offset. Read literally, +6 gives Rd = −24 B and W = Rd − s = +508 B = 21 frames + 4 B, i.e. the ±4 B off-grid write framing that the previous bullet argues against. With W on the grid, the read correction would be +1 sample (W = +528 B, WS as parameterised above), +7 samples (W = +504 B), or +133 samples (RS) [V arithmetic, `analysis\review\check_circ_out.txt`]. A 1-sample difference could come from the database's zero convention, which is itself uncertain by up to ~30 samples, or from this unit [I, `analysis\review\mechanism_check.md` §7–8].
- Pressed-CD read-offset check on this drive (read-only, minutes): RS predicts +133 samples, WS +1 (or +7), relative to subcode-synchronous framing; AccurateRip lists +6 (§9).
- Therefore s alone does not determine x: on this drive s = −532 B while x ≈ 0. But x + s = Rd − U (± e/b) involves only the reader [V algebra, bookkeeping above]. So for a disc burned by another burner, with its write framing W′ on the 24-byte grid, and timed on this reader, the content of that disc against its own fit has x′ = (x + s) − s′ = −532 − s′ (± this drive's ~100 B), under RS and WS alike [I: assumes that U and Rd do not depend on the disc or the burner, and the app's 111-frame pre-compensation; `analysis\review\check_circ_out.txt`]. Examples: RS with W′ = 0 gives s′ = −532 and x′ = 0; WS with W′ = 0 gives s′ = −4 and x′ = −528 B, i.e. B ≈ −7.2 mm on a ruler.
  - Hence, for a fixed reader, a change of burner, write path or burning software is tracked by s (Δx = −Δs, gate G5). Only a change of reader (drive or firmware) needs a new physical check (§6.3). One physical look at the first disc from a new burner is still advised [P].
  - s′ of such a disc also tells RS from WS in seconds: s′ = Rd − W′ is about −532 − W′ under RS and −4 − W′ under WS, so W′ need only be known to well within ±264 B (±66 samples). This needs a second burner; the pressed-CD check needs none (§9).
  - A probe and a final disc burned on different drives add any difference between the two burners' subcode-to-ATIP alignment, which neither s nor timing sees [I]. So the probe should come from the burner of the final disc (§6.1).

### 2.6 Completion-gating experiment

Source [V]: `results\gating\SUMMARY.md`, `console.txt`, `gating_*.csv`; disc 4 in the drive, SET CD SPEED 0x0583, CAV 1241 rpm. At one LBA L, a baseline READ CD of one audio sector (`BE 04 L 00 00 01 10 00 00`) alternates with a variant, 24 pairs each. Each timed read follows an untimed far read and a random wait. Δ = variant − baseline phase, at r = 39.96 mm (1° = 102.5 B) and 28.00 mm (1° = 71.8 B). Two radii split Δ(r) = a + d·b/r into a time-like part a and an along-track part d [V, recomputed here (`analysis\review\verify_numbers_out.txt`) and by another analysis that re-reduced the raw CSVs (`analysis\review\gating_recheck_out.txt`)]:

| Variant (same L unless stated) | Δ at 40 mm (°) | Δ at 28 mm (°) | d (bytes) |
|---|---|---|---|
| A baseline vs itself (null) | +0.105 ± 0.118 | −0.026 ± 0.127 | −31 ± 42 |
| F next sector L+1 | +23.262 ± 0.124 (one sector: 22.944) | +32.840 ± 0.117 (one sector: 32.740) | 2352 − 53 ± 41 |
| D two sectors L−1..L | −0.161 ± 0.132 | +0.158 ± 0.133 | +77 ± 45 |
| C audio + raw P-W | +0.413 ± 0.184 | +0.327 ± 0.140 | −21 ± 55 |
| H audio + formatted Q | +0.406 ± 0.116 | +0.171 ± 0.124 | −56 ± 41 |
| E audio + C2 error flags | +0.421 ± 0.097 | +0.243 ± 0.098 | −43 ± 33 |
| B sub-channel Q only, no audio | +15.212 ± 0.134 | +15.338 ± 0.135 | +30 ± 46; a = 2.0 ms |
| G nothing selected | returns in 5.7 ms without reading (unusable) | same | — |

- [V] Completion is at the end of the last requested sector. Two sectors L−1..L complete with L, and L+1 one sector later.
- [V] Extra fields with the audio add 0.17–0.42° (25–55 µs of processing), with no along-track change.
- [V] Sub-channel only completes about 15.3° later at both radii: a fixed 2.05 ms, not a track distance (1,559 B would be 21.7° at 28 mm).
- [V] This refutes the literal rule "completion when the requested fields are decoded". That rule puts the sub-channel-only read 2,132 B earlier: Δ28 − Δ40 = −8.88° expected, +0.13 ± 0.19° observed (47σ). A completion on the raw subcode block (2,664 B earlier, −11.10°) is excluded at 59σ, so READ CD gives no direct handle on the subcode timing.
- [I] Gating cannot tell RS from WS, nor whether s arises in the read path. `SUMMARY.md` states that nothing in the audio data path moves completion and that the withdrawn assumption is contradicted; that overstates it, because a unit-gated version of the old rule fits gating equally well. The burns, not gating, refute the withdrawn correction.

---

## 3. Model and mathematics

### 3.1 App spiral in byte units

The CD generator's model (`CdDiscParameters`, `CalibrationGeometry`) uses the area approximation, with r² linear in byte index. In app byte units:

```
b = v/(75·2352) mm per byte, v = 1200 mm/s           (b = 0.006802721 mm)
S(q) = sqrt(u² + w·q/π)                               radius in bytes, r(q) = b·S(q)
Θ(q) = 2q/(S(q) + u) = (2π/w)·(S(q) − u)              cumulative angle, dΘ/dq = 1/S = b/r
u = r0/b,  w = p/b (p = pitch),  r1 = b·S(2352·N)
p = π(r1² − r0²)/(2352·N·b)   (equivalently g = p/2π = (r1² − r0²)/(2L), L = N·v/75)
∂Θ/∂u = −2q/(S(S+u)),   ∂Θ/∂w = −q²/(π·S·(S+u)²)
```

u and w do not depend on N. If a final burn uses a different sector count, recompute r1 from u and w.

### 3.2 Measurement equation

For rung j (target X, reference R):

`Δ_j ≡ Θ(q_X) − Θ(q_R) + ε_j  (mod 2π)`, with `q_k = 2352(k+1) − x` (§2.5).

Θ is the spiral in file-byte (design) coordinates. The run is fitted with x = 0, giving the "fit frame" (model F). The design-frame burn values follow from the exact identity of §3.5 with d = x. x comes from a physical check once per drive (§6.3), never from s alone; for other burners timed on the same reader, s′ then predicts x′ (§2.5) [I]. For this drive x = 0 (§6.4), so the fit frame is the burn frame.

### 3.3 Per-rung robust estimator

Each rung has 24 pairs. Every timed read is preceded by an untimed far read and a random wait uniform in [0, 1.2·T].

1. Drop failed reads and cache-like reads, i.e. duration at or below the cache threshold. Here 8.5 ms is used; the command latency floor is 6.5–7 ms.
2. **Reference phases, robust centring.** φ_i = 2π t_i/T. Centre = circular mean, then plus the median of the wrapped deviations. Keep only reads within `max(4·1.4826·MAD, 1.5°)` of the centre, then re-centre the same way. Median centring matters because USB/host delays are one-sided late outliers of 2–3 ms (15–22°). They bias a plain circular mean and inflate the spread.
3. **Period refinement guarded by coherence.** T_j = argmax of the coherence `|Σ exp(2πi·t_i/T)|/n` over the kept reference reads, within T_prev·(1 ± 10⁻³) in 2 ppm steps. Repeat steps 2–3 three times. Accept T_j only if the coherence is ≥ 0.99 and `|T_j/T_settle − 1| ≤ 10⁻⁴`. Otherwise keep T_prev and flag the rung [P].
4. **Drift.** Fit a line, intercept plus slope, to the wrapped reference residuals against time within the rung.
5. **Target offsets.** `δ_i = wrap(2π t_i^X/T_j − centre − line(t_i^X))`. Apply the same median-centred clipping. Δ_j = robust centre.
6. `σ_j² = s_X²/n_X + s_R²/n_R`, using the residual SDs of the kept reads.

[V] With this estimator (as implemented in `fv_check.py`, without the [P] guard) all three runs give per-rung σ = 0.087–0.21° (median 0.13°). Between 3.5% and 4.4% of reads are clipped, and per-rung periods span 48.34844–48.34882 ms. The probe's original estimator gave σ up to 1.11° on the same disc 1 data (`results\disc1\ladder_log.txt`).

**Implementations differ [V, code read].** Three per-rung estimators are in use:

- `analysis\calibrate.py`, through `fv\common.py` `reduce_ladder`, does **not** centre on the median. It clips at `max(4·1.4826·MAD, 1.5°)` about the plain circular mean, takes the circular mean of the kept reads, and searches the period within ±2·10⁻³ of the probe's rung period, without the guard. Unless stated otherwise, every fit-frame value in this document uses it: F, §3.7 and §9 (`pitchpoly_fitframe.py`, `speed_compare.py` and `pattern_v2.py` call the same function).
- `fv\fv_check.py` implements steps 1–6 above, with a ±2·10⁻³ period search.
- The probe (`src\Ladder.cs`, `EstimateDelta`) clips about the median-centred centre, then takes the circular mean of the kept reads. Its period search is ±10⁻³, and its target clip is `4·max(1.4826·MAD, 0.2°)` without the 1.5° floor.

Effect on the four runs [V, `analysis\review\estimator_check_out.txt`]: F from `calibrate.py` is 24.9216305 / 57.8390244 (χ²/ν 14.69). Steps 1–6 give 24.9216319 / 57.8390228 (χ²/ν 14.71; another implementation gave 24.9216321 / 57.8390228), i.e. +1.5 / −1.6 nm in r0 / r1, a map difference of 0.085° p-p and a ruler reading B of −0.08 mm on a straight edge burned with F. The probe's own phases give 24.9216323 / 57.8390220 (χ²/ν 14.13): +1.9 / −2.4 nm, 0.137° p-p, B −0.17 mm. Both are within σ = 3.7 nm; the spread is row 12 of §3.6. F stays the `calibrate.py` value. Making `calibrate.py` follow steps 1–6 is [P]; it would move every fit-frame value by about these amounts.

### 3.4 Fit

Weighted Gauss–Newton on `Y_j = Δ_j + 2π·n_j`:

`χ² = Σ_j (Y_j − [Θ(q_Xj) − Θ(q_Rj)])²/σ_j²`

with the analytic gradients of §3.1. Optional nuisance terms are a constant phase κ (1 parameter) and read-time eccentricity `(e/r)·sin(Θ − θ_e)` (2 parameters). On run 1, against the constant-pitch model, κ is significant (0.16 ± 0.03°) and e is marginal (0.032 ± 0.014 mm). Both stop being significant once the radial structure is modelled (κ 0.09 ± 0.06°, e 0.04 ± 0.02 mm), and neither moves r0/r1 by more than about 5 nm [V, `independent_run1.txt`]. A weak prior around the preset has no effect on the result, about 10⁻¹¹ mm [V].

With the constant-pitch model, also fit a free κ per run [P]. Every X−R difference carries −ε(r_R), the model error at the reference radius, as a constant; without κ that constant bends (u, w). Joint fits in the fit frame with the `calibrate.py` estimator (circular-mean clipping, §3.3) [V, `analysis\calibrate_x0_out.txt` and `analysis\review\verify_numbers_out.txt`]:

- 3 runs with κ: r0 24.9216303, r1 57.8390247, χ²/ν 17.9; without κ: r0 24.9216374, r1 57.8390221, χ²/ν 22.5;
- 4 runs (adding disc 3 at 2482 rpm) with κ: r0 24.9216305, r1 57.8390244, χ²/ν 14.7 (model F);
- the maps with and without κ differ by 0.47° p-p (0.51° with the `fv_check` estimator). This is the size of the constant-pitch modelling ambiguity.

The covariance is `C = (JᵀWJ)⁻¹·max(1, χ²/ν)`. The scaled C is used both for reporting and for predicting the next rung's σ [P]. For prediction, add a model floor of 0.5° (plus 0.2°/mm·|r_X − r_R| while using constant pitch) [P].

### 3.5 Along-track constant (exact identity)

For constant pitch the identity is exact:

```
Θ_u(q + d) = Θ_u'(q) + (2π/w)(u − u'),   u'² = u² + w·d/π
```

[V: numerically |error| ≤ 3·10⁻¹¹ rad for d = +532, +2352, −2664.]

The fit frame assumes x = 0. With the per-drive constant x, `Θ_true(q) = Θ_F(q + x) + E(r) + const` (§2.5), so the burn values are

```
u_burn = sqrt(u_F² + w·x/π),  w unchanged
r0_burn² = r0_F² + p·b·x/π,   r1_burn² = r1_F² + p·b·x/π
```

Both r² values grow by the area of a recorded strip of length x·b. x comes from the physical check of §6.3, never from s alone (Erratum, §2.5). `calibrate.py --x BYTES` applies it; the default is 0. The equivalent and more general route is to refit with `q_k = 2352(k+1) − x`; this route is required for the polynomial model. [V] The direct refit reproduces the closed form to all printed digits, with identical χ², for all three runs (checked with d = 532).

Sensitivities [V]:

- Per byte of x: r0 +0.0646 nm, r1 +0.0278 nm; along-track 6.80 µm.
- Ruler reading B of a straight radial edge (§6.4): +1.3605 mm per +100 B, so x = 73.5 B per mm of B.
- 1 byte = 8.9 mdeg differential arc between r0 and r1; 1 frame = 0.214°; 1 sector = 20.9°.
- 1 nm of r0 at fixed pitch = 15.5 bytes = 0.138°.
- 1 nm in r0 or r1 alone = 0.096° twist at the rim. A true r0 (r1) 1 nm above the burn value moves B by +0.135 (+0.175) mm.
- For scale, the withdrawn correction (d = 532 B) was 3.619 mm along the track: 8.32° at r0 and 3.585° at r1, a differential arc of 4.735°, with r0 +34.36 nm and r1 +14.80 nm.

### 3.6 Uncertainty budget (differential arc, inner to outer edge, this box and drive)

| # | Term | Size | Tag |
|---|---|---|---|
| 1 | Statistics of one ladder (scaled C) | σ(r0) 5–10 nm, σ(r1) 5–10 nm per run; joint of 4 runs: 3.7 / 3.7 nm | V |
| 2 | Constant-pitch model error | residual rms 0.51–0.64° in single-run fits (0.49–0.58° per run in the joint fit), p-p 1.7–3.0°; smooth part E(r) 1.83° p-p, ±1 mm tangential | V |
| 3 | Reference-choice dependence, constant pitch | map p-p 1.3–1.6° (R at 30 mm vs 40 mm); same R on two discs 0.51°; joint fit with vs without κ 0.47–0.51° | V |
| 4 | Same as rows 2–3 with quadratic pitch | joint rms 0.19° (fit frame, 4 runs); run/disc map p-p 0.15–0.29° | V |
| 5 | Framing offset s | not part of the geometry (diagnostic, G5) | V |
| 6 | Along-track constant x of this drive: write framing, completion point, pickup line offset, decoder latency | now −45 B, 68 % [−152, +64]: about ±0.9° differential, ruler B about ±1.4 mm. After one v2-pattern check: about ±25 B if that disc also gets a ladder, ±45 B without (row 10), i.e. ≤ 0.4°, B ≤ 0.6 mm | V, user (readings); I (interval from an assumed reading model, §6.4; check precision) |
| 7 | x′ for a disc burned on a different drive and timed on this reader | x′ = x − (s′ − s) = −532 − s′, ± the uncertainty of row 6: e.g. 0 for s′ = −532, −528 B (4.7°, B ≈ −7.2 mm) for s′ = −4 (§2.5). A different reader: unknown until checked | I |
| 8 | Completion gating | end of the last requested sector, independent of the returned fields; contained in x | V |
| 9 | Read-time eccentricity | 0.03–0.05 ± 0.02 mm, not significant with structure modelled; ≤ 0.1° and averages over rung angles | V |
| 10 | Disc to disc within a box | 0.51° (constant pitch) / 0.29° (quadratic), from 2 discs only; about ±0.5 mm in B | V |
| 11 | Radial scale (v) | none: uniform magnification ≤ 0.4% | I |
| 12 | Per-rung estimator choice (§3.3: `calibrate.py`'s circular-mean clipping, the median centring of steps 1–6, the probe's own phases) | ±2 nm in r0/r1 (+1.5…+1.9 / −1.6…−2.4 nm against F); map ≤ 0.14° p-p; ruler B ≤ 0.17 mm | V |

Propagation:

- Per-read σ_t gives an angle error of 2πσ_t/T per read and `σ_rung ≈ 2πσ_t/T·sqrt(2/n)`. That is 0.13° here, as observed [V].
- A map uncertainty `σ_Θ(q) = sqrt(gᵀCg)` with `g = ∂[Θ(q) − Θ(0)]/∂(u,w)`.
- An uncertainty δx gives 0.0089° differential per byte, and 1.36 mm of ruler B per 100 B.

### 3.7 Optional richer geometry: polynomial pitch or pre-warp

The app's DVD model is `dr/dθ = g·(1 + c1·x + c2·x² + c3·x³)` with `x = (r − ri)/(ro − ri)` and g solved from the track length (`DvdTrackGeometry`). Applied to CD (thin-track arc length) and fitted jointly in the fit frame, 4 runs, κ per run [V, `analysis\pitchpoly_fitframe.py`, rerun here with identical output]:

| Model | ri (mm) | ro (mm) | c1 | c2 | c3 | χ²/ν | rms* | ruler B, straight edge |
|---|---|---|---|---|---|---|---|---|
| constant (F) | 24.9216305 | 57.8390244 | — | — | — | 14.69 | 0.537° | −1.26 ± 0.21 mm |
| 1 coefficient | 24.9215614 | 57.8389348 | −2.4266e−5 | — | — | 1.79 | 0.199° | +0.23 ± 0.21 mm |
| 2 coefficients | 24.9215518 | 57.8389502 | −3.8951e−5 | +1.5749e−5 | — | 1.72 | 0.193° | +0.04 ± 0.21 mm |
| 3 coefficients | 24.9215700 | 57.8389799 | +3.6938e−5 | −1.6621e−4 | +1.2696e−4 | 1.63 | 0.189° | −0.01 ± 0.21 mm |

\* rms over the 98 rungs with σ < 1°; the one disc-3 rung at 2482 rpm with σ 1.9° is left out.

- The linear term does almost all the work. c2 and c3 each add only about 2.3σ [V]. Angle data cannot tell a pitch polynomial from a speed polynomial [I].
- The 2-coefficient map minus the constant-pitch map reproduces E(r) to 0.035° rms [V].
- A model's ri/ro work only with its own coefficients. Burning the 2-coefficient radii with constant pitch would give B ≈ +21.4 mm, in exact plane geometry with the 2-coefficient model (or F + E) as the truth. The +23.6 mm quoted before ignored E and used the small-angle formula [V, `analysis\review\mix_sets_out.txt`].
- The previous version's polynomial fits were made in the withdrawn shifted frame (for example the 3-run joint quadratic: c1 −4.98e−5, c2 2.77e−5). The table above supersedes them. The differences, about 1.7σ of the joint fit, come from the frame, the κ terms and the fourth run [I].

The residual shape is the same on disc 1 and disc 3: correlation 0.92 over 23 common targets [V]. It is therefore deterministic.

**Speed-invariance test [V]** (`analysis\speed_compare.py`, `results\disc3_2x`):

- **Setup.** Disc 3 was re-measured at SET CD SPEED 0x0B06 (CAV, 2482 rpm, twice the spindle speed), same reference LBA 128,842, 32 pairs per rung, 24 rungs, 0 failed reads. Per-rung σ was 0.235° (median); one rung at 36 mm had σ 1.9° and carries little weight.
- **What it distinguishes.** Real track geometry keeps the same angles at any speed. A completion artefact that is fixed in time would double in angle.
- **Result.** The 2482 rpm residual equals k × (1241 rpm residual) + const with **k = 0.87 ± 0.11**. Without the noisy rung, the two speeds agree to 0.28° rms, the 2482 rpm noise level.
- **Conclusion.** A time-like artefact is excluded. The structure is real track geometry of this box's blanks, or a byte-locked drive effect; only a second drive model can separate those two [I].
- **Fits.** The 2482 rpm constant-pitch fit (fit frame, κ) gives 24.9216325 / 57.8390212, 0.21° p-p from the 3-run joint value. The 4-run joint fit gives 24.9216305 / 57.8390244 (F), 0.017° p-p from it (`analysis\calibrate_x0_out.txt`).

**Pre-warp of the design [V/P]** (`analysis\prewarp.py`, standard library only). The tool resamples a design so that output pixel (r, φ) takes the input pixel at (r, φ + E(r)). φ = atan2(y, x) with y down, as in the app's CD preview, and the image spans ±r1 as an app layer at 100 % does. Burned with F, a straight edge then reads B = 0.00 ± 0.21 mm instead of −1.29 mm [V computation]. Checks by another analysis [V, `analysis\review\validate_prewarp_out.txt`, `validate_real_composite_out.txt`]:

- synthetic spokes and the real app composite are bent by −E(r) within 0.003°;
- a round trip (+E, then −E) returns within 0.003°;
- the v2 pattern's P set is pre-bent by exactly the same E within 0.018°, so the sign convention matches.

Limits:

- It is valid only with the radii E was measured against (F). With disc 3's radii it would leave B = +0.96 mm.
- Re-run it whenever r1 or the layer scale changes.
- Do not prewarp the v2 verification pattern; its P set is already pre-bent.
- `calibrate.py` prints the `--coeffs`/`--const` arguments for another box.

Rules:

- [P] Use the quadratic model only with at least 12 distinct radii, including the band-edge rungs, and only if it lowers χ²/ν by more than 2×.
- [P] Use the cubic only with a significant F-test and leave-one-out-stable coefficients.
- [V] Extrapolation risk: the probe's rungs stop at 25.60 and 57.62 mm. Outside them the polynomial and constant maps diverge by a further 0.5–0.7°, and a degree-5 nuisance polynomial moved the rim twist by 0.25 turn. So [P] add rungs at LBA ≈ 150 and ≈ N − 150.

---

## 4. Measurement procedure and gates

### 4.1 Session

1. Acquire IMAPI exclusive access (`AcquireExclusiveAccess(false, appName)`) and call `DisableMcn`.
2. Raise priority (process High, thread Highest) and avoid GC during runs; spin-wait for the random delays.
3. Timestamp with QPC immediately around `SendCommandGetDataFromDevice`, using a pre-allocated, aligned buffer.
4. Always restore: read speed `0xFFFF`, MCN, and release of exclusive access, on success, cancel, exception and Ctrl+C or process exit.

### 4.2 Gates (all read-only; thresholds are [P]; measured values [V]: G1–G4 and G6 on disc 1, `D:\CD\cd-timing-probe\results`, G5 on discs 3 and 4, G7 on disc 3, G8 on disc 4)

| Gate | Method | Pass rule | Measured here |
|---|---|---|---|
| G0 Inventory | INQUIRY, GET CONFIGURATION, READ DISC INFO, READ TOC, ATIP, READ CAPACITY | finalized disc; 1 audio track at LBA 0; N matches; store ATIP as the box key [P] | not recorded in these runs |
| G1 Latency | 2,000× TEST UNIT READY / INQUIRY (no media access) | robust σ ≤ 0.15 ms; warn and double the pairs if larger; abort if > 0.5 ms | TUR median 7.06 ms, σ 0.053 ms, p99 7.28, max 42 ms; INQUIRY 6.80 / 0.066 ms |
| G2 CAV | per speed setting, lowest first: 40 reads at about 26, 40 and 57.5 mm (far read + random wait); period by coherence with alias check | coherence ≥ 0.99 at all 3 radii; periods agree within 50 ppm; prefer the setting with the lowest per-read σ | 4x / 8x / 10x: 48.347–48.349 ms (1241 rpm), coherence 0.9976–1.0000, robust per-read σ 0.34–0.93°; 16x: 24.174 ms (CAV, 2482 rpm), σ 1.3–3.0°; 24x and max: 14.503 ms (CAV, 4137 rpm), σ 1.6–4.2° (an earlier coarse period search missed these; corrected by a fine re-scan of `rotation_far.csv`) |
| G3 Cache | 12× (R, R) and 12× (R, far, R) | (R, R) shows cache times; (R, far, R) all above the threshold | R,R 6.50–6.69 ms (12/12 cached); R,R+5 / R+40 cached (read-ahead); R,R−40 55–64 ms; R,far,R 167–218 ms (0/12 cached); READ(12) FUA with 0 blocks does not defeat (9/12 cached); 900-sector eviction defeats |
| G4 Readability | 100-point scan, READ CD with C2 pointers | ≥ 99% readable, ≤ 1% sectors with C2 | 100/100 readable, 0 C2 sectors |
| G5 Framing offset s (diagnostic) | READ CD LBA 0–7, staircase match (§2.4); with a calibration record, exact byte match against the regenerated stream | 0 mismatches (≤ 2 if C2-flagged), runner-up margin ≥ 20; s equal to the value stored for this drive pair, else x′ = x − (s′ − s) for the same reader, confirmed physically (§2.5, §6.3). Never applied to r0/r1 by itself | s = −532, 0 vs 24, on discs 3 and 4 |
| G6 Settle | 40 reference reads | coherence ≥ 0.99; per-read σ ≤ 0.1 ms | 48.3486 ms, σ 0.060 ms |
| G7 Speed invariance (optional, once per drive model) | repeat the ladder at a second CAV speed, same reference | residual scale k within 1 ± 0.3 (k = 2 means a time-like artefact) | 1241 vs 2482 rpm: k = 0.87 ± 0.11 |
| G8 Completion gating (optional, once per drive model) | baseline READ CD vs next sector, two sectors, audio + sub-channel/C2, sub-channel only; at two radii (§2.6) | next sector = one sector, two sectors = 0, added fields: along-track part d within 3σ of 0 | next sector: one sector − 53 ± 41 B; two sectors: +77 ± 45 B; added fields: −21 to −56 B (± 33–55); sub-channel only: +2.0 ms, no along-track change |

Role of G5 [P]:

- G5 identifies an app burn with interleave on, confirms the byte order and fingerprints the drive pair.
- It is not a geometry input by itself.
- With the same reader, a changed s (another burner, write path or burning software) shifts x by −Δs: x′ = x − (s′ − s) [I, §2.5]. Store x′ and confirm it once physically.
- A changed reader (drive or firmware) can change both U and Rd, which s cannot separate: re-check x physically.
- No gate measures x itself. Its value for a reader comes from the physical check (§6.3); G5 then tracks burner changes.

Period alias rule [V/P]:

- Completion times that are congruent mod T are also congruent mod T/n, and regularly spaced reads can make 1.5·T or 22/21·T look best. Seen here: 72.52 ms at 4x / 26 mm had coherence 0.9992 against 0.9982 at 48.35 ms, and an independent analysis fell into 50.63 ms.
- Therefore randomise the waits over at least one period.
- Score each candidate by its minimum coherence over all groups (radii and roles).
- Among candidates within 0.002 of the best score, take the largest period. Sub-multiples T/n tie with T, while multiples and rational aliases fail on some group.

### 4.3 Ladder plan

| Step | Content |
|---|---|
| Reference | R near 40 mm (LBA ≈ 128,842) |
| Bootstrap | rungs at ±0.5, ±1.5, ±4 turns (±8, ±24, ±63 sectors at 40 mm) |
| Extension | alternate outward and inward to the farthest target whose predicted σ (scaled C plus floor, §3.4) is < 25° |
| Edges [P] | rungs at LBA ≈ 150 and N − 150 |
| Fill | a rung every 2 mm from 26 to 56 mm (≥ 16 radii) |
| Pairs | 24 per rung; 48 if the G1 σ is above 0.1 ms |
| Size | ≈ 26–28 rungs, ≈ 12 min [V: 24–26 rungs took 10.2–11.9 min; 3,600 timed reads, 0 failed, 0 cache-like, durations 194–355 ms] |

Do not cap the extension at 4× the current span: in simulation that caused 37–40 aborts out of 40 (earlier review's simulations, `analysis\review\verify_tail.md`; not rerun here).

### 4.4 Rung acceptance and abort rules (computed before a rung enters the fit) [P]

| Rule | Condition | Action |
|---|---|---|
| A1 | kept reads ≥ 16 of 24 for both R and X | else re-measure once, then move the target by ±50–500 sectors |
| A2 | σ_j ≤ 0.5° | same as A1 |
| A3 | period guard of §3.3 holds | else use T_prev and flag; re-measure if Δ_j changes by > 3σ between the two T values |
| A4 | `miss = Y_j − P_j`; \|miss\| ≤ 90° | else abort the run (turn ambiguity or wrong model); this is the prototype's guard |
| A5 | \|miss\| ≤ max(5·σ_pred, 3°) | else re-measure once; abort if it repeats |
| A6 | after all rungs: every leave-one-out residual < 0.1 turn; a ±1 change of any n_j raises χ² by ≥ 100; max residual < 10° | else mark the run unreliable |

The prototype currently adds the rung and refits before checking A4 (`Ladder.cs:263–268`). That order must be reversed so that a bad rung never reaches the fit or the report.

Simulation evidence from the earlier review (about 2,000 virtual-drive runs, `analysis\review\verify_tail.md`; not rerun here):

- No wrong unwrap went undetected.
- Completion snapped to 2- or 4-sector blocks made all 40 runs abort.
- An along-track byte offset of 1–2 sectors passes silently: χ² cannot see it, by §3.5. This is why the physical check of §6.3 exists; G5 does not measure it (§2.5).

### 4.5 Fit and model selection

1. Constant pitch is always fitted and reported.
2. Quadratic pitch is fitted when the §3.7 rules are met.
3. Report χ²/ν, scaled C, the residual table, leave-one-out results and, if several runs exist, the joint fit and the pairwise map differences.

---

## 5. Outputs

1. **Preset values at full precision (G17).**
   - Constant pitch: `innerRadiusMm`, `outerRadiusMm`, `sectors`, `linearVelocityMmPerSecond = 1200`.
   - Optionally `pitchLinear` and `pitchQuadratic` (§3.7).
   - The calibration apply path already writes CD radii with "G17" (`CalibrationViewModel.cs:516–523`), and presets load with round-trip format "R".
   - **Recommended for this box and drive [V fit; x = 0 from the user's readings, its interval I]: r0 = 24.9216305 mm, r1 = 57.8390244 mm, N = 359,845.** This is the fit-frame joint of four ladders with κ per run, at x = 0, with `calibrate.py`'s per-rung estimator (`analysis\calibrate_x0_out.txt`; σ ≈ 3.7 nm each, statistical).
     - Estimator dependence [V, §3.3]: the median-centred estimator of §3.3 gives 24.9216319 / 57.8390228, the probe's own phases 24.9216323 / 57.8390220. On a straight edge burned with F these differences read as B = −0.08 and −0.17 mm (§3.6 row 12).
     - It is not adjusted by the x estimate. The analysts recommend x = 0: it is fully consistent with the readings, and the −45 B alternative (24.9216276 / 57.8390231) differs by only 0.6 mm of B, which discs 3 and 4 cannot resolve [V]. The final disc measures x (§6.5).
     - Other x, from F through §3.5 [V arithmetic]:

       | x (bytes) | r0 (mm) | r1 (mm) | ruler B shift (mm) |
       |---|---|---|---|
       | −152 (68 % low) | 24.9216207 | 57.8390202 | −2.07 |
       | −45 (estimate) | 24.9216276 | 57.8390231 | −0.61 |
       | 0 (recommended) | 24.9216305 | 57.8390244 | 0 |
       | +64 (68 % high) | 24.9216346 | 57.8390262 | +0.87 |
       | +532 (withdrawn) | 24.9216649 | 57.8390392 | +7.24 |

     - The 3-run joint (without the 2482 rpm run) gives 24.9216303 / 57.8390247, 0.017° p-p from F. Disc 3 alone (+κ) gives 24.9216305 / 57.8390244; disc 1 run 1 alone 24.9216271 / 57.8390225 [V].
     - Withdrawn: 24.9216646 / 57.8390395 (3-run joint + 532 B; disc 4, Erratum).
     - Expect about 1.8° p-p of S-shaped residual, about ±1 mm, with any constant-pitch value. `prewarp.py` or the pitch polynomial removes it (§3.7).
     - Quadratic alternative, which needs app support: ri 24.9215518, ro 57.8389502, c1 −3.8951e−5, c2 +1.5749e−5 (fit frame, 4 runs, κ).
2. **Residual map.**
   - Per-rung residual (degrees and tangential mm) against radius, with σ.
   - The predicted picture-error map of the probe disc as burned, and its expected ruler reading B(x) (§6.4).
   - The expected residual for the final disc under the chosen model.
   - Examples: discs 3 and 4 (§6.4), the final disc (§6.5).
3. **Report (JSON) [P].** Contents:
   - drive vendor, product, revision and transport;
   - ATIP and TOC (box key);
   - gates with values;
   - speed code and period;
   - s with its mismatch margin (diagnostic);
   - rungs (target, Δ, σ, n, period, kept/total);
   - fit (model, u, w or ri, ro, c, C, χ², ν);
   - the along-track constant x used, with its source (physical check, date, disc);
   - preset values;
   - warnings;
   - path of the raw CSV (`rung, role, lba, completion_ms, duration_ms, ok`).

---

## 6. The 1–2 disc workflow

### 6.1 Per box: one probe disc and one final disc

1. **Disc 1, the probe.** Burn any picture with the nearest preset, as a full-length app burn of the same N.
   - The picture and preset do not matter for timing. The probe measures the blank's groove, not the content [I].
   - Any earlier full-length app burn from the same box can be the probe, if the same drive burned it (x belongs to the burner/reader pair). That makes it 1 new disc per box.
   - **First box on a new drive:** the probe can carry the v2 pattern (§6.5) and so also serve as the drive's physical check (§6.3), at no extra disc.
     - Its expected ruler readings B(x) follow from its own ladder fit and its known burn values, as in §6.4. A small tool for this is [P]: `calibrate.py` does not yet print B(x) for other burn values.
     - Such a probe gives x = 73.5 × (B − B_pred(0)) per set, not x = 73.5 × B; the plain rule holds only for a disc burned with its own fitted values (§6.3, §6.5). The burn values alone can be large: disc 3's and disc 4's values against F (no E) give B_pred(0) = +0.96 and −7.2 mm, i.e. +70 and −530 B of apparent x [V, `analysis\review\estimator_check_out.txt`, `check_estimator_out.txt`]. Until the tool exists, B_pred(0) is a manual computation by the method of §6.4 (`analysis\review\verify_numbers.py`).
     - The P set is pre-bent with this box's E. On another box, B_pred also needs that box's E from its own ladder, unless E turns out to be a drive effect (§3.7) [I].
     - The spokes must stay readable. That needs burn values within roughly ±50 nm of the box's fit (|B| ≲ 10 mm, as on disc 4), for example an earlier box of the same media [I].
     - Otherwise the first final disc, burned with x = 0, is the check.
2. **Measure.** Run the gates (G5 prints s as a diagnostic) and the ladder (about 12 minutes). Fit with `calibrate.py`, adding `--x` if this drive's check found x ≠ 0, and review the report.
3. **Disc 2, the final.** Burn the picture with the calibrated values. If the S-bend matters, prewarp the picture first (§3.7).
   - Optional: a small radial witness line in an unused area. It allows a photo check of every final disc at no extra cost.

### 6.2 Re-use

- x belongs to the (burner, reader) pair and x + s to the reader alone (§2.5); here one drive is both. Determine x once per reader (§6.3). With the same reader, a change of burner, write mode or burning software shows as a change of G5's s, and x′ = x − (s′ − s) [I]; confirm it once physically. Re-check x physically when the reader's drive or firmware changes. Whether one check per drive model suffices is open [I].
- s belongs to the drive pair too. Re-measure it on every probe disc as a fingerprint; it takes seconds.
- Geometry belongs to the box. Two discs of this box gave r0/r1 within 7.6 nm / 3.5 nm at the same reference [V]; more boxes are needed before this is called a rule [I].
- No disc is consumed for re-checks: any already-burned disc can be re-measured.

### 6.3 Once per drive: determine the along-track constant x

Timing cannot see x (§3.5), and s alone does not give it (§2.5). Measure x once per reader, on a disc that drive burned itself with a straight radial edge; for other burners timed on the same reader, s′ then predicts x′ (§2.5) [I]. Default before the check: x = 0.

- **Preferred: the v2 pattern** (§6.5) on the first box's probe or final disc.
  - The rings fix the ruler's contact radii, and the P set has no bend.
  - x = 73.5 × B bytes for a disc burned with its own fitted values, where B (mm) is the reading of the set that shows no bow: normally the P set (§6.5). On a probe burned with other values, subtract its B_pred(0) first (§6.1).
- **Any straight radial edge**, e.g. a half-plane design.
  - Lay the ruler, or draw on an overlay, through one half at exactly r = 28.0 and 57.0 mm: 20.5 mm out from the hole edge and 3.0 mm in from the rim.
  - Fix these radii: moving the inner contact by 1 mm moves the inferred x by about 45 B, the outer by about 30 B [V, `analysis\review\convention_out.txt`; `offset_model_out.txt` §6: dB/dr = +0.57 and −0.40 mm per mm on disc 3].
  - Convert with that disc's predicted reading: x = 73.5 × (B − B_pred(x = 0)) bytes.
- **Phone photo**, data side, camera parallel to the disc, scale from the 120 mm rim: about ±10–15 B per disc [I].

Sign: + = the other half is clockwise of the extended ruler, viewed from the data side, unmirrored (as in the app preview). Precision: contact dots placed to ±0.1 mm give about ±0.34 mm of B per disc (±25 B); two repeats on two discs about ±20 B [I, offset report §7 in `analysis\review\wf2_results_partial.md`]. The far half gives the same distance at r = 28 and at r = 57 mm: its two ring crossings are the point reflections of the near half's, so they lie on a line parallel to the ruler (`offset_model_out.txt` §6) [V]. Average the two distances, and average over the three diameters of a set.

Pass rule [P]: |B| ≤ 0.5 mm (|x| ≤ 37 B) on the set without bow (normally B_P) keeps x = 0. Otherwise store x for the drive and pass `--x` to `calibrate.py`.

A disc burned on a different drive and timed on this one: x′ = x − (s′ − s), i.e. −532 − s′ on this reader (§2.5) [I]; confirm it once physically. A different reader needs its own check.

### 6.4 Worked example: discs 3 and 4 (physical results)

Both discs carry the half-plane design: 0x0D where x + y < 0 in the app frame (x right, y down), i.e. one straight diameter edge at −45°/135° through the centre; 2 tone levels, interleave on.

| Disc | Burn values (mm) | User reading [V, user; ruler, faint lines] | Predicted B, x = 0 | Predicted B, x = +532 |
|---|---|---|---|---|
| 3 | 24.921633 / 57.839017 (uncorrected) | ruler along one half, extended across the hub, lines up with the other half: "symmetric"; matched legend panel "residual only" | −0.33 mm | +6.88 mm |
| 4 | 24.9216646 / 57.8390395 (s-corrected) | halves offset by "about 1 cm (may be inaccurate, the lines are faint)"; matched legend panel "offset + S-bend" | −8.49 mm | −1.30 mm |

Model [V computation; I physics]:

- The content of file byte q lands at Θ_F(q + x) + E(r) + const, with F = 24.9216305 / 57.8390244.
- The app placed it at the angle of the disc's own burn model.
- B is the offset of the other half from a ruler through one half at r = 28 and 57 mm, extended across the hub. + = clockwise, data-side view.

Results:

- B3(x) = −0.33 + 0.0136·x mm and B4(x) = −8.49 + 0.0136·x mm [V]. In exact plane geometry the nonlinearity is < 0.05 mm for |x| ≤ 532 on disc 3; on disc 4, whose offset is large, it is ≤ 0.09 mm for |x| ≤ 239 and 0.30 mm at x = −532 [V, `analysis\review\b_nonlin_out.txt`].
  - Disc 3 at x = 0: +0.96 mm from its burn values against F, −1.29 mm from E.
  - B4 − B3 = −8.16 mm whatever x is.
  - Two other analyses give −0.30 to −0.33 and −8.46 to −8.54 mm, depending on the E estimate [V, `analysis\review\offset_model_out.txt` §1, `legends_analysis_out.txt`, `mechanism_check.md` §2].
- Bow of one half against its own ruler at 30 / 35 / 40 / 45 / 50 / 55 mm [V, `analysis\review\verify_numbers_out.txt`]: disc 3 +0.22 / +0.18 / −0.34 / −0.87 / −0.95 / −0.38 mm; disc 4 +0.17 / +0.06 / −0.51 / −1.03 / −1.07 / −0.43 mm. This is the gentle S-bend.
- **x from the readings** [I: computation on an assumed reading model; the readings themselves are V, user, qualitative, with unknown contact radii]:
  - "symmetric", taken as |B3| ≤ 1 mm, gives x ∈ [−49, +98] B;
  - "about 1 cm", taken as B4 = −7 … −13 mm, gives x ∈ [−343, +111] B (exact geometry).
  - The likelihood model reads "symmetric" as |B3| < 1.5 mm with 0.5 mm reading noise and "about 1 cm" as |B4| = 10 ± 2.5 mm. Folding in where the ruler touched (these discs have no rings; 75 % two-point, 25 % least-squares rulers) gives x = −45 B, 68 % [−152, +64], 95 % [−239, +160]. With the ruler exactly at r = 28/57: +2 B, 68 % [−67, +80] [`analysis\review\offset_model_out.txt` §3, §3b].
  - Variants of these assumptions move the median between −70 and −20 B and the 68 % bounds between −177 and +88 B. Judging "symmetric" with a least-squares ruler or a ruler through the edge ends instead gives −88 or +127 B (same file, §3).
  - x = 0 is fully consistent (likelihood ratio 0.92–0.97 against the best x).
  - Under this reading model x = +532 is excluded by each disc on its own: disc 3 by more than 5σ, disc 4 by about 3σ, the latter set by the assumed ±2.5 mm [I]. Without any reading model, disc 3 alone excludes it: +532 predicts a 6.9 mm offset where the user saw the halves line up [V, user].
- The previous version predicted, for disc 3, B ≈ +6.8 to +7.2 mm under H1 (s applies) and |B| < 0.5 mm plus the S-bend under H0 (no offset). Disc 3 matched H0.
- Legends: `docs\legend_disc3_disc4_x0.png` shows the predicted look at x = 0, true scale. `docs\disc3_predicted_edge.png` is the previous legend: left offset + S-bend, middle offset only, right residual only.

Zero-cost repeat on discs 3 and 4 [P]:

- Mark dots at exactly r = 28.0 and 57.0 mm on each half, on a clear overlay, and read B between the two lines.
- Expected at x = 0: disc 4's other half lies counter-clockwise of the extended ruler (B < 0) by about 8.5 mm, and B4 − B3 = −8.2 ± 0.6 mm. A positive difference means the reading was mirrored.
- Two repeats on both discs give x to about ±20 B, plus ±0.5 mm (about 35 B) from disc 4's unmeasured geometry. A ladder on disc 4 would remove that term.
- Also look along the track on both sides of each edge for fainter parallel copies 4–23 mm away (partial contrast). Their absence excludes a write framing off the frame grid by ±4 or 12 B (§2.5).

### 6.5 Final disc for this box: v2 verification burn with F

Burn values: r0 = 24.9216305, r1 = 57.8390244, N = 359,845, with the CD interleave on and 2 tone levels. Enter the radii before importing the pattern: at scale 100 % a layer's larger side spans 2 × the CD outer radius in effect at import time (`DesignLayerViewModel.LoadImage`). Do not prewarp the pattern.

Pattern `patterns\verify_pattern_v2_4096.png` (`analysis\pattern_v2.py`), the only layer, at 100 % scale with zero offset and zero rotation:

- **S set:** six plain spokes (0°, 60°, …, 300°), i.e. three diameters (0/180°, 60/240°, 120/300°), 0.45 mm wide, each spoke from 25.6 to 57.3 mm, so the hub region carries no line.
- **P set:** six dashed spokes (30°, 90°, …, 330°), i.e. three diameters, each drawn at θ − E(r). E is the joint smooth residual of the three 1241 rpm ladders: poly4, 1.83° p-p, `pattern_v2_out.txt`. It is the same function in either frame [V]. Measured pre-bend in the PNG at 26 / 28.5 / 54 mm: +0.63 / −0.30 / −0.16°.
- **Rings:** at 28, 30, 35, 40, 45, 50, 55 and 57 mm.
- **Chirality:** an "F" at r = 42.6 mm, θ = 15°.

The PNG was made for the withdrawn radii and spans ±57.8390395 mm. Imported into a project with r1 = 57.8390244 it is scaled by 1 − 2.6·10⁻⁷: features move ≤ 15 nm and E changes by < 4·10⁻⁶°. The pattern stays valid [V, `analysis\review\legends_analysis_out.txt`].

Expected ruler readings, with the ruler through one spoke's ring-28 and ring-57 crossings; B = offset of the opposite spoke of the same diameter; dev = deviation of the same spoke at rings 30–55 [V computation]:

| x (bytes) | S set B (mm) | P set B (mm) |
|---|---|---|
| −239 (95 % low) | −4.53 | −3.25 |
| −152 (68 % low) | −3.35 | −2.07 |
| −45 (estimate) | −1.90 | −0.61 |
| 0 | −1.29 | 0.00 |
| +64 (68 % high) | −0.42 | +0.87 |
| +160 (95 % high) | +0.89 | +2.18 |

- S set: dev +0.17 / +0.06 / −0.50 / −1.02 / −1.07 / −0.42 mm at 30 / 35 / 40 / 45 / 50 / 55 mm, for any x. P set: no bow.
- If E were not on the disc, the S set would be straight with B = 0.0136·x, and the P set bowed (mirrored dev) with B = +1.29 + 0.0136·x. B_S − B_P = −1.29 mm in both cases, so use the bow, not B, to tell them apart.
- Readout: x = 73.5 × B bytes, with B (mm) from the set that shows no bow: normally the P set; the S set if E is absent [V algebra]. Averaging B over the three diameters of that set reduces the reading noise.
  - If both sets bow, the disc carries a fraction α of the pattern's E. Then B_S = −1.29·α + 0.0136·x and B_P = B_S + 1.29, so x = 73.5 × (B_S + 1.29·α), with α = (S-set dev at 45–50 mm)/(−1.05 mm) [V algebra, linear model; I if the disc's E has another shape].
  - A common shift of both sets measures x. The disc's own deviation from F (about ±0.5 mm of B, row 10 of §3.6) enters the readout; a ladder on this disc (12 min, read-only) removes it.
  - The rule applies to a disc burned with its own fitted values. On a probe burned with other values, subtract that disc's B_pred(0) first (§6.1).
- Pass: |B| ≤ 0.5 mm on the set without bow (≤ 37 B of x, ≤ 2.4 nm of r0) keeps x = 0. Otherwise store x and rerun `calibrate.py --x`. A P-set |dev| ≤ 0.3 mm also confirms that the disc carries the pattern's E; if not, do not use `prewarp.py` with this E until the reason is known.
- Picture error of this burn if x ≠ 0: every point moves B/2 along the track. 68 % range: B from −2.07 to +0.87 mm, plus about ±0.5 mm from disc-to-disc differences.
- Legend: `docs\legend_final_disc_v2.png`.

### 6.6 One-disc calibration of a new model

Scope: a CD-R model without a calibration yet, burned and read by this drive (HP BU20N, x = 0, §6.4–6.5). One blank is the probe and also the disc on which the result is checked. The user-facing steps are the README section "换新型号：一张盘完成标定".

Procedure [P]:

1. Blank in the drive: `Probe.exe <dir> inventory` prints the ATIP capacity N (`==> blank disc: burn the probe disc with the sector count N`) [V, code read: `src\Disc.cs` `PrintCapacity`].
2. `analysis\make_probe_project.py --sectors N --make-pattern <png>` writes the project and a probe pattern for the same band, with the twist gauge (`make_probe_pattern.py --gauge`, same code). The nominal radii default to the probe's generic prior, ri = 24.92 mm and constant pitch 1.4865 µm, so ro² = ri² + p·16 mm·N/π: 57.83838331174797 mm at 359,845 sectors and 56.053934892096805 mm at 333,000. These equal the prior printed by `Probe.exe … calibrate --dry-run` to the last digit, so `calibrate` needs no `--prior` [V]. The user burns the project with the test build (cdcubic.1) on this drive, at full length.
3. `Probe.exe <dir> calibrate` runs inventory, head (s, gate G5) and the ladder, all read-only, in about 12–14 min [I: 35 rungs and 10.1 min in simulation]. Then `calibrate_pitch.py --sectors N --burn ri,ro --json <dir>\fit.json <dir>`.
4. `predict_disc.py --burn <nominal> --true <selected model> --x 0 --sectors N --pattern <png> --out … --report …`. Compare it with the disc and a data-side photo: rings, winding, counts and angles.
5. Result: ri, ro, c1, c2, c3 of the selected model (`app_values` in `fit.json`) for N sectors.

Project file [V]:

- The fields, their order and their JSON types copy `D:\CD\三次轨距验证.discproj`; the script checks this on every run.
- A harness compiled from the test build's own sources (cubic branch d11ed56: `ProjectJsonStore.cs`, `ToneProfile.cs`, `DvdTrackGeometry.cs`, `OpticalDiscContracts.cs`) loaded the template and the generated projects (generic 80 min, generic 74 min, a quadratic nominal, a v2-pattern variant). `ProjectJsonStore.Save` wrote them back byte-identically apart from CRLF line ends and the final newline. The same loader rejected the negative controls: an unknown field, a pitch shape ≤ 0, 3 tone levels. Evidence: scratchpad `wf5\onedisc\projload_out.txt`, `projload_out2.txt`.

Constraints the procedure works around:

- **Sector count [V, test; fixed in the review of 2026-11-05].** The probe writes `capacity.sectors_used`, `capacity.toc_lead_out_lba`, `prior.sectors` and `atip.last_lead_out_start` to `summary.json`. `calibrate_pitch.py` (also through `calibrate.py --pitch`) now reads them in this order. Before, it looked only for `sectors`, `toc_leadout_lba`, `atip.last_leadout` and similar keys and fell back to 359,845 with only a note, which gives a wrong ro on any other capacity. The output line `sectors:` names the source. Passing `--sectors N` stays good practice; `predict_disc.py` reads no summary and always needs it.
- **Canvas edge [V, code read; I: not yet seen on a disc].** The app composes a CD design on a ±57.5 mm canvas (`DesignViewModel.CanvasOuterRadiusMm` = `CdDiscParameters.StandardImageOuterRadiusMm`, `DesignComposer.Render`); burn and export use `ImageOuterRadiusMm` = 57.5, and pixels outside the image are sampled as white (`RasterImage.GrayAtPixel`). With ro > 57.5 mm the probe pattern's outer edge ring (ro − 0.3 … ro) and the ends of the 0/90/180/270° spokes are lost within acos(57.5/r) of the image axes: ±2.1° at 57.54 mm, ±6.2° at 57.84 mm. Everything inside 57.5 mm is unaffected. `predict_disc.py` draws the gaps (`--canvas`, default 57.5 mm; `--canvas 0` for a track made by `cd-generate` with a larger `--outer`). [P] Keep the probe pattern inside 57.5 mm.
- **Sign of x [V, code read].** `calibrate_pitch.py` and `predict_disc.py` follow §2.5 (q_k = 2352(k+1) − x); `pitchfit/fitlib.py` and the C# harness use 2352(k+1) + x. Irrelevant at x = 0.

What the same-disc check shows. Two simulated probe ladders from the capacity-aware probe were fitted with `calibrate_pitch.py` and predicted with `predict_disc.py`, one realisation each [V sim]:

- `e2e_box80`: this box's quadratic truth at 359,845 sectors, burned with the generic nominal.
- `e2e_std74`: truth 24.77 / 57.46 mm with this box's shape at 333,000 sectors, burned with the generic 24.92 / 56.05 mm.

| Case | Twist, inner to outer ring | Arm width (0.45 mm spokes) | Gauge band | Ring radius shift |
|---|---|---|---|---|
| e2e_box80 | −0.59 turns | 0.07–0.17 mm (hard to see) | 12–67 mm | ≤ 1.5 µm |
| e2e_std74 | −318 turns | ≈ 0.001 mm | 0.03–0.14 mm | −0.14 … +1.40 mm |

- In e2e_box80, the tick angles predicted from the single-run fit and from the simulated truth differ by at most 0.19°. The check therefore cannot see the fit's statistical error.
- It is coarse [V computation, `predict_disc.py`]. With the generic nominal and this box's truth, a 50 nm error in ri moves the tick angles relative to the 40 mm ring by +3.9° at 25.07 mm and −0.9° at 57.69 mm. A straight line burned with the same error would read B = +6.7 mm. So the ±5° tolerance bounds the fit only to roughly 50–100 nm; the mm-level precision of the final disc rests on the ladder statistics.
- What it catches is gross errors [I]: a burned project that differs from the generated one (layer scale or offset, pattern), a mirrored view, or a lost turn (360° at some radius).
- It does not measure x. 100 B is 0.68 mm along the track, and it moves the arm angles relative to the 40 mm ring by only 0.58° at 25.07 mm and 0.30° at 57.69 mm [V arithmetic]. x stays a per-drive quantity (§6.3).
- When arms and gauge are both too fine to see, as in e2e_std74, only the rings can be checked. The rings then move by up to 1.4 mm, which a ruler resolves.
- Ring radii on the disc are λ·r_true, with λ = v_true/(1200 mm/s), the blank's real scanning velocity, which timing cannot see (§2.3) [I]. A ratio measured/predicted that is the same at all rings is λ, not an error. A layer scaled away from 100 % gives the same signature in the ring ratios [I].
- Single-run precision: a straight line burned with the single-run fit reads B = −0.21 mm (e2e_box80) and −0.38 mm (e2e_std74) against the simulated truth. `calibrate_pitch.py` reports 1σ of 0.25 and 0.34 mm for its own map ("own map" B) [V sim]. A second ladder run of the same disc (read-only) adds the run-to-run stability test and averages down the noise.

Pass rules [P]:

- **Fit.** The ladder completes. s = −532 B (G5); otherwise re-check x (§2.5). The selected model has χ²/ν ≤ 3 and no rung with |z| > 4, z = residual/σ of that rung (`calibrate_pitch.py` prints the largest z of each model and warns above 4). A fixed 1° limit would fail good runs, because single rungs can have σ of 1–2°: the simulated 74-minute probe ladder has 1.70° at σ 1.14° (z −1.5), disc 3 at 2x has 4.50° at σ 1.92° (z +2.3). Good runs reach |z| ≤ 3.1 (discs 1–3, 3 at 2x, the simulations); the disc-5 read anomaly is at z −6.8 (run r3, LBA 128835) [V].
- **Rings.** All rings are present, round and concentric. The ratios measured/predicted of the diameters of the inner edge ring, the 40 mm ring and the outer edge ring agree within 1 %. The canvas gaps above are expected.
- **Winding.** The winding direction is the same as predicted. The arm and gauge-edge counts between neighbouring rings are within ±1 of `crossings/next` and `gauge edges/next`. Where they can be measured, the tick angles relative to the 40 mm ring are within ±5° of the prediction.

Fail actions [P]:

- **Reversed winding:** a mirrored view. Re-photograph the data side; if it stays reversed, stop.
- **Rings wrong:** the burned project is not the generated one. The ladder result may still stand, because it measures the groove, but this disc cannot confirm it. The first final disc becomes the check: a thin straight diameter covering 28–57 mm on both halves, read as in §6.3, with |B| ≤ 0.5 mm. That disc is burned with its own fitted values, so x = 73.5 × B applies directly.
- **Counts or angles wrong:** run `calibrate` a second time on the same disc and fit both runs jointly. If the two runs agree and the disc still disagrees, do not use the values. If the runs disagree, one of them lost a turn: measure again.
- **Fit check fails** (χ²/ν > 3 or a rung beyond 4σ): run `calibrate` a second time on the same disc. If the second run passes on its own, use it. If the same LBA is off in both runs (a local read anomaly, as near 40 mm on disc 5), stop. `calibrate_pitch.py` has no option to drop a rung [P: add one].
- **Too fine to see** (arm width < 0.1 mm and gauge band < about 0.3 mm in `predicted.txt`): check the rings only, and make the first final disc the check as above.

Open [I]:

- No probe disc of a new model has been burned or measured yet.
- The visibility limits (0.1 mm arms, about 0.3 mm gauge bands) and the canvas gaps have not been checked on a disc.
- The ring-ratio test of λ is untested.
- x = 0 holds for the HP BU20N burning and reading its own discs only. Another drive needs its own check (§6.3) and `--x`.

---

## 7. Failure modes and fallbacks

| Failure | Detection | Fallback |
|---|---|---|
| CLV-only drive, or zoned/partial CAV | G2: incoherent phase or period depends on radius | Try other speed codes (here 4x–16x were CAV, 24x and max were not). Keep the ladder within a CAV zone. Otherwise use another drive or the photo workflow |
| Cache cannot be defeated | G3: timed reads near the command-latency floor | Evict with a 900-sector read elsewhere. On Mode 1 data discs (`CdDataImageGenerator`), READ(12) with FUA works and s = 0 by sector headers; x still needs its own check [I]. Otherwise abort |
| Unreadable or marginal disc | G4 failures, sense errors, C2 | Retry once, move the target, lower the speed; abort if > 5% of targets fail. Large uniform byte areas can trigger retries (#72 note) |
| USB jitter or host stalls | G1 σ; late outliers | Median-centred clipping; double the pairs; powered port or hub; high priority, spin-waits, no GC; abort if per-rung σ > 1° |
| Spindle re-spin or speed change mid-run | coherence drop, period jump | Re-settle and re-measure the rung |
| Wrong turn count | A4, A5, A6 | Abort or mark unreliable; repeat with more bootstrap rungs |
| Wrong along-track constant: s applied, or x not checked for this drive | pinwheel break: both v2 sets (or both halves of any radial edge) shifted by the same B | x = 73.5 B per mm of B; store x; rerun `calibrate.py --x` (§6.3) |
| Probe or disc burned on another drive than the reader | burn record; G5 s differs from the stored value | Same reader: x′ = x − (s′ − s), here −532 − s′ (§2.5) [I]; confirm once physically. Burn the final disc on the probe's burner (§2.5, §6.1) |
| s changed for the same drive (G5) | G5 | Write path or burning software changed, reader unchanged: x shifts by −Δs; store it and confirm physically. Reader firmware or drive changed: re-check x physically |
| Block-granular or unusual completion | ladder aborts (simulation); G8 | Characterise per drive (x, G8), or reject the drive |
| No app staircase (non-app disc) or zeros in content | G5 ambiguous | No effect on the geometry, since s is diagnostic. Skip G5, or match exact regenerated content |
| Visible S-bend (±1 mm) | bow of the S set; bend of a radial edge | `prewarp.py` with the same radii, or the pitch polynomial once the app supports it (§3.7) |
| Different N between probe and final | TOC | u and w transfer; recompute r1 for the final N |

---

## 8. Safety

- **Read-only command allow-list**, enforced before any command reaches the device. Opcodes: 0x00 TEST UNIT READY, 0x12 INQUIRY, 0x25 READ CAPACITY, 0x43 READ TOC/PMA/ATIP, 0x46 GET CONFIGURATION, 0x51 READ DISC INFORMATION, 0x5A MODE SENSE(10), 0xAC GET PERFORMANCE, 0xA8 READ(12), 0xBE READ CD, and 0xBB SET CD SPEED (volatile; restored to 0xFFFF on exit).
  - Everything else is rejected, including WRITE, BLANK, CLOSE TRACK/SESSION, MODE SELECT, SEND OPC, FORMAT and SYNCHRONIZE CACHE.
  - Also reject a CDB longer than 16 bytes (the prototype lacks this check, `Drive.cs:67`) and a READ(12) with a transfer length on the no-data path.
- **No administrator rights.** `IDiscRecorder2Ex::SendCommand*` through IMAPI works for a standard user [V: every measurement here ran without admin]. #72's DVD tool uses SPTI and needs admin.
- **Exclusive access.**
  - `AcquireExclusiveAccess` plus `DisableMcn` keep Explorer, AutoPlay and other programs from polluting the cache or the timing.
  - The session must not overlap a burn or another device query (the app's `OpticalBurnOperationGate`).
  - Release on every exit path, including Ctrl+C or process exit; the prototype lacks this handler.
- **No writes.** Nothing is written to the disc, the drive, the registry or the system.

---

## 9. Local validation status

Verified [V]:

- Gates G1–G4 and G6 on disc 1; G5 (s = −532) on discs 3 and 4; G7 on disc 3; G8 (completion gating) on disc 4.
- Four ladders: disc 1 twice, with R = 128,842 and R = 36,840; disc 3 with R = 128,842 at 1241 rpm and at 2482 rpm. Fit-frame values from the `calibrate.py` estimator (circular-mean clipping, §3.3; `analysis\review\verify_numbers_out.txt` §B):

  | Run | no κ: r0 / r1 (mm) | χ²/ν | rms / p-p | with κ: r0 / r1 (mm) | κ |
  |---|---|---|---|---|---|
  | disc 1, R 40 mm | 24.9216322 / 57.8390175 | 16.4 | 0.51° / 1.75° | 24.9216271 / 57.8390225 | +0.17° |
  | disc 1, R 30 mm | 24.9216351 / 57.8390321 | 23.0 | 0.62° / 2.95° | 24.9216333 / 57.8390270 | −0.39° |
  | disc 3, R 40 mm | 24.9216390 / 57.8390165 | 21.2 | 0.57° / 1.92° | 24.9216305 / 57.8390244 | +0.26° |
  | disc 3, R 40 mm, 2482 rpm | 24.9216348 / 57.8390189 | 5.2 | 1.15° / 5.96°* | 24.9216325 / 57.8390212 | +0.07° |
  | joint, 3 runs (1241 rpm) | 24.9216374 / 57.8390221 | 22.5 | — | 24.9216303 / 57.8390247 | +0.16 / −0.51 / +0.26° |
  | joint, 4 runs | 24.9216373 / 57.8390219 | 18.2 | — | **24.9216305 / 57.8390244** (F) | +0.16 / −0.51 / +0.26 / +0.11° |

  \* inflated by one rung at 36 mm with σ 1.9°. Disc 3 was burned with 24.921633 / 57.839017, from an independent fit of disc 1 run 1 without κ (`analysis\independent_run1.txt`).
- The exact degeneracy identity.
- Reproducibility, and the polynomial-pitch improvement in the fit frame (§3.7).
- Speed invariance of the smooth residual (G7).
- The completion-gating experiment (§2.6, G8).
- **Physical [V, user]:** ruler readings of discs 3 and 4 (§6.4). They match the x = 0 predictions and refute the s correction. The interval x = 0 ± ~100 B rests on an assumed reading model [I] (§6.4). Only one drive and one box have been tested.
- Disc identities [V, `analysis\review\disc_identity_out.txt`]: the content samples of disc 3 and disc 4 match regenerations with their own burn values (4 and 6 of 159,936 bytes differ), against 2,897 and 2,901 for the other disc's values.
- CIRC lane accounting: app lead + encoder delay = 111 frames for all 24 lanes; 1,332 placeholders = sum of the leads (`fv\circ_chain_out.txt`, `analysis\review\circ_timing_out.txt`).
- `analysis\calibrate.py`: fit-frame joint κ fit, `--x` (default 0), s from `--head` as a diagnostic, and the E(r) arguments for `prewarp.py`. On the four runs it gives 24.9216305 / 57.8390244 (`calibrate_x0_out.txt`); `--x 532` reproduces the earlier, withdrawn 4-run output 24.9216648 / 57.8390392 (`calibrate_4runs_out_WITHDRAWN.txt`). Its per-rung estimator is not the one of §3.3 (§3.3, §3.6 row 12).
- `analysis\prewarp.py` on synthetic spokes, the v2 pattern and a real app composite (§3.7; `analysis\review\validate_prewarp_out.txt`, `validate_real_composite_out.txt`).

Not yet done:

- The final disc of this box (v2 pattern burned with F, §6.5). It measures x to about ±25 B with a ladder on that disc, ±45 B without.
- A pressed-CD read offset on this BU20N (read-only, minutes). It decides between RS (+133 samples) and WS (+1, or +7 with W = 21 frames; AccurateRip lists +6) (§2.5).
- Alternatively, s′ of an app disc (interleave on) burned on a second drive and read here: s′ = Rd − W′ is about −532 − W′ under RS and −4 − W′ under WS, and x′ = −532 − s′ predicts that disc's along-track constant (§2.5). This needs a second burner with W′ known to well within ±66 samples.
- A second drive, as burner or reader; a second box.
- A ladder on disc 4, which would pin its geometry for the zero-cost repeat of §6.4; and the zero-cost look for lane copies of the edges on discs 3 and 4 (§6.4).
- The rule changes marked [P] in the prototype. Median-centred clipping is now in `src\Ladder.cs` (`EstimateDelta`; identical to the scratchpad copy used before). Still open: the edge rungs, the period guard, the A4 ordering, the CDB length check and the exit handler, and aligning `calibrate.py`'s estimator with §3.3.
- CD pitch polynomial or pre-warp in the app (§11).

---

## 10. Relation to issue #72 (DVD timing calibration by another contributor)

- **Shared ideas.** Both use the same physics: rotational-latency phase under CAV, ladder unwrapping, and a turn-ambiguity abort guard. #72 reached 0.106° p-p (rms 0.032°) over 25.5–55.5 mm on a DVD burned from timing alone and checked with a scanner [V, disc-probe (https://github.com/Ashley-QwQ/disc-probe, commit 222560e) `docs/PREREG_remeasure.md`, read only for this comparison].
- **Independence.** This spec is written from the physics and the app's own CD model. It shares ideas with #72 but copies none of its code. Integration code should be written fresh against the app's own interfaces [P].
- **CD-specific differences:**
  - READ CD has no FUA, so the cache is defeated by far reads;
  - IMAPI is used without admin, where #72's tool uses SPTI and needs an administrator terminal [V, its README];
  - completion is per 2352-byte sector, not per 16-sector ECC block;
  - the CIRC staircase gives the framing offset s as a diagnostic only; the along-track constant x needs one physical check per drive (§6.3);
  - USB jitter is about 60 µs, against about 30 µs on SATA;
  - about 22,144 turns, against about 46,000.
- **Shared core [P].** A media-neutral timing core (period/coherence, robust rung estimator, ladder planner, unwrapping, fit and uncertainty) could serve both CD and DVD, with thin media adapters. The maintainer and the #72 author should decide whether that is wanted.

---

## 11. Integration proposal and questions for the maintainer

Proposed placement, following ARCHITECTURE.md ("media-specific stays in its module; only stable shared concepts enter Core") [P]:

| Layer | Content |
|---|---|
| `DiscImageStudio.Core/Calibration/Timing/` | media-neutral: spiral in unit-length coordinates (u, w), with reuse of `DvdTrackGeometry` for polynomial pitch; circular robust statistics; ladder planner; fit, covariance and model selection; virtual CAV drive for tests |
| `DiscImageStudio.Cd` | CD adapter: `q_k = 2352(k+1) − x`, with x per drive from a physical check; staircase detector for the G5 diagnostic (needs the internal `CddaInterleaveTable`); exact-content alignment |
| `DiscImageStudio.Burning` | read-only timed MMC transport on the existing `IDiscRecorder2ExCommands` vtable (allow-list, aligned pre-allocated buffer, QPC stamps, exclusive access); gates and ladder runner |
| `DiscImageStudio.App` | calibration workspace: method switch "照片标定 / 读取时序标定 (CD)" with step cards: drive and gates → measure (rung x/y, σ, ETA, cancel) → result (values, residual chart, disc error map) → apply (existing G17 path) or save as preset; a one-time "drive check" card (v2 pattern, ruler reading → x) |
| `tests/DiscImageStudio.ArchitectureTests` | simulation-only, no hardware in CI (§11 Q6) |
| Prototype alternative | `tools/CdTimingProbe` (like `tools/DvdGrayProbe`), for field data from more drives before app integration |

Questions:

1. **Location.** Should the first PR be a `tools/` prototype plus the Core math and tests, or go straight into Core, Cd, Burning and App as tabled above? Is a `Calibration/Timing` folder in Core acceptable, given that the unit length is the only media input?
2. **Contract.** Should measurement be a Burning-layer service called from the calibration workspace, or a module command in `DiscModuleCatalog`? Device access is Windows-only, while the CLI also runs on Linux and macOS.
3. **UI.** Is a method switch inside the calibration workspace right, or a separate entry? Is it acceptable that the drive is exclusively locked for about 12 minutes, with cancel support?
4. **Preset precision and format.** May CD presets carry full G17 precision, as DVD presets do? Should provenance (method, drive, s, x, χ², rms, ATIP, date) go into the preset `description` and `contributor`, or into a new `.calibration.json` timing section? The latter is a schema change because unknown members are rejected.
5. **Per-drive along-track constant x.**
   - Where should it be stored: per drive model, per drive (serial), or per (burner, reader) pair? In app settings, in the preset, or in a `.calibration.json` timing section?
   - Should it be folded into r0/r1 (exact for constant pitch, no schema change), or become an explicit along-track offset in `CdDiscParameters` and `CdTrackGenerator`? The explicit offset would also be the natural place for audit finding 4's boundary handling.
   - Should the app require one physical check (v2 pattern) before it trusts timing values from a new drive, and warn when G5's s changes?
6. **Tests.** Acceptable test set (seeded, deterministic):
   - identity and the x correction;
   - virtual CAV drive with jitter, late outliers, cache hits, drift, eccentricity, pitch variation and along-track offset (recovery, no wrong unwrap, abort on block completion);
   - staircase recovery of a synthetic s from a real `CddaInterleaver` stream, with an ambiguity rejection;
   - the allow-list refusing write opcodes and CDBs longer than 16 bytes;
   - JSON round trip.

   May the recorded CSVs (about 45 KB each, timings only) be added as regression fixtures?
7. **Polynomial pitch for CD.** In the fit frame two terms take χ²/ν from 14.7 to 1.7, the rms from 0.54° to 0.19°, and a straight edge's ruler reading from −1.26 to +0.04 mm (§3.7).
   - Today the CD path neither accepts nor uses pitch terms [V, code read by another analysis, `analysis\review\wf2_results_rest.md`]. The changes needed:
     - `CdDiscParameters` (geometry), `CdImageSampler` (scalar and SIMD paths), `CdTrackGenerator` and `cd-preview-warp`;
     - `CdDiscModule` options, `CdTrackMetadata`;
     - `DiscParametersState`, `ProjectSession`, `ProjectDialogViewModel`, `ExportViewModel` (`--pitch-*`);
     - `CalibrationParameters.Validate`, which rejects pitch terms for non-DVD.
   - `DvdTrackGeometry` (in Core, same parameterisation) can be reused; its exact arc differs from the CD thin-track arc by ≤ 1.35·10⁻⁴°.
   - With all coefficients 0, the current constant-pitch code path should be kept, so existing outputs stay bit-identical.
   - Is this acceptable as a separate follow-up PR?
8. **Pre-warp.** Until then, `analysis\prewarp.py` removes the S-bend by resampling the design, taking a straight edge from B −1.29 mm to 0.00 ± 0.21 mm. Should the app offer a pre-warp step, or wait for the pitch polynomial? A pre-warp is box-specific and valid only with the radii E was measured against.
9. **Allow-list.** Is SET CD SPEED acceptable in a read-only feature?
10. **Hardware coverage.** Who can run the prototype on other drives (SATA, other vendors)? Each would establish x per reader. A pressed-CD read offset, a second reader of discs 3/4, or s′ of a disc burned on another drive and read on the BU20N (§2.5) would show where s arises.
11. **#72.** Should CD and DVD timing share one core, and in which order should they land?

---

## 12. Reproduction

Python 3.14 with `-I`, standard library only:

| Item | Path |
|---|---|
| Prototype probe (user's) | `D:\CD\cd-timing-probe\src` (phases incl. `head`, `ladder`, `gating`). It now includes the median-centred clipping (`Ladder.cs`, `EstimateDelta`) and is identical to the scratch copy used before |
| Raw data | `D:\CD\cd-timing-probe\results\disc1`, `results\disc2` (two runs on disc 1), `results\disc3` (incl. `head_lba0-7.bin`, `content_samples.bin`), `results\disc3_2x` (disc 3 at 2482 rpm), `results\drive_now` (disc 4: `head_lba0-7.bin`, `content_samples.bin`), `results\gating` (completion gating on disc 4) |
| One-command fit | `analysis\calibrate.py --head results\disc3\head_lba0-7.bin results\disc1 results\disc2 results\disc3 results\disc3_2x` → `analysis\calibrate_x0_out.txt`. The older output, now `analysis\calibrate_4runs_out_WITHDRAWN.txt` (formerly `calibrate_4runs_out.txt`), applied the withdrawn correction: its fit-frame line is valid, its `==> burn values` 24.9216648 / 57.8390392 are not |
| Pitch polynomial, fit frame | `analysis\pitchpoly_fitframe.py` (§3.7) |
| Pre-warp | `analysis\prewarp.py` (§3.7) |
| Speed invariance | `analysis\speed_compare.py` → `analysis\speed_compare_out.txt`. Works in the withdrawn frame (S_OFF = −532): k and the residuals are valid, the printed "own fit (+kappa, s applied)" radii are not burn values |
| Staircase | `analysis\staircase.py` on `results\disc3\head_lba0-7.bin` or `results\drive_now\head_lba0-7.bin` |
| This spec's earlier checks | `D:\CD\cd-timing-probe\analysis\fv\` — `fv_check.py` (robust re-estimation, fits, correction, identity, sensitivities), `disc3_error_map.py`, `pitchpoly_fit.py`, `joint_fit.py`, `joint_const_kappa.py`, `poly_repro.py`, `gates_summary.py`, `run_stats.py`, `sigma_stats.py`, each with an `*_output.txt`. Scripts that apply s work in the withdrawn shifted frame: their residuals are frame-independent, their radii are not |
| Cross-checks by another analysis (cited, not rerun) | `analysis\fv\circ_chain_out.txt` (CIRC label simulation), `analysis\fv\staircase_alt_out.txt` (framing alternatives, content de-interleave), `analysis\fv\final_numbers_out.txt` |
| Verification pattern and predictions | `analysis\pattern_v2.py` → `patterns\verify_pattern_v2_4096.png`, `analysis\pattern_v2_out.txt`. Computed for the withdrawn radii, which the script header marks as such; the pattern stays valid and the predictions carry over to F within 0.03 mm. "Disc 4" in that output means the then-planned v2 disc, not the half-plane disc 4 |
| Other files in the withdrawn frame | `analysis\compare_sets.py` (candidate sets A–E are shifted-frame values); the scripts in `analysis\fv\` that apply s (above) |
| Legends | `docs\legend_disc3_disc4_x0.png`, `docs\legend_final_disc_v2.png`, `docs\disc3_predicted_edge.png` (previous) |
| Revision analyses (cited) | `analysis\review\`: unchanged copies of the working files of the analyses behind this revision (they used to live in a temporary folder): `offset_model.py`/`_out.txt` (x estimate and reading model, §6.4), `convention.py`/`_out.txt` (ruler contact radii), `disc2disc.py`/`_out.txt`, `mechanism_check.md` and `mechanism_blind.md` (mechanism), `circ_timing.py`/`_out.txt` and `lane_scatter.py`/`_out.txt` (CIRC timing, lane scatter), `check_circ.py`/`_out.txt` (lane scatter, offset arithmetic, x′ invariant), `gating_recheck.py`/`_out.txt`, `disc_identity.py`/`_out.txt`, `offset_convert.py`/`_output.txt` (published offsets), `validate_prewarp.py`/`_out.txt` and `validate_real_composite.py`/`_out.txt` (pre-warp), `legends_analysis.py`/`_out.txt`, `verify_numbers.py`/`_out.txt` (s on discs 3 and 4, per-run and joint fits, ruler readings, x table, gating split), `estimator_check.py`/`_out.txt` and `check_estimator.py`/`_out.txt` (estimator dependence; B_pred for other burn values), `b_nonlin.py`/`_out.txt` (exact B(x)), `mix_sets.py`/`_out.txt` (polynomial radii burned with constant pitch), `verify_tail.md` (earlier review and its simulations), `wf2_results_partial.md` and `wf2_results_rest.md` (the analysts' reports) |

The scripts in `analysis\fv\` and `analysis\review\` were written in a scratch folder; where a script still names a scratch path, pass the `D:\CD\cd-timing-probe` equivalent on the command line.

---

## 13. Plain-language summary

The drive can measure the burned spiral itself. It times how long each read waits for the disc to come round. Over a few hundred reads, from the middle to both edges, this pins down the two numbers the app needs, the inner and outer radius, to a few millionths of a millimetre.

Timing cannot see one thing: a fixed shift along the track. The previous version took that shift from the pattern of zero bytes at the start of the track (532 bytes) and corrected for it. The user's two discs showed that this was wrong. The disc burned without the correction has a straight edge; the disc burned with it has its two halves about 1 cm apart. The zero pattern only says which bytes a read returns, not where the drive writes or where a read finishes. For this drive, burning and reading its own discs, the shift is zero within about ±100 bytes, about ±1.4 mm on a ruler, as far as two faint ruler readings can tell. This has been seen on one drive and one box only.

So:

- Per drive, once: check the shift with a ruler on a burned straight edge, best with the v2 test pattern. For this drive it is zero.
- Per box: burn one disc with any picture, let the drive measure it for about 12 minutes, and burn the final disc. If a disc from that box, burned on this drive, already exists, only the final disc is needed. On the first box with a new drive, the probe disc can carry the test pattern and double as the drive check, but its reading must first be corrected for its own burn values, which is not automated yet; the simpler check is the first final disc.
- For this box and drive: r0 = 24.9216305 mm, r1 = 57.8390244 mm.
- The app's single-pitch spiral still leaves a gentle S-bend of about ±1 mm. Pre-warping the picture with `prewarp.py` removes it today. Adding the two DVD pitch terms to the app would remove it too.
