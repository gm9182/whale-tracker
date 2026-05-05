"""
Japan Whale Tracker — EDINET / JPX / Yahoo Finance Japan / TDnet からの大口投資家シグナル

データソース:
  ① EDINET API     : 大量保有報告書(5%ルール) [完全無料・公式・金融庁]
  ② JPX 空売り残高 : 0.5%以上の銘柄別空売り残高 [完全無料・東証]
  ③ Yahoo!ファイナンス: 株価・出来高 [無料]
  ④ TDnet 適時開示 : 上方修正・自社株買い等 [完全無料・非公式WEB-API]
  ⑤ 信用取引残高   : 踏み上げ余地検出 [完全無料]

⚠️ 米国版との重要な違い:
  - 日本にはForm 4(役員2日以内開示)に相当するリアルタイム機構が無い
    → 役員売買報告は数日~月単位で遅い。ここではEDINETの「変更報告書」を活用
  - 個別株オプション流動性が低いため代わりに「先物建玉」「裁定残」を見る
  - 立会外取引(ToSTNeT)が米国ダークプール相当。出来高急増を機関買い候補として検出

実行: python fetch_jp.py
出力: data/jp_signals.json
"""

import json
import re
import time
import io
import zipfile
from datetime import datetime, timedelta, timezone, date
from pathlib import Path
from urllib.parse import urlencode
import urllib.request
import urllib.error
import sys

# 同じディレクトリの他モジュールをimport可能に
sys.path.insert(0, str(Path(__file__).parent))
from fetch_tdnet import fetch_tdnet_recent, index_disclosures, score_tdnet
from fetch_margin import fetch_margin_data, score_margin

USER_AGENT = "WhaleTracker-JP research-tool"
EDINET_BASE = "https://api.edinet-fsa.go.jp/api/v2"
JPX_SHORT_INDEX = "https://www.jpx.co.jp/markets/public/short-selling/index.html"
YAHOO_JP_BASE = "https://finance.yahoo.co.jp"
JST = timezone(timedelta(hours=9))

OUTPUT_DIR = Path(__file__).parent.parent / "data"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================
# 日本株のおすすめユニバース
# TOPIX Core30 + 日経225主力 + 高出来高動的銘柄
# ============================================================
JP_TICKERS = {
    # TOPIX Core30 (主要)
    "7203": "トヨタ自動車",
    "9432": "NTT",
    "6758": "ソニーグループ",
    "8306": "三菱UFJフィナンシャル",
    "9984": "ソフトバンクグループ",
    "6861": "キーエンス",
    "8035": "東京エレクトロン",
    "7974": "任天堂",
    "8316": "三井住友フィナンシャル",
    "4063": "信越化学工業",
    "6098": "リクルートホールディングス",
    "9433": "KDDI",
    "8411": "みずほフィナンシャル",
    "4502": "武田薬品工業",
    "7267": "ホンダ",
    "6594": "ニデック",
    "7741": "HOYA",
    "6501": "日立製作所",
    "8001": "伊藤忠商事",
    "9434": "ソフトバンク",
    "8058": "三菱商事",
    "6981": "村田製作所",
    "9020": "JR東日本",
    "9983": "ファーストリテイリング",
    "7011": "三菱重工業",
    "4519": "中外製薬",
    "8766": "東京海上ホールディングス",
    
    # 日経主力・高ボラ・話題銘柄
    "6920": "レーザーテック",
    "9613": "NTTデータグループ",
    "6502": "東芝",
    "6857": "アドバンテスト",
    "9101": "日本郵船",
    "9104": "商船三井",
    "5803": "フジクラ",
    "6526": "ソシオネクスト",
    "5831": "しずおかフィナンシャル",
    "4661": "オリエンタルランド",
    "4385": "メルカリ",
    "3659": "ネクソン",
    "4477": "BASE",
    "4385": "メルカリ",
    "3092": "ZOZO",
    "4307": "野村総研",
    "4751": "サイバーエージェント",
    "6273": "SMC",
    
    # 半導体・AI関連
    "6963": "ローム",
    "8035": "東京エレクトロン",
    "6701": "NEC",
    "6702": "富士通",
    "6532": "ベイカレント",
    
    # 銀行・金融
    "8473": "SBI HD",
    "8593": "三菱HCキャピタル",
    
    # 中小型・グロース
    "4385": "メルカリ",
    "4490": "ビザスク",
    "4488": "AI inside",
    "4475": "HENNGE",
    "4424": "Amazia",
    "9519": "レノバ",
    
    # バリュー注目
    "5401": "日本製鉄",
    "5713": "住友金属鉱山",
    "5020": "ENEOSホールディングス",
    "1605": "INPEX",
}


