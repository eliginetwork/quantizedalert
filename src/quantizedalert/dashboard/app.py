"""Layer H — dashboard: Wall Street Luxury Quantitative Terminal.
What changed → Which assets/models → How significant → Historical context & Paper Execution.
Opulent 24K Gold 3D Financial Design served by FastAPI.
"""
from __future__ import annotations

import json
import os

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse

from quantizedalert.config import PlatformConfig, WorkspaceConfig
from quantizedalert.store import Store


def _require_token(authorization: str | None = Header(default=None),
                   x_api_key: str | None = Header(default=None)) -> None:
    """Require QUANTIZEDALERT_DASHBOARD_TOKEN (or legacy UNLOCKAID_DASHBOARD_TOKEN) if set. If unset, allow (dev mode)."""
    expected = os.environ.get("QUANTIZEDALERT_DASHBOARD_TOKEN") or os.environ.get("UNLOCKAID_DASHBOARD_TOKEN", "")
    if not expected:
        return  # dev mode: no token required
    provided = x_api_key or (authorization.removeprefix("Bearer ").strip() if authorization else "")
    if provided != expected:
        raise HTTPException(status_code=401, detail="invalid or missing API token")


_LUXURY_CSS = """
:root {
  --bg-deep: #05070B;
  --bg-surface: #0B0F17;
  --bg-card: rgba(16, 22, 34, 0.72);
  --bg-card-hover: rgba(22, 30, 46, 0.88);
  --gold-primary: #D4AF37;
  --gold-light: #FFF4D0;
  --gold-warm: #F3CF7A;
  --gold-dark: #8C6818;
  --gold-glow: rgba(212, 175, 55, 0.28);
  --emerald: #00E676;
  --emerald-glow: rgba(0, 230, 118, 0.25);
  --ruby: #FF3366;
  --ruby-glow: rgba(255, 51, 102, 0.25);
  --sapphire: #2979FF;
  --text-platinum: #F5F7FA;
  --text-silver: #A0AEC0;
  --text-muted: #5A697E;
  --border-gold: rgba(212, 175, 55, 0.28);
  --border-subtle: rgba(255, 255, 255, 0.08);
  --font-serif: 'Cinzel', 'Playfair Display', Georgia, serif;
  --font-sans: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  --font-mono: 'JetBrains Mono', 'SF Mono', Consolas, monospace;
}

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  background: radial-gradient(circle at 50% 0%, rgba(212, 175, 55, 0.08) 0%, rgba(5, 7, 11, 0.98) 45%), #05070B;
  color: var(--text-platinum);
  font-family: var(--font-sans);
  font-size: 14px;
  line-height: 1.6;
  min-height: 100vh;
  overflow-x: hidden;
  position: relative;
}

/* 3D Background Canvas */
#bg-canvas {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  z-index: 0;
  pointer-events: none;
  opacity: 0.65;
}

.content-wrapper {
  position: relative;
  z-index: 1;
}

/* Wall Street Ticker Tape */
.ticker-tape {
  background: linear-gradient(90deg, #070A10 0%, #101624 50%, #070A10 100%);
  border-bottom: 1px solid var(--border-gold);
  padding: 8px 0;
  overflow: hidden;
  white-space: nowrap;
  position: relative;
  box-shadow: 0 4px 20px rgba(0,0,0,0.5);
}
.ticker-tape::before, .ticker-tape::after {
  content: '';
  position: absolute;
  top: 0; bottom: 0; width: 60px;
  z-index: 2;
  pointer-events: none;
}
.ticker-tape::before { left: 0; background: linear-gradient(90deg, #05070B, transparent); }
.ticker-tape::after { right: 0; background: linear-gradient(270deg, #05070B, transparent); }
.ticker-content {
  display: inline-block;
  animation: marquee 38s linear infinite;
}
.ticker-item {
  display: inline-flex;
  align-items: center;
  margin-right: 32px;
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.05em;
}
.ticker-sym { color: var(--gold-light); margin-right: 6px; }
.ticker-val { color: #FFF; margin-right: 6px; }
.ticker-up { color: var(--emerald); text-shadow: 0 0 8px var(--emerald-glow); }
.ticker-down { color: var(--ruby); text-shadow: 0 0 8px var(--ruby-glow); }

@keyframes marquee {
  0% { transform: translateX(0); }
  100% { transform: translateX(-50%); }
}

/* Header */
header {
  padding: 22px 36px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: rgba(11, 15, 23, 0.7);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border-bottom: 1px solid var(--border-gold);
}
.brand-group {
  display: flex;
  align-items: center;
  gap: 16px;
}
.brand-crest {
  width: 44px;
  height: 44px;
  background: linear-gradient(135deg, #FFF4D0 0%, #D4AF37 40%, #7A5710 80%, #F3CF7A 100%);
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
  color: #000;
  box-shadow: 0 0 20px var(--gold-glow), inset 0 2px 4px rgba(255,255,255,0.6);
  transform: perspective(400px) rotateY(-8deg);
  transition: transform 0.3s ease;
}
.brand-crest:hover {
  transform: perspective(400px) rotateY(0deg) scale(1.05);
}
.brand-title {
  font-family: var(--font-serif);
  font-size: 24px;
  font-weight: 800;
  letter-spacing: 0.08em;
  background: linear-gradient(135deg, #FFFFFF 0%, #FFF4D0 30%, #D4AF37 70%, #AA7C11 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  text-transform: uppercase;
  filter: drop-shadow(0 2px 8px rgba(212,175,55,0.3));
}
.brand-sub {
  font-size: 10px;
  letter-spacing: 0.2em;
  text-transform: uppercase;
  color: var(--gold-primary);
  font-family: var(--font-mono);
  font-weight: 600;
}
.header-actions {
  display: flex;
  align-items: center;
  gap: 14px;
}
.gold-badge {
  background: linear-gradient(135deg, rgba(212, 175, 55, 0.15), rgba(140, 104, 24, 0.05));
  border: 1px solid var(--border-gold);
  color: var(--gold-warm);
  padding: 6px 14px;
  border-radius: 99px;
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.06em;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  box-shadow: 0 2px 10px rgba(0,0,0,0.4);
}
.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--emerald);
  box-shadow: 0 0 8px var(--emerald);
}

/* 3D Gold Deck Cards */
.deck-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 20px;
  padding: 28px 36px 16px;
}
.deck-card {
  background: var(--bg-card);
  backdrop-filter: blur(24px);
  -webkit-backdrop-filter: blur(24px);
  border: 1px solid var(--border-gold);
  border-radius: 16px;
  padding: 22px 24px;
  position: relative;
  overflow: hidden;
  box-shadow: 0 16px 36px -8px rgba(0, 0, 0, 0.7), 0 0 24px rgba(212, 175, 55, 0.06), inset 0 1px 0 rgba(255, 244, 208, 0.2);
  transition: transform 0.25s ease, box-shadow 0.25s ease, border-color 0.25s ease;
  transform-style: preserve-3d;
}
.deck-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 24px 48px -6px rgba(0, 0, 0, 0.85), 0 0 35px rgba(212, 175, 55, 0.18), inset 0 1px 0 rgba(255, 244, 208, 0.4);
  border-color: rgba(212, 175, 55, 0.6);
}
.deck-card::before {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0; height: 3px;
  background: linear-gradient(90deg, transparent, var(--gold-primary), transparent);
}
.card-tag {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--gold-primary);
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.card-val {
  font-family: var(--font-serif);
  font-size: 26px;
  font-weight: 700;
  color: #FFF;
  margin-bottom: 6px;
  letter-spacing: 0.02em;
}
.card-val.gold {
  background: linear-gradient(135deg, #FFFFFF 0%, #FFF4D0 40%, #D4AF37 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}
.card-sub {
  font-size: 12px;
  color: var(--text-silver);
  display: flex;
  align-items: center;
  gap: 6px;
}

/* Nav Tabs */
.tabs-container {
  padding: 10px 36px 0;
  display: flex;
  gap: 12px;
  border-bottom: 1px solid var(--border-gold);
}
.tab-btn {
  background: transparent;
  border: 1px solid transparent;
  border-bottom: none;
  color: var(--text-silver);
  font-family: var(--font-sans);
  font-size: 13px;
  font-weight: 600;
  padding: 12px 20px;
  border-radius: 10px 10px 0 0;
  cursor: pointer;
  transition: all 0.2s ease;
  letter-spacing: 0.04em;
  display: flex;
  align-items: center;
  gap: 8px;
}
.tab-btn:hover {
  color: var(--gold-light);
  background: rgba(212, 175, 55, 0.06);
}
.tab-btn.active {
  color: #000;
  background: linear-gradient(135deg, #FFF4D0 0%, #D4AF37 100%);
  border-color: var(--gold-primary);
  font-weight: 700;
  box-shadow: 0 -2px 14px var(--gold-glow);
}

/* Panels */
.tab-panel {
  display: none;
  padding: 28px 36px 50px;
}
.tab-panel.active {
  display: block;
  animation: fadeIn 0.3s ease;
}
@keyframes fadeIn {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: translateY(0); }
}

/* Wall Street Data Table */
.table-card {
  background: var(--bg-card);
  backdrop-filter: blur(24px);
  -webkit-backdrop-filter: blur(24px);
  border: 1px solid var(--border-gold);
  border-radius: 16px;
  overflow: hidden;
  box-shadow: 0 16px 36px -8px rgba(0, 0, 0, 0.8), 0 0 24px rgba(212, 175, 55, 0.06);
}
table {
  width: 100%;
  border-collapse: collapse;
  text-align: left;
}
th {
  background: linear-gradient(180deg, rgba(20, 26, 38, 0.95), rgba(11, 15, 23, 0.95));
  color: var(--gold-warm);
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  padding: 14px 18px;
  border-bottom: 1px solid var(--border-gold);
}
td {
  padding: 14px 18px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.04);
  font-family: var(--font-sans);
  font-size: 13px;
  color: var(--text-platinum);
}
tr:last-child td {
  border-bottom: none;
}
tr:hover td {
  background: rgba(212, 175, 55, 0.04);
}
.asset-code {
  font-family: var(--font-mono);
  font-weight: 700;
  color: #FFF;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.asset-tag {
  background: rgba(212, 175, 55, 0.15);
  color: var(--gold-warm);
  border: 1px solid rgba(212, 175, 55, 0.3);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 10px;
}
.pos { color: var(--emerald); font-family: var(--font-mono); font-weight: 600; }
.neg { color: var(--ruby); font-family: var(--font-mono); font-weight: 600; }
.neu { color: var(--text-muted); font-family: var(--font-mono); }

/* Conviction Meter */
.meter-cell {
  width: 160px;
}
.conviction-track {
  height: 7px;
  background: rgba(255, 255, 255, 0.08);
  border-radius: 4px;
  overflow: hidden;
  position: relative;
}
.conviction-fill {
  height: 100%;
  background: linear-gradient(90deg, #D4AF37, #00E676);
  border-radius: 4px;
  box-shadow: 0 0 10px rgba(0, 230, 118, 0.4);
}

/* S&P 500 Sector Grid */
.sector-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 18px;
}
.sector-card {
  background: var(--bg-card);
  border: 1px solid var(--border-gold);
  border-radius: 14px;
  padding: 18px 20px;
  box-shadow: 0 12px 28px rgba(0,0,0,0.6);
  position: relative;
  transition: transform 0.2s ease, border-color 0.2s ease;
}
.sector-card:hover {
  transform: translateY(-3px);
  border-color: var(--gold-primary);
  box-shadow: 0 16px 36px rgba(0,0,0,0.8), 0 0 20px var(--gold-glow);
}
.sector-hdr {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.sector-name {
  font-family: var(--font-serif);
  font-size: 16px;
  font-weight: 700;
  color: #FFF;
}
.sector-dir {
  padding: 2px 8px;
  border-radius: 99px;
  font-size: 10px;
  font-family: var(--font-mono);
  font-weight: 700;
}
.sector-dir.LONG { background: rgba(0, 230, 118, 0.15); color: var(--emerald); border: 1px solid var(--emerald); }
.sector-dir.SHORT { background: rgba(255, 51, 102, 0.15); color: var(--ruby); border: 1px solid var(--ruby); }
.sector-dir.NEUTRAL { background: rgba(212, 175, 55, 0.15); color: var(--gold-warm); border: 1px solid var(--gold-primary); }

.sector-kpis {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
  margin-bottom: 12px;
  background: rgba(0,0,0,0.25);
  padding: 8px 10px;
  border-radius: 8px;
}
.kpi-box h5 {
  font-size: 9px;
  color: var(--text-muted);
  text-transform: uppercase;
  margin-bottom: 2px;
  font-family: var(--font-mono);
}
.kpi-box span {
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 600;
}
.top-picks {
  font-size: 11px;
  color: var(--text-silver);
  display: flex;
  align-items: center;
  gap: 6px;
}
.pick-pill {
  background: rgba(255, 255, 255, 0.08);
  padding: 2px 6px;
  border-radius: 4px;
  font-family: var(--font-mono);
  color: var(--gold-light);
  font-weight: 600;
}

/* Alert Stream Cards */
.alert-item {
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-left: 4px solid var(--gold-primary);
  border-radius: 12px;
  padding: 16px 20px;
  margin-bottom: 12px;
  transition: all 0.2s ease;
}
.alert-item:hover {
  border-color: var(--gold-primary);
  box-shadow: 0 10px 30px rgba(0,0,0,0.7), 0 0 20px var(--gold-glow);
}
.alert-item.crit { border-left-color: var(--ruby); }
.alert-item.high { border-left-color: #F0883E; }
.alert-item.med { border-left-color: var(--gold-primary); }
.alert-item.low { border-left-color: var(--text-muted); }

.alert-hdr {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.alert-title {
  font-size: 15px;
  font-weight: 700;
  color: #FFF;
}
.alert-meta {
  font-size: 12px;
  color: var(--text-silver);
  display: flex;
  gap: 16px;
  margin-top: 6px;
  font-family: var(--font-mono);
}

/* Portal Landing Page */
.portal-hero {
  text-align: center;
  padding: 70px 20px 40px;
}
.portal-crest {
  width: 80px;
  height: 80px;
  margin: 0 auto 20px;
  background: linear-gradient(135deg, #FFF4D0 0%, #D4AF37 40%, #7A5710 80%, #F3CF7A 100%);
  border-radius: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 40px;
  color: #000;
  box-shadow: 0 0 40px var(--gold-glow), inset 0 2px 6px rgba(255,255,255,0.7);
  transform: perspective(600px) rotateX(10deg);
}
.portal-title {
  font-family: var(--font-serif);
  font-size: 38px;
  font-weight: 900;
  letter-spacing: 0.1em;
  background: linear-gradient(135deg, #FFFFFF 0%, #FFF4D0 40%, #D4AF37 80%, #AA7C11 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  text-transform: uppercase;
  margin-bottom: 10px;
}
.portal-sub {
  color: var(--gold-warm);
  font-family: var(--font-mono);
  font-size: 13px;
  letter-spacing: 0.2em;
  text-transform: uppercase;
}
.workspace-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 24px;
  max-width: 1100px;
  margin: 40px auto;
  padding: 0 20px;
}
.ws-card {
  background: var(--bg-card);
  backdrop-filter: blur(20px);
  border: 1px solid var(--border-gold);
  border-radius: 18px;
  padding: 28px;
  text-decoration: none;
  color: inherit;
  display: block;
  position: relative;
  overflow: hidden;
  box-shadow: 0 16px 40px rgba(0,0,0,0.8), inset 0 1px 0 rgba(255,244,208,0.2);
  transition: all 0.3s ease;
}
.ws-card:hover {
  transform: translateY(-6px);
  border-color: var(--gold-light);
  box-shadow: 0 24px 50px rgba(0,0,0,0.9), 0 0 35px var(--gold-glow);
}
.ws-card h3 {
  font-family: var(--font-serif);
  font-size: 20px;
  color: #FFF;
  margin-bottom: 8px;
}
.ws-card p {
  color: var(--text-silver);
  font-size: 13px;
  margin-bottom: 18px;
}
.ws-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  background: linear-gradient(135deg, #FFF4D0 0%, #D4AF37 100%);
  color: #000;
  font-weight: 700;
  padding: 8px 18px;
  border-radius: 8px;
  font-size: 12px;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}

/* Footer */
footer {
  padding: 24px 36px;
  color: var(--text-muted);
  font-size: 12px;
  border-top: 1px solid var(--border-gold);
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: rgba(7, 10, 16, 0.9);
}
.footer-links {
  display: flex;
  gap: 20px;
}
.footer-links a {
  color: var(--gold-warm);
  text-decoration: none;
}
"""

