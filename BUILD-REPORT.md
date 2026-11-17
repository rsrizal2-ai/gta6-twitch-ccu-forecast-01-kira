# BUILD-REPORT — gta6-twitch-ccu-forecast-01

Forecast GTA VI's launch-day Twitch viewers hour by hour. Reward $250
(20 places). Entries close 2026-11-19T01:00:00Z (09:00 WITA).

## What was built

`main.py` — a single-file Python 3.13 (standard library only) program at
the repository root. No network, no randomness, no model calls, fully
deterministic. It reads every `*.in` in `$MAKEFUN_INPUT_DIR` (else
`/input`) and writes one `<id>.out` per case to `$MAKEFUN_OUTPUT_DIR`
(else `/output`): exactly `{"hours": [...]}` with 23 rows (hours 2–24),
each five quantiles at levels 0.05/0.25/0.5/0.75/0.95, non-decreasing,
in (0, 1e9], ~1.5 KB per file.

### Model

Per forecast hour h = 2..24, fit a weighted line over comparable past
launches, refitted from the case file on every run:

    ln(v_h / v_1) = a_h + b_h * ln(v_1) + noise

and forecast `q_tau(h) = p1 * exp(mu_h + z_tau * sd_h)`, where p1 is
hour 1's print, mu_h is the fitted line at ln(p1), sd_h is the residual
spread (x1.1, floored at 0.15), and z_tau is the exact standard-normal
quantile (statistics.NormalDist).

Why this shape: across past launches the later-hours ratio depends
strongly on hour-1 size (correlation of log ratio with log hour-1
reaches −0.80 by hour 20). Big openers stay flat; small openers grow
several-fold as regions unlock and viewers wake.