def http_get(url: str, headers: dict = None, max_retries: int = 3, timeout: int = 30) -> bytes:
    h = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate"}
    if headers:
        h.update(headers)
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    import gzip
                    data = gzip.decompress(data)
                return data
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(2 ** (attempt + 1))
                continue
            if e.code in (404, 403):
                return b""
            time.sleep(1)
        except Exception:
            time.sleep(1)
    return b""


# ============================================================
# Phase 1: EDINET 大量保有報告書
# ============================================================
def fetch_edinet_filings(lookback_days: int = 30) -> list:
    """
    EDINETから直近N日の大量保有報告書一覧を取得。
    
    様式コード:
      010 = 大量保有報告書
      020 = 変更報告書
      030 = 訂正大量保有報告書
      040 = 訂正変更報告書
    """
    print("[1/4] EDINET 大量保有報告書取得中...")
    all_docs = []
    
    for offset in range(lookback_days):
        d = datetime.now(JST).date() - timedelta(days=offset)
        url = f"{EDINET_BASE}/documents.json?date={d}&type=2"
        time.sleep(0.3)  # EDINET API: 適度な間隔
        data = http_get(url)
        if not data:
            continue
        try:
            obj = json.loads(data)
        except json.JSONDecodeError:
            continue
        
        for doc in obj.get("results", []):
            form_code = doc.get("formCode") or ""
            doc_type = doc.get("docTypeCode") or ""
            # 大量保有関連は doc_type=350(初回)/360(変更)/370(訂正)
            if doc_type in ("350", "360", "370"):
                all_docs.append({
                    "doc_id": doc.get("docID"),
                    "filer": doc.get("filerName"),
                    "issuer_edinet_code": doc.get("edinetCode"),
                    "issuer_security_code": (doc.get("secCode") or "")[:4],
                    "issuer_name": doc.get("filerName"),  # filerNameが提出者
                    "subject_name": doc.get("legalStatus"),
                    "doc_type": doc_type,
                    "doc_description": doc.get("docDescription"),
                    "submit_date": doc.get("submitDateTime"),
                    "period_end": doc.get("periodEnd"),
                })
        if len(all_docs) > 500:
            break
    
    print(f"  → {len(all_docs)}件の大量保有関連書類を検出")
    return all_docs


def index_holding_filings(docs: list) -> dict:
    """
    {証券コード: [filings]} に集約。
    EDINETでは "secCode" が証券コード(4桁+0埋め=5桁)で入っている。
    """
    by_ticker = {}
    for d in docs:
        sec = (d.get("issuer_security_code") or "").lstrip("0")
        if not sec:
            continue
        # 4桁の証券コード(銘柄)
        if len(sec) <= 5:
            key = sec.zfill(4) if len(sec) <= 4 else sec[:4]
            by_ticker.setdefault(key, []).append(d)
    return by_ticker


# 著名アクティビスト・有名機関(部分一致用)
ACTIVIST_JP = {
    "オアシス", "oasis", "エフィッシモ", "村上", "シルチェスター",
    "blackrock", "ブラックロック", "vanguard", "vanguardグループ",
    "野村アセット", "三井住友トラスト", "アセットマネジメントone",
    "city of london", "シティ・オブ・ロンドン", "abrdn", "fidelity",
    "ストラテジック", "tペック", "tpg", "elliott", "エリオット",
}