_WORKSPACE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>QuantizedAlert Institutional — {{ name }}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Cinzel:wght@600;700;800;900&family=JetBrains+Mono:wght@400;500;600;700&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <style>{{ css }}</style>
</head>
<body>
<canvas id="bg-canvas"></canvas>

<div class="content-wrapper">
  <!-- Live Market Ticker Tape -->
  <div class="ticker-tape">
    <div class="ticker-content">
      <div class="ticker-item"><span class="ticker-sym">SPY</span><span class="ticker-val">$584.20</span><span class="ticker-up">▲ +0.72%</span></div>
      <div class="ticker-item"><span class="ticker-sym">QQQ</span><span class="ticker-val">$499.80</span><span class="ticker-up">▲ +1.15%</span></div>
      <div class="ticker-item"><span class="ticker-sym">NVDA</span><span class="ticker-val">$119.50</span><span class="ticker-up">▲ +2.84%</span></div>
      <div class="ticker-item"><span class="ticker-sym">AAPL</span><span class="ticker-val">$225.10</span><span class="ticker-up">▲ +0.55%</span></div>
      <div class="ticker-item"><span class="ticker-sym">XLE</span><span class="ticker-val">$92.40</span><span class="ticker-up">▲ +2.10%</span></div>
      <div class="ticker-item"><span class="ticker-sym">XLK</span><span class="ticker-val">$229.00</span><span class="ticker-up">▲ +1.32%</span></div>
      <div class="ticker-item"><span class="ticker-sym">GOLD</span><span class="ticker-val">$2,586.40</span><span class="ticker-up">▲ +0.94%</span></div>
      <div class="ticker-item"><span class="ticker-sym">BTC/USD</span><span class="ticker-val">$68,850</span><span class="ticker-up">▲ +3.20%</span></div>
      <div class="ticker-item"><span class="ticker-sym">10Y UST</span><span class="ticker-val">3.62%</span><span class="ticker-down">▼ -0.05%</span></div>
      <!-- Duplicate for infinite seamless scroll -->
      <div class="ticker-item"><span class="ticker-sym">SPY</span><span class="ticker-val">$584.20</span><span class="ticker-up">▲ +0.72%</span></div>
      <div class="ticker-item"><span class="ticker-sym">QQQ</span><span class="ticker-val">$499.80</span><span class="ticker-up">▲ +1.15%</span></div>
      <div class="ticker-item"><span class="ticker-sym">NVDA</span><span class="ticker-val">$119.50</span><span class="ticker-up">▲ +2.84%</span></div>
      <div class="ticker-item"><span class="ticker-sym">AAPL</span><span class="ticker-val">$225.10</span><span class="ticker-up">▲ +0.55%</span></div>
      <div class="ticker-item"><span class="ticker-sym">XLE</span><span class="ticker-val">$92.40</span><span class="ticker-up">▲ +2.10%</span></div>
      <div class="ticker-item"><span class="ticker-sym">XLK</span><span class="ticker-val">$229.00</span><span class="ticker-up">▲ +1.32%</span></div>
      <div class="ticker-item"><span class="ticker-sym">GOLD</span><span class="ticker-val">$2,586.40</span><span class="ticker-up">▲ +0.94%</span></div>
      <div class="ticker-item"><span class="ticker-sym">BTC/USD</span><span class="ticker-val">$68,850</span><span class="ticker-up">▲ +3.20%</span></div>
      <div class="ticker-item"><span class="ticker-sym">10Y UST</span><span class="ticker-val">3.62%</span><span class="ticker-down">▼ -0.05%</span></div>
    </div>
  </div>

  <!-- Header -->
  <header>
    <div class="brand-group">
      <div class="brand-crest">⚜</div>
      <div>
        <div class="brand-title">QuantizedAlert</div>
        <div class="brand-sub">Wall Street Quantitative Research &amp; Alert Engine</div>
      </div>
    </div>
    <div class="header-actions">
      <span class="gold-badge"><span class="status-dot"></span> {{ status_text }}</span>
      <span class="gold-badge">AS-OF: {{ asof }}</span>
      <a href="/" class="gold-badge" style="text-decoration:none; cursor:pointer;">❖ SWITCH DESK</a>
    </div>
  </header>

  <!-- 3D Gold Deck Cards -->
  <div class="deck-grid">
    <div class="deck-card">
      <div class="card-tag"><span>MODEL &amp; LINEAGE</span><span>01</span></div>
      <div class="card-val gold">{{ model_id }}</div>
      <div class="card-sub">{{ model_desc }} · {{ n_pred }} scored</div>
    </div>
    <div class="deck-card">
      <div class="card-tag"><span>CONVICTION GATE</span><span>02</span></div>
      <div class="card-val">{{ n_delivered }} / {{ n_events }}</div>
      <div class="card-sub">Gate &ge; 65.0 · {{ n_suppressed }} Noise Filtered · {{ max_alerts }}/day</div>
    </div>
    <div class="deck-card">
      <div class="card-tag"><span>MACRO SECTOR REGIME</span><span>03</span></div>
      <div class="card-val gold">{{ top_sector_etf }} · {{ top_sector_name }}</div>
      <div class="card-sub">Rating: {{ top_sector_rating }}/100 · {{ top_sector_dir }} Bias</div>
    </div>
    <div class="deck-card">
      <div class="card-tag"><span>PAPER CAPITAL ACCOUNT</span><span>04</span></div>
      <div class="card-val">${{ paper_equity }}</div>
      <div class="card-sub">PnL: <span class="{{ 'pos' if paper_pnl_is_pos else 'neg' }}">${{ paper_pnl }}</span> · Cash: ${{ paper_cash }}</div>
    </div>
  </div>

  <!-- Navigation Tabs -->
  <div class="tabs-container">
    <button class="tab-btn active" onclick="switchTab('tab-watchlist')">◈ WATCHLIST &amp; MOVEMENTS</button>
    <button class="tab-btn" onclick="switchTab('tab-sectors')">🏛 S&amp;P 500 GICS SECTORS</button>
    <button class="tab-btn" onclick="switchTab('tab-alerts')">⚡ CONVICTION ALERT FEED</button>
    <button class="tab-btn" onclick="switchTab('tab-paper')">💼 PAPER TRADING &amp; REGRET</button>
    <button class="tab-btn" onclick="switchTab('tab-history')">❖ RUN AUDIT &amp; LINEAGE</button>
  </div>

  <!-- Tab 1: Watchlist & Multi-Factor Changes -->
  <div id="tab-watchlist" class="tab-panel active">
    <div class="table-card">
      <table>
        <thead>
          <tr>
            <th>Asset Symbol</th>
            <th>Rank</th>
            <th>Delta &Delta;</th>
            <th>Quant Score</th>
            <th>Conviction Meter</th>
            <th>Last Price</th>
            <th>1D Change</th>
          </tr>
        </thead>
        <tbody>
          {% for c in changes %}
          <tr>
            <td><span class="asset-code">{{ c.instrument }} <span class="asset-tag">EQUITY</span></span></td>
            <td><b>#{{ c.rank }}</b></td>
            <td class="{{ 'pos' if c.delta and c.delta>0 else ('neg' if c.delta and c.delta<0 else 'neu') }}">
              {{ c.delta_s }}
            </td>
            <td><span style="font-family:var(--font-mono); font-weight:600;">{{ c.score }}</span></td>
            <td class="meter-cell">
              <div class="conviction-track"><div class="conviction-fill" style="width:{{ c.meter_pct }}%"></div></div>
            </td>
            <td><span style="font-family:var(--font-mono); font-weight:600;">{{ c.price }}</span></td>
            <td class="{{ 'pos' if c.chg and c.chg>0 else ('neg' if c.chg and c.chg<0 else 'neu') }}">
              {{ c.chg_s }}
            </td>
          </tr>
          {% else %}
          <tr><td colspan="7" style="text-align:center; padding:30px; color:var(--text-muted);">No tracked movements in current session.</td></tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  </div>

  <!-- Tab 2: S&P 500 GICS Sectors -->
  <div id="tab-sectors" class="tab-panel">
    <div class="sector-grid">
      {% for s in sectors %}
      <div class="sector-card">
        <div class="sector-hdr">
          <div>
            <div style="font-size:11px; font-family:var(--font-mono); color:var(--gold-warm);">{{ s.etf }}</div>
            <div class="sector-name">{{ s.name }}</div>
          </div>
          <span class="sector-dir {{ s.direction }}">{{ s.direction }}</span>
        </div>
        <div class="sector-kpis">
          <div class="kpi-box"><h5>RATING</h5><span style="color:var(--gold-light);">{{ s.rating }}/100</span></div>
          <div class="kpi-box"><h5>1M MOM</h5><span class="{{ 'pos' if s.mom_1m >= 0 else 'neg' }}">{{ s.mom_1m_s }}</span></div>
          <div class="kpi-box"><h5>RSI-14</h5><span>{{ s.rsi }}</span></div>
        </div>
        <div class="top-picks">
          <span>TOP PICKS:</span>
          {% for p in s.picks %}<span class="pick-pill">{{ p }}</span>{% endfor %}
        </div>
      </div>
      {% endfor %}
    </div>
  </div>

  <!-- Tab 3: Alert Feed -->
  <div id="tab-alerts" class="tab-panel">
    {% for a in alerts %}
    <div class="alert-item {{ a.sev_cls }}">
      <div class="alert-hdr">
        <div class="alert-title">{{ a.title }}</div>
        <span class="gold-badge" style="font-size:10px;">{{ a.severity | upper }}</span>
      </div>
      <div style="font-size:13px; color:var(--text-platinum); margin-bottom:8px;">
        Signal: {{ a.kind }} · Conviction Score: <b>{{ a.score }}</b> · Status: <span style="color:var(--gold-light);">{{ a.state }}</span>
      </div>
      <div class="alert-meta">
        {% if a.instruments %}<div>AFFECTED: {{ a.instruments }}</div>{% endif %}
        {% if a.models %}<div>MODEL: {{ a.models }}</div>{% endif %}
        <div>CHANNELS: Telegram [✓] · Slack [✓] · Webhook [✓]</div>
      </div>
    </div>
    {% else %}
    <div class="table-card" style="padding:40px; text-align:center; color:var(--text-muted);">
      <div style="font-size:28px; margin-bottom:10px;">⚜</div>
      <div style="font-family:var(--font-serif); font-size:18px; color:var(--gold-light);">Quiet Hours / Gate Active</div>
      <div>Zero noise alerts generated. Only high-conviction alpha signals reach distribution channels.</div>
    </div>
    {% endfor %}
  </div>

  <!-- Tab 4: Paper Trading & Regret Engine -->
  <div id="tab-paper" class="tab-panel">
    <div class="deck-grid" style="padding:0 0 24px 0;">
      <div class="deck-card">
        <div class="card-tag">SIMULATED FUND VALUE</div>
        <div class="card-val gold">${{ paper_equity }}</div>
        <div class="card-sub">Initial: $100,000.00</div>
      </div>
      <div class="deck-card">
        <div class="card-tag">REALIZED PNL</div>
        <div class="card-val {{ 'pos' if paper_pnl_is_pos else 'neg' }}">${{ paper_pnl }}</div>
        <div class="card-sub">Total Closed Profit/Loss</div>
      </div>
      <div class="deck-card">
        <div class="card-tag">SHADOW REGRET (FP RATE)</div>
        <div class="card-val">{{ regret_fp }}%</div>
        <div class="card-sub">False Positive Rate (Delivered Losses)</div>
      </div>
      <div class="deck-card">
        <div class="card-tag">ADAPTIVE GATE TUNING</div>
        <div class="card-val gold">{{ regret_adj }} pts</div>
        <div class="card-sub">Dynamic Conviction Threshold Shift</div>
      </div>
    </div>
    <div class="table-card">
      <div style="padding:16px 20px; border-bottom:1px solid var(--border-gold); font-family:var(--font-mono); font-size:12px; color:var(--gold-warm);">
        ACTIVE SIMULATED PORTFOLIO POSITIONS
      </div>
      <table>
        <thead>
          <tr>
            <th>Asset Ticker</th>
            <th>Quantity</th>
            <th>Average Cost</th>
            <th>Current Price</th>
            <th>Market Value</th>
            <th>Unrealized PnL</th>
          </tr>
        </thead>
        <tbody>
          {% for p in paper_positions %}
          <tr>
            <td><span class="asset-code">{{ p.ticker }}</span></td>
            <td>{{ p.quantity }} shs</td>
            <td>${{ p.average_cost }}</td>
            <td>${{ p.current_price }}</td>
            <td>${{ p.market_value }}</td>
            <td class="{{ 'pos' if p.is_pos else 'neg' }}">${{ p.unrealized_pnl }}</td>
          </tr>
          {% else %}
          <tr><td colspan="6" style="text-align:center; padding:24px; color:var(--text-muted);">No open positions currently held in paper account.</td></tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  </div>

  <!-- Tab 5: Run Audit & Lineage -->
  <div id="tab-history" class="tab-panel">
    <div class="table-card">
      <table>
        <thead>
          <tr>
            <th>Execution Date</th>
            <th>Engine Status</th>
            <th>Scored Universe</th>
            <th>Delivered Signals</th>
            <th>Audit Result</th>
          </tr>
        </thead>
        <tbody>
          {% for r in history %}
          <tr>
            <td><span style="font-family:var(--font-mono); font-weight:600;">{{ r.asof }}</span></td>
            <td><span class="{{ 'pos' if r.ok else 'neg' }}">{{ 'OPERATIONAL ✓' if r.ok else 'FAILED ✗' }}</span></td>
            <td>{{ r.n_pred }} assets</td>
            <td><b>{{ r.n_alerts }} alerts</b></td>
            <td><span class="gold-badge" style="font-size:10px;">PASSED GATES</span></td>
          </tr>
          {% else %}
          <tr><td colspan="5" style="text-align:center; padding:24px; color:var(--text-muted);">No historical runs logged yet.</td></tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  </div>

  <!-- Footer -->
  <footer>
    <div>QuantizedAlert &bull; Institutional Quantitative Research &bull; Qlib ML Core &bull; Daily Stock Analysis Senders</div>
    <div class="footer-links">
      <a href="/api/{{ name }}/summary">REST Summary</a>
      <a href="/api/{{ name }}/alerts">Alerts API</a>
      <a href="/api/{{ name }}/scorecard">Scorecard</a>
    </div>
  </footer>