Pool selection (from the case file only, never the target's future):

- complete 24-hour release day + pre-day data, positive hour 1;
- tier annotation "comparable" when present (drops the 9
  early-access-contaminated and 2 weak launches, plus the GTA VI
  target-history series, which is also incomplete);
- rolling-midnight shape: pre-12h max ≥ 20% of the release-day peak
  (drops 8 simultaneous global unlocks — Silksong, Battlefield 6,
  Baldur's Gate 3, etc. — whose hour 1 is ~zero and whose ratios
  explode; GTA VI is rolling midnight-local);
- console-only comparables (no PC/Steam/Stadia in platforms) get
  weight 3, others weight 1 — the target is console-only.
- Result on the practice files: 18 of 38 comparables (7 console-only
  at weight 3). Filters relax in order (20% → 10% → tier-only →
  all complete) if the pool falls below 6.

Extrapolation: beyond the fitted ln(hour-1) range the line continues
at half slope, and fitted log ratios are railed to [−2.5, +3.5].
Fallbacks: pooled-median forecast for tiny pools, persistence with a
widening spread when no pool exists, and a per-case try/except that
always emits a valid-shaped file (even for malformed input) — an
invalid case forfeits prizes, so the program never crashes.

Deliberately unused: the target's `history`/`streams`/
`categories_hourly` (pre-day dip and stream data added nothing in
backtests; streams are null in practice cases), and any hard-coded
forecast numbers — everything is fitted from the input case, so the
final case's 42 comparables (including the 4 practice launches) are
used automatically.

## Files

- `main.py` — the entry (sole entrypoint; no `main.ts`).
- `LICENSE` — MIT (SPDX header included).
- `README.md` — method summary + run instructions. NOTE: it has NO
  make.fun badges yet — phase 2 must add them (see below).
- `BUILD-REPORT.md` — this file.

## Local grade / test evidence

There is NO local grader for this competition (RULES.txt: "There is no
local grade of this competition: the server grades every entry"). The
kit has no grade-local command or Docker setup. Validation below was
done by direct execution the way the grader runs the entry, plus a
leave-one-out (LOO) backtest harness built from the comparables'
full curves (each comparable held out in turn, forecast from the
others, scored with the exact pinball-on-log-scale rule).

### 1. LOO backtest through the shipped code (gold standard)

Synthetic cases were built for each of the 18 rolling comparable
launches (its hour 1 as `known`, the other 37 comparables as its pool),
`main.py` was run over them, and outputs scored against the held-out
release days:

- Shipped model: loss **0.2306**, typical miss 40.1%, 90% coverage 0.841
- House baseline (same targets): loss **0.3899** — matches the house's
  stated practice loss of ~0.387, which validates the harness.
- Pooled-median variant: ~0.31. Model selection was done on this LOO:
  per-hour OLS on log hour-1 beat pooled-slope, dip-augmented, DST /
  weekday-weighted, Huber, and empirical-quantile variants; console
  weight 3, SD x1.1, and half-slope extrapolation were each the LOO
  winner in their sweep (differences among top variants were small,
  ~0.001–0.005, so the simplest robust winner was kept).

Command: `MAKEFUN_INPUT_DIR=/tmp/gta6loo/in MAKEFUN_OUTPUT_DIR=/tmp/gta6loo/out python3 main.py`
(18 cases in 1.1 s), then pinball scoring in the test script.
Re-run after the final edits: loss still 0.2306 exactly.

### 2. Practice-case runs + strict shape validation

`MAKEFUN_INPUT_DIR=<kit>/input MAKEFUN_OUTPUT_DIR=out python3 main.py`
— all 4 practice outputs valid: exactly one `hours` key, 23 rows,
hours 2–24 each once, 5 finite quantiles each in (0, 1e9],
non-decreasing, ≤ 65,536 bytes (actual ~1.5 KB). Median forecasts look
sane (dip after hour 1, rise into the evening, peak ~hour 18–20,
scale-appropriate: p00 h1=23,357 → h18 median 80,572; p02 h1=269,517
→ h18 median 369,130).

### 3. Determinism + grader-style invocation

- Two runs byte-identical (`diff -r` clean).
- Grader-style flags byte-identical to a normal run:
  `PYTHONHASHSEED=0 MAKEFUN_INPUT_DIR=... MAKEFUN_OUTPUT_DIR=... python3 -P -s main.py`.
- Single-case run: 0.099 s (cap is 8 s/case). 18 cases: 1.1 s.

### 4. Edge cases (10 synthetic inputs, all valid outputs, exit 0)

Empty comparables; no tier annotations; 2-comparable pool; hour-1
print of 5,000,000 (medians sane, h24 ≈ 3.3M); missing/zero hour 1;
malformed JSON; non-object JSON; wrong levels list; comparables with
holes/None/zero viewers; missing forecast/levels keys. Every case
produced a valid-shaped file; no crashes.

### 5. Normal-quantile check

`statistics.NormalDist().inv_cdf` reproduces the reference values
(0.05 → −1.6448536269514726, etc.) to float precision. (An earlier
hand-rolled Acklam approximation was 3e-5 off at the tails and was
replaced.)

## Known gaps / risks

- Practice answers are server-side only; the true practice score is
  unknown until submission. LOO on comparables is the proxy, and the
  house warns a practice score is no guide to the final.
- Tail risk: Resident Evil Requiem (US-unlock jump to ~10x hour 1) is
  the worst LOO target (loss 0.97) and is systematically
  under-forecast. GTA VI shares its console-rolling, no-PC structure,
  so a similar jump is a live scenario; widening spreads to cover it
  hurt overall LOO, so the model accepts it as a tail event.
- Extrapolation: GTA VI's hour 1 may exceed every comparable
  (max 875,155). Half-slope extrapolation is untestable beyond a
  hold-out-the-two-biggest experiment, where it beat hard clipping
  (0.146 vs 0.184) but lost to unclipped extrapolation (0.127).
- Final case untested directly: it will carry 42 comparables, minute
  reads, and `streams`/`categories_hourly` (ignored here). The minute
  -read hour means vs SullyGnome hourly averages are slightly
  different measures; ratio shapes are assumed to transfer.
- Local Python is 3.12.3 (grader: 3.13); only stable stdlib is used.

## Commits

- Code commit (main.py final): `87c623794851e5f01de2f46757886c8023a12dad`
- History: `1522ddd` (initial entry) → `87c6237` (quantile + rails).
  This report was committed on top; submit HEAD. Local commits only —
  never pushed; no credentials exist in this environment.
- Git identity used locally: `muse-builder <builder@local.invalid>`
  (repo-local config only).

## Phase 2 needs (submission, handled centrally)

1. Create the GitHub repository AFTER the competition opened
   (2026-11-17T06:00:00Z) and push HEAD there; or, for a source-bundle
   entry, run the kit's `init` in an EMPTY repo first, then copy these
   files in on top (init refuses a repo that already holds a commit).
2. README badges + GitHub About MUST be set before submitting
   (checks `repo_readme` / `repo_about`): add the three live badge
   URLs from the requirements' `readme_template` with the real
   `{owner}`/`{repo}`, a link to make.fun, no `{placeholder}` left;
   set About description/homepage/topics per `repo_about`.
3. Add `.makefun/owner.json` naming the account wallet with the first
   commit, unless the GitHub owner is the account's GitHub login.
4. Bundle transcripts of ALL sessions that built this entry (this
   builder session + the parent session) with the kit CLI; this
   competition requires transcripts and `handed_over_places` is
   `none`, so a handed-over session takes no paid place.
5. No secrets were used or stored; the entry needs no pushed secrets.
6. Deadline: 2026-11-19T01:00:00Z. Last submission before the deadline
   is the final entry.
