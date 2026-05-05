"""
オプションスイープ精緻化モジュール (米国株向け)

機関のスマートマネーは、情報優位性を以下のパターンで現金化する:
  ① 複数の取引所に分散して同時発注 (= スイープ) → 痕跡を消す
  ② 満期間近のOTMコール大量買い (高レバレッジ)
  ③ 単一の大型ブロック ($1M+)

無料のYahoo Optionsから完全なスイープ判定はできないが、
代理指標として下記を組み合わせる:
  - Vol/OI比 >= 5x (新規ポジション証拠)
  - 単一行使価格でのプレミアム >= $1M (ブロック相当)
  - 複数満期(2-3週間+1-2ヶ月)で同時にコール集中 (= スプレッド戦略)
  - lastTradeDate が直近1時間以内 (= 緊急性)
"""

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
import urllib.request
import urllib.error

UTC = timezone.utc


def http_get(url: str, max_retries: int = 3) -> bytes:
    h = {"User-Agent": "Mozilla/5.0", "Accept-Encoding": "gzip, deflate"}
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    import gzip
                    data = gzip.decompress(data)
                return data
        except urllib.error.HTTPError as e:
            if e.code in (404, 403):
                return b""
            time.sleep(1)
        except Exception:
            time.sleep(1)
    return b""


def fetch_yahoo_expirations(ticker: str) -> list:
    """全満期日リスト取得"""
    url = f"https://query1.finance.yahoo.com/v7/finance/options/{ticker}"
    data = http_get(url)
    if not data:
        return []
    try:
        obj = json.loads(data)
        result = obj.get("optionChain", {}).get("result", [])
        if not result:
            return []
        return result[0].get("expirationDates", [])[:6]  # 最初の6満期のみ
    except Exception:
        return []


def fetch_options_chain(ticker: str, expiration: int) -> dict:
    """指定満期のオプションチェーン取得"""
    url = f"https://query1.finance.yahoo.com/v7/finance/options/{ticker}?date={expiration}"
    data = http_get(url)
    if not data:
        return {}
    try:
        obj = json.loads(data)
        result = obj.get("optionChain", {}).get("result", [])
        if not result:
            return {}
        opts = result[0].get("options", [])
        if not opts:
            return {}
        return {
            "calls": opts[0].get("calls", []),
            "puts": opts[0].get("puts", []),
            "underlying": result[0].get("quote", {}).get("regularMarketPrice", 0),
            "expiration": expiration,
        }
    except Exception:
        return {}


def detect_sweep(ticker: str) -> dict:
    """
    複数満期にまたがる異常フローを検出。
    """
    expirations = fetch_yahoo_expirations(ticker)
    if not expirations:
        return _empty()
    
    all_unusual_calls = []
    all_unusual_puts = []
    underlying = 0
    
    # 直近3満期(短期スイープ)を分析
    recent_now = datetime.now(UTC).timestamp()
    for exp in expirations[:3]:
        time.sleep(0.3)  # Yahoo保護
        chain = fetch_options_chain(ticker, exp)
        if not chain:
            continue
        underlying = chain["underlying"] or underlying
        exp_iso = datetime.fromtimestamp(exp, UTC).strftime("%Y-%m-%d")
        days_to_exp = max(1, int((exp - recent_now) / 86400))
        
        for c in chain["calls"]:
            vol = c.get("volume", 0) or 0
            oi = c.get("openInterest", 0) or 1
            if vol < 200:
                continue
            vol_oi = vol / max(oi, 1)
            premium = (c.get("lastPrice", 0) or 0) * vol * 100
            strike = c.get("strike", 0)
            
            if vol_oi >= 2.0 or premium >= 100_000:
                last_trade = c.get("lastTradeDate", 0)
                trade_iso = datetime.fromtimestamp(last_trade, UTC).strftime("%Y-%m-%d %H:%M") if last_trade else ""
                # 直近性スコア: 1時間以内 = 1.0, 24時間以内 = 0.7, それ以降 = 0.3
                age_h = (recent_now - last_trade) / 3600 if last_trade else 999
                recency = 1.0 if age_h < 1 else 0.7 if age_h < 24 else 0.3
                
                # OTM判定(行使価格 > 現値 = 投機色強)
                is_otm = strike > underlying * 1.02
                
                all_unusual_calls.append({
                    "strike": strike,
                    "vol": vol,
                    "oi": oi,
                    "vol_oi": vol_oi,
                    "premium": premium,
                    "expiration": exp_iso,
                    "days_to_exp": days_to_exp,
                    "last_trade": trade_iso,
                    "last_trade_ts": last_trade,
                    "recency": recency,
                    "is_otm": is_otm,
                    "last_price": c.get("lastPrice", 0),
                })
        
        for p in chain["puts"]:
            vol = p.get("volume", 0) or 0
            oi = p.get("openInterest", 0) or 1
            if vol < 200:
                continue
            vol_oi = vol / max(oi, 1)
            premium = (p.get("lastPrice", 0) or 0) * vol * 100
            strike = p.get("strike", 0)
            
            if vol_oi >= 2.0 or premium >= 100_000:
                last_trade = p.get("lastTradeDate", 0)
                trade_iso = datetime.fromtimestamp(last_trade, UTC).strftime("%Y-%m-%d %H:%M") if last_trade else ""
                age_h = (recent_now - last_trade) / 3600 if last_trade else 999
                recency = 1.0 if age_h < 1 else 0.7 if age_h < 24 else 0.3
                
                all_unusual_puts.append({
                    "strike": strike,
                    "vol": vol,
                    "oi": oi,
                    "vol_oi": vol_oi,
                    "premium": premium,
                    "expiration": exp_iso,
                    "days_to_exp": days_to_exp,
                    "last_trade": trade_iso,
                    "last_trade_ts": last_trade,
                    "recency": recency,
                    "is_otm": strike < underlying * 0.98,
                })
    
    return _score_advanced_options(all_unusual_calls, all_unusual_puts, underlying)