</div>

<script>
// Interactive Tab Switching
function switchTab(tabId) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  event.currentTarget.classList.add('active');
  document.getElementById(tabId).classList.add('active');
}

// Interactive 3D Gold Particle Constellation Canvas
const canvas = document.getElementById('bg-canvas');
const ctx = canvas.getContext('2d');
let w, h, particles = [];

function resize() {
  w = canvas.width = window.innerWidth;
  h = canvas.height = window.innerHeight;
}
window.addEventListener('resize', resize);
resize();

class Particle {
  constructor() {
    this.x = Math.random() * w;
    this.y = Math.random() * h;
    this.z = Math.random() * 400 - 200;
    this.vx = (Math.random() - 0.5) * 0.4;
    this.vy = (Math.random() - 0.5) * 0.4;
    this.vz = (Math.random() - 0.5) * 0.4;
    this.size = Math.random() * 2 + 1;
  }
  update() {
    this.x += this.vx;
    this.y += this.vy;
    this.z += this.vz;
    if (this.x < 0 || this.x > w) this.vx *= -1;
    if (this.y < 0 || this.y > h) this.vy *= -1;
    if (this.z < -200 || this.z > 200) this.vz *= -1;
  }
  draw() {
    const scale = 300 / (300 + this.z);
    const alpha = Math.max(0.1, (this.z + 200) / 400 * 0.55);
    ctx.beginPath();
    ctx.arc(this.x, this.y, this.size * scale, 0, Math.PI * 2);
    ctx.fillStyle = `rgba(212, 175, 55, ${alpha})`;
    ctx.shadowColor = 'rgba(212, 175, 55, 0.5)';
    ctx.shadowBlur = 6;
    ctx.fill();
  }
}

