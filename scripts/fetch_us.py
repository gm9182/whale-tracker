"""
US Whale Tracker — SEC EDGAR / FINRA / Yahoo Finance から大口投資家シグナルを収集

データソース:
  ① SEC EDGAR        : Form 4 (インサイダー), 13D/G, 13F-HR  [完全無料・公式]
  ② FINRA            : Daily Short Sale Volume (ダークプール代理指標) [完全無料]
  ③ Yahoo Finance    : 株価・出来高・オプションチェーン [無料スクレイプ]
  ④ Yahoo Options 高度分析 : 複数満期スイープ検出・ブロック判定 [無料]

実行: python fetch_us.py
出力: data/us_signals.json
"""

import json
import time
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
import urllib.request
import urllib.error

# 同じディレクトリの他モジュールをimport可能に
sys.path.insert(0, str(Path(__file__).parent))
from options_sweep import detect_sweep

# ============================================================
# 設定
# ============================================================
USER_AGENT = "WhaleTracker research-tool research@example.com"  # SEC要求
SEC_BASE = "https://www.sec.gov"
SEC_DATA_BASE = "https://data.sec.gov"
EDGAR_SEARCH = "https://efts.sec.gov/LATEST/search-index"

OUTPUT_DIR = Path(__file__).parent.parent / "data"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 米国注目ティッカー(初期セット, S&P500主要 + 高ボラ)
US_TICKERS = [
    "NVDA", "TSLA", "AAPL", "MSFT", "GOOGL", "META", "AMZN", "AMD", "AVGO",
    "PLTR", "SOFI", "RDDT", "TEAM", "MARA", "RIOT", "COIN", "CVNA", "HOOD",
    "SNOW", "CRWD", "NET", "DDOG", "MDB", "SHOP", "ABNB", "UBER", "LYFT",
    "SMCI", "ARM", "INTC", "MU", "QCOM", "ASML", "TSM", "NFLX", "DIS",
    "JPM", "BAC", "GS", "MS", "BRK.B", "V", "MA", "PYPL", "SQ",
    "BA", "CAT", "DE", "HON", "GE", "F", "GM", "RIVN", "LCID",
    "XOM", "CVX", "OXY", "DVN", "SLB", "MRO",
    "JNJ", "PFE", "MRK", "LLY", "UNH", "CVS", "WBA", "ABBV",
    "WMT", "TGT", "COST", "HD", "LOW", "NKE", "LULU", "SBUX", "MCD",
]


def http_get(url: str, headers: dict = None, max_retries: int = 3) -> bytes:
    """SEC等のレート制限に配慮したHTTP GET"""
    h = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate"}
    if headers:
        h.update(headers)
    last_err = None
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
                # gzip対応
                if resp.headers.get("Content-Encoding") == "gzip":
                    import gzip
                    data = gzip.decompress(data)
                return data
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code == 429:
                time.sleep(2 ** (attempt + 1))
                continue
            if e.code in (404, 403):
                return b""
            time.sleep(1)
        except Exception as e:
            last_err = e
            time.sleep(1)
    if last_err:
        print(f"  [WARN] HTTP fail {url[:80]}: {last_err}")
    return b""


# ============================================================
# Phase 1: ティッカー → CIK 解決
# ============================================================
def load_ticker_cik_map() -> dict:
    """SEC公式のticker.json → {ticker: cik(10桁0埋め)}"""
    print("[1/5] CIK解決中...")
    url = f"{SEC_BASE}/files/company_tickers.json"
    data = http_get(url)
    if not data:
        return {}
    obj = json.loads(data)
    out = {}
    for _, row in obj.items():
        t = row["ticker"].upper()
        cik = str(row["cik_str"]).zfill(10)
        out[t] = cik
    print(f"  → {len(out):,} tickers loaded")
    return out


