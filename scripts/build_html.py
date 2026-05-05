"""
Dashboard Builder — JSONデータから静的HTMLダッシュボードを生成

入力: data/us_signals.json, data/jp_signals.json
出力: docs/index.html (GitHub Pages用), docs/data.json (バックアップ)
"""

import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))
ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"
DOCS_DIR = ROOT / "docs"
DOCS_DIR.mkdir(parents=True, exist_ok=True)

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<meta name="theme-color" content="#0a0e27">
<title>WHALE TRACKER — 大口投資家動向 [JP/US]</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700;800&family=Bricolage+Grotesque:opsz,wght@12..96,400;12..96,500;12..96,700;12..96,800&display=swap" rel="stylesheet">
<style>
:root {
  --bg-primary: #0a0e27;
  --bg-secondary: #131836;
  --bg-card: #1a1f3f;
  --bg-elevated: #232a52;
  --accent-cyan: #00f0ff;
  --accent-gold: #ffb800;
  --accent-red: #ff3b6b;
  --accent-green: #00ff9d;
  --accent-purple: #b87fff;
  --accent-jp: #ff6b9d;
  --text-primary: #ffffff;
  --text-secondary: #a4adc7;
  --text-muted: #6b7494;
  --border: rgba(255,255,255,0.08);
  --grid: rgba(0,240,255,0.04);
}
* { box-sizing: border-box; margin: 0; padding: 0; -webkit-tap-highlight-color: transparent; }
html, body {
  background: var(--bg-primary);
  color: var(--text-primary);
  font-family: 'Bricolage Grotesque', -apple-system, sans-serif;
  min-height: 100vh; overflow-x: hidden;
  font-size: 15px; -webkit-font-smoothing: antialiased;
}
body::before {
  content: ''; position: fixed; inset: 0;
  background: radial-gradient(ellipse at 20% 0%, rgba(0,240,255,0.08), transparent 50%),
              radial-gradient(ellipse at 80% 100%, rgba(184,127,255,0.08), transparent 50%),
              linear-gradient(0deg, var(--grid) 1px, transparent 1px) 0 0/40px 40px,
              linear-gradient(90deg, var(--grid) 1px, transparent 1px) 0 0/40px 40px;
  pointer-events: none; z-index: 0;
}
.app { position: relative; z-index: 1; padding: 16px; padding-bottom: 80px; max-width: 480px; margin: 0 auto; }
.hdr { padding: 24px 4px 18px; border-bottom: 1px solid var(--border); margin-bottom: 18px; }
.hdr-top { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
.logo {
  width: 38px; height: 38px;
  background: linear-gradient(135deg, var(--accent-cyan), var(--accent-purple));
  border-radius: 10px; display: grid; place-items: center;
  font-family: 'JetBrains Mono', monospace; font-weight: 800;
  color: var(--bg-primary); font-size: 18px;
  box-shadow: 0 0 30px rgba(0,240,255,0.4);
}
.brand h1 {
  font-family: 'JetBrains Mono', monospace; font-size: 18px; font-weight: 800;
  letter-spacing: -0.5px;
  background: linear-gradient(90deg, #fff, var(--accent-cyan));
  -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent;
}
.brand .sub { font-size: 10px; color: var(--text-muted); letter-spacing: 2px; text-transform: uppercase; font-family: 'JetBrains Mono', monospace; }
.live-dot {
  display: inline-block; width: 7px; height: 7px;
  background: var(--accent-green); border-radius: 50%; margin-left: auto;
  box-shadow: 0 0 10px var(--accent-green); animation: pulse 1.5s infinite;
}
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }

.update-time {
  font-family: 'JetBrains Mono', monospace; font-size: 10px;
  color: var(--text-muted); letter-spacing: 1px; margin-top: 4px;
}

.market-toggle {
  display: flex; gap: 6px; background: var(--bg-card);
  padding: 4px; border-radius: 12px; border: 1px solid var(--border);
  margin-bottom: 14px;
}
.mt-btn {
  flex: 1; padding: 10px; text-align: center; font-size: 13px;
  font-weight: 700; font-family: 'JetBrains Mono', monospace; letter-spacing: 1px;
  color: var(--text-muted); border-radius: 8px; cursor: pointer;
  transition: all 0.2s;
}
.mt-btn.active { background: var(--bg-elevated); color: var(--accent-cyan); }
.mt-btn[data-market="JP"].active { color: var(--accent-jp); }
.mt-btn .flag { margin-right: 4px; }

.hdr-stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-top: 14px; }
.stat { background: var(--bg-card); border: 1px solid var(--border); border-radius: 10px; padding: 10px 8px; text-align: center; }
.stat-val { font-family: 'JetBrains Mono', monospace; font-size: 18px; font-weight: 700; color: var(--accent-cyan); }
.stat-lbl { font-size: 9px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 1px; margin-top: 2px; }