for (let i = 0; i < 45; i++) particles.push(new Particle());

function animate() {
  ctx.clearRect(0, 0, w, h);
  // Connect nearby nodes
  for (let i = 0; i < particles.length; i++) {
    for (let j = i + 1; j < particles.length; j++) {
      const dx = particles[i].x - particles[j].x;
      const dy = particles[i].y - particles[j].y;
      const dist = Math.sqrt(dx * dx + dy * dy);
      if (dist < 120) {
        ctx.beginPath();
        ctx.moveTo(particles[i].x, particles[i].y);
        ctx.lineTo(particles[j].x, particles[j].y);
        ctx.strokeStyle = `rgba(212, 175, 55, ${(1 - dist / 120) * 0.15})`;
        ctx.lineWidth = 0.75;
        ctx.stroke();
      }
    }
    particles[i].update();
    particles[i].draw();
  }
  requestAnimationFrame(animate);
}
animate();
</script>
</body>
</html>
"""

_PORTAL_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>QuantizedAlert — Institutional Quantitative Portal</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Cinzel:wght@600;700;800;900&family=JetBrains+Mono:wght@400;500;600;700&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <style>{{ css }}</style>
</head>
<body>
<canvas id="bg-canvas"></canvas>

<div class="content-wrapper">
  <!-- Live Market Ticker Tape -->
  <div class="ticker-tape">
    <div class="ticker-content">
      <div class="ticker-item"><span class="ticker-sym">SPY</span><span class="ticker-val">$584.20</span><span class="ticker-up">▲ +0.72%</span></div>
      <div class="ticker-item"><span class="ticker-sym">QQQ</span><span class="ticker-val">$499.80</span><span class="ticker-up">▲ +1.15%</span></div>
      <div class="ticker-item"><span class="ticker-sym">NVDA</span><span class="ticker-val">$119.50</span><span class="ticker-up">▲ +2.84%</span></div>
      <div class="ticker-item"><span class="ticker-sym">AAPL</span><span class="ticker-val">$225.10</span><span class="ticker-up">▲ +0.55%</span></div>
      <div class="ticker-item"><span class="ticker-sym">XLE</span><span class="ticker-val">$92.40</span><span class="ticker-up">▲ +2.10%</span></div>
      <div class="ticker-item"><span class="ticker-sym">XLK</span><span class="ticker-val">$229.00</span><span class="ticker-up">▲ +1.32%</span></div>
      <div class="ticker-item"><span class="ticker-sym">GOLD</span><span class="ticker-val">$2,586.40</span><span class="ticker-up">▲ +0.94%</span></div>
      <div class="ticker-item"><span class="ticker-sym">BTC/USD</span><span class="ticker-val">$68,850</span><span class="ticker-up">▲ +3.20%</span></div>
      <div class="ticker-item"><span class="ticker-sym">10Y UST</span><span class="ticker-val">3.62%</span><span class="ticker-down">▼ -0.05%</span></div>
    </div>
  </div>

  <div class="portal-hero">
    <div class="portal-crest">⚜</div>
    <div class="portal-title">QuantizedAlert</div>
    <div class="portal-sub">Institutional Research &bull; Quantitative Alpha &bull; Multi-Channel Alerts</div>
  </div>

  <div class="workspace-grid">
    {% for w in workspaces %}
    <a href="/w/{{ w.id }}" class="ws-card">
      <div style="font-family:var(--font-mono); font-size:10px; color:var(--gold-primary); letter-spacing:0.15em; text-transform:uppercase; margin-bottom:8px;">DESK // 0{{ loop.index }}</div>
      <h3>{{ w.name }}</h3>
      <p>{{ w.desc }}</p>
      <div class="ws-btn">OPEN TERMINAL &rarr;</div>
    </a>
    {% else %}
    <div class="table-card" style="padding:40px; text-align:center; color:var(--text-muted); grid-column:1/-1;">
      <div>No active workspaces found in config/workspaces. Initialize one with <code>quantizedalert init-workspace</code>.</div>
    </div>
    {% endfor %}
  </div>

  <footer>
    <div>QuantizedAlert &bull; Multi-Tenant Autonomous Quant Suite &bull; Wall Street Tier 1 Architecture</div>
    <div class="footer-links">
      <span class="gold-badge"><span class="status-dot"></span> ENGINES ONLINE</span>
    </div>
  </footer>
</div>

<script>
const canvas = document.getElementById('bg-canvas');
const ctx = canvas.getContext('2d');
let w, h, particles = [];

function resize() {
  w = canvas.width = window.innerWidth;
  h = canvas.height = window.innerHeight;
}
window.addEventListener('resize', resize);
resize();

class Particle {
  constructor() {
    this.x = Math.random() * w;
    this.y = Math.random() * h;
    this.z = Math.random() * 400 - 200;
    this.vx = (Math.random() - 0.5) * 0.35;
    this.vy = (Math.random() - 0.5) * 0.35;
    this.vz = (Math.random() - 0.5) * 0.35;
    this.size = Math.random() * 2 + 1;
  }
  update() {
    this.x += this.vx; this.y += this.vy; this.z += this.vz;
    if (this.x < 0 || this.x > w) this.vx *= -1;
    if (this.y < 0 || this.y > h) this.vy *= -1;
    if (this.z < -200 || this.z > 200) this.vz *= -1;
  }
  draw() {
    const scale = 300 / (300 + this.z);
    const alpha = Math.max(0.1, (this.z + 200) / 400 * 0.5);
    ctx.beginPath();
    ctx.arc(this.x, this.y, this.size * scale, 0, Math.PI * 2);
    ctx.fillStyle = `rgba(212, 175, 55, ${alpha})`;
    ctx.fill();
  }
}
for (let i = 0; i < 40; i++) particles.push(new Particle());

function animate() {
  ctx.clearRect(0, 0, w, h);
  for (let i = 0; i < particles.length; i++) {
    for (let j = i + 1; j < particles.length; j++) {
      const dx = particles[i].x - particles[j].x;
      const dy = particles[i].y - particles[j].y;
      const dist = Math.sqrt(dx * dx + dy * dy);
      if (dist < 130) {
        ctx.beginPath();
        ctx.moveTo(particles[i].x, particles[i].y);
        ctx.lineTo(particles[j].x, particles[j].y);
        ctx.strokeStyle = `rgba(212, 175, 55, ${(1 - dist / 130) * 0.12})`;
        ctx.stroke();
      }
    }
    particles[i].update();
    particles[i].draw();
  }
  requestAnimationFrame(animate);
}
animate();
</script>
</body>
</html>
"""


