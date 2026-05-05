"""
信用取引週末残高(Margin Balance) フェッチャー + 急変分析

データソース:
  softhompo.a.la9.jp が東証日報PDFをCSV化して公開(完全無料)
  - 信用買残・売残・前週比変動
  - 全プライム銘柄、毎週金曜更新

判定ロジック(プロのトレーダー視点):
  ★★★★★ 信用買残急減 + 株価上昇傾向 = 踏み上げ余地大
  ★★★★  信用売残急増 + ポジティブ材料 = ショートカバー候補
  ★★★   信用倍率 < 1.0 (売残>買残) + 出来高増 = 強気サイン
  ★★    信用買残急増 = 個人の追加買い(過熱警戒)
"""

import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
import urllib.request
import urllib.error

JST = timezone(timedelta(hours=9))
USER_AGENT = "WhaleTracker-Margin research-tool"
SOURCE_INDEX = "https://softhompo.a.la9.jp/Data/StockData.html"

OUTPUT_DIR = Path(__file__).parent.parent / "data"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def http_get(url: str, max_retries: int = 3) -> bytes:
    h = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate"}
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=30) as resp:
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


def fetch_margin_index() -> list:
    """
    信用残CSVのリンクをインデックスページから取得。
    URLパターン: 信用週末残高_YYYYMMDD.csv 形式
    """
    print("[Margin] 信用残データのインデックス取得中...")
    data = http_get(SOURCE_INDEX)
    if not data:
        print("  → インデックス取得失敗")
        return []
    
    html = data.decode("shift_jis", errors="ignore")
    if "html" not in html.lower():
        # shift_jisで読めなかった場合
        html = data.decode("utf-8", errors="ignore")
    
    # 信用残CSVファイル名を検索
    csv_patterns = [
        r'href="([^"]*信用[^"]*\.csv)"',
        r'href="([^"]*margin[^"]*\.csv)"',
        r'href="([^"]*shinyo[^"]*\.csv)"',
    ]
    links = []
    for pat in csv_patterns:
        found = re.findall(pat, html, re.IGNORECASE)
        links.extend(found)
    
    return links


def fetch_margin_data() -> dict:
    """
    softhompo の信用残データを取得し {code: {buy, sell, ratio, prev_week_buy, prev_week_sell}} 形式で返す。
    
    ※実際のCSV取得は接続失敗するため、本実装ではフォールバック方式を採用:
     1. インデックスページから最新CSVを試行
     2. 失敗時は空辞書を返す
    """
    print("[Margin] データ取得中...")
    
    # 直近の金曜日(信用残データの基準日)
    today = datetime.now(JST).date()
    days_back = (today.weekday() - 4) % 7  # 4=金曜
    if days_back == 0 and datetime.now(JST).hour < 18:
        days_back = 7  # まだ更新前なら先週
    last_friday = today - timedelta(days=max(days_back, 1))
    
    # softhompo URL試行(複数パターン)
    date_strs = [
        last_friday.strftime("%Y%m%d"),
        last_friday.strftime("%Y_%m_%d"),
        last_friday.strftime("%y%m%d"),
    ]
    
    margin_data = {}
    
    for date_str in date_strs:
        # 想定パスをいくつか試行
        for path_pattern in [
            f"https://softhompo.a.la9.jp/Data/Margin/{date_str}.csv",
            f"https://softhompo.a.la9.jp/Data/信用週末残高_{date_str}.csv",
            f"https://softhompo.a.la9.jp/Data/StockMargin{date_str}.csv",
        ]:
            time.sleep(0.5)
            data = http_get(path_pattern)
            if data and len(data) > 1000:
                try:
                    text = data.decode("shift_jis", errors="ignore")
                except Exception:
                    text = data.decode("utf-8", errors="ignore")
                margin_data = _parse_margin_csv(text)
                if margin_data:
                    print(f"  → 取得成功: {len(margin_data)}銘柄 ({date_str})")
                    return margin_data
    
    print("  → 公開信用残データ取得失敗(URL構造未特定/欠損中)")
    print("  → 代替: J-Quants APIまたは個別証券会社のRSS/CSV連携を推奨")
    return {}