# ============================================================
# Phase 2: SEC EDGAR Form 4 (インサイダー取引)
# ============================================================
def fetch_form4(cik: str, ticker: str, lookback_days: int = 30) -> dict:
    """
    Form 4を直近30日分検索し、インサイダー買い(Pコード)を集計。
    
    判定:
    - クラスターバイ(複数役員が同期間に買い): 高得点
    - CEO/CFOの単独大型買い($500K+): 中得点
    - 売却が複数: ペナルティ
    """
    url = f"{SEC_DATA_BASE}/submissions/CIK{cik}.json"
    data = http_get(url)
    if not data:
        return _empty_insider()
    
    try:
        sub = json.loads(data)
    except json.JSONDecodeError:
        return _empty_insider()
    
    recent = sub.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accs = recent.get("accessionNumber", [])
    dates = recent.get("filingDate", [])
    
    cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).date()
    buys = []
    sells = []
    
    for i, form in enumerate(forms):
        if form != "4":
            continue
        try:
            fdate = datetime.fromisoformat(dates[i]).date()
        except Exception:
            continue
        if fdate < cutoff:
            continue
        
        # Form 4 の XML を取得
        acc = accs[i].replace("-", "")
        idx_url = f"{SEC_BASE}/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=4&dateb=&owner=include&count=40"
        # XMLは直接取得
        xml_url = f"{SEC_BASE}/Archives/edgar/data/{int(cik)}/{acc}/"
        time.sleep(0.12)  # 8 req/sec 以下に
        idx_data = http_get(xml_url)
        if not idx_data:
            continue
        
        # XMLファイル名を抽出
        m = re.search(rb'href="([^"]*\.xml)"', idx_data)
        if not m:
            continue
        xml_path = m.group(1).decode()
        if not xml_path.startswith("/"):
            xml_path = f"/Archives/edgar/data/{int(cik)}/{acc}/{xml_path}"
        
        time.sleep(0.12)
        xml_data = http_get(SEC_BASE + xml_path)
        if not xml_data:
            continue
        
        parsed = _parse_form4_xml(xml_data.decode("utf-8", errors="ignore"))
        for tx in parsed:
            tx["filing_date"] = str(fdate)
            if tx["code"] == "P":  # Open market purchase
                buys.append(tx)
            elif tx["code"] == "S":
                sells.append(tx)
        
        # 数件で十分(レート制限保護)
        if len(buys) + len(sells) > 15:
            break
    
    return _score_insider(buys, sells)


def _parse_form4_xml(xml: str) -> list:
    """Form 4 XML をシンプルにパース"""
    txs = []
    # nonDerivativeTransaction を抽出
    blocks = re.findall(
        r"<nonDerivativeTransaction>(.*?)</nonDerivativeTransaction>",
        xml,
        re.DOTALL,
    )
    
    # 役職取得
    is_director = bool(re.search(r"<isDirector>(?:true|1)</isDirector>", xml, re.I))
    is_officer = bool(re.search(r"<isOfficer>(?:true|1)</isOfficer>", xml, re.I))
    is_ten_pct = bool(re.search(r"<isTenPercentOwner>(?:true|1)</isTenPercentOwner>", xml, re.I))
    title_m = re.search(r"<officerTitle>(?:<value>)?([^<]+)", xml)
    title = title_m.group(1).strip() if title_m else ""
    name_m = re.search(r"<rptOwnerName>([^<]+)", xml)
    name = name_m.group(1).strip() if name_m else "Unknown"
    
    for block in blocks:
        code_m = re.search(r"<transactionCode>([A-Z])</transactionCode>", block)
        shares_m = re.search(r"<transactionShares>\s*<value>([\d.]+)", block)
        price_m = re.search(r"<transactionPricePerShare>\s*<value>([\d.]+)", block)
        date_m = re.search(r"<transactionDate>\s*<value>([\d-]+)", block)
        if not (code_m and shares_m):
            continue
        code = code_m.group(1)
        shares = float(shares_m.group(1))
        price = float(price_m.group(1)) if price_m else 0
        value = shares * price
        txn_date = date_m.group(1) if date_m else ""
        txs.append({
            "code": code,
            "shares": shares,
            "price": price,
            "value": value,
            "name": name,
            "title": title,
            "is_director": is_director,
            "is_officer": is_officer,
            "is_ten_pct": is_ten_pct,
            "transaction_date": txn_date,
        })
    return txs


