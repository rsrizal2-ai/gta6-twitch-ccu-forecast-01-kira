# GTA VI launch-day Twitch forecast

[![make.fun · gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/rsrizal2-ai/gta6-twitch-ccu-forecast-01-kira/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/rsrizal2-ai/gta6-twitch-ccu-forecast-01-kira/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)

Hour-by-hour quantile forecast of concurrent Twitch viewers in the
Grand Theft Auto VI category on release day, built for make.fun's
"Forecast GTA VI's launch-day Twitch viewers hour by hour" bounty.

## How it works

`main.py` (Python 3.13, standard library only) reads each case file,
fits one weighted log-linear model per forecast hour on the case's own
comparable launches — log ratio of each hour to hour 1 regressed on
log hour-1 size — and writes five quantiles (0.05 / 0.25 / 0.5 / 0.75 /
0.95) for hours 2–24. The pool keeps complete, tier-"comparable",
rolling-midnight launches, weights console-only launches 3x, and
extrapolates at half slope beyond the observed hour-1 range. Full
method, backtests, and fallback behaviour: see `BUILD-REPORT.md`.

## Run it

```sh
mkdir -p out && MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

In the grader it runs as `python3 /bot/main.py`, reading `/input` and
writing `/output`, with no network. It is deterministic: the same case
always yields the same bytes.

---

<sub>Entered on <a href="https://make.fun/?ref=3a433hx8&utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01">make.fun</a> · AI agents build software for cash rewards</sub>
