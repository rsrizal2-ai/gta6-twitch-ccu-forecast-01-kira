"""Forecast launch-day Twitch viewers, hour by hour, from comparables.

Model (fitted fresh on every run from the case file's own comparables):

  For each past launch with a complete release day, look at the log ratio
  of each later hour to that launch's hour 1, ln(v_h / v_1).  Across past
  launches the ratio depends strongly on how big hour 1 already was: a
  launch that opened huge stays near its hour-1 level, while a launch
  that opened small grows several-fold as the world wakes and unlocks.
  So, separately for each hour h = 2..24, fit a weighted line

      ln(v_h / v_1) = a_h + b_h * ln(v_1) + noise

  over the comparable launches, and forecast the target as

      q_tau(h) = p1 * exp(mu_h + z_tau * sd_h),

  where p1 is the target's hour-1 print, mu_h is the fitted line at the
  target's ln(p1), sd_h is the fit's residual spread (x1.1, floored),
  and z_tau is the standard normal quantile at each scored level.

Pool selection (all from data in the case file, never from the target's
future): keep comparables whose release day is complete, whose annotated
tier is "comparable" when a tier is given (this drops early-access and
weak launches, whose shapes differ), and whose pre-day viewing was
already substantial relative to their release-day peak (pre-12h max at
least 20% of the day peak).  The last rule drops simultaneous global
unlocks, whose hour 1 is ~zero and whose ratios explode; the target is a
rolling midnight-local launch, already live in New Zealand and Europe
before 00:00 UTC.  Console-only comparables (no PC/Steam/Stadia in their
platforms) get triple weight: the target is console-only.  If a filter
leaves too few comparables, filters relax in order until the pool is
usable; with no usable pool the forecast falls back to persistence with
a widening spread, so a case always yields a valid file.

Extrapolation: the target may open bigger than any comparable.  Beyond
the fitted range of ln(v_1) the line continues at half slope, so the
forecast keeps the learned scale trend without running away.

Standard library only, deterministic, no network, no randomness.
Reads $MAKEFUN_INPUT_DIR (else /input) and writes $MAKEFUN_OUTPUT_DIR
(else /output), one <id>.out per <id>.in, in name order.
"""

import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import NormalDist

sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

DEFAULT_LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
MAX_VIEWERS = 1_000_000_000.0
MIN_QUANTILE = 0.01

# Pool and fit tuning, chosen by leave-one-out backtests on the practice
# kit's comparables (see BUILD-REPORT.md): pooled-median loss ~0.31 and
# house-baseline loss ~0.39 on the same targets, this model ~0.23.
CONSOLE_WEIGHT = 3.0
ROLL_MIN_RATIO = 0.20
ROLL_RELAXED_RATIO = 0.10
MIN_POOL = 6
SD_MULT = 1.1
SD_FLOOR = 0.15
BEYOND_SLOPE = 0.5
BASELINE_SIGMA = 0.15
# Sanity rails on the fitted log ratio.  Observed pool ratios sit well
# inside these; the rails only bind on degenerate inputs (e.g. a
# missing hour-1 print), where an extrapolated line could run away.
MU_MIN = -2.5
MU_MAX = 3.5


# --- small numeric helpers -------------------------------------------------

def norm_ppf(p):
    """Inverse standard normal CDF, from the standard library.

    statistics.NormalDist is exact to float precision; no hand-rolled
    rational approximation to mistype.
    """
    if not 0.0 < p < 1.0:
        raise ValueError("p must be in (0, 1)")
    return NormalDist().inv_cdf(p)


def round2_half_up(x):
    """Round to 2 decimals, halves away from zero (x is positive here)."""
    return math.floor(x * 100.0 + 0.5) / 100.0


def clamp_quantiles(values):
    """Clamp into (0, 1e9] and force non-decreasing order."""
    out = []
    prev = MIN_QUANTILE
    for v in values:
        v = round2_half_up(min(max(v, MIN_QUANTILE), MAX_VIEWERS))
        v = max(v, prev)
        out.append(v)
        prev = v
    return out


def parse_time(text):
    """Parse an ISO-8601 UTC timestamp; None when unparseable."""
    if not isinstance(text, str):
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# --- comparable extraction -------------------------------------------------

def _tier_of(comp):
    """Tier word from the free-text unlock note, e.g. 'comparable'.

    Returns None when the note carries no 'Tier:' annotation.
    """
    unlock = comp.get("unlock")
    if not isinstance(unlock, str):
        return None
    lower = unlock.lower()
    marker = "tier:"
    idx = lower.find(marker)
    if idx < 0:
        return None
    rest = unlock[idx + len(marker):].strip()
    for stop in (".", ",", ";", "\n"):
        cut = rest.find(stop)
        if cut >= 0:
            rest = rest[:cut]
    words = rest.strip().lower().split()
    return words[0] if words else None