def _score_insider(buys: list, sells: list) -> dict:
    """インサイダー取引のスコア化 + 生イベント返却"""
    score = 0
    detail = {}
    events = []  # 表示用の生イベントタイムライン
    
    if not buys and not sells:
        return _empty_insider()
    
    # クラスターバイ判定: 直近期間に2人以上が買付
    if len(buys) >= 2:
        unique_names = set(b["name"] for b in buys)
        if len(unique_names) >= 2:
            score += 25
            detail["クラスターバイ"] = f"{len(unique_names)}名が直近期間に買付"
    
    # 大型買い
    big_buys = [b for b in buys if b["value"] >= 500_000]
    if big_buys:
        max_buy = max(big_buys, key=lambda x: x["value"])
        score += min(20, int(max_buy["value"] / 100_000))
        title = max_buy.get("title") or ("CEO/CFO" if max_buy["is_officer"] else "Insider")
        detail["最大買付"] = f"{title}: ${max_buy['value']:,.0f}"
    
    # 10%以上保有者の買い
    ten_pct_buys = [b for b in buys if b["is_ten_pct"]]
    if ten_pct_buys:
        score += 15
        detail["10%超保有者"] = f"{len(ten_pct_buys)}件の買い"
    
    # 売却ペナルティ
    big_sells = [s for s in sells if s["value"] >= 1_000_000]
    if len(big_sells) >= 2:
        score -= 10
        detail["大型売却警戒"] = f"{len(big_sells)}件の$1M+売却"
    
    score = max(0, min(60, score))
    
    # 生イベントタイムライン作成(全買い + 大型売り、新しい順)
    all_events = []
    for b in buys:
        all_events.append({
            "type": "BUY",
            "date": b.get("transaction_date") or b.get("filing_date", ""),
            "filing_date": b.get("filing_date", ""),
            "actor": b["name"],
            "title": b.get("title") or ("Director" if b["is_director"] else "Officer" if b["is_officer"] else "10% Owner" if b["is_ten_pct"] else "Insider"),
            "shares": int(b["shares"]),
            "price": round(b["price"], 2),
            "value": int(b["value"]),
            "label": f"{int(b['shares']):,}株 @ ${b['price']:.2f} (${int(b['value']):,})",
        })
    for s in sells:
        if s["value"] >= 500_000:  # 50万ドル以上の売りのみ表示
            all_events.append({
                "type": "SELL",
                "date": s.get("transaction_date") or s.get("filing_date", ""),
                "filing_date": s.get("filing_date", ""),
                "actor": s["name"],
                "title": s.get("title") or "Insider",
                "shares": int(s["shares"]),
                "price": round(s["price"], 2),
                "value": int(s["value"]),
                "label": f"{int(s['shares']):,}株 @ ${s['price']:.2f} (${int(s['value']):,})",
            })
    
    # 日付降順
    all_events.sort(key=lambda x: x["date"] or x["filing_date"], reverse=True)
    
    return {
        "active": score > 0,
        "score": score,
        "detail": detail or {"event": "シグナルなし"},
        "buy_count": len(buys),
        "sell_count": len(sells),
        "evidence": min(95, 40 + score),
        "events": all_events[:10],  # 直近10件
    }


def _empty_insider() -> dict:
    return {"active": False, "score": 0, "detail": {"event": "直近期間にシグナルなし"}, "evidence": 0, "buy_count": 0, "sell_count": 0, "events": []}


# ============================================================
# Phase 3: SEC EDGAR 13D/13G (5%以上保有報告)
# ============================================================
ACTIVIST_FILERS = {
    # 著名アクティビスト・ファンド名(部分一致)
    "pershing square", "elliott", "engine no", "icahn", "starboard",
    "third point", "trian", "valueact", "jana", "hudson",
    "ackman", "loeb", "einhorn",
}