def score_jp_holdings(filings: list) -> dict:
    """大量保有報告のスコア化 + 生イベント"""
    if not filings:
        return _empty_holdings()
    
    score = 0
    detail = {}
    events = []
    
    has_activist = False
    new_filings = []
    change_filings = []
    
    for f in filings:
        filer = (f.get("filer") or "").lower()
        is_activist = False
        for activist in ACTIVIST_JP:
            if activist.lower() in filer:
                has_activist = True
                is_activist = True
                detail.setdefault("著名機関", f.get("filer", "")[:30])
                break
        
        dt = f.get("doc_type") or ""
        submit_date = (f.get("submit_date") or "")[:10]
        filer_name = f.get("filer", "Unknown")[:60]
        
        if dt == "350":
            new_filings.append(f)
            events.append({
                "type": "5%",
                "date": submit_date,
                "filing_date": submit_date,
                "actor": filer_name,
                "title": "Activist" if is_activist else "Institution",
                "label": "初回大量保有報告書(5%超取得)",
                "is_activist": is_activist,
            })
        elif dt == "360":
            change_filings.append(f)
            events.append({
                "type": "CHANGE",
                "date": submit_date,
                "filing_date": submit_date,
                "actor": filer_name,
                "title": "Amendment",
                "label": "変更報告書(保有比率変動)",
                "is_activist": is_activist,
            })
        elif dt == "370":
            events.append({
                "type": "CORRECT",
                "date": submit_date,
                "filing_date": submit_date,
                "actor": filer_name,
                "title": "Correction",
                "label": "訂正報告書",
                "is_activist": is_activist,
            })
    
    if new_filings:
        score += 25
        detail["初回大量保有"] = f"{len(new_filings)}件 ({new_filings[0].get('filer','?')[:25]})"
    
    if change_filings:
        score += 10
        detail["変更報告"] = f"{len(change_filings)}件"
    
    if has_activist:
        score += 15
    
    score = min(40, score)
    if score == 0:
        return _empty_holdings()
    
    events.sort(key=lambda x: x["date"], reverse=True)
    
    return {
        "active": True,
        "score": score,
        "detail": detail,
        "evidence": min(90, 50 + score),
        "events": events[:10],
    }


def _empty_holdings() -> dict:
    return {"active": False, "score": 0, "detail": {"event": "直近期間に大量保有報告なし"}, "evidence": 0, "events": []}


# ============================================================
# Phase 2: JPX 空売り残高
# ============================================================
def fetch_jpx_short_balance() -> dict:
    """
    JPXの「空売り残高に関する情報」から最新Excel/CSVを取得。
    残高割合0.5%以上の銘柄のみ公開。
    
    取得戦略:
    1. インデックスHTMLをスクレイプして最新ファイルURL取得
    2. Excelダウンロード(openpyxlに依存しないようXLSX→Zip→XML直接パース)
    """
    print("[2/4] JPX 空売り残高取得中...")
    
    # 直近営業日の空売り残高ファイル名パターン:
    # https://www2.jpx.co.jp/disc/{コード}/...形式は複雑。
    # 簡易: インデックスから最初のファイルリンク抽出
    data = http_get(JPX_SHORT_INDEX)
    if not data:
        print("  → JPX索引ページ取得失敗")
        return {}
    
    html = data.decode("utf-8", errors="ignore")
    # 直近のExcelリンクを検索
    links = re.findall(
        r'href="([^"]+(?:\.xlsx?|\.csv))"[^>]*>(?:[^<]*?)(?:空売り|残高|short)',
        html, re.I
    )
    
    if not links:
        # フォールバック: 全てのxlsxリンクを取得し最新と思しきを取る
        links = re.findall(r'href="(/markets/public/short-selling/[^"]+\.xlsx?)"', html)
    
    if not links:
        print("  → JPXファイルリンク検出失敗(構造変更の可能性)")
        return {}
    
    # 最新らしき1つ
    file_url = links[0]
    if not file_url.startswith("http"):
        file_url = "https://www.jpx.co.jp" + file_url
    
    print(f"  → ダウンロード: {file_url[-50:]}")
    xlsx_data = http_get(file_url)
    if not xlsx_data:
        return {}
    
    # XLSX を直接パース(openpyxl不使用)
    short_data = _parse_xlsx_simple(xlsx_data)
    print(f"  → {len(short_data)}銘柄の空売り残高データ")
    return short_data