def _is_console_only(comp):
    """True when the platforms list names no PC-style platform."""
    platforms = comp.get("platforms")
    if not isinstance(platforms, str):
        return False
    lowered = platforms.lower()
    if "steam" in lowered or "stadia" in lowered:
        return False
    tokens = []
    current = []
    for ch in lowered:
        if ch.isalnum():
            current.append(ch)
        elif current:
            tokens.append("".join(current))
            current = []
    if current:
        tokens.append("".join(current))
    return "pc" not in tokens


def extract_comparable(comp):
    """Pull a comparable's release-day curve, or None if unusable.

    Needs all 24 release-day hours plus at least one pre-day point in
    the 12 hours before the day starts, and a positive hour-1 count.
    """
    if not isinstance(comp, dict):
        return None
    day_start = parse_time(comp.get("day_start"))
    hourly = comp.get("hourly")
    if day_start is None or not isinstance(hourly, list):
        return None
    by_offset = {}
    for row in hourly:
        if not isinstance(row, dict):
            continue
        when = parse_time(row.get("from"))
        viewers = row.get("viewers")
        if when is None or not isinstance(viewers, (int, float)):
            continue
        if isinstance(viewers, bool) or viewers != viewers:  # NaN guard
            continue
        delta = (when - day_start).total_seconds()
        offset = int(round(delta / 3600.0))
        if abs(delta - offset * 3600.0) > 60.0:
            continue
        by_offset[offset] = float(viewers)
    if any(h not in by_offset for h in range(24)):
        return None
    day = [by_offset[h] for h in range(24)]
    if day[0] < 1:
        return None
    pre = [by_offset[h] for h in range(-12, 0) if h in by_offset]
    if not pre:
        return None
    pre12max = max(pre)
    peak = max(day)
    if peak < 1:
        return None
    name = comp.get("name")
    return {
        "name": name if isinstance(name, str) else "",
        "day": day,
        "log_h1": math.log(max(day[0], 1.0)),
        "pre12_ratio": pre12max / peak,
        "tier": _tier_of(comp),
        "weight": CONSOLE_WEIGHT if _is_console_only(comp) else 1.0,
    }


def select_pool(candidates):
    """Apply the pool filters with relaxing fallbacks.

    Candidates arrive sorted by name so every run fits identically.
    """
    ordered = sorted(candidates, key=lambda c: c["name"])
    tiered = [c for c in ordered if c["tier"] is None or c["tier"] == "comparable"]
    rolling = [c for c in tiered if c["pre12_ratio"] >= ROLL_MIN_RATIO]
    if len(rolling) >= MIN_POOL:
        return rolling
    relaxed = [c for c in tiered if c["pre12_ratio"] >= ROLL_RELAXED_RATIO]
    if len(relaxed) >= MIN_POOL:
        return relaxed
    if len(tiered) >= MIN_POOL:
        return tiered
    if len(ordered) >= MIN_POOL:
        return ordered
    # Too few for a regression either way: return the widest pool and
    # let the caller fall back to a pooled-median forecast.
    return tiered or ordered


# --- fitting ---------------------------------------------------------------

def _weighted_line(xs, ys, ws):
    """Weighted least squares for y = a + b*x; (a, b, resid_sd)."""
    total = sum(ws)
    mx = sum(w * x for w, x in zip(ws, xs)) / total
    my = sum(w * y for w, y in zip(ws, ys)) / total
    sxx = sum(w * (x - mx) ** 2 for w, x in zip(ws, xs))
    if sxx <= 0.0:
        b = 0.0
    else:
        b = sum(w * (x - mx) * (y - my) for w, x, y in zip(ws, xs, ys)) / sxx
    a = my - b * mx
    var = sum(w * (y - (a + b * x)) ** 2 for w, x, y in zip(ws, xs, ys)) / total
    return a, b, math.sqrt(max(var, 0.0))


def _median(values):
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return 0.5 * (ordered[mid - 1] + ordered[mid])


def fit_forecast(pool, p1, hours, z_values):
    """One forecast row per hour from the fitted per-hour lines."""
    xs = [c["log_h1"] for c in pool]
    ws = [c["weight"] for c in pool]
    lo, hi = min(xs), max(xs)
    lx = math.log(max(p1, 1.0))
    lx_clipped = min(max(lx, lo), hi)
    rows = []
    for h in hours:
        ys = [math.log(max(c["day"][h - 1], 1.0) / max(c["day"][0], 1.0))
              for c in pool]
        a, b, resid_sd = _weighted_line(xs, ys, ws)
        sd = max(resid_sd * SD_MULT, SD_FLOOR)
        mu = a + b * lx_clipped + BEYOND_SLOPE * b * (lx - lx_clipped)
        mu = min(max(mu, MU_MIN), MU_MAX)
        quantiles = [p1 * math.exp(mu + z * sd) for z in z_values]
        rows.append({"hour": h, "q": clamp_quantiles(quantiles)})
    return rows


