"""
TDnet 適時開示情報フェッチャー
非公式WEB-API (webapi.yanoshin.jp) 経由で全件取得し、カテゴリ分類してスコア化。

カテゴリ別重要度(プロのトレーダー視点):
  ★★★★★ 上方修正/下方修正        — 翌日寄り付き直撃
  ★★★★★ 自社株買い                 — 需給改善・株主還元シグナル
  ★★★★  業務提携/資本提携          — 中期テーマ性
  ★★★★  株式分割                   — 個人投資家流入
  ★★★   M&A・公開買付              — プレミアム織込み
  ★★★   配当変更(増配)             — インカム評価
  ★★    新製品/新サービス開発       — テーマ材料
  ★★    決算短信                   — 既知織込み多
  ★     役員/組織変更               — 経営方針変更余地
"""

import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
import urllib.request
import urllib.error

JST = timezone(timedelta(hours=9))
USER_AGENT = "WhaleTracker-TDnet research-tool"
TDNET_API = "https://webapi.yanoshin.jp/webapi/tdnet"

OUTPUT_DIR = Path(__file__).parent.parent / "data"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# カテゴリ分類辞書 (タイトルキーワード → カテゴリ + スコア)
# ============================================================
CATEGORIES = [
    # (キーワードリスト, カテゴリID, 表示名, ベーススコア, 強気=1/弱気=-1)
    (["業績予想.*上方修正", "通期業績予想の修正", "通期連結業績予想の修正"], "UPWARD", "上方修正", 35, 1),
    (["業績予想.*下方修正"], "DOWNWARD", "下方修正", 30, -1),
    (["自己株式の取得", "自己株式取得", "自社株買"], "BUYBACK", "自社株買い", 30, 1),
    (["株式分割", "株式の分割"], "SPLIT", "株式分割", 22, 1),
    (["増配", "配当.*予想.*修正", "配当.*増額", "配当.*変更"], "DIV_UP", "増配・配当変更", 18, 1),
    (["減配"], "DIV_DOWN", "減配", 15, -1),
    (["業務提携", "業務.*資本提携", "資本業務提携", "戦略的提携"], "PARTNERSHIP", "業務提携", 20, 1),
    (["株式公開買付", "株式公開買い付け", "TOB", "公開買付"], "TOB", "TOB・公開買付", 28, 1),
    (["子会社化", "完全子会社", "株式取得.*連結"], "ACQUISITION", "M&A・買収", 25, 1),
    (["第三者割当", "新株予約権.*第三者", "ストックオプション以外.*第三者"], "DILUTION", "第三者割当(希薄化)", 12, -1),
    (["新製品", "新サービス", "発売", "リリース.*開始", "提供開始"], "PRODUCT", "新製品・新サービス", 8, 1),
    (["決算短信"], "EARNINGS", "決算短信", 5, 0),
    (["代表取締役.*異動", "社長交代", "代表者交代"], "EXEC_CHANGE", "経営トップ交代", 10, 0),
    (["上場廃止"], "DELIST", "上場廃止", 0, -1),
    (["特別利益", "特別損失"], "SPECIAL_PL", "特別損益", 8, 0),
]

# ノイズ(スコア対象外)
NOISE_PATTERNS = [
    r"株主総会.*招集", r"定款", r"四半期報告書$", r"有価証券報告書",
    r"独立役員.*届出", r"コーポレート.*ガバナンス報告書",
    r"自己株式.*消却",  # 償却は中立
    r"譲渡制限付株式報酬",  # 報酬付与は弱いシグナル
    r"訂正", r"内部統制", r"ストックオプション",
    r"株式報酬",
]


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
            if e.code == 429:
                time.sleep(2 ** (attempt + 1))
                continue
            return b""
        except Exception:
            time.sleep(1)
    return b""


def classify(title: str) -> dict:
    """タイトルを分類してスコアと方向を返す"""
    # ノイズ判定
    for pat in NOISE_PATTERNS:
        if re.search(pat, title):
            return None
    
    for keywords, cid, label, score, direction in CATEGORIES:
        for kw in keywords:
            if re.search(kw, title):
                return {
                    "category_id": cid,
                    "category": label,
                    "base_score": score,
                    "direction": direction,  # +1 強気 / -1 弱気 / 0 中立
                }
    return None


def fetch_tdnet_recent(days: int = 5) -> list:
    """直近N日分のTDnet開示を全件取得"""
    print(f"[TDnet] 直近{days}日分取得中...")
    all_disclosures = []
    
    today = datetime.now(JST).date()
    
    # 日付指定で取得(複数日まとめて取れるが負荷分散のため日次)
    for offset in range(days):
        d = today - timedelta(days=offset)
        # 土日スキップ(更新少)
        if d.weekday() >= 5:
            continue
        
        date_str = d.strftime("%Y%m%d")
        # ページング(1日200件以上ある可能性)
        for page in range(1, 6):  # 最大1000件/日まで
            url = f"{TDNET_API}/list/{date_str}.json?limit=200&start={(page-1)*200}"
            time.sleep(0.5)
            data = http_get(url)
            if not data:
                break
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                break
            
            items = obj.get("items", [])
            if not items:
                break
            
            for item in items:
                tdnet = item.get("Tdnet", {})
                code = (tdnet.get("company_code") or "").strip()
                if not code:
                    continue
                # 5桁コード→4桁化
                if len(code) == 5 and code.endswith("0"):
                    code = code[:4]
                
                title = tdnet.get("title", "")
                cls = classify(title)
                if cls is None:
                    continue
                
                pubdate = tdnet.get("pubdate", "")  # "2026-05-02 15:00:00"
                
                all_disclosures.append({
                    "code": code,
                    "company": tdnet.get("company_name", ""),
                    "title": title,
                    "pubdate": pubdate,
                    "url": tdnet.get("document_url", ""),
                    **cls,
                })
            
            if len(items) < 200:
                break
        
        print(f"  → {date_str}: 累計{len(all_disclosures)}件(ノイズ除外後)")
        
        # 取得しすぎ防止
        if len(all_disclosures) > 2000:
            print(f"  → 上限到達、ここで中断")
            break
    
    print(f"[TDnet] 取得完了: {len(all_disclosures)}件の重要開示")
    return all_disclosures