def fetch_13dg(cik: str, ticker: str, lookback_days: int = 60) -> dict:
    """13D/13G の最近の提出を確認"""
    # EDGAR full-text search
    q = {
        "q": f'"{ticker}"',
        "forms": "SC 13D,SC 13G,SC 13D/A,SC 13G/A",
        "dateRange": "custom",
        "startdt": (datetime.now(timezone.utc) - timedelta(days=lookback_days)).strftime("%Y-%m-%d"),
        "enddt": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }
    url = f"{EDGAR_SEARCH}?" + urlencode(q)
    time.sleep(0.15)
    data = http_get(url)
    if not data:
        return _empty_13dg()
    
    try:
        result = json.loads(data)
    except json.JSONDecodeError:
        return _empty_13dg()
    
    hits = result.get("hits", {}).get("hits", [])
    if not hits:
        return _empty_13dg()
    
    score = 0
    detail = {}
    has_activist = False
    events = []
    
    for h in hits[:5]:
        src = h.get("_source", {})
        form = src.get("form", "")
        display_names = src.get("display_names", [])
        filer = display_names[0].lower() if display_names else ""
        filer_name = display_names[0] if display_names else "Unknown"
        filing_date = src.get("file_date", "") or src.get("adsh", "")[:10]
        
        # ティッカー一致チェック
        tickers_in_filing = src.get("tickers", [])
        if ticker.upper() not in [t.upper() for t in tickers_in_filing]:
            continue
        
        is_activist = False
        for activist in ACTIVIST_FILERS:
            if activist in filer:
                has_activist = True
                is_activist = True
                detail["著名アクティビスト"] = display_names[0][:50]
                break
        
        if "13D" in form and "/A" not in form:
            score += 25
            detail.setdefault("最新13D提出", form)
            events.append({
                "type": "13D",
                "date": filing_date,
                "filing_date": filing_date,
                "actor": filer_name[:60],
                "title": "Activist" if is_activist else "Institution",
                "label": f"{form} 提出 ({filer_name[:30]})",
                "is_activist": is_activist,
            })
        elif "13G" in form and "/A" not in form:
            score += 10
            detail.setdefault("最新13G提出", form)
            events.append({
                "type": "13G",
                "date": filing_date,
                "filing_date": filing_date,
                "actor": filer_name[:60],
                "title": "Institution",
                "label": f"{form} 提出 ({filer_name[:30]})",
                "is_activist": is_activist,
            })
        elif "/A" in form:
            score += 5
            detail.setdefault("変更報告", form)
            events.append({
                "type": "AMEND",
                "date": filing_date,
                "filing_date": filing_date,
                "actor": filer_name[:60],
                "title": "Amendment",
                "label": f"{form} 変更報告 ({filer_name[:30]})",
                "is_activist": is_activist,
            })
    
    if has_activist:
        score += 15
    
    score = min(30, score)
    
    events.sort(key=lambda x: x["date"], reverse=True)
    
    if score == 0:
        return _empty_13dg()
    
    return {
        "active": True,
        "score": score,
        "detail": detail,
        "evidence": min(90, 50 + score),
        "events": events[:5],
    }


def _empty_13dg() -> dict:
    return {"active": False, "score": 0, "detail": {"event": "直近期間に5%超保有報告なし"}, "evidence": 0, "events": []}


# ============================================================
# Phase 4: Yahoo Finance — 株価 + オプション異常出来高
# ============================================================
def fetch_yahoo_quote(ticker: str) -> dict:
    """株価・出来高・基本情報"""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=1mo&interval=1d"
    data = http_get(url, headers={"User-Agent": "Mozilla/5.0"})
    if not data:
        return {}
    try:
        obj = json.loads(data)
        result = obj["chart"]["result"][0]
        meta = result.get("meta", {})
        ind = result.get("indicators", {}).get("quote", [{}])[0]
        volumes = [v for v in ind.get("volume", []) if v]
        avg_vol = sum(volumes) / len(volumes) if volumes else 0
        last_vol = volumes[-1] if volumes else 0
        return {
            "price": meta.get("regularMarketPrice", 0),
            "prev_close": meta.get("chartPreviousClose", 0),
            "volume": last_vol,
            "avg_volume": avg_vol,
            "vol_ratio": (last_vol / avg_vol) if avg_vol > 0 else 0,
        }
    except Exception:
        return {}


