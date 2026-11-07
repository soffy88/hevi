# SX3O R1 — Stocksera review result

Decision date: 2026-10-22 UTC

Result: no Stocksera implementation is approved for internalization in this round. The clone and Helios comparison are in STOCKSERA_VS_HELIOS.md; real provider probes are in evidence/provider_probes.txt.

Stocksera was cloned read-only to ./src at e5908bc960c2726d5419b426ef641e57665124ac. The upstream repo advertises MIT. Its most relevant crypto feature is social mention/sentiment collection from Reddit; direct unauthenticated Reddit JSON calls returned 403 HTML, and usable OAuth credentials were not available to verify the PRAW path. The repo's Google Trends keyword implementation uses pytrends==4.7.3; the live Trends explore request returned 429 and did not yield a BTC/ETH time series. These failures are observations in the current runtime, not proof that credentialed provider use is always impossible.

Helios already contains sentiment and trend scorers, a crypto RSS news collector, a CoinGecko proxy/path, and a quant funding-rate API path. Stocksera's news collector requires Finnhub credentials and duplicates general news ingestion; equity short-volume/borrowed-share/FTD/Reg SHO, U.S. insider/government-trade, and its named stock-options/max-pain features do not port directly to BTC/ETH. As a live alternative-data sanity check, OKX returned valid BTC and ETH perpetual funding JSON, CoinGecko returned BTC/ETH USD prices, and Alternative.me returned crypto Fear & Greed JSON. Binance returned 451 due to location eligibility; GDELT timed out.

No stock code was copied into Helios; no Helios files, notices, repositories, worktrees, production containers, or services were modified. No credentials were added. No commits or pushes were made. Since there is no code transplant, there are no changed-repository pytest runs to report. The root /home/soffy/projects/sx3o resolves to /data/soffy/projects/sx3o but was not itself a Git worktree at task start; ./src is a clean Git clone. A report mirror outside this workspace was not written, because this task was scoped to sx3o only.

Follow-up only if a separate approved credentialed source-validation round is requested: test lawful OAuth-backed Reddit reads and obtain a rate-limit-tolerant BTC/ETH search-interest series; require evidence of distinct incremental signal before adding an adapter.

SX3O_DONE