def _parse_xlsx_simple(xlsx_bytes: bytes) -> dict:
    """
    XLSXは ZIP内 xl/sharedStrings.xml + xl/worksheets/sheet1.xml の構造。
    軽量にパースし {証券コード: [{filer, ratio, date}]} を返す。
    """
    out = {}
    try:
        with zipfile.ZipFile(io.BytesIO(xlsx_bytes)) as z:
            # 共有文字列
            shared = []
            try:
                ss_xml = z.read("xl/sharedStrings.xml").decode("utf-8", errors="ignore")
                shared = re.findall(r"<t[^>]*>([^<]*)</t>", ss_xml)
            except KeyError:
                pass
            
            # シート1
            try:
                sheet_xml = z.read("xl/worksheets/sheet1.xml").decode("utf-8", errors="ignore")
            except KeyError:
                return out
            
            # 行ごとにセル抽出
            rows = re.findall(r"<row[^>]*>(.*?)</row>", sheet_xml, re.DOTALL)
            for row_xml in rows:
                cells = re.findall(
                    r'<c[^>]*r="([A-Z]+)\d+"(?:\s+t="([^"]+)")?[^>]*>(?:<v>([^<]+)</v>)?',
                    row_xml,
                )
                row_vals = {}
                for col, t, v in cells:
                    if v is None or v == "":
                        continue
                    if t == "s":  # shared string
                        try:
                            row_vals[col] = shared[int(v)] if int(v) < len(shared) else ""
                        except ValueError:
                            row_vals[col] = v
                    else:
                        row_vals[col] = v
                
                # 銘柄コードらしき列(数字4-5桁)を探す
                code = None
                filer = None
                ratio = None
                for col, val in row_vals.items():
                    s = str(val).strip()
                    if not code and re.fullmatch(r"\d{4,5}", s):
                        code = s.zfill(4)[:4]
                    elif filer is None and len(s) > 3 and not s.isdigit() and "%" not in s:
                        # 最初に出てくる長めの非数値文字列が空売り報告者である可能性
                        if any(ch in s for ch in ["証券", "銀行", "アセット", "Capital", "Securities", "投資", "Inc", "Ltd", "GmbH"]):
                            filer = s
                    elif ratio is None and re.fullmatch(r"[\d.]+", s):
                        try:
                            f = float(s)
                            if 0.4 < f < 30:
                                ratio = f
                        except ValueError:
                            pass
                
                if code and filer:
                    out.setdefault(code, []).append({
                        "filer": filer[:40],
                        "ratio": ratio or 0,
                    })
    except Exception as e:
        print(f"  → XLSXパースエラー: {e}")
    return out


def score_jp_short_balance(short_entries: list) -> dict:
    """
    日本では空売り残高が高い = 機関のヘッジ付きロングまたはショートポジション。
    「ショート残高が急減 = ショートカバー圧力」を狙うのが王道。
    ここでは現スナップショットのみ:
    - 機関名がアクティビスト/著名: 警戒(売り意図)
    - 残高合計が大きい(>3%): 値動き発生時にスクイーズ余地あり(中立~ややプラス)
    """
    if not short_entries:
        return _empty_short()
    
    total_ratio = sum(e.get("ratio", 0) for e in short_entries)
    score = 0
    detail = {}
    today_iso = datetime.now(JST).strftime("%Y-%m-%d")
    
    if total_ratio >= 5.0:
        score += 12
        detail["空売り残高合計"] = f"{total_ratio:.2f}% (スクイーズ余地大)"
    elif total_ratio >= 3.0:
        score += 8
        detail["空売り残高合計"] = f"{total_ratio:.2f}%"
    elif total_ratio >= 1.0:
        score += 4
        detail["空売り残高合計"] = f"{total_ratio:.2f}%"
    
    detail["報告機関数"] = f"{len(short_entries)}社"
    
    # 各機関のショートポジションをイベント化
    events = []
    for e in sorted(short_entries, key=lambda x: -x.get("ratio", 0))[:10]:
        events.append({
            "type": "SHORT",
            "date": today_iso,
            "filing_date": today_iso,
            "actor": e.get("filer", "Unknown")[:50],
            "title": "Short Position",
            "label": f"空売り残高 {e.get('ratio', 0):.2f}%",
        })
    
    if score == 0:
        return _empty_short()
    
    return {
        "active": True,
        "score": score,
        "detail": detail,
        "evidence": min(70, 35 + score),
        "events": events,
    }


def _empty_short() -> dict:
    return {"active": False, "score": 0, "detail": {"event": "空売り残高0.5%超なし"}, "evidence": 0, "events": []}


