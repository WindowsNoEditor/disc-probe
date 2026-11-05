# disc-probe `timing` over SPTI and over IMAPI2, same disc and drive

HP BD-RE BU20N (USB), the new-model probe disc (CD-DA, ATIP 97:27:18), `--speed 1411` (1241 rpm), `--evict-sectors 54 --reps 32`, run one after the other as a standard user. Code: branches `imapi-transport` (the IMAPI2 transport) and `readcd-usb-cache` (READ CD cache detection) of WindowsNoEditor/disc-probe, merged locally.

- Both: strategy `evict` (plain re-reads 9.8 ms from the cache, after an eviction 176–212 ms), CAV at 48.3485 ms in all three zones.
- Jitter: SPTI 55–62 µs (0.41–0.46°), IMAPI2 43–63 µs (0.32–0.47°).
- Phases of the 5 targets differ by −0.31…+0.28° (χ² 10.0 for 5 dof), about the run-to-run scatter seen in repeated ladders on this drive.

`comparison.txt` is the side-by-side table; the summaries are the unmodified `summary.json` files.