.search-bar { display: flex; gap: 8px; margin-bottom: 18px; }
.search-bar input {
  flex: 1; background: var(--bg-card); border: 1px solid var(--border);
  color: var(--text-primary); padding: 14px 16px; border-radius: 12px;
  font-size: 15px; font-family: 'JetBrains Mono', monospace; font-weight: 600;
  outline: none; letter-spacing: 1px; text-transform: uppercase;
}
.search-bar input:focus { border-color: var(--accent-cyan); box-shadow: 0 0 0 3px rgba(0,240,255,0.15); }
.search-bar button {
  background: linear-gradient(135deg, var(--accent-cyan), #0099ff);
  color: var(--bg-primary); border: none; padding: 0 20px; border-radius: 12px;
  font-weight: 800; font-family: 'JetBrains Mono', monospace;
  font-size: 14px; cursor: pointer; transition: transform 0.15s;
}
.search-bar button:active { transform: scale(0.95); }

.sec-title { display: flex; align-items: center; gap: 10px; margin: 22px 0 12px; padding: 0 4px; }
.sec-title .num { font-family: 'JetBrains Mono', monospace; font-size: 11px; color: var(--accent-cyan); font-weight: 700; }
.sec-title h2 { font-size: 16px; font-weight: 700; letter-spacing: -0.3px; }
.sec-title .line { flex: 1; height: 1px; background: linear-gradient(90deg, var(--border), transparent); }

.tickers { display: grid; gap: 10px; }
.ticker-card {
  background: var(--bg-card); border: 1px solid var(--border); border-radius: 14px;
  padding: 14px; display: grid; grid-template-columns: auto 1fr auto;
  gap: 12px; align-items: center; cursor: pointer;
  transition: all 0.2s; position: relative; overflow: hidden;
}
.ticker-card::before {
  content: ''; position: absolute; left: 0; top: 0; bottom: 0;
  width: 3px; background: var(--bar-color, var(--accent-cyan));
}
.ticker-card:active { transform: scale(0.98); }
.ticker-card.tier-strong { border-color: rgba(0,255,157,0.3); }
.ticker-card.tier-strong::before { background: var(--accent-green); box-shadow: 0 0 12px var(--accent-green); }
.ticker-card.tier-watch { border-color: rgba(255,184,0,0.3); }
.ticker-card.tier-watch::before { background: var(--accent-gold); }
.ticker-card.tier-monitor::before { background: var(--accent-cyan); }

.ticker-symbol { font-family: 'JetBrains Mono', monospace; font-size: 19px; font-weight: 800; letter-spacing: 0.5px; }
.ticker-name { font-size: 11px; color: var(--text-muted); margin-top: 2px; }
.ticker-meta { font-size: 10px; color: var(--text-secondary); margin-top: 4px; font-family: 'JetBrains Mono', monospace; }
.ticker-meta .pos { color: var(--accent-green); }
.ticker-meta .neg { color: var(--accent-red); }
.ticker-signals { display: flex; gap: 4px; margin-top: 6px; }
.sig-dot {
  width: 22px; height: 18px; border-radius: 4px; display: grid; place-items: center;
  font-size: 8px; font-weight: 800; font-family: 'JetBrains Mono', monospace;
  background: var(--bg-elevated); color: var(--text-muted);
}
.sig-dot.active { background: var(--sig-bg); color: var(--sig-color); }

.score-display { text-align: right; }
.score-val {
  font-family: 'JetBrains Mono', monospace; font-size: 28px; font-weight: 800; line-height: 1;
  background: linear-gradient(135deg, var(--bar-color, var(--accent-cyan)), #fff);
  -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent;
}
.score-tier { font-size: 9px; font-family: 'JetBrains Mono', monospace; font-weight: 700; letter-spacing: 1px; color: var(--bar-color); margin-top: 2px; }

/* スコア急変バッジ */
.score-change {
  display: inline-block;
  font-family: 'JetBrains Mono', monospace;
  font-size: 9px;
  font-weight: 800;
  padding: 2px 5px;
  border-radius: 4px;
  margin-top: 3px;
}
.score-change.up {
  background: rgba(0,255,157,0.2);
  color: var(--accent-green);
}
.score-change.down {
  background: rgba(255,59,107,0.2);
  color: var(--accent-red);
}

/* お気に入りボタン */
.fav-btn {
  position: absolute;
  top: 10px;
  right: 10px;
  width: 26px; height: 26px;
  display: grid;
  place-items: center;
  background: rgba(0,0,0,0.3);
  border-radius: 50%;
  font-size: 14px;
  cursor: pointer;
  z-index: 2;
  border: 1px solid var(--border);
  transition: all 0.15s;
}
.fav-btn:active { transform: scale(0.9); }
.fav-btn.active {
  background: rgba(255,184,0,0.25);
  border-color: var(--accent-gold);
}

/* 市場時計 */
.market-clocks {
  display: flex;
  gap: 6px;
  margin-bottom: 12px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  letter-spacing: 1px;
}
.clock {
  flex: 1;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 6px 8px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.clock-status {
  width: 6px; height: 6px;
  border-radius: 50%;
  background: var(--text-muted);
  flex-shrink: 0;
}
.clock-status.open {
  background: var(--accent-green);
  box-shadow: 0 0 6px var(--accent-green);
  animation: pulse 1.5s infinite;
}
.clock-status.pre, .clock-status.after {
  background: var(--accent-gold);
}
.clock-label { color: var(--text-muted); font-size: 9px; }
.clock-time { color: var(--text-primary); font-weight: 600; margin-left: auto; font-size: 10px; }

.modal-overlay { position: fixed; inset: 0; background: rgba(10,14,39,0.9); backdrop-filter: blur(10px); z-index: 100; display: none; align-items: flex-end; }
.modal-overlay.show { display: flex; animation: fadeIn 0.2s; }
@keyframes fadeIn { from{opacity:0} to{opacity:1} }
.modal { width: 100%; max-width: 480px; margin: 0 auto; background: var(--bg-secondary); border-radius: 24px 24px 0 0; max-height: 92vh; overflow-y: auto; animation: slideUp 0.3s cubic-bezier(0.16, 1, 0.3, 1); border-top: 1px solid var(--border); }
@keyframes slideUp { from{transform:translateY(100%)} to{transform:translateY(0)} }
.modal-header { position: sticky; top: 0; background: var(--bg-secondary); padding: 18px 18px 14px; border-bottom: 1px solid var(--border); z-index: 10; }
.modal-grab { width: 40px; height: 4px; background: var(--text-muted); border-radius: 2px; margin: 0 auto 14px; }
.modal-close { position: absolute; right: 14px; top: 24px; background: var(--bg-elevated); border: none; color: var(--text-secondary); width: 32px; height: 32px; border-radius: 8px; font-size: 18px; cursor: pointer; }
.modal-ticker { font-family: 'JetBrains Mono', monospace; font-size: 26px; font-weight: 800; letter-spacing: 1px; }
.modal-name { font-size: 13px; color: var(--text-secondary); margin-top: 2px; }
.modal-score { margin-top: 14px; padding: 16px; background: var(--bg-card); border-radius: 12px; display: flex; align-items: center; justify-content: space-between; }
.modal-score-num { font-family: 'JetBrains Mono', monospace; font-size: 42px; font-weight: 800; line-height: 1; }
.modal-score-tier { font-family: 'JetBrains Mono', monospace; font-weight: 800; font-size: 13px; padding: 6px 12px; border-radius: 8px; letter-spacing: 1px; }
.modal-body { padding: 18px; }

.signal-block { background: var(--bg-card); border: 1px solid var(--border); border-radius: 14px; padding: 14px; margin-bottom: 12px; }
.signal-block.active { border-color: var(--sig-color); }
.signal-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; margin-bottom: 10px; }
.signal-icon {
  width: 36px; height: 36px; border-radius: 10px; background: var(--bg-elevated);
  display: grid; place-items: center; font-family: 'JetBrains Mono', monospace;
  font-weight: 800; font-size: 12px; flex-shrink: 0;
  color: var(--sig-color, var(--text-muted)); border: 1px solid var(--sig-color, var(--border));
}
.signal-info { flex: 1; }
.signal-title { font-size: 13px; font-weight: 700; letter-spacing: -0.2px; }
.signal-desc { font-size: 11px; color: var(--text-muted); margin-top: 2px; line-height: 1.4; }
.signal-points { font-family: 'JetBrains Mono', monospace; font-size: 14px; font-weight: 700; color: var(--sig-color, var(--text-muted)); }
.signal-detail { background: var(--bg-elevated); border-radius: 8px; padding: 10px 12px; margin-top: 8px; font-size: 12px; }
.signal-detail-row { display: flex; justify-content: space-between; padding: 4px 0; color: var(--text-secondary); border-bottom: 1px dashed rgba(255,255,255,0.05); gap: 8px; }
.signal-detail-row:last-child { border-bottom: none; }
.signal-detail-row strong { color: var(--text-primary); font-family: 'JetBrains Mono', monospace; text-align: right; }
.evidence-bar { margin-top: 10px; height: 6px; background: var(--bg-elevated); border-radius: 3px; overflow: hidden; }
.evidence-fill { height: 100%; background: var(--sig-color); border-radius: 3px; }

/* EVENT TIMELINE — 各シグナルの根拠となった具体イベント */
.events-section {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--border);
}
.events-label {
  font-size: 9px;
  font-family: 'JetBrains Mono', monospace;
  color: var(--text-muted);
  letter-spacing: 1.5px;
  margin-bottom: 8px;
}
.event-item {
  background: rgba(0,0,0,0.2);
  border-left: 2px solid var(--sig-color);
  padding: 8px 10px;
  margin-bottom: 6px;
  border-radius: 0 6px 6px 0;
  font-size: 11px;
}
.event-item:last-child { margin-bottom: 0; }
.event-row1 {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 6px;
  margin-bottom: 3px;
}
.event-type {
  font-family: 'JetBrains Mono', monospace;
  font-weight: 800;
  font-size: 9px;
  padding: 2px 6px;
  border-radius: 3px;
  letter-spacing: 0.5px;
  flex-shrink: 0;
  background: var(--sig-color);
  color: var(--bg-primary);
}
.event-type.buy { background: var(--accent-green); color: var(--bg-primary); }
.event-type.sell { background: var(--accent-red); color: #fff; }
.event-type.put { background: var(--accent-red); color: #fff; }
.event-type.short { background: var(--accent-red); color: #fff; }
.event-date {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  color: var(--text-muted);
}
.event-actor {
  font-weight: 600;
  color: var(--text-primary);
  font-size: 11px;
  line-height: 1.3;
}
.event-actor .actor-title {
  font-size: 9px;
  color: var(--text-muted);
  margin-left: 4px;
  font-weight: 400;
}
.event-actor .activist-tag {
  background: rgba(255,184,0,0.2);
  color: var(--accent-gold);
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 8px;
  font-weight: 700;
  margin-left: 4px;
  letter-spacing: 0.5px;
  font-family: 'JetBrains Mono', monospace;
}
.event-label {
  margin-top: 3px;
  color: var(--text-secondary);
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  word-break: break-all;
}

.tabs { display: flex; gap: 6px; margin-bottom: 14px; background: var(--bg-card); padding: 4px; border-radius: 10px; border: 1px solid var(--border); }
.tab { flex: 1; padding: 8px; text-align: center; font-size: 11px; font-weight: 700; font-family: 'JetBrains Mono', monospace; letter-spacing: 1px; color: var(--text-muted); border-radius: 7px; cursor: pointer; }
.tab.active { background: var(--bg-elevated); color: var(--accent-cyan); }

.info-box { background: linear-gradient(135deg, rgba(0,240,255,0.05), rgba(184,127,255,0.05)); border: 1px solid rgba(0,240,255,0.15); border-radius: 12px; padding: 12px 14px; margin-bottom: 14px; font-size: 12px; color: var(--text-secondary); line-height: 1.6; }
.info-box strong { color: var(--accent-cyan); }

.disclaimer { background: rgba(255,59,107,0.08); border: 1px solid rgba(255,59,107,0.2); border-radius: 10px; padding: 10px 12px; font-size: 10px; color: var(--text-secondary); line-height: 1.5; margin: 16px 0 0; }
.disclaimer strong { color: var(--accent-red); }

.footer { text-align: center; margin-top: 24px; padding: 16px 0; font-family: 'JetBrains Mono', monospace; font-size: 9px; color: var(--text-muted); letter-spacing: 2px; }

.empty-state { padding: 40px 20px; text-align: center; color: var(--text-muted); font-size: 13px; }
.empty-state .icon { font-size: 32px; margin-bottom: 12px; opacity: 0.4; }
</style>
</head>
<body>
<div class="app">
  <header class="hdr">
    <div class="hdr-top">
      <div class="logo">W</div>
      <div class="brand">
        <h1>WHALE TRACKER</h1>
        <div class="sub">JP / US Smart Money Detector v2.0</div>
        <div class="update-time" id="update-time">UPDATING...</div>
      </div>
      <span class="live-dot"></span>
    </div>
    
    <div class="market-toggle">
      <div class="mt-btn active" data-market="JP" onclick="switchMarket('JP')"><span class="flag">🇯🇵</span> JAPAN</div>
      <div class="mt-btn" data-market="US" onclick="switchMarket('US')"><span class="flag">🇺🇸</span> US</div>
    </div>
    
    <div class="market-clocks" id="market-clocks">
      <div class="clock"><span class="clock-status" id="jp-status"></span><span class="clock-label">JPX</span><span class="clock-time" id="jp-time">--:--</span></div>
      <div class="clock"><span class="clock-status" id="us-status"></span><span class="clock-label">NYSE</span><span class="clock-time" id="us-time">--:--</span></div>
    </div>
    
    <div class="hdr-stats">
      <div class="stat"><div class="stat-val" id="stat-strong">0</div><div class="stat-lbl">Strong</div></div>
      <div class="stat"><div class="stat-val" id="stat-watch">0</div><div class="stat-lbl">Watch</div></div>
      <div class="stat"><div class="stat-val" id="stat-total">0</div><div class="stat-lbl">Tracked</div></div>
    </div>
  </header>

  <div class="info-box" id="info-box">
    <strong>JP:</strong> EDINET大量保有 + JPX空売り残高 + 出来高急増を統合スコア化。<br>
    <strong>US:</strong> Form 4 + 13D/G + オプションフロー + FINRAダークプール。<br>
    全データは公式無料ソース由来。タップで詳細表示。
  </div>

  <div class="search-bar">
    <input type="text" id="search-input" placeholder="銘柄コード/Ticker" maxlength="6">
    <button onclick="searchTicker()">SCAN</button>
  </div>

  <div class="tabs">
    <div class="tab active" data-tab="all" onclick="filterTab('all')">ALL</div>
    <div class="tab" data-tab="strong" onclick="filterTab('strong')">STRONG</div>
    <div class="tab" data-tab="watch" onclick="filterTab('watch')">WATCH</div>
    <div class="tab" data-tab="movers" onclick="filterTab('movers')">⚡ MOVERS</div>
    <div class="tab" data-tab="favorites" onclick="filterTab('favorites')">★ FAV</div>
  </div>

  <div class="sec-title">
    <span class="num">[01]</span>
    <h2>大口シグナル検出銘柄</h2>
    <span class="line"></span>
  </div>
  <div class="tickers" id="ticker-list"></div>

  <div class="disclaimer">
    <strong>DISCLAIMER:</strong> 本ツールは情報提供のみが目的で、投資助言ではありません。
    データには遅延があります(米Form 4: 最大2日 / EDINET大量保有: 最大10日 / 空売り残高: T+2日)。
    実トレードでは必ず最新公式情報をご確認ください。
  </div>
  <div class="footer">
    SOURCES · SEC EDGAR · FINRA · EDINET · JPX · YAHOO FINANCE
  </div>
</div>

<div class="modal-overlay" id="modal" onclick="closeModal(event)">
  <div class="modal" onclick="event.stopPropagation()">
    <div class="modal-header">
      <div class="modal-grab"></div>
      <button class="modal-close" onclick="closeModal()">×</button>
      <div class="modal-ticker" id="m-ticker">—</div>
      <div class="modal-name" id="m-name">—</div>
      <div class="modal-score">
        <div>
          <div class="modal-score-num" id="m-score">0</div>
          <div style="font-size:10px;color:var(--text-muted);font-family:'JetBrains Mono',monospace;letter-spacing:1px;margin-top:4px;">WHALE SCORE / 100</div>
        </div>
        <div class="modal-score-tier" id="m-tier">—</div>
      </div>
    </div>
    <div class="modal-body" id="m-body"></div>
  </div>
</div>

<script>
// ============================================================
// データ埋め込み(ビルド時に挿入)
// ============================================================
const DATA = __DATA_PLACEHOLDER__;

const SIGNAL_META_US = {
  insider: { code: 'P', color: '#00ff9d', bg: 'rgba(0,255,157,0.2)', title: 'Form 4: インサイダー取引', desc: '役員・取締役の自社株売買 (SEC公開・2日以内)' },
  filing13d: { code: '5%', color: '#b87fff', bg: 'rgba(184,127,255,0.2)', title: '13D/G: 5%以上大量保有', desc: '機関の大型取得開示 (10日以内)' },
  options: { code: '$$', color: '#ffb800', bg: 'rgba(255,184,0,0.2)', title: 'オプション異常出来高', desc: 'スイープ・Vol/OI急騰検出' },
  darkpool: { code: 'DP', color: '#00f0ff', bg: 'rgba(0,240,255,0.2)', title: 'ダークプール出来高', desc: '市場外大口取引の集中 (FINRA T+1)' },
  filing13f: { code: '13F', color: '#ff3b6b', bg: 'rgba(255,59,107,0.2)', title: '13F: 機関四半期', desc: '$100M+機関の保有開示' },
};

const SIGNAL_META_JP = {
  holdings: { code: '5%', color: '#b87fff', bg: 'rgba(184,127,255,0.2)', title: 'EDINET 大量保有報告', desc: '5%超の保有・変更報告 (金融庁公開)' },
  tdnet: { code: '📰', color: '#00ff9d', bg: 'rgba(0,255,157,0.2)', title: 'TDnet 適時開示', desc: '上方修正・自社株買い・業務提携・株式分割等' },
  volume: { code: 'VOL', color: '#ffb800', bg: 'rgba(255,184,0,0.2)', title: '出来高急増', desc: 'ToSTNeT代理: 平均比×価格動向' },
  short: { code: 'SS', color: '#ff6b9d', bg: 'rgba(255,107,157,0.2)', title: 'JPX 空売り残高', desc: '0.5%超のショートポジション集計' },
  margin: { code: 'MGN', color: '#00f0ff', bg: 'rgba(0,240,255,0.2)', title: '信用取引残高', desc: '信用倍率・前週比急変(踏み上げ余地検出)' },
};

// お気に入り管理(LocalStorage)
function getFavorites() {
  try {
    return JSON.parse(localStorage.getItem('whale_favs_' + currentMarket) || '[]');
  } catch { return []; }
}
function isFavorite(sym) {
  return getFavorites().includes(sym);
}
function toggleFavorite(sym, ev) {
  if (ev) ev.stopPropagation();
  const favs = getFavorites();
  const idx = favs.indexOf(sym);
  if (idx >= 0) favs.splice(idx, 1);
  else favs.push(sym);
  localStorage.setItem('whale_favs_' + currentMarket, JSON.stringify(favs));
  render();
}

// 市場時間判定
function updateMarketClocks() {
  const now = new Date();
  const jstTime = new Date(now.getTime() + (now.getTimezoneOffset() + 540) * 60000);
  const estTime = new Date(now.getTime() + (now.getTimezoneOffset() - 300) * 60000);
  
  // JPX: 9:00-11:30, 12:30-15:00 (土日除く)
  const jpHour = jstTime.getHours();
  const jpMin = jstTime.getMinutes();
  const jpDay = jstTime.getDay();
  let jpStatus = 'closed';
  let jpLabel = 'CLOSED';
  if (jpDay >= 1 && jpDay <= 5) {
    const jpMinutes = jpHour * 60 + jpMin;
    if (jpMinutes >= 540 && jpMinutes < 690) { jpStatus = 'open'; jpLabel = '前場'; }
    else if (jpMinutes >= 690 && jpMinutes < 750) { jpStatus = 'after'; jpLabel = '昼休'; }
    else if (jpMinutes >= 750 && jpMinutes < 900) { jpStatus = 'open'; jpLabel = '後場'; }
    else if (jpMinutes >= 480 && jpMinutes < 540) { jpStatus = 'pre'; jpLabel = '寄前'; }
  }
  
  // NYSE: 9:30-16:00 EST (土日除く)
  const usHour = estTime.getHours();
  const usMin = estTime.getMinutes();
  const usDay = estTime.getDay();
  let usStatus = 'closed';
  let usLabel = 'CLOSED';
  if (usDay >= 1 && usDay <= 5) {
    const usMinutes = usHour * 60 + usMin;
    if (usMinutes >= 570 && usMinutes < 960) { usStatus = 'open'; usLabel = 'OPEN'; }
    else if (usMinutes >= 240 && usMinutes < 570) { usStatus = 'pre'; usLabel = 'PRE'; }
    else if (usMinutes >= 960 && usMinutes < 1200) { usStatus = 'after'; usLabel = 'AFTER'; }
  }
  
  document.getElementById('jp-status').className = 'clock-status ' + jpStatus;
  document.getElementById('jp-time').textContent = jstTime.toTimeString().slice(0,5) + ' ' + jpLabel;
  document.getElementById('us-status').className = 'clock-status ' + usStatus;
  document.getElementById('us-time').textContent = estTime.toTimeString().slice(0,5) + ' ' + usLabel;
}

let activeFilter = 'all';

function getSignalMeta(market) {
  return market === 'JP' ? SIGNAL_META_JP : SIGNAL_META_US;
}

function getTier(score) {
  if (score >= 80) return { label: '🔥 STRONG', color: '#00ff9d', class: 'tier-strong', key: 'strong' };
  if (score >= 65) return { label: '⭐ WATCH', color: '#ffb800', class: 'tier-watch', key: 'watch' };
  if (score >= 50) return { label: '👀 MONITOR', color: '#00f0ff', class: 'tier-monitor', key: 'monitor' };
  return { label: 'LOW', color: '#6b7494', class: '', key: 'low' };
}

let currentMarket = 'JP';

function switchMarket(market) {
  currentMarket = market;
  document.querySelectorAll('.mt-btn').forEach(b => b.classList.toggle('active', b.dataset.market === market));
  const info = document.getElementById('info-box');
  if (market === 'JP') {
    info.innerHTML = '<strong>JP:</strong> EDINET大量保有 + TDnet適時開示 + 出来高急増 + 空売り残高 + 信用残を統合スコア化。市場時間中は1時間ごと自動更新。';
  } else {
    info.innerHTML = '<strong>US:</strong> Form 4(インサイダー) + 13D/G(5%超) + オプションスイープ詳細化 + FINRAダークプール + 13F機関四半期 を統合。';
  }
  render();
}

function filterTab(key) {
  activeFilter = key;
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === key));
  render();
}

function render() {
  const list = document.getElementById('ticker-list');
  const data = DATA[currentMarket];
  
  if (!data || !data.tickers || data.tickers.length === 0) {
    list.innerHTML = '<div class="empty-state"><div class="icon">📊</div>データ未生成<br><span style="font-size:10px;color:var(--text-muted)">スクリプトを実行してください</span></div>';
    document.getElementById('stat-strong').textContent = '0';
    document.getElementById('stat-watch').textContent = '0';
    document.getElementById('stat-total').textContent = '0';
    document.getElementById('update-time').textContent = 'NO DATA';
    return;
  }
  
  const updated = new Date(data.generated_at);
  document.getElementById('update-time').textContent = 'LAST UPDATE: ' + updated.toLocaleString('ja-JP', {hour:'2-digit', minute:'2-digit', month:'2-digit', day:'2-digit'});
  
  const tickers = data.tickers;
  document.getElementById('stat-strong').textContent = tickers.filter(t => t.tier === 'strong').length;
  document.getElementById('stat-watch').textContent = tickers.filter(t => t.tier === 'watch').length;
  document.getElementById('stat-total').textContent = tickers.length;
  
  const favs = getFavorites();
  let filtered = tickers;
  if (activeFilter === 'strong') {
    filtered = tickers.filter(t => t.tier === 'strong');
  } else if (activeFilter === 'watch') {
    filtered = tickers.filter(t => t.tier === 'watch');
  } else if (activeFilter === 'movers') {
    filtered = tickers.filter(t => Math.abs(t.score_change || 0) >= 10);
    filtered.sort((a, b) => Math.abs(b.score_change || 0) - Math.abs(a.score_change || 0));
  } else if (activeFilter === 'favorites') {
    filtered = tickers.filter(t => favs.includes(t.symbol));
  }
  
  if (filtered.length === 0) {
    let msg = '該当銘柄なし';
    if (activeFilter === 'movers') msg = 'スコア急変なし<br><span style="font-size:10px;color:var(--text-muted)">前回スキャンとの差分が±10以上の銘柄が表示されます</span>';
    else if (activeFilter === 'favorites') msg = 'お気に入り未登録<br><span style="font-size:10px;color:var(--text-muted)">銘柄カード右上の★ボタンで追加</span>';
    list.innerHTML = '<div class="empty-state"><div class="icon">🔍</div>' + msg + '</div>';
    return;
  }
  
  const meta = getSignalMeta(currentMarket);
  
  list.innerHTML = filtered.slice(0, 50).map(t => {
    const tier = getTier(t.score);
    const sigKeys = Object.keys(meta);
    const sigDots = sigKeys.map(s => {
      const sig = t.signals[s] || { active: false };
      const m = meta[s];
      return `<div class="sig-dot ${sig.active ? 'active' : ''}" style="--sig-bg:${m.bg};--sig-color:${m.color}">${m.code}</div>`;
    }).join('');
    
    let metaLine = '';
    if (t.price && t.price > 0) {
      const change = currentMarket === 'JP' ? (t.change_pct || 0) : ((t.price - t.prev_close) / (t.prev_close || 1) * 100);
      const cls = change >= 0 ? 'pos' : 'neg';
      const sign = change >= 0 ? '+' : '';
      const priceStr = currentMarket === 'JP' ? '¥' + t.price.toLocaleString() : '$' + t.price.toFixed(2);
      metaLine = `<div class="ticker-meta">${priceStr} <span class="${cls}">${sign}${change.toFixed(2)}%</span></div>`;
    }
    
    // スコア急変バッジ
    let changeBadge = '';
    if (typeof t.score_change === 'number' && Math.abs(t.score_change) >= 5) {
      const cls = t.score_change > 0 ? 'up' : 'down';
      const sign = t.score_change > 0 ? '+' : '';
      changeBadge = `<div class="score-change ${cls}">${sign}${t.score_change}</div>`;
    }
    
    const isFav = favs.includes(t.symbol);
    const favBtn = `<div class="fav-btn ${isFav ? 'active' : ''}" onclick="toggleFavorite('${t.symbol}', event)">${isFav ? '★' : '☆'}</div>`;
    
    return `
      <div class="ticker-card ${tier.class}" style="--bar-color:${tier.color}" onclick="showDetail('${t.symbol}','${currentMarket}')">
        ${favBtn}
        <div>
          <div class="ticker-symbol">${t.symbol}</div>
          <div class="ticker-name">${escapeHtml(t.name || '')}</div>
          ${metaLine}
          <div class="ticker-signals">${sigDots}</div>
        </div>
        <div></div>
        <div class="score-display">
          <div class="score-val">${t.score}</div>
          <div class="score-tier">${tier.label}</div>
          ${changeBadge}
        </div>
      </div>
    `;
  }).join('');
}

function showDetail(symbol, market) {
  const data = DATA[market];
  const t = data.tickers.find(x => x.symbol === symbol);
  if (!t) return;
  
  const tier = getTier(t.score);
  document.getElementById('m-ticker').textContent = t.symbol;
  document.getElementById('m-name').textContent = t.name || '';
  document.getElementById('m-score').textContent = t.score;
  document.getElementById('m-score').style.color = tier.color;
  
  const tierEl = document.getElementById('m-tier');
  tierEl.textContent = tier.label;
  tierEl.style.background = tier.color + '22';
  tierEl.style.color = tier.color;
  
  const meta = getSignalMeta(market);
  const body = document.getElementById('m-body');
  body.innerHTML = '<div class="sec-title" style="margin-top:0"><span class="num">[02]</span><h2>シグナル内訳</h2><span class="line"></span></div>' +
    Object.keys(meta).map(key => {
      const sig = t.signals[key] || { active: false, score: 0, detail: {}, evidence: 0, events: [] };
      const m = meta[key];
      const detailHtml = sig.active && sig.detail && Object.keys(sig.detail).length
        ? Object.entries(sig.detail).map(([k,v]) => `<div class="signal-detail-row"><span>${k}</span><strong>${escapeHtml(String(v))}</strong></div>`).join('')
        : '<div class="signal-detail-row" style="justify-content:center;color:var(--text-muted)">直近期間にシグナル検出なし</div>';
      
      // イベントタイムライン
      const events = (sig.events || []);
      let eventsHtml = '';
      if (sig.active && events.length > 0) {
        eventsHtml = `
          <div class="events-section">
            <div class="events-label">📋 シグナル発生イベント (${events.length}件)</div>
            ${events.map(ev => {
              const typeLower = (ev.type || '').toLowerCase();
              const dateDisplay = formatEventDate(ev.date || ev.filing_date);
              const activistTag = ev.is_activist ? '<span class="activist-tag">ACTIVIST</span>' : '';
              const titleSpan = ev.title ? `<span class="actor-title">[${escapeHtml(ev.title)}]</span>` : '';
              return `
                <div class="event-item">
                  <div class="event-row1">
                    <span class="event-type ${typeLower}">${escapeHtml(ev.type || '?')}</span>
                    <span class="event-date">${dateDisplay}</span>
                  </div>
                  <div class="event-actor">${escapeHtml(ev.actor || 'Unknown')}${titleSpan}${activistTag}</div>
                  ${ev.label ? `<div class="event-label">${escapeHtml(ev.label)}</div>` : ''}
                </div>
              `;
            }).join('')}
          </div>
        `;
      }
      
      return `
        <div class="signal-block ${sig.active ? 'active' : ''}" style="--sig-color:${m.color}">
          <div class="signal-head">
            <div class="signal-icon">${m.code}</div>
            <div class="signal-info">
              <div class="signal-title">${m.title}</div>
              <div class="signal-desc">${m.desc}</div>
            </div>
            <div class="signal-points">${sig.active ? '+' + sig.score : '0'}</div>
          </div>
          <div class="signal-detail">${detailHtml}</div>
          ${sig.active ? `
          <div class="evidence-bar"><div class="evidence-fill" style="width:${sig.evidence}%"></div></div>
          <div style="margin-top:6px;font-size:9px;color:var(--text-muted);font-family:'JetBrains Mono',monospace;letter-spacing:1px">CONFIDENCE ${sig.evidence}%</div>
          ` : ''}
          ${eventsHtml}
        </div>
      `;
    }).join('');
  
  document.getElementById('modal').classList.add('show');
  document.body.style.overflow = 'hidden';
}

function escapeHtml(s) {
  return String(s || '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function formatEventDate(dateStr) {
  if (!dateStr) return '日付不明';
  const s = String(dateStr).slice(0, 10);
  if (!/^\d{4}-\d{2}-\d{2}/.test(s)) return s;
  // 経過日数を計算
  const d = new Date(s);
  const now = new Date();
  const diffDays = Math.floor((now - d) / 86400000);
  if (diffDays === 0) return s + ' (今日)';
  if (diffDays === 1) return s + ' (昨日)';
  if (diffDays > 0 && diffDays <= 7) return s + ` (${diffDays}日前)`;
  if (diffDays > 0 && diffDays <= 30) return s + ` (${diffDays}日前)`;
  if (diffDays > 30) return s;
  return s;
}

function closeModal(e) {
  if (e && e.target.closest('.modal') && !e.target.classList.contains('modal-close')) return;
  document.getElementById('modal').classList.remove('show');
  document.body.style.overflow = '';
}

function searchTicker() {
  const sym = document.getElementById('search-input').value.trim().toUpperCase();
  if (!sym) return;
  const data = DATA[currentMarket];
  if (!data) return;
  const found = data.tickers.find(t => t.symbol === sym);
  if (found) showDetail(sym, currentMarket);
  else alert(`${sym} は現在のユニバースに含まれていません。\n対象銘柄を増やすには scripts/fetch_*.py の TICKERS リストを編集してください。`);
}

document.getElementById('search-input').addEventListener('keypress', e => { if (e.key === 'Enter') searchTicker(); });

// INIT
render();
updateMarketClocks();
setInterval(updateMarketClocks, 30000);  // 30秒ごとに時計更新

// データ自動再読み込み(5分ごとにdata.jsonを再取得)
async function reloadData() {
  try {
    const res = await fetch('data.json?_=' + Date.now());
    if (!res.ok) return;
    const newData = await res.json();
    if (newData && newData.JP && newData.US) {
      Object.assign(DATA, newData);
      render();
    }
  } catch (e) { /* 静かに失敗 */ }
}
setInterval(reloadData, 5 * 60 * 1000);
</script>
</body>
</html>
"""


def build():
    print("=" * 60)
    print(" 📊 Whale Tracker — Dashboard Builder ")
    print("=" * 60)
    
    # 米国データ
    us_path = DATA_DIR / "us_signals.json"
    jp_path = DATA_DIR / "jp_signals.json"
    
    us_data = {"tickers": [], "generated_at": datetime.now(timezone.utc).isoformat()}
    jp_data = {"tickers": [], "generated_at": datetime.now(JST).isoformat()}
    
    if us_path.exists():
        us_data = json.loads(us_path.read_text())
        print(f" ✅ US: {len(us_data.get('tickers', []))} tickers")
    else:
        print(f" ⚠️  US: データ未生成 (まず fetch_us.py を実行)")
    
    if jp_path.exists():
        jp_data = json.loads(jp_path.read_text())
        print(f" ✅ JP: {len(jp_data.get('tickers', []))} tickers")
    else:
        print(f" ⚠️  JP: データ未生成 (まず fetch_jp.py を実行)")
    
    combined = {"US": us_data, "JP": jp_data}
    json_str = json.dumps(combined, ensure_ascii=False)
    
    html = HTML_TEMPLATE.replace("__DATA_PLACEHOLDER__", json_str)
    
    # メインHTML
    out_html = DOCS_DIR / "index.html"
    out_html.write_text(html, encoding="utf-8")
    
    # バックアップJSON
    (DOCS_DIR / "data.json").write_text(json_str, encoding="utf-8")
    
    print(f"\n ✅ HTML生成: {out_html}")
    print(f"    サイズ: {out_html.stat().st_size:,} bytes")


if __name__ == "__main__":
    build()