# ============================================================
# Phase 3: Yahoo Finance Japan — 株価・出来高
# ============================================================
def fetch_yahoo_jp_quote(code: str) -> dict:
    """
    Yahoo!ファイナンス 株価ページ(東証) から直近価格・出来高を抽出。
    Yahoo は HTMLスクレイプ。
    """
    url = f"{YAHOO_JP_BASE}/quote/{code}.T"
    data = http_get(url, headers={"User-Agent": "Mozilla/5.0"})
    if not data:
        return {}
    
    html = data.decode("utf-8", errors="ignore")
    out = {}
    
    # 現在値
    m = re.search(r'data-value="([\d,.]+)"\s+aria-label="現在値', html)
    if m:
        try:
            out["price"] = float(m.group(1).replace(",", ""))
        except ValueError:
            pass
    
    # シンプル抽出: 数値+「円」と「出来高」
    m_price = re.search(r'<span[^>]*PriceBoard[^>]*>([\d,.]+)\s*円', html)
    if m_price and "price" not in out:
        try:
            out["price"] = float(m_price.group(1).replace(",", ""))
        except ValueError:
            pass
    
    # 出来高
    m_vol = re.search(r'出来高[^0-9]*([\d,]+)', html)
    if m_vol:
        try:
            out["volume"] = int(m_vol.group(1).replace(",", ""))
        except ValueError:
            pass
    
    # 前日終値
    m_prev = re.search(r'前日終値[^0-9]*([\d,.]+)', html)
    if m_prev:
        try:
            out["prev_close"] = float(m_prev.group(1).replace(",", ""))
        except ValueError:
            pass
    
    # 値動き(%変化)
    if out.get("price") and out.get("prev_close"):
        out["change_pct"] = ((out["price"] - out["prev_close"]) / out["prev_close"]) * 100
    
    return out


# ============================================================
# Phase 4: 出来高急増スクリーニング(機関の集中買いプロキシ)
# ============================================================
def fetch_jp_volume_signal(code: str, current: dict) -> dict:
    """
    Yahoo!ファイナンスの時系列ページから過去20日出来高を取得し、
    当日 vs 平均比を判定。日本では立会外(ToSTNeT)単独データが個人入手困難なため、
    出来高比×価格動向で機関の動きを推定する。
    """
    url = f"{YAHOO_JP_BASE}/quote/{code}.T/history"
    data = http_get(url, headers={"User-Agent": "Mozilla/5.0"})
    if not data:
        return _empty_volume()
    
    html = data.decode("utf-8", errors="ignore")
    
    # 出来高列を抽出
    rows = re.findall(
        r'<tr[^>]*>\s*<td[^>]*>(\d{4})/(\d{1,2})/(\d{1,2})</td>.*?<td[^>]*>([\d,]+)</td>',
        html, re.DOTALL,
    )
    
    volumes = []
    for r in rows[:20]:
        try:
            volumes.append(int(r[3].replace(",", "")))
        except ValueError:
            continue
    
    if len(volumes) < 5:
        return _empty_volume()
    
    avg_vol = sum(volumes[1:]) / max(len(volumes) - 1, 1)
    today_vol = volumes[0] if volumes else 0
    
    if avg_vol == 0:
        return _empty_volume()
    
    ratio = today_vol / avg_vol
    
    score = 0
    detail = {}
    
    if ratio >= 3.0:
        score += 20
        detail["出来高急増"] = f"{ratio:.1f}倍 (機関集中の可能性大)"
    elif ratio >= 2.0:
        score += 12
        detail["出来高増加"] = f"{ratio:.1f}倍"
    elif ratio >= 1.5:
        score += 6
        detail["出来高増"] = f"{ratio:.1f}倍"
    
    # 価格上昇を伴う出来高増は強気
    change = current.get("change_pct", 0)
    if score > 0 and change > 2:
        score += 8
        detail["価格動向"] = f"+{change:.1f}% (買い圧力)"
    elif score > 0 and change < -2:
        score -= 6
        detail["価格動向"] = f"{change:.1f}% (売り圧力)"
    
    score = max(0, min(35, score))
    if score == 0:
        return _empty_volume()
    
    today_iso = datetime.now(JST).strftime("%Y-%m-%d")
    events = [{
        "type": "VOLUME",
        "date": today_iso,
        "filing_date": today_iso,
        "actor": "Yahoo!ファイナンス株価データ",
        "title": "出来高急増シグナル",
        "label": f"当日 {today_vol:,}株 (20日平均 {int(avg_vol):,}株 の {ratio:.1f}倍) / 価格変化 {change:+.2f}%",
    }]
    
    return {
        "active": True,
        "score": score,
        "detail": detail,
        "evidence": min(85, 40 + score),
        "events": events,
    }


def _empty_volume() -> dict:
    return {"active": False, "score": 0, "detail": {"event": "出来高に特異性なし"}, "evidence": 0, "events": []}


