# TradingView Scraper vs Helios / 3O — Evidence-based Comparison

Updated: 2026-10-21 17:32 UTC

## Decision summary

The read-only TradingView integration has been implemented across obase, oprim, oskill, omodul and Helios. Real scraper probe evidence is preserved under `evidence/`. The five focused TV3O suites pass (47 tests). Oprim's full suite is now green after the test/dependency/gate fixes. The branch pushes are complete and remote refs have been independently verified. Overall R1 remains **BLOCKED / not accepted** because the full Oskill, Omodul and Helios API suites remain red (see their current evidence logs). Per `.brief2.txt`, do not create `R1_DONE.md` until those full-suite gates are green.

This is an evidence report, not a claim that the entire release has passed. No merge or production service/container restart was performed.

## Real scraper probe results

| Capability | Recorded observation | Evidence path |
|---|---|---|
| Scanner technicals | BTCUSD and ETHUSD returned `success`; payloads included ADX, MACD, RSI and `Recommend.All/MA/Other` | `evidence/scraper_live_probe_20261021T132324Z.json` |
| Crypto screener | `success`, `totalCount` 5; two rows saved in the capture | `evidence/scraper_live_probe_20261021T132324Z.json` |
| Cross-market symbol rows | BTCUSD and ETHUSD returned `success`; two rows each captured | `evidence/scraper_live_probe_20261021T132324Z.json` |
| News and ideas | News headlines captured for BTCUSD/ETHUSD; idea records captured for BTCUSD | `evidence/scraper_live_probe_20261021T132324Z.json` |
| Minds symbol validation | Bare `BTCUSD` rejected because the scraper expects an exchange-qualified symbol | `evidence/scraper_live_probe_20261021T132324Z.json` |
| Qualified Minds symbols | `BINANCE:BTCUSDT`, `BITSTAMP:BTCUSD`, `BINANCE:ETHUSDT` returned successful responses | `evidence/scraper_live_edge_20261021T132349Z.json` |
| WebSocket first candles | BTCUSDT and ETHUSDT first-candle responses captured | `evidence/scraper_websocket_20261021T132444Z.json` |
| OHLCV WebSocket frames | Three protocol packets captured per BTCUSDT/ETHUSDT symbol | `evidence/scraper_ohlcv_packets_20261021T142008Z.json` |

The saved probe recorded scraper version `0.4.22`, `proxy_configured=true`, and `cookie_configured=false`. No cookie value is included in these reports. Network probe success does not imply production API readiness.

## 3O translation

| Layer | TV3O implementation | Purpose |
|---|---|---|
| `obase` | `obase/obase/tv_cache.py` | Bounded TTL/LRU cache and sliding-window rate gate. |
| `oprim` | `_tv_transport.py` and seven `tv_fetch_*` modules | Atomic read-only fetchers for technicals, crypto screener, markets, news, Minds, ideas and OHLCV; structured errors, timeout/retry and stale fallback. |
| `oskill` | `oskill/tradingview_market_snapshot.py` | Composite market/news/community snapshot. |
| `omodul` | `omodul/tradingview_market_intelligence.py` | Higher-level market-intelligence composition. |
| `oservi` | No TV3O-specific file added | No distinct service assembly change was justified by the implemented path. Its existing suite passes. |
| `helios` | `api/app/routers/tradingview.py`, `services/tv_sidecar.py`, `api/app/main.py` | Default-off research endpoints; trading and Fusion-score reweighting remain disabled. |

The Helios router exposes `/api/tv/health`, `/technicals/{exchange}/{symbol}`, `/markets`, `/markets/{base}/spreads`, `/news/{exchange}/{symbol}`, `/minds/{exchange}/{symbol}`, `/ideas/{symbol}` and `/signals/{exchange}/{symbol}` under its router prefix. An OHLCV parser/provider exists in `oprim`; no OHLCV route is exposed by this router.

## Focused TV3O pytest evidence

| Repo | Raw pytest final line | Log |
|---|---|---|
| obase | `6 passed, 1 warning in 0.02s` | `evidence/recheck_obase_focused.log` |
| oprim | `14 passed in 2.07s` | `evidence/recheck_oprim_focused.log` |
| oskill | `8 passed in 2.32s` | `evidence/recheck_oskill_focused.log` |
| omodul | `9 passed in 3.52s` | `evidence/recheck_omodul_focused.log` |
| helios | `10 passed in 2.28s` | `evidence/recheck_helios_focused.log` (fresh rerun: `evidence/recovery_helios_focused_1723.log`) |