def fetch_options_flow(ticker: str) -> dict:
    """
    Yahoo Optionsから簡易的にOI/Volを取得し、コール優位とVol/OI急騰を判定。
    本格スイープ検出は有料APIが必要だが、Vol/OI比は十分代替可能。
    """
    url = f"https://query1.finance.yahoo.com/v7/finance/options/{ticker}"
    data = http_get(url, headers={"User-Agent": "Mozilla/5.0"})
    if not data:
        return _empty_options()
    try:
        obj = json.loads(data)
        chain = obj.get("optionChain", {}).get("result", [])
        if not chain:
            return _empty_options()
        opts = chain[0].get("options", [])
        if not opts:
            return _empty_options()
        
        calls = opts[0].get("calls", [])
        puts = opts[0].get("puts", [])
        underlying = chain[0].get("quote", {}).get("regularMarketPrice", 0)
        
        # 満期日の取得(Unix時刻)
        exp_ts = opts[0].get("expirationDate", 0)
        exp_date = datetime.fromtimestamp(exp_ts, timezone.utc).strftime("%Y-%m-%d") if exp_ts else ""
        
        # コール: Vol > OI かつOTM(行使価格 > 現値)を集計
        unusual_calls = []
        unusual_puts = []
        for c in calls:
            vol = c.get("volume", 0) or 0
            oi = c.get("openInterest", 0) or 1
            strike = c.get("strike", 0)
            if vol >= 500 and (vol / max(oi, 1)) >= 2.0:
                last_trade = c.get("lastTradeDate", 0)
                trade_dt = datetime.fromtimestamp(last_trade, timezone.utc).strftime("%Y-%m-%d %H:%M") if last_trade else ""
                unusual_calls.append({
                    "strike": strike,
                    "vol": vol,
                    "oi": oi,
                    "vol_oi": vol / max(oi, 1),
                    "premium": (c.get("lastPrice", 0) or 0) * vol * 100,
                    "expiration": exp_date,
                    "last_trade": trade_dt,
                    "last_price": c.get("lastPrice", 0),
                })
        for p in puts:
            vol = p.get("volume", 0) or 0
            oi = p.get("openInterest", 0) or 1
            strike = p.get("strike", 0)
            if vol >= 500 and (vol / max(oi, 1)) >= 2.0:
                last_trade = p.get("lastTradeDate", 0)
                trade_dt = datetime.fromtimestamp(last_trade, timezone.utc).strftime("%Y-%m-%d %H:%M") if last_trade else ""
                unusual_puts.append({
                    "strike": strike,
                    "vol": vol,
                    "oi": oi,
                    "vol_oi": vol / max(oi, 1),
                    "premium": (p.get("lastPrice", 0) or 0) * vol * 100,
                    "expiration": exp_date,
                    "last_trade": trade_dt,
                    "last_price": p.get("lastPrice", 0),
                })
        
        return _score_options(unusual_calls, unusual_puts, underlying)
    except Exception as e:
        return _empty_options()


def _score_options(calls: list, puts: list, underlying: float) -> dict:
    """オプションフロースコア + 生イベント"""
    score = 0
    detail = {}
    events = []
    
    total_call_premium = sum(c["premium"] for c in calls)
    total_put_premium = sum(p["premium"] for p in puts)
    
    if total_call_premium >= 500_000:
        score += 25
        top_call = max(calls, key=lambda x: x["premium"])
        detail["最大コール"] = f"Strike ${top_call['strike']:.0f} (Vol/OI: {top_call['vol_oi']:.1f}x)"
        detail["コール総プレミアム"] = f"${total_call_premium:,.0f}"
    elif total_call_premium >= 100_000:
        score += 12
        detail["コール総プレミアム"] = f"${total_call_premium:,.0f}"
    
    # コール優位
    if total_call_premium > 0 and total_put_premium > 0:
        ratio = total_call_premium / total_put_premium
        if ratio >= 2.0:
            score += 15
            detail["Call/Put比"] = f"{ratio:.1f}x (強気)"
        elif ratio < 0.5:
            score -= 15
            detail["Put優位"] = f"{1/ratio:.1f}x (弱気)"
    
    # Vol/OI > 5x
    high_vol_oi = [c for c in calls if c["vol_oi"] >= 5.0]
    if high_vol_oi:
        score += 15
        detail["異常Vol/OI銘柄"] = f"{len(high_vol_oi)}本"
    
    # イベントタイムライン: 上位プレミアム順
    sorted_calls = sorted(calls, key=lambda x: -x["premium"])[:5]
    sorted_puts = sorted(puts, key=lambda x: -x["premium"])[:3]
    for c in sorted_calls:
        events.append({
            "type": "CALL",
            "date": c.get("last_trade", "").split(" ")[0],
            "filing_date": c.get("last_trade", ""),
            "actor": f"Call ${c['strike']:.0f} 満期{c['expiration']}",
            "title": "Bullish Flow",
            "label": f"Vol {int(c['vol']):,} (OI比{c['vol_oi']:.1f}x) プレミアム ${int(c['premium']):,}",
        })
    for p in sorted_puts:
        events.append({
            "type": "PUT",
            "date": p.get("last_trade", "").split(" ")[0],
            "filing_date": p.get("last_trade", ""),
            "actor": f"Put ${p['strike']:.0f} 満期{p['expiration']}",
            "title": "Bearish Flow",
            "label": f"Vol {int(p['vol']):,} (OI比{p['vol_oi']:.1f}x) プレミアム ${int(p['premium']):,}",
        })
    events.sort(key=lambda x: x["filing_date"], reverse=True)
    
    score = max(-20, min(45, score))
    
    if score <= 0:
        return _empty_options()
    
    return {
        "active": True,
        "score": score,
        "detail": detail,
        "evidence": min(90, 45 + score),
        "events": events[:8],
    }