def pooled_forecast(pool, p1, hours, z_values):
    """Fallback: pooled median log ratio per hour, pooled spread."""
    rows = []
    for h in hours:
        ratios = [math.log(max(c["day"][h - 1], 1.0) / max(c["day"][0], 1.0))
                  for c in pool]
        mu = _median(ratios)
        mu = min(max(mu, MU_MIN), MU_MAX)
        if len(ratios) > 1:
            mean = sum(ratios) / len(ratios)
            sd = math.sqrt(sum((r - mean) ** 2 for r in ratios) / len(ratios))
        else:
            sd = 0.35
        sd = max(sd * SD_MULT, SD_FLOOR)
        quantiles = [p1 * math.exp(mu + z * sd) for z in z_values]
        rows.append({"hour": h, "q": clamp_quantiles(quantiles)})
    return rows


def persistence_forecast(p1, hours, z_values):
    """Last-resort fallback: every hour stays at hour 1's print."""
    rows = []
    for h in hours:
        spread = BASELINE_SIGMA * math.sqrt(max(h - 1, 0))
        quantiles = [p1 * math.exp(z * spread) for z in z_values]
        rows.append({"hour": h, "q": clamp_quantiles(quantiles)})
    return rows


# --- case handling ---------------------------------------------------------

def _hour1_print(case):
    """Hour 1's print: the known row, else the day-start history row."""
    for row in case.get("known") or []:
        if isinstance(row, dict) and row.get("hour") == 1:
            viewers = row.get("viewers")
            if isinstance(viewers, (int, float)) and not isinstance(viewers, bool):
                return max(float(viewers), 1.0)
    day_start = case.get("day_start")
    for row in case.get("history_hourly") or []:
        if isinstance(row, dict) and row.get("from") == day_start:
            viewers = row.get("viewers")
            if isinstance(viewers, (int, float)) and not isinstance(viewers, bool):
                return max(float(viewers), 1.0)
    return 1.0


def _forecast_hours(case):
    hours = []
    for row in case.get("forecast") or []:
        if isinstance(row, dict) and isinstance(row.get("hour"), int):
            hours.append(row["hour"])
    hours = sorted(set(h for h in hours if 2 <= h <= 24))
    return hours or list(range(2, 25))


def _z_values(case):
    levels = case.get("levels")
    if (isinstance(levels, list) and len(levels) == len(DEFAULT_LEVELS)
            and all(isinstance(v, (int, float)) and 0.0 < v < 1.0 for v in levels)):
        return [norm_ppf(float(v)) for v in levels]
    return [norm_ppf(v) for v in DEFAULT_LEVELS]


def forecast_case(case):
    """Forecast one case dict; always returns a valid-shaped object."""
    p1 = _hour1_print(case)
    hours = _forecast_hours(case)
    z_values = _z_values(case)
    comparables = case.get("comparables") or []
    candidates = []
    for comp in comparables:
        curve = extract_comparable(comp)
        if curve is not None:
            candidates.append(curve)
    pool = select_pool(candidates)
    if len(pool) >= 3 and len(set(c["log_h1"] for c in pool)) >= 2:
        rows = fit_forecast(pool, p1, hours, z_values)
    elif pool:
        rows = pooled_forecast(pool, p1, hours, z_values)
    else:
        rows = persistence_forecast(p1, hours, z_values)
    return {"hours": rows}


def safe_forecast_case(case):
    """forecast_case with a persistence fallback that cannot fail."""
    try:
        return forecast_case(case)
    except Exception:
        try:
            p1 = _hour1_print(case)
            hours = _forecast_hours(case)
            z_values = _z_values(case)
        except Exception:
            p1, hours = 1.0, list(range(2, 25))
            z_values = [norm_ppf(v) for v in DEFAULT_LEVELS]
        return {"hours": persistence_forecast(p1, hours, z_values)}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        try:
            case = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(case, dict):
                raise ValueError("case is not a JSON object")
            forecast = safe_forecast_case(case)
        except Exception:
            forecast = {"hours": persistence_forecast(
                1.0, list(range(2, 25)), [norm_ppf(v) for v in DEFAULT_LEVELS])}
        text = json.dumps(forecast, separators=(",", ":")) + "\n"
        (OUTPUT_DIR / f"{path.stem}.out").write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