# ============================================================
# 統合スコアリング(日本市場用に調整)
# ============================================================
def compute_jp_score(signals: dict) -> int:
    """
    日本市場用の重み付け(機能拡張版):
    - holdings(EDINET大量保有): 1.5倍 — 5%超は重大シグナル
    - tdnet(適時開示): 1.6倍 — 上方修正/自社株買は最重要
    - volume(出来高急増): 1.4倍 — ToSTNeT代替として重視
    - short(空売り残高): 1.0倍 — ショートカバー余地
    - margin(信用残): 1.2倍 — 踏み上げ余地
    """
    score = 0
    score += signals["holdings"]["score"] * 1.5
    score += signals.get("tdnet", {"score": 0})["score"] * 1.6
    score += signals["volume"]["score"] * 1.4
    score += signals["short"]["score"] * 1.0
    score += signals.get("margin", {"score": 0})["score"] * 1.2
    return min(100, max(0, round(score)))


def get_tier(score: int) -> dict:
    if score >= 80:
        return {"label": "🔥 STRONG", "key": "strong"}
    if score >= 65:
        return {"label": "⭐ WATCH", "key": "watch"}
    if score >= 50:
        return {"label": "👀 MONITOR", "key": "monitor"}
    return {"label": "LOW", "key": "low"}


# ============================================================
# メイン
# ============================================================
def main():
    print("=" * 60)
    print(" 🇯🇵 Japan Whale Tracker — Smart Money Detector v3 ")
    print("=" * 60)
    print(f" 開始: {datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S JST')}")
    print(f" 対象: {len(JP_TICKERS)} tickers\n")
    
    # 一括取得(銘柄横断)
    holding_docs = fetch_edinet_filings(lookback_days=30)
    holdings_by_ticker = index_holding_filings(holding_docs)
    
    short_data = fetch_jpx_short_balance()
    
    # TDnet取得(全件)
    print()
    tdnet_disclosures = fetch_tdnet_recent(days=5)
    tdnet_by_ticker = index_disclosures(tdnet_disclosures)
    
    # 信用残取得
    print()
    margin_data = fetch_margin_data()
    
    print(f"\n[最終] 銘柄別シグナル集計中...")
    
    results = []
    for i, (code, name) in enumerate(JP_TICKERS.items(), 1):
        print(f"[{i:3d}/{len(JP_TICKERS)}] {code} {name[:15]:<15} ...", end=" ", flush=True)
        
        signals = {
            "holdings": _empty_holdings(),
            "tdnet": {"active": False, "score": 0, "detail": {"event": "適時開示なし"}, "evidence": 0, "events": []},
            "volume": _empty_volume(),
            "short": _empty_short(),
            "margin": {"active": False, "score": 0, "detail": {"event": "信用残データなし"}, "evidence": 0, "events": []},
        }
        
        # ① EDINET 大量保有
        if code in holdings_by_ticker:
            signals["holdings"] = score_jp_holdings(holdings_by_ticker[code])
        
        # ② TDnet 適時開示
        if code in tdnet_by_ticker:
            signals["tdnet"] = score_tdnet(tdnet_by_ticker[code])
        
        # ③ JPX 空売り残高
        if code in short_data:
            signals["short"] = score_jp_short_balance(short_data[code])
        
        # ④ 信用残
        if code in margin_data:
            quote_for_margin = {}  # 後で価格取得後に再評価可
            signals["margin"] = score_margin(code, margin_data[code])
        
        # ⑤ Yahoo!ファイナンス 株価+出来高
        try:
            quote = fetch_yahoo_jp_quote(code)
            signals["volume"] = fetch_jp_volume_signal(code, quote)
            time.sleep(0.4)  # Yahoo保護
        except Exception as e:
            quote = {}
            print(f"  yahoo err: {e}", end=" ")
        
        score = compute_jp_score(signals)
        tier = get_tier(score)
        
        results.append({
            "symbol": code,
            "name": name,
            "market": "JP",
            "score": score,
            "tier": tier["key"],
            "tier_label": tier["label"],
            "price": quote.get("price", 0),
            "prev_close": quote.get("prev_close", 0),
            "change_pct": round(quote.get("change_pct", 0), 2),
            "signals": signals,
        })
        print(f"score={score} [{tier['label']}]")
    
    results.sort(key=lambda x: -x["score"])
    
    # 前回データとの差分(スコア急変ハイライト用)
    prev_path = OUTPUT_DIR / "jp_signals.json"
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
        "generated_at": datetime.now(JST).isoformat(),
        "market": "JP",
        "total": len(results),
        "tickers": results,
    }
    
    out_path = OUTPUT_DIR / "jp_signals.json"
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(f"\n✅ 保存: {out_path}")


if __name__ == "__main__":
    main()