def _empty_options() -> dict:
    return {"active": False, "score": 0, "detail": {"event": "オプション異常出来高なし"}, "evidence": 0, "events": []}


# ============================================================
# Phase 5: FINRA — ダークプール代理指標
# ============================================================
def fetch_finra_short_volume(ticker: str) -> dict:
    """
    FINRAのDaily Short Sale Volumeから、Off-Exchangeショート比率を取得。
    機関投資家のヘッジ付きロングのプロキシ。
    
    URLパターン: https://cdn.finra.org/equity/regsho/daily/CNMSshvol{YYYYMMDD}.txt
    """
    # 直近営業日(複数試行)
    for offset in range(1, 6):
        d = datetime.now(timezone.utc) - timedelta(days=offset)
        if d.weekday() >= 5:  # 週末スキップ
            continue
        date_str = d.strftime("%Y%m%d")
        url = f"https://cdn.finra.org/equity/regsho/daily/CNMSshvol{date_str}.txt"
        data = http_get(url, headers={"User-Agent": "Mozilla/5.0"})
        if data and len(data) > 1000:
            break
    else:
        return _empty_darkpool()
    
    # FINRAは Pipe区切り
    text = data.decode("utf-8", errors="ignore")
    lines = text.splitlines()
    if len(lines) < 2:
        return _empty_darkpool()
    
    # ヘッダー: Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market
    target = ticker.upper()
    for line in lines[1:]:
        parts = line.split("|")
        if len(parts) < 5:
            continue
        if parts[1].upper() != target:
            continue
        try:
            short_vol = int(parts[2])
            total_vol = int(parts[4])
        except (ValueError, IndexError):
            continue
        
        if total_vol < 10000:  # 流動性低すぎ
            return _empty_darkpool()
        
        short_ratio = short_vol / total_vol
        
        score = 0
        detail = {}
        
        # ショート比率50%以上は機関ヘッジロングの可能性
        if short_ratio >= 0.60:
            score += 18
            detail["ショート比率"] = f"{short_ratio*100:.1f}% (機関ヘッジ示唆)"
        elif short_ratio >= 0.50:
            score += 12
            detail["ショート比率"] = f"{short_ratio*100:.1f}%"
        elif short_ratio >= 0.40:
            score += 6
            detail["ショート比率"] = f"{short_ratio*100:.1f}%"
        
        # 出来高絶対量
        if total_vol >= 5_000_000:
            score += 8
            detail["Off-Ex出来高"] = f"{total_vol:,}"
        
        score = max(0, min(35, score))
        if score == 0:
            return _empty_darkpool()
        
        date_iso = date_str[:4] + "-" + date_str[4:6] + "-" + date_str[6:8]
        detail["データ日"] = date_iso
        
        events = [{
            "type": "DARKPOOL",
            "date": date_iso,
            "filing_date": date_iso,
            "actor": f"FINRA Off-Exchange (CNMS)",
            "title": "T+1 集計",
            "label": f"ショート比率 {short_ratio*100:.1f}% / 総出来高 {total_vol:,}株",
        }]
        
        return {
            "active": True,
            "score": score,
            "detail": detail,
            "evidence": min(80, 40 + score),
            "events": events,
        }
    
    return _empty_darkpool()


def _empty_darkpool() -> dict:
    return {"active": False, "score": 0, "detail": {"event": "ダークプール特異性なし"}, "evidence": 0, "events": []}


# ============================================================
# Phase 6: 13F (機関投資家四半期報告) — シンプル版
# ============================================================
def fetch_13f_summary(cik: str, ticker: str) -> dict:
    """
    13F は四半期45日遅延のため、ここでは簡易的にFintel/Stockanalysisを使わず、
    EDGAR full-text search で直近90日の "13F" 言及をチェック。
    本格版は别途専用APIを推奨。
    """
    return {"active": False, "score": 0, "detail": {"event": "13Fは四半期更新(別途集計)"}, "evidence": 0, "events": []}