def index_disclosures(disclosures: list) -> dict:
    """{銘柄コード: [disclosures]} に集約"""
    by_ticker = {}
    for d in disclosures:
        code = d["code"]
        by_ticker.setdefault(code, []).append(d)
    return by_ticker


def score_tdnet(disclosures: list) -> dict:
    """銘柄ごとのTDnetシグナル統合スコア"""
    if not disclosures:
        return _empty_tdnet()
    
    # 直近を優先(古いものは減衰)
    today = datetime.now(JST)
    
    score = 0
    direction_sum = 0
    detail = {}
    events = []
    bullish_categories = []
    bearish_categories = []
    
    for d in disclosures:
        # 経過時間で減衰
        try:
            pub = datetime.strptime(d["pubdate"][:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=JST)
            age_hours = (today - pub).total_seconds() / 3600
        except Exception:
            age_hours = 24
        
        # 24時間以内は満点、72時間以上は半減
        decay = 1.0
        if age_hours > 72:
            decay = 0.5
        elif age_hours > 24:
            decay = 0.75
        
        contrib = d["base_score"] * decay
        if d["direction"] >= 0:
            score += contrib
            if d["direction"] > 0:
                bullish_categories.append(d["category"])
        else:
            score -= contrib  # 弱気開示はペナルティ
            bearish_categories.append(d["category"])
        
        direction_sum += d["direction"]
        
        # イベント化
        events.append({
            "type": d["category_id"],
            "date": d["pubdate"][:10] if d["pubdate"] else "",
            "filing_date": d["pubdate"],
            "actor": d["company"][:40],
            "title": d["category"],
            "label": d["title"][:80] + ("..." if len(d["title"]) > 80 else ""),
            "url": d["url"],
            "is_bullish": d["direction"] > 0,
            "is_bearish": d["direction"] < 0,
        })
    
    # detail整形
    if bullish_categories:
        unique_bullish = list(dict.fromkeys(bullish_categories))[:3]
        detail["強気開示"] = " / ".join(unique_bullish)
    if bearish_categories:
        unique_bearish = list(dict.fromkeys(bearish_categories))[:3]
        detail["弱気開示"] = " / ".join(unique_bearish)
    
    detail["開示件数"] = f"{len(disclosures)}件 (直近{(min(72, age_hours) if disclosures else 0):.0f}h以内)" if disclosures else "0件"
    
    # スコア正規化(上限45、下限-30)
    score = max(-30, min(45, round(score)))
    
    if score == 0:
        return _empty_tdnet()
    
    events.sort(key=lambda x: x["filing_date"], reverse=True)
    
    return {
        "active": True,
        "score": score,
        "detail": detail,
        "evidence": min(95, 50 + abs(score)),
        "events": events[:8],
        "direction": "bullish" if score > 0 else "bearish" if score < 0 else "neutral",
    }


def _empty_tdnet() -> dict:
    return {
        "active": False,
        "score": 0,
        "detail": {"event": "直近期間に重要な適時開示なし"},
        "evidence": 0,
        "events": [],
        "direction": "neutral",
    }


# ============================================================
# 単独実行 — 開示インデックスをjsonに保存
# ============================================================
def main():
    print("=" * 60)
    print(" 📰 TDnet 適時開示インデクサー ")
    print("=" * 60)
    print(f" 開始: {datetime.now(JST).strftime('%Y-%m-%d %H:%M JST')}\n")
    
    disclosures = fetch_tdnet_recent(days=5)
    by_ticker = index_disclosures(disclosures)
    
    # 銘柄別スコアサマリ
    summary = {}
    for code, ds in by_ticker.items():
        sig = score_tdnet(ds)
        if sig["active"]:
            summary[code] = sig
    
    out = {
        "generated_at": datetime.now(JST).isoformat(),
        "total_disclosures": len(disclosures),
        "tickers_with_signal": len(summary),
        "by_ticker": summary,
        "all_events": disclosures[:500],  # 最大500件保存
    }
    
    out_path = OUTPUT_DIR / "tdnet_signals.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"\n✅ 保存: {out_path}")
    print(f"   重要開示: {len(disclosures)}件")
    print(f"   シグナル発火銘柄: {len(summary)}件")
    
    # 上位ハイライト
    top = sorted(summary.items(), key=lambda x: -x[1]["score"])[:10]
    if top:
        print(f"\n🔥 トップ強気銘柄:")
        for code, sig in top:
            cat = sig["detail"].get("強気開示", sig["detail"].get("弱気開示", "?"))
            print(f"   {code}: +{sig['score']} [{cat}]")


if __name__ == "__main__":
    main()