def _parse_margin_csv(text: str) -> dict:
    """
    信用残CSVをパース。フォーマット例:
    銘柄コード,銘柄名,信用買残,信用売残,前週比買残,前週比売残,信用倍率
    """
    out = {}
    lines = text.splitlines()
    
    for line in lines[1:]:  # ヘッダースキップ
        parts = [p.strip().strip('"') for p in line.split(",")]
        if len(parts) < 4:
            continue
        
        code = parts[0]
        if not re.fullmatch(r"\d{4,5}", code):
            continue
        if len(code) == 5 and code.endswith("0"):
            code = code[:4]
        
        try:
            buy = int(parts[2].replace(",", "")) if parts[2] else 0
            sell = int(parts[3].replace(",", "")) if parts[3] else 0
            prev_buy = int(parts[4].replace(",", "")) if len(parts) > 4 and parts[4] else 0
            prev_sell = int(parts[5].replace(",", "")) if len(parts) > 5 and parts[5] else 0
            ratio = float(parts[6]) if len(parts) > 6 and parts[6] else (buy / max(sell, 1) if sell else 999)
        except (ValueError, IndexError):
            continue
        
        out[code] = {
            "buy": buy,
            "sell": sell,
            "prev_buy": prev_buy,
            "prev_sell": prev_sell,
            "ratio": ratio,
            "buy_change_pct": (prev_buy / max(buy, 1) - 1) * 100 if buy > 0 and prev_buy else 0,
            "sell_change_pct": (prev_sell / max(sell, 1) - 1) * 100 if sell > 0 and prev_sell else 0,
        }
    return out


def score_margin(code: str, margin: dict, current_price: float = 0, vol_ratio: float = 0) -> dict:
    """
    信用残データから踏み上げ余地・蓄積過熱を判定。
    """
    if not margin:
        return _empty_margin()
    
    buy = margin.get("buy", 0)
    sell = margin.get("sell", 0)
    ratio = margin.get("ratio", 0)
    buy_chg = margin.get("buy_change_pct", 0)
    sell_chg = margin.get("sell_change_pct", 0)
    
    score = 0
    detail = {}
    events = []
    today_iso = datetime.now(JST).strftime("%Y-%m-%d")
    
    # ① 信用倍率(buy/sell): 1.0未満は踏み上げ余地
    if 0 < ratio < 1.0:
        score += 12
        detail["信用倍率"] = f"{ratio:.2f} (売残>買残: 踏み上げ余地)"
    elif ratio >= 5.0:
        score -= 8
        detail["信用倍率"] = f"{ratio:.2f} (買残過熱: 利確売り警戒)"
    elif 0 < ratio < 2.0:
        score += 4
        detail["信用倍率"] = f"{ratio:.2f}"
    else:
        detail["信用倍率"] = f"{ratio:.2f}"
    
    # ② 信用買残急減 = 過去の買い圧力解消(価格上昇でカバー余地)
    if buy_chg < -15:
        score += 10
        detail["信用買残急減"] = f"前週比 {buy_chg:.1f}%"
    
    # ③ 信用売残急増 = ショート蓄積(踏み上げ候補)
    if sell_chg > 25:
        score += 12
        detail["信用売残急増"] = f"前週比 +{sell_chg:.1f}% (踏み上げ候補)"
    
    # ④ 価格情報がある場合の組み合わせ
    if vol_ratio >= 2.0 and ratio < 1.5:
        score += 8
        detail["強気組合せ"] = "信用倍率低 × 出来高急増"
    
    # 絶対値表示
    detail["信用買残"] = f"{buy:,}株"
    detail["信用売残"] = f"{sell:,}株"
    
    if score == 0:
        return _empty_margin()
    
    score = max(-15, min(25, score))
    
    # イベント生成
    events.append({
        "type": "MARGIN",
        "date": today_iso,
        "filing_date": today_iso,
        "actor": "JPX 信用取引週末残高",
        "title": "Weekly Snapshot",
        "label": f"買残{buy:,} / 売残{sell:,} / 倍率{ratio:.2f} / 前週比 買{buy_chg:+.1f}%/売{sell_chg:+.1f}%",
    })
    
    return {
        "active": True,
        "score": score,
        "detail": detail,
        "evidence": min(80, 40 + abs(score)),
        "events": events,
    }


def _empty_margin() -> dict:
    return {
        "active": False,
        "score": 0,
        "detail": {"event": "信用残データなし"},
        "evidence": 0,
        "events": [],
    }


def main():
    print("=" * 60)
    print(" 📊 信用取引残高 アナライザー ")
    print("=" * 60)
    
    margin_data = fetch_margin_data()
    
    out = {
        "generated_at": datetime.now(JST).isoformat(),
        "total_tickers": len(margin_data),
        "data": margin_data,
    }
    
    out_path = OUTPUT_DIR / "margin_signals.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"\n✅ 保存: {out_path}")
    print(f"   銘柄数: {len(margin_data)}")


if __name__ == "__main__":
    main()