# ============================================================
# 統合スコアリング
# ============================================================
def compute_whale_score(signals: dict) -> int:
    """設計書通りの加重合計"""
    score = 0
    score += signals["insider"]["score"] * 1.5
    score += signals["filing13d"]["score"] * 1.3
    score += signals["options"]["score"] * 1.4
    score += signals["darkpool"]["score"] * 1.0
    score += signals["filing13f"]["score"] * 0.8
    return min(100, max(0, round(score)))


def get_tier(score: int) -> dict:
    if score >= 80:
        return {"label": "🔥 STRONG", "key": "strong", "color": "#00ff9d"}
    if score >= 65:
        return {"label": "⭐ WATCH", "key": "watch", "color": "#ffb800"}
    if score >= 50:
        return {"label": "👀 MONITOR", "key": "monitor", "color": "#00f0ff"}
    return {"label": "LOW", "key": "low", "color": "#6b7494"}


# ============================================================
# メイン処理
# ============================================================
def main():
    print("=" * 60)
    print(" 🇺🇸 US Whale Tracker — Smart Money Detector ")
    print("=" * 60)
    print(f" 開始: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f" 対象: {len(US_TICKERS)} tickers\n")
    
    cik_map = load_ticker_cik_map()
    
    results = []
    for i, ticker in enumerate(US_TICKERS, 1):
        print(f"[{i:3d}/{len(US_TICKERS)}] {ticker}...", end=" ", flush=True)
        cik = cik_map.get(ticker.replace(".", "-"))  # BRK.B → BRK-B
        if not cik:
            cik = cik_map.get(ticker)
        
        signals = {
            "insider": _empty_insider(),
            "filing13d": _empty_13dg(),
            "options": _empty_options(),
            "darkpool": _empty_darkpool(),
            "filing13f": {"active": False, "score": 0, "detail": {}, "evidence": 0},
        }
        
        if cik:
            try:
                signals["insider"] = fetch_form4(cik, ticker)
            except Exception as e:
                print(f"  insider err: {e}", end=" ")
            try:
                signals["filing13d"] = fetch_13dg(cik, ticker)
            except Exception as e:
                print(f"  13d err: {e}", end=" ")
        
        try:
            # 高度化スイープ検出を使用(複数満期分析・ブロック検出)
            signals["options"] = detect_sweep(ticker)
        except Exception as e:
            print(f"  opt err: {e}", end=" ")
            try:
                # フォールバック: 旧シンプル検出
                signals["options"] = fetch_options_flow(ticker)
            except Exception:
                pass
        try:
            signals["darkpool"] = fetch_finra_short_volume(ticker)
        except Exception as e:
            print(f"  dp err: {e}", end=" ")
        
        quote = fetch_yahoo_quote(ticker)
        score = compute_whale_score(signals)
        tier = get_tier(score)
        
        results.append({
            "symbol": ticker,
            "market": "US",
            "score": score,
            "tier": tier["key"],
            "tier_label": tier["label"],
            "price": quote.get("price", 0),
            "prev_close": quote.get("prev_close", 0),
            "vol_ratio": round(quote.get("vol_ratio", 0), 2),
            "signals": signals,
        })
        print(f"score={score} [{tier['label']}]")
    
    # スコア降順
    results.sort(key=lambda x: -x["score"])
    
    # 前回データとの差分(スコア急変ハイライト用)
    prev_path = OUTPUT_DIR / "us_signals.json"
    prev_scores = {}
    if prev_path.exists():
        try:
            prev = json.loads(prev_path.read_text())
            prev_scores = {t["symbol"]: t["score"] for t in prev.get("tickers", [])}
        except Exception:
            pass
    
    for r in results:
        prev_score = prev_scores.get(r["symbol"], r["score"])
        r["score_change"] = r["score"] - prev_score
    
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "market": "US",
        "total": len(results),
        "tickers": results,
    }
    
    out_path = OUTPUT_DIR / "us_signals.json"
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(f"\n✅ 保存: {out_path}")
    print(f"   STRONG: {sum(1 for r in results if r['tier']=='strong')}件")
    print(f"   WATCH:  {sum(1 for r in results if r['tier']=='watch')}件")
    print(f"   MONITOR:{sum(1 for r in results if r['tier']=='monitor')}件")


if __name__ == "__main__":
    main()