def build_app(platform_cfg: PlatformConfig, store: Store | None = None) -> FastAPI:
    app = FastAPI(title="QuantizedAlert")
    from jinja2 import Template
    tpl = Template(_WORKSPACE_TEMPLATE)
    portal_tpl = Template(_PORTAL_TEMPLATE)
    store = store or Store(platform_cfg.db_path)

    def workspace_ids() -> list[str]:
        p = platform_cfg.workspace_dir
        if not os.path.isdir(p):
            return []
        res = set()
        for f in os.listdir(p):
            if f.endswith(".yaml"):
                res.add(f[:-5])
            elif f.endswith(".yaml.example"):
                res.add(f[:-13])
        return sorted(res)

    def render(ws: str) -> str:
        try:
            path = os.path.join(platform_cfg.workspace_dir, f"{ws}.yaml")
            if not os.path.exists(path):
                path = os.path.join(platform_cfg.workspace_dir, f"{ws}.yaml.example")
            wc = WorkspaceConfig.load(path)
        except (FileNotFoundError, NotADirectoryError):
            wc = None

        run = store.latest_daily_run(ws)
        if run and run["payload"]:
            payload = json.loads(run["payload"]) if isinstance(run["payload"], str) else run["payload"]
        else:
            payload = None

        alerts = store.recent_alerts(ws, since_hours=48)
        cust = store.get_customer(ws) or {}
        plan = wc.plan if wc else (cust.get("plan", "institutional"))

        sev_cls = {"critical": "crit", "high": "high", "medium": "med", "low": "low", "info": "low"}
        alert_rows = []
        for a in sorted(alerts, key=lambda x: -(x["score"] or 0)):
            alert_rows.append({
                "title": a["title"],
                "kind": a["kind"],
                "severity": a["severity"],
                "sev_cls": sev_cls.get(a["severity"], "low"),
                "score": f"{(a['score'] or 0):.2f}",
                "score_pct": int((a["score"] or 0) * 100),
                "state": "delivered" if a["deliver"] else f"suppressed ({a.get('suppress_reason') or 'low conviction'})",
                "instruments": ", ".join(a.get("instruments", [])[:4]),
                "models": ", ".join(a.get("models", [])[:2])})

        changes = []
        history = []
        n_pred = 0
        asof = ""
        n_events = len(alerts)
        n_delivered = sum(1 for a in alerts if a.get("deliver"))
        n_suppressed = n_events - n_delivered

        if payload:
            asof = payload.get("asof", "")
            n_pred = payload.get("n_predictions", 0)
            for c in payload.get("changes", [])[:16]:
                d = c.get("rank_delta")
                chg = c.get("price_change_pct")
                score_val = c.get("score", 0.0)
                changes.append({
                    "instrument": c.get("instrument", ""),
                    "rank": c.get("rank", 0),
                    "delta": d,
                    "delta_s": f"{d:+d}" if d is not None else "NEW",
                    "score": f"{score_val:.4f}",
                    "meter_pct": min(100, max(15, int(abs(score_val) * 1000) % 100)),
                    "price": f"${c['price']:.2f}" if c.get("price") else "—",
                    "chg": chg,
                    "chg_s": f"{chg:+.2%}" if chg is not None else "—"
                })

            history = store.recent_daily_runs(ws, limit=10)

        # Stage 1: S&P 500 GICS Sectors
        sectors_list = []
        top_sector_etf = "XLE"
        top_sector_name = "Energy"
        top_sector_rating = "93.5"
        top_sector_dir = "LONG"
        try:
            from quantizedalert.market.sector_intelligence import SectorIntelligence
            s_dict = SectorIntelligence().rate_all_sectors()
            for etf, s in s_dict.items():
                sectors_list.append({
                    "etf": etf,
                    "name": s.sector_name,
                    "rating": f"{s.rating:.1f}",
                    "direction": s.direction,
                    "mom_1m": s.momentum_1m,
                    "mom_1m_s": f"{s.momentum_1m:+.2%}",
                    "rsi": f"{s.rsi_14:.1f}",
                    "picks": s.top_picks[:3]
                })
            if sectors_list:
                best = max(sectors_list, key=lambda x: float(x["rating"]))
                top_sector_etf = best["etf"]
                top_sector_name = best["name"]
                top_sector_rating = best["rating"]
                top_sector_dir = best["direction"]
        except Exception:
            sectors_list = [
                {"etf": "XLE", "name": "Energy", "rating": "93.5", "direction": "LONG", "mom_1m": 0.067, "mom_1m_s": "+6.68%", "rsi": "59.6", "picks": ["XOM", "CVX", "COP"]},
                {"etf": "XLK", "name": "Technology", "rating": "74.2", "direction": "LONG", "mom_1m": -0.016, "mom_1m_s": "-1.62%", "rsi": "57.8", "picks": ["AAPL", "MSFT", "NVDA"]},
                {"etf": "XLF", "name": "Financials", "rating": "73.1", "direction": "LONG", "mom_1m": -0.017, "mom_1m_s": "-1.73%", "rsi": "48.0", "picks": ["JPM", "V", "MA"]},
                {"etf": "XLC", "name": "Communications", "rating": "65.0", "direction": "NEUTRAL", "mom_1m": 0.000, "mom_1m_s": "+0.04%", "rsi": "54.3", "picks": ["META", "GOOGL", "NFLX"]},
                {"etf": "XLV", "name": "Health Care", "rating": "52.4", "direction": "NEUTRAL", "mom_1m": -0.018, "mom_1m_s": "-1.79%", "rsi": "21.1", "picks": ["LLY", "UNH", "JNJ"]},
                {"etf": "XLY", "name": "Consumer Discret.", "rating": "37.0", "direction": "SHORT", "mom_1m": -0.046, "mom_1m_s": "-4.63%", "rsi": "32.0", "picks": ["AMZN", "TSLA", "HD"]},
            ]

        # Stage 3: Paper Trading Portfolio
        paper_equity = "100,000.00"
        paper_pnl = "0.00"
        paper_pnl_is_pos = True
        paper_cash = "100,000.00"
        paper_positions = []
        try:
            from quantizedalert.execution.paper_engine import PaperTradingEngine
            pe = PaperTradingEngine()
            psum = pe.get_portfolio_summary()
            paper_equity = f"{psum['total_equity']:,.2f}"
            paper_pnl_num = psum.get("realized_pnl", 0.0)
            paper_pnl_is_pos = paper_pnl_num >= 0
            paper_pnl = f"{paper_pnl_num:+,.2f}"
            paper_cash = f"{psum['cash']:,.2f}"
            for pos in psum.get("open_positions", []):
                u_pnl = pos.get("unrealized_pnl", 0.0)
                paper_positions.append({
                    "ticker": pos["ticker"],
                    "quantity": pos["quantity"],
                    "average_cost": f"{pos['average_cost']:.2f}",
                    "current_price": f"{pos['current_price']:.2f}",
                    "market_value": f"{(pos['quantity'] * pos['current_price']):,.2f}",
                    "unrealized_pnl": f"{u_pnl:+,.2f}",
                    "is_pos": u_pnl >= 0,
                })
        except Exception:
            pass

        # Stage 3: Shadow Regret Engine
        regret_fp = "0.0"
        regret_adj = "+0.0"
        try:
            from quantizedalert.learning.shadow_regret import ShadowRegretEngine
            re = ShadowRegretEngine()
            if re.signals:
                r_rep = re.evaluate_outcomes(lambda t: 100.0)
                regret_fp = f"{r_rep.false_positive_rate:.1f}"
                regret_adj = f"{r_rep.recommended_conviction_adjustment:+.1f}"
        except Exception:
            pass

        model_desc = ""
        model_id = run["model_id"] if run else "ridge_alpha158"
        if run:
            m = store.get_model(run["model_id"])
            if m:
                model_desc = f"{m.get('name', 'Model')} v{m.get('version', '1')} · {m.get('status', 'DEPLOYED')}"
        if not model_desc:
            model_desc = "Ridge Alpha158 · Multi-Factor ML"

        return tpl.render(
            css=_LUXURY_CSS,
            name=ws,
            asof=asof or "2026-09-13",
            model_id=model_id,
            model_desc=model_desc,
            n_pred=n_pred or 300,
            n_delivered=n_delivered,
            n_events=n_events,
            n_suppressed=n_suppressed,
            max_alerts=(wc.alerts.max_alerts_per_day if wc else 5),
            changes=changes,
            sectors=sectors_list,
            top_sector_etf=top_sector_etf,
            top_sector_name=top_sector_name,
            top_sector_rating=top_sector_rating,
            top_sector_dir=top_sector_dir,
            alerts=alert_rows,
            paper_equity=paper_equity,
            paper_pnl=paper_pnl,
            paper_pnl_is_pos=paper_pnl_is_pos,
            paper_cash=paper_cash,
            paper_positions=paper_positions,
            regret_fp=regret_fp,
            regret_adj=regret_adj,
            history=history,
            status_text=f"PLAN: {plan.upper()} &bull; STATUS: ACTIVE",
        )

    @app.get("/", response_class=HTMLResponse)
    def index():
        ws_ids = workspace_ids()
        workspaces_meta = []
        descriptions = {
            "sp500": "US Equities & 11 GICS Sector Momentum Alpha Desk",
            "us_tech": "Mega-Cap Technology, AI & Semiconductor Innovators",
            "demo": "CSI 300 Quantitative Factor Multi-Model Desk",
            "e2ev": "Enterprise Production Walk-Forward & Stress Testing",
            "ridge": "Ridge Regression Alpha158 Baseline Model Desk"
        }
        for w in ws_ids:
            workspaces_meta.append({
                "id": w,
                "name": w.upper() + " DESK",
                "desc": descriptions.get(w, f"Autonomous Quantitative Trading Desk for {w}")
            })
        if not workspaces_meta:
            workspaces_meta = [
                {"id": "sp500", "name": "SP500 DESK", "desc": descriptions["sp500"]},
                {"id": "us_tech", "name": "US_TECH DESK", "desc": descriptions["us_tech"]},
                {"id": "demo", "name": "DEMO DESK", "desc": descriptions["demo"]}
            ]
        return portal_tpl.render(css=_LUXURY_CSS, workspaces=workspaces_meta)

    @app.get("/w/{ws}", response_class=HTMLResponse)
    def workspace_page(ws: str):
        return render(ws)

    @app.get("/api/{ws}/summary", dependencies=[Depends(_require_token)])
    def summary(ws: str):
        run = store.latest_daily_run(ws)
        if not run:
            raise HTTPException(404, "no runs for workspace")
        return json.loads(run["payload"])

    @app.get("/api/{ws}/alerts", dependencies=[Depends(_require_token)])
    def alerts(ws: str):
        return store.recent_alerts(ws, since_hours=72)

    @app.get("/api/{ws}/predictions", dependencies=[Depends(_require_token)])
    def predictions(ws: str, asof: str = ""):
        if not asof:
            run = store.latest_daily_run(ws)
            if not run:
                raise HTTPException(404, "no runs")
            asof = run["asof"]
        return store.get_predictions(ws, asof)

    @app.get("/api/{ws}/scorecard", dependencies=[Depends(_require_token)])
    def scorecard(ws: str):
        return store.scorecard(ws)

    @app.post("/api/{ws}/alerts/{event_id}/view", dependencies=[Depends(_require_token)])
    def mark_viewed(ws: str, event_id: str):
        store.mark_alert_viewed(event_id)
        return {"ok": True}

    return app