def _score_advanced_options(calls: list, puts: list, underlying: float) -> dict:
    """高度化スイープスコアリング"""
    if not calls and not puts:
        return _empty()
    
    score = 0
    detail = {}
    sweep_signals = []
    
    total_call_premium = sum(c["premium"] * c["recency"] for c in calls)
    total_put_premium = sum(p["premium"] * p["recency"] for p in puts)
    
    # ① ブロック相当($1M+)
    big_call_blocks = [c for c in calls if c["premium"] >= 1_000_000]
    big_put_blocks = [p for p in puts if p["premium"] >= 1_000_000]
    
    if big_call_blocks:
        score += 25
        max_block = max(big_call_blocks, key=lambda x: x["premium"])
        detail["大型コールブロック"] = f"${int(max_block['premium']):,} (Strike ${max_block['strike']:.0f})"
        sweep_signals.append("BLOCK_CALL")
    
    if big_put_blocks:
        score -= 18
        detail["大型プットブロック"] = f"${int(big_put_blocks[0]['premium']):,} (弱気)"
        sweep_signals.append("BLOCK_PUT")
    
    # ② スイープ判定: 複数満期にまたがるコール集中
    call_expirations = set(c["expiration"] for c in calls)
    if len(call_expirations) >= 3 and total_call_premium >= 500_000:
        score += 20
        detail["複数満期スプレッド"] = f"{len(call_expirations)}満期にコール集中(機関的戦略)"
        sweep_signals.append("MULTI_EXP_SWEEP")
    
    # ③ Vol/OI極端値
    extreme_calls = [c for c in calls if c["vol_oi"] >= 10.0]
    if extreme_calls:
        score += 15
        top = max(extreme_calls, key=lambda x: x["vol_oi"])
        detail["極端Vol/OI"] = f"{top['vol_oi']:.1f}x (Strike ${top['strike']:.0f}, 満期{top['days_to_exp']}日)"
        sweep_signals.append("EXTREME_VOL_OI")
    
    # ④ OTMコール集中(投機色強)
    otm_calls_premium = sum(c["premium"] for c in calls if c["is_otm"])
    if otm_calls_premium >= 500_000:
        score += 12
        detail["OTMコール集中"] = f"${int(otm_calls_premium):,}"
        sweep_signals.append("OTM_CALL_HEAVY")
    
    # ⑤ Call/Put比
    if total_call_premium > 0 and total_put_premium > 0:
        ratio = total_call_premium / total_put_premium
        if ratio >= 3.0:
            score += 12
            detail["Call/Put比"] = f"{ratio:.1f}x (極強気)"
        elif ratio >= 2.0:
            score += 8
            detail["Call/Put比"] = f"{ratio:.1f}x (強気)"
        elif ratio < 0.5:
            score -= 12
            detail["Put優位"] = f"{1/ratio:.1f}x (弱気警戒)"
    
    # ⑥ 直近1時間以内の集中(緊急性 = 情報優位の可能性)
    fresh_calls = [c for c in calls if c["recency"] >= 1.0 and c["premium"] >= 100_000]
    if len(fresh_calls) >= 2:
        score += 10
        detail["緊急コール集中"] = f"直近1時間内に{len(fresh_calls)}件"
        sweep_signals.append("URGENT_FLOW")
    
    score = max(-30, min(60, score))
    
    if score <= 0:
        return _empty()
    
    # イベントタイムライン(プレミアム降順上位8件)
    all_options = [{**c, "type": "CALL", "is_bullish": True} for c in calls] + \
                  [{**p, "type": "PUT", "is_bullish": False} for p in puts]
    all_options.sort(key=lambda x: -x["premium"])
    
    events = []
    for opt in all_options[:8]:
        date_only = opt.get("last_trade", "").split(" ")[0] or ""
        sweep_tag = ""
        if opt["type"] == "CALL" and opt["premium"] >= 1_000_000:
            sweep_tag = " [BLOCK]"
        if opt["vol_oi"] >= 10:
            sweep_tag += " [EXTREME]"
        if opt["recency"] >= 1.0:
            sweep_tag += " [FRESH]"
        
        events.append({
            "type": opt["type"],
            "date": date_only,
            "filing_date": opt.get("last_trade", ""),
            "actor": f"{opt['type']} ${opt['strike']:.0f} 満期{opt['expiration']}",
            "title": "Bullish Flow" if opt["is_bullish"] else "Bearish Flow",
            "label": f"Vol {int(opt['vol']):,} (OI比{opt['vol_oi']:.1f}x) プレミアム ${int(opt['premium']):,}{sweep_tag}",
        })
    
    return {
        "active": True,
        "score": round(score),
        "detail": detail,
        "evidence": min(95, 50 + score),
        "events": events,
        "sweep_signals": sweep_signals,
    }


def _empty() -> dict:
    return {
        "active": False,
        "score": 0,
        "detail": {"event": "オプション異常出来高なし"},
        "evidence": 0,
        "events": [],
        "sweep_signals": [],
    }