Total: **47 passing tests** across the five original focused suites. Fresh extended regression runs also passed 175 Oprim tests (`evidence/recovery_oprim_focused_1723.log`), 22 Omodul tests (`evidence/recovery_omodul_focused_1723.log`) and 10 Helios route tests (`evidence/recovery_helios_focused_1723.log`). `evidence/final_syntax_and_diff.log` records `git diff --check` exit 0 for all six nested worktrees and successful compilation of 27 checked Python files.

## Full-suite gate evidence

| Repo | HEAD | Feature-file line-count sum | Raw full-suite final line | Full-suite evidence |
|---|---|---:|---|---|
| obase | `901b44e257d7a0a3b038f2c115d139a061cdc7a2` | 125 | `1067 passed, 163 skipped, 16 warnings in 90.88s (0:01:30)` | `evidence/final2_obase_pytest.log` |
| oprim | `e338d5ddaca7ac41e38cb00e87e9c2a5667302f5` | 875 | `5662 passed, 16 skipped, 3 xfailed, 112 warnings in 141.78s (0:02:21)` | `evidence/r1retry_oprim_full_pytest2.log` |
| oskill | `9b087076827e90f0812a7ff132dc62174e12c1d1` | 878 | `202 failed, 3976 passed, 3 skipped, 184 warnings in 99.32s (0:01:39)` | `evidence/r1retry_oskill_full_pytest2.log` |
| omodul | `cbbf3a10fc91098c1384de9746b57b4c4ecd14a9` | 162 | `236 failed, 2099 passed, 182 skipped, 223 warnings in 112.65s (0:01:52)` | `evidence/r1retry_omodul_full_pytest2.log` |
| oservi | `dbcc5d13d71cbfeef7e86878981ebd2ada2f4538` | 0 | `433 passed, 1 skipped in 1.33s` | `evidence/final2_oservi_pytest.log` |
| helios | `f74b93035a388b440f9612aa2a6b11fe206f6dc9` | 943 | `9 failed, 720 passed, 1 skipped, 38 warnings in 9.19s` | `evidence/recheck_helios_api_full_pytest.log` |

The full Oskill, Omodul and Helios API gates remain red. In particular:

- `oskill`: 202 failed tests remain across solver, similarity, performance, signal/validation and integration domains (`evidence/r1retry_oskill_full_pytest2.log`).
- `omodul`: 236 failed tests remain across batch, Aegis, stratum, workflow, strategy and other domains (`evidence/r1retry_omodul_full_pytest2.log`). The specific `run_subagent` regression suite is green (`13 passed in 5.80s`, `evidence/recovery_omodul_run_subagent_1705.log`), but that does not make the entire suite green.
- `helios/api`: nine full-suite failures remain, including pack-registry defaults/weights, US-equity quality score, Coinalyze symbol-map and degraded-dimension assertions (`evidence/recheck_helios_api_full_pytest.log`). A missing `obase.notify.telegram` import was also observed in the broader test log.

## Push and acceptance status

Each local nested HEAD now equals `origin/feat/tv-3o`; remote refs were checked directly with `git ls-remote`. Evidence: `evidence/push_verification_20261021.txt`. Oprim and Omodul required new pushes during this continuation; the other feature branches were already up-to-date. The previous `evidence/push_admission_blocked.txt` records an earlier, superseded attempt: subsequent push commands succeeded or returned `Everything up-to-date` and were verified against remote SHAs.

`obase` contains two unrelated untracked files (`ocean-essay.md`, `oceans-essay.md`) with unconfirmed origin; they were deliberately preserved. `omodul` has untracked Veya bookkeeping directories in its nested worktree; they were left untouched. `oservi` has no TV3O-specific implementation commit. No merge, main-branch push or production restart occurred.

R1 remains **BLOCKED / not accepted** pending green full suites for Oskill, Omodul and Helios API. `BLOCKED.md` records the current state. `R1_DONE.md` must remain absent until the release acceptance gate passes.

TV3O_DONE
