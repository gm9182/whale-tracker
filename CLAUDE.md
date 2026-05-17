# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with this repository.

## Commands

```bash
# Fetch both JP and US signals, then build the dashboard
./run.sh

# Fetch individual markets
./run.sh jp       # Japan signals only
./run.sh us       # US signals only
./run.sh build    # Build HTML from existing JSON (no fetch)

# Run scripts directly
python3 scripts/fetch_jp.py
python3 scripts/fetch_us.py
python3 scripts/build_html.py

# Standalone sub-modules (can also be run independently)
python3 scripts/fetch_tdnet.py   # TDnet disclosure indexer → data/tdnet_signals.json
python3 scripts/fetch_margin.py  # Margin balance analyzer → data/margin_signals.json
```

**No external dependencies** — everything uses Python standard library only (no pip install needed). Python 3.12+ is used in CI.

## Architecture

### Data Pipeline

```
fetch_jp.py ──┬─ imports fetch_tdnet.py  ─┐
              └─ imports fetch_margin.py  ─┼──► data/jp_signals.json ─┐
fetch_us.py ──── imports options_sweep.py ─┘                           │
                                                data/us_signals.json ──┤
                                                                        │
                                                build_html.py ◄─────────┘
                                                    │
                                               docs/index.html  (GitHub Pages)
                                               docs/data.json   (live reload target)
```

`fetch_jp.py` bulk-fetches shared datasets first (EDINET filings, JPX short balance, TDnet disclosures, margin data) then iterates per ticker. `fetch_us.py` fetches per-ticker from SEC/FINRA/Yahoo.

### Signal Architecture

Every signal function returns this standard dict:
```python
{
    "active": bool,
    "score": int,          # raw signal score (pre-weighting)
    "detail": dict,        # human-readable key/value breakdown
    "evidence": int,       # 0-100 confidence percentage
    "events": list,        # timeline items shown in the modal
}
```

**US signals and weights** (`compute_whale_score` in `fetch_us.py`):
| Key | Source | Weight | Max Score |
|---|---|---|---|
| `insider` | SEC Form 4 | 1.5x | 60 |
| `filing13d` | SEC 13D/G | 1.3x | 30 |
| `options` | Yahoo Options (via `options_sweep.detect_sweep`) | 1.4x | 60 |
| `darkpool` | FINRA Daily Short Volume | 1.0x | 35 |
| `filing13f` | SEC 13F (stub — always 0) | 0.8x | — |

**JP signals and weights** (`compute_jp_score` in `fetch_jp.py`):
| Key | Source | Weight | Max Score |
|---|---|---|---|
| `holdings` | EDINET (5% 大量保有) | 1.5x | 40 |
| `tdnet` | TDnet via yanoshin.jp unofficial API | 1.6x | 45 |
| `volume` | Yahoo Finance Japan HTML scrape | 1.4x | 35 |
| `short` | JPX short balance Excel | 1.0x | — |
| `margin` | softhompo CSV (often unavailable) | 1.2x | 25 |

Final whale score is `min(100, max(0, round(weighted_sum)))`.

### Tier Classification
| Score | Tier key | Display |
|---|---|---|
| 80-100 | `strong` | 🔥 STRONG |
| 65-79 | `watch` | ⭐ WATCH |
| 50-64 | `monitor` | 👀 MONITOR |
| 0-49 | `low` | LOW |

### Output JSON Schema

Both `data/us_signals.json` and `data/jp_signals.json` share the same top-level structure:
```json
{
  "generated_at": "ISO timestamp",
  "market": "US" | "JP",
  "total": 80,
  "tickers": [
    {
      "symbol": "NVDA",
      "name": "...",          // JP only
      "market": "US",
      "score": 72,
      "tier": "watch",
      "tier_label": "⭐ WATCH",
      "price": 123.45,
      "vol_ratio": 1.8,       // US
      "change_pct": 2.3,      // JP
      "score_change": 15,     // delta from previous run
      "signals": { "insider": {...}, "filing13d": {...}, ... }
    }
  ]
}
```

`score_change` is computed by diffing against the existing JSON file before overwriting.

### HTML Dashboard

`build_html.py` generates a single-file static app by string-replacing `__DATA_PLACEHOLDER__` in the inline HTML template with the combined JSON (`{"US": ..., "JP": ...}`). The same data is also written to `docs/data.json` for the 5-minute live-reload fetch in the browser.

The dashboard has no build step — it is pure vanilla JS with no framework.

### GitHub Actions (`update.yml`)

Runs hourly via two cron schedules targeting JP and US market hours. Both `fetch_us.py` and `fetch_jp.py` run with `continue-on-error: true` (one market failing doesn't block the other). The workflow commits `data/` and `docs/` then deploys to GitHub Pages.

## Ticker Universes

- **US**: Hardcoded list `US_TICKERS` in `fetch_us.py` (~80 S&P 500 + high-volatility names).
- **JP**: Hardcoded dict `JP_TICKERS` in `fetch_jp.py` (4-digit code → company name). TOPIX Core30 + Nikkei 225 major + semiconductor/AI names.

To add tickers, edit these lists directly.

## External Data Sources

| Source | URL pattern | Notes |
|---|---|---|
| SEC EDGAR submissions | `https://data.sec.gov/submissions/CIK{CIK}.json` | 10 req/sec limit; `User-Agent` required |
| FINRA daily short vol | `https://cdn.finra.org/equity/regsho/daily/CNMSshvol{YYYYMMDD}.txt` | Pipe-delimited, T+1 |
| EDINET API v2 | `https://api.edinet-fsa.go.jp/api/v2/documents.json?date={date}&type=2` | doc_type 350/360/370 = 大量保有 |
| JPX short balance | `https://www.jpx.co.jp/markets/public/short-selling/index.html` | Excel download; URL structure changes occasionally |
| TDnet (unofficial) | `https://webapi.yanoshin.jp/webapi/tdnet/list/{YYYYMMDD}.json` | May go down without notice |
| softhompo margin | `https://softhompo.a.la9.jp/Data/...` | Often unreachable; margin signal is frequently empty |
| Yahoo Finance Options | `https://query1.finance.yahoo.com/v7/finance/options/{ticker}` | Scraped without API key |

## Known Fragile Areas

- **JPX short balance**: regex-scrapes the index HTML for Excel links; breaks when JPX changes page layout.
- **softhompo margin CSV**: URL structure frequently changes; `fetch_margin_data()` typically returns `{}` in practice.
- **TDnet yanoshin API**: unofficial, may stop without notice.
- **Yahoo Finance Japan**: HTML scraping with regex; breaks when Yahoo changes DOM structure.
- **XLSX parsing** (`_parse_xlsx_simple`): manual ZIP/XML parsing without openpyxl; fragile against format changes.

## Code Conventions

- `http_get()` is copy-pasted with minor variations across all five script files — no shared utility module.
- Rate-limiting is handled inline via `time.sleep()` calls (SEC: 0.12s between requests; Yahoo JP: 0.4s; TDnet: 0.5s).
- All output paths are resolved relative to the script's own location using `Path(__file__).parent.parent / "data"`.
- Japanese text is used extensively in comments, `detail` dict keys, and print output — this is intentional.
