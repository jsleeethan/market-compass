#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
마켓 나침반 (Market Compass) — 리포트 빌더
data.json -> docs/index.html (+ docs/archive/<date>.html + docs/archive/index.html)

표준 라이브러리만 사용 (pip 의존성 없음). 히트맵은 순수 SVG/CSS 트리맵으로 직접 계산.

사용법:
    python3 build_report.py [data.json]     # 기본값: data.json (없으면 sample_data.json)
"""

import sys
import os
import re
import json
import html
import glob

ROOT = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(ROOT, "docs")
ARCHIVE = os.path.join(DOCS, "archive")

UP = "#1ed98a"
DOWN = "#ff5468"
NEUTRAL = "#f0b24a"

TAG_COLORS = {
    "강세": UP,
    "약세": DOWN,
    "중립": NEUTRAL,
    "혼조": NEUTRAL,
    "고변동": NEUTRAL,
}


# ---------------------------------------------------------------- helpers
def esc(s):
    return html.escape(str(s), quote=True)


def fmt_pct(p):
    try:
        p = float(p)
    except (TypeError, ValueError):
        return ""
    sign = "+" if p > 0 else ""
    return "{}{:.2f}%".format(sign, p)


def arrow(p):
    try:
        p = float(p)
    except (TypeError, ValueError):
        return "·"
    if p > 0:
        return "▲"
    if p < 0:
        return "▼"
    return "▬"


def pct_class(p):
    try:
        p = float(p)
    except (TypeError, ValueError):
        return "flat"
    if p > 0:
        return "up"
    if p < 0:
        return "down"
    return "flat"


def chip(p):
    cls = pct_class(p)
    return '<span class="chip {c}">{a} {v}</span>'.format(
        c=cls, a=arrow(p), v=esc(fmt_pct(p))
    )


def _hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def _rgb_to_hex(rgb):
    return "#{:02x}{:02x}{:02x}".format(*(max(0, min(255, int(round(c)))) for c in rgb))


def _lerp(a, b, t):
    ca, cb = _hex_to_rgb(a), _hex_to_rgb(b)
    return _rgb_to_hex(tuple(ca[i] + (cb[i] - ca[i]) * t for i in range(3)))


def color_for_pct(p):
    """finviz 스타일: 상승 녹색 / 하락 적색 그라데이션, 보합 회색."""
    try:
        p = float(p)
    except (TypeError, ValueError):
        p = 0.0
    x = max(-3.0, min(3.0, p))
    if x > 0.05:
        return _lerp("#163a2a", "#1ed98a", x / 3.0)
    if x < -0.05:
        return _lerp("#3a1622", "#ff5468", -x / 3.0)
    return "#2a2f3a"


# ---------------------------------------------------------------- squarified treemap
# Bruls, Huizing & van Wijk (2000) — pure-python port.
def _normalize(sizes, area):
    total = float(sum(sizes)) or 1.0
    return [s * area / total for s in sizes]


def _layout_row(sizes, x, y, dy):
    covered = sum(sizes)
    width = covered / dy if dy else 0
    rects, yy = [], y
    for s in sizes:
        h = s / width if width else 0
        rects.append({"x": x, "y": yy, "dx": width, "dy": h})
        yy += h
    return rects


def _layout_col(sizes, x, y, dx):
    covered = sum(sizes)
    height = covered / dx if dx else 0
    rects, xx = [], x
    for s in sizes:
        w = s / height if height else 0
        rects.append({"x": xx, "y": y, "dx": w, "dy": height})
        xx += w
    return rects


def _layout(sizes, x, y, dx, dy):
    return _layout_row(sizes, x, y, dy) if dx >= dy else _layout_col(sizes, x, y, dx)


def _leftover(sizes, x, y, dx, dy):
    covered = sum(sizes)
    if dx >= dy:
        w = covered / dy if dy else 0
        return (x + w, y, dx - w, dy)
    h = covered / dx if dx else 0
    return (x, y + h, dx, dy - h)


def _worst(sizes, x, y, dx, dy):
    rects = _layout(sizes, x, y, dx, dy)
    worst = 0.0
    for r in rects:
        if r["dx"] <= 0 or r["dy"] <= 0:
            return float("inf")
        worst = max(worst, r["dx"] / r["dy"], r["dy"] / r["dx"])
    return worst


def squarify(sizes, x, y, dx, dy):
    sizes = [float(s) for s in sizes if s > 0]
    if not sizes:
        return []
    if len(sizes) == 1:
        return [{"x": x, "y": y, "dx": dx, "dy": dy}]
    i = 1
    while i < len(sizes) and _worst(sizes[:i], x, y, dx, dy) >= _worst(
        sizes[: i + 1], x, y, dx, dy
    ):
        i += 1
    current, remaining = sizes[:i], sizes[i:]
    lx, ly, ldx, ldy = _leftover(current, x, y, dx, dy)
    return _layout(current, x, y, dx, dy) + squarify(remaining, lx, ly, ldx, ldy)


def render_treemap(heatmap, W=1080, H=560, gap=3, header_h=22):
    """2단 트리맵: 섹터별 영역 분할 -> 섹터 내 종목 타일."""
    sectors = []
    for sec in heatmap or []:
        stocks = [s for s in sec.get("stocks", []) if (s.get("weight") or 0) > 0]
        if not stocks:
            continue
        total = sum(float(s["weight"]) for s in stocks)
        sectors.append({"sector": sec.get("sector", ""), "stocks": stocks, "total": total})
    if not sectors:
        return '<div class="treemap-empty">데이터 없음</div>'

    sectors.sort(key=lambda s: s["total"], reverse=True)
    sec_sizes = _normalize([s["total"] for s in sectors], W * H)
    sec_rects = squarify(sec_sizes, 0, 0, W, H)

    parts = ['<svg viewBox="0 0 {} {}" class="treemap" preserveAspectRatio="xMidYMid meet" role="img" aria-label="시장 히트맵">'.format(W, H)]
    parts.append('<rect x="0" y="0" width="{}" height="{}" fill="#0a0c10"/>'.format(W, H))

    for sec, rect in zip(sectors, sec_rects):
        sx = rect["x"] + gap / 2
        sy = rect["y"] + gap / 2
        sw = max(0.0, rect["dx"] - gap)
        sh = max(0.0, rect["dy"] - gap)
        if sw < 6 or sh < 6:
            continue
        # 섹터 헤더 밴드
        hh = min(header_h, sh * 0.5)
        parts.append('<rect x="{:.1f}" y="{:.1f}" width="{:.1f}" height="{:.1f}" fill="#11151c"/>'.format(sx, sy, sw, hh))
        if sw > 46:
            parts.append('<text x="{:.1f}" y="{:.1f}" class="tm-sector">{}</text>'.format(
                sx + 7, sy + hh - 7, esc(sec["sector"])))
        # 종목 타일 영역
        bx, by = sx, sy + hh
        bw, bh = sw, max(0.0, sh - hh)
        if bw < 4 or bh < 4:
            continue
        stocks = sorted(sec["stocks"], key=lambda s: float(s["weight"]), reverse=True)
        sizes = _normalize([float(s["weight"]) for s in stocks], bw * bh)
        trects = squarify(sizes, bx, by, bw, bh)
        for st, tr in zip(stocks, trects):
            tx = tr["x"] + gap / 2
            ty = tr["y"] + gap / 2
            tw = max(0.0, tr["dx"] - gap)
            th = max(0.0, tr["dy"] - gap)
            if tw < 3 or th < 3:
                continue
            fill = color_for_pct(st.get("change_pct", 0))
            parts.append('<rect x="{:.1f}" y="{:.1f}" width="{:.1f}" height="{:.1f}" rx="2" fill="{}"/>'.format(tx, ty, tw, th, fill))
            cx = tx + tw / 2
            cy = ty + th / 2
            if tw >= 42 and th >= 26:
                parts.append('<text x="{:.1f}" y="{:.1f}" class="tm-tic">{}</text>'.format(cx, cy - 2, esc(st["ticker"])))
                if th >= 40:
                    parts.append('<text x="{:.1f}" y="{:.1f}" class="tm-pct">{}</text>'.format(cx, cy + 13, esc(fmt_pct(st.get("change_pct", 0)))))
            elif tw >= 26 and th >= 14:
                parts.append('<text x="{:.1f}" y="{:.1f}" class="tm-tic sm">{}</text>'.format(cx, cy + 3, esc(st["ticker"])))
    parts.append("</svg>")
    return "".join(parts)


# ---------------------------------------------------------------- section renderers
def render_index_table(rows, extra=False):
    out = ['<table class="idx">']
    for r in rows:
        note = ""
        if extra and r.get("note"):
            note = '<span class="note">{}</span>'.format(esc(r["note"]))
        out.append(
            '<tr><td class="idx-name">{name}{note}</td>'
            '<td class="idx-val">{val}</td>'
            '<td class="idx-chg">{chip}</td></tr>'.format(
                name=esc(r["name"]), note=note, val=esc(r.get("value", "")),
                chip=chip(r.get("change_pct", 0)),
            )
        )
    out.append("</table>")
    return "".join(out)


def render_movers(items, direction):
    icon = "🔼" if direction == "up" else "🔽"
    title = "상승" if direction == "up" else "하락"
    out = ['<div class="movers-col"><h3 class="movers-h {d}">{i} {t}</h3>'.format(d=direction, i=icon, t=title)]
    for m in items or []:
        out.append(
            '<div class="mover">'
            '<div class="mover-top"><span class="mover-name">{name}'
            '<span class="mover-tic">{tic}</span></span>{chip}</div>'
            '<div class="mover-reason">{reason}</div></div>'.format(
                name=esc(m.get("name_kr", "")), tic=esc(m.get("ticker", "")),
                chip=chip(m.get("change_pct", 0)), reason=esc(m.get("reason", "")),
            )
        )
    out.append("</div>")
    return "".join(out)


def render_themes(themes):
    out = ['<div class="themes">']
    for t in themes or []:
        tag = t.get("tag", "중립")
        color = TAG_COLORS.get(tag, NEUTRAL)
        out.append(
            '<div class="theme-card" style="--bar:{color}">'
            '<div class="theme-head"><span class="theme-name">{name}</span>'
            '<span class="theme-tag" style="color:{color};border-color:{color}">{tag}</span></div>'
            '<div class="theme-comment">{comment}</div></div>'.format(
                color=color, name=esc(t.get("name", "")), tag=esc(tag),
                comment=esc(t.get("comment", "")),
            )
        )
    out.append("</div>")
    return "".join(out)


def render_macro(macro):
    labels = [
        ("ust10y", "금리"), ("fed", "연준"), ("usdkrw", "환율"),
        ("wti", "유가"), ("kospi", "코스피"),
    ]
    out = ['<div class="macro">']
    for key, label in labels:
        if macro.get(key):
            out.append(
                '<div class="macro-row"><span class="macro-label">{l}</span>'
                '<span class="macro-text">{t}</span></div>'.format(
                    l=esc(label), t=esc(macro[key])))
    out.append("</div>")
    return "".join(out)


def render_schedule(sch):
    cols = [("today", "오늘"), ("this_week", "이번 주"), ("this_month", "이번 달")]
    out = ['<div class="schedule">']
    for key, label in cols:
        items = sch.get(key, []) or []
        lis = "".join("<li>{}</li>".format(esc(x)) for x in items) or "<li class='muted'>—</li>"
        out.append(
            '<div class="sch-col"><h4>{l}</h4><ul>{lis}</ul></div>'.format(l=esc(label), lis=lis))
    out.append("</div>")
    return "".join(out)


# ---------------------------------------------------------------- page
CSS = """
:root{--up:#1ed98a;--down:#ff5468;--neutral:#f0b24a;--bg:#0a0c10;--panel:#12151c;
--panel2:#171b24;--line:#232936;--text:#e8edf5;--muted:#8a93a6;--mono:'JetBrains Mono',monospace;}
*{box-sizing:border-box;}
body{margin:0;background:radial-gradient(1200px 600px at 50% -200px,#16203a 0%,var(--bg) 60%);
color:var(--text);font-family:'Noto Sans KR','Inter',sans-serif;line-height:1.55;
-webkit-font-smoothing:antialiased;}
.wrap{max-width:1140px;margin:0 auto;padding:24px 18px 60px;}
.hero{position:relative;border-radius:20px;padding:34px 32px;margin-bottom:26px;overflow:hidden;
background:linear-gradient(120deg,#1b2a55 0%,#243b7a 40%,#1f6f6a 100%);
box-shadow:0 20px 50px -20px rgba(0,0,0,.7);}
.hero::after{content:"";position:absolute;inset:0;background:radial-gradient(600px 200px at 90% 0,rgba(255,255,255,.10),transparent);}
.hero-top{display:flex;align-items:center;gap:14px;}
.hero-ico{font-size:42px;filter:drop-shadow(0 4px 10px rgba(0,0,0,.4));}
.hero-title{font-weight:800;font-size:30px;letter-spacing:-.5px;line-height:1.1;}
.hero-title small{display:block;font-family:var(--mono);font-weight:600;font-size:13px;
letter-spacing:4px;color:#cfe0ff;margin-top:4px;}
.hero-meta{display:flex;justify-content:space-between;align-items:flex-end;margin-top:22px;flex-wrap:wrap;gap:10px;}
.hero-date{font-size:18px;font-weight:700;}
.tag{font-family:var(--mono);font-size:12px;font-weight:700;letter-spacing:2px;
background:rgba(0,0,0,.28);border:1px solid rgba(255,255,255,.18);padding:6px 12px;border-radius:999px;}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:18px;}
.card{background:linear-gradient(180deg,var(--panel),var(--panel2));border:1px solid var(--line);
border-radius:16px;padding:20px 22px;margin-bottom:18px;position:relative;
box-shadow:0 10px 30px -22px rgba(0,0,0,.9);}
.card::before{content:"";position:absolute;left:0;top:16px;bottom:16px;width:4px;border-radius:4px;
background:linear-gradient(180deg,var(--up),#2aa6ff);}
.card.full{grid-column:1/-1;}
h2.sec{font-size:15px;font-weight:800;letter-spacing:.5px;margin:0 0 14px;color:#fff;
display:flex;align-items:center;gap:8px;}
h2.sec .en{font-family:var(--mono);font-size:11px;color:var(--muted);font-weight:600;letter-spacing:2px;}
.chip{font-family:var(--mono);font-weight:700;font-size:12.5px;padding:2px 8px;border-radius:7px;white-space:nowrap;}
.chip.up{color:var(--up);background:rgba(30,217,138,.12);}
.chip.down{color:var(--down);background:rgba(255,84,104,.12);}
.chip.flat{color:var(--neutral);background:rgba(240,178,74,.12);}
table.idx{width:100%;border-collapse:collapse;}
table.idx td{padding:9px 4px;border-bottom:1px solid var(--line);vertical-align:middle;}
table.idx tr:last-child td{border-bottom:none;}
.idx-name{font-weight:600;font-size:14px;}
.idx-name .note{display:block;font-size:11px;color:var(--muted);font-weight:500;margin-top:2px;}
.idx-val{font-family:var(--mono);text-align:right;font-size:15px;font-weight:600;}
.idx-chg{text-align:right;width:90px;}
.treemap{width:100%;height:auto;border-radius:10px;display:block;}
.tm-sector{fill:#aeb8cc;font:700 12px 'Noto Sans KR',sans-serif;}
.tm-tic{fill:#fff;font:700 14px var(--mono);text-anchor:middle;dominant-baseline:middle;}
.tm-tic.sm{font-size:10px;}
.tm-pct{fill:rgba(255,255,255,.85);font:600 11px var(--mono);text-anchor:middle;dominant-baseline:middle;}
.tm-cap{font-size:11.5px;color:var(--muted);margin-top:10px;}
.tm-cap a{color:#7fb4ff;text-decoration:none;}
.movers{display:grid;grid-template-columns:1fr 1fr;gap:20px;}
.movers-h{font-size:13px;margin:0 0 10px;font-weight:800;letter-spacing:.5px;}
.movers-h.up{color:var(--up);}
.movers-h.down{color:var(--down);}
.mover{padding:10px 0;border-bottom:1px dashed var(--line);}
.mover:last-child{border-bottom:none;}
.mover-top{display:flex;justify-content:space-between;align-items:center;gap:8px;}
.mover-name{font-weight:700;font-size:14px;}
.mover-tic{font-family:var(--mono);font-size:11px;color:var(--muted);margin-left:6px;}
.mover-reason{font-size:12.5px;color:#c3cbd9;margin-top:3px;}
.themes{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px;}
.theme-card{background:var(--panel2);border:1px solid var(--line);border-left:3px solid var(--bar);
border-radius:11px;padding:12px 14px;transition:transform .15s ease,box-shadow .15s ease;}
.theme-card:hover{transform:translateY(-2px);box-shadow:0 12px 24px -16px rgba(0,0,0,.8);}
.theme-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:5px;}
.theme-name{font-weight:700;font-size:14px;}
.theme-tag{font-size:11px;font-weight:700;border:1px solid;padding:1px 8px;border-radius:999px;}
.theme-comment{font-size:12.5px;color:#c3cbd9;}
.macro{display:flex;flex-direction:column;gap:2px;}
.macro-row{display:flex;gap:14px;padding:9px 2px;border-bottom:1px solid var(--line);align-items:baseline;}
.macro-row:last-child{border-bottom:none;}
.macro-label{flex:0 0 56px;font-weight:700;font-size:12px;color:var(--neutral);letter-spacing:1px;}
.macro-text{font-size:13.5px;color:#dbe2ee;}
.schedule{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;}
.sch-col h4{margin:0 0 8px;font-size:13px;font-weight:800;color:#fff;
border-bottom:2px solid var(--line);padding-bottom:6px;}
.sch-col ul{margin:0;padding-left:0;list-style:none;}
.sch-col li{font-size:12.5px;color:#c8d0de;padding:5px 0 5px 14px;position:relative;}
.sch-col li::before{content:"›";position:absolute;left:0;color:var(--neutral);}
.sch-col li.muted{color:var(--muted);}
.footer{margin-top:30px;text-align:center;color:var(--muted);font-size:12px;line-height:1.7;}
.footer .sign{margin-top:10px;font-weight:700;color:#aeb8cc;}
.footer a{color:#7fb4ff;text-decoration:none;}
.footer .src{margin-top:6px;}
@media(max-width:760px){.grid2,.movers,.schedule{grid-template-columns:1fr;}
.hero-title{font-size:24px;}.wrap{padding:16px 12px 40px;}}
"""


def build_page(d):
    treemap = render_treemap(d.get("heatmap", []))
    macro = d.get("macro", {}) or {}
    sch = d.get("schedule", {}) or {}
    sources = d.get("sources", []) or []
    src_html = " · ".join(
        '<a href="{u}" target="_blank" rel="noopener">{t}</a>'.format(u=esc(s.get("url", "#")), t=esc(s.get("title", "")))
        for s in sources
    )

    head = """<!doctype html>
<html lang="ko"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>🧭 마켓 나침반 · {date}</title>
<meta name="description" content="마켓 나침반 — 매일 오전 7시 자동 생성 모닝 마켓 브리핑 ({date})">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&family=JetBrains+Mono:wght@500;600;700&family=Noto+Sans+KR:wght@400;500;700;800&display=swap" rel="stylesheet">
<style>{css}</style>
</head><body><div class="wrap">""".format(date=esc(d.get("date_display", d.get("date", ""))), css=CSS)

    hero = """
<header class="hero">
  <div class="hero-top">
    <div class="hero-ico">🧭</div>
    <div class="hero-title">마켓 나침반<small>MARKET COMPASS</small></div>
  </div>
  <div class="hero-meta">
    <div class="hero-date">{date}</div>
    <div class="tag">DAILY · 07:00 KST</div>
  </div>
</header>""".format(date=esc(d.get("date_display", d.get("date", ""))))

    indices = """
<div class="grid2">
  <section class="card"><h2 class="sec">미국 3대 지수 <span class="en">US INDICES</span></h2>{a}</section>
  <section class="card"><h2 class="sec">반도체·한국·신흥국 <span class="en">SOX · KOREA · EM</span></h2>{b}</section>
</div>""".format(
        a=render_index_table(d.get("indices_us", [])),
        b=render_index_table(d.get("indices_extra", []), extra=True),
    )

    heatmap = """
<section class="card full"><h2 class="sec">전체 시장 히트맵 <span class="en">MARKET HEATMAP</span></h2>
{tm}
<div class="tm-cap">시총 가중 트리맵 · 녹색=상승 / 적색=하락 · 라이브: <a href="https://finviz.com/map.ashx" target="_blank" rel="noopener">finviz.com/map</a></div>
</section>""".format(tm=treemap)

    movers = """
<section class="card full"><h2 class="sec">주요 종목 <span class="en">TOP MOVERS</span></h2>
<div class="movers">{up}{down}</div></section>""".format(
        up=render_movers(d.get("movers_up", []), "up"),
        down=render_movers(d.get("movers_down", []), "down"),
    )

    themes = """
<section class="card full"><h2 class="sec">테마별 섹터 코멘트 <span class="en">7 THEMES</span></h2>
{t}</section>""".format(t=render_themes(d.get("themes", [])))

    macro_html = """
<section class="card full"><h2 class="sec">경제 · 금리 · 환율 <span class="en">MACRO</span></h2>
{m}</section>""".format(m=render_macro(macro))

    schedule = """
<section class="card full"><h2 class="sec">주목할 일정 <span class="en">CALENDAR</span></h2>
{s}</section>""".format(s=render_schedule(sch))

    footer = """
<footer class="footer">
  <div>{disc}</div>
  <div class="src">출처: {src}</div>
  <div class="sign">🧭 마켓 나침반 · 매일 오전 7시 자동 생성</div>
</footer>""".format(disc=esc(d.get("disclaimer", "")), src=src_html or "—")

    return head + hero + indices + heatmap + movers + themes + macro_html + schedule + footer + "</div></body></html>"


def build_archive_index():
    files = sorted(glob.glob(os.path.join(ARCHIVE, "*.html")), reverse=True)
    rows = []
    for f in files:
        name = os.path.basename(f)
        if name == "index.html":
            continue
        date = name[:-5]
        rows.append('<li><a href="{n}">{d}</a></li>'.format(n=esc(name), d=esc(date)))
    body = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>마켓 나침반 · 지난 리포트</title>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;700;800&display=swap" rel="stylesheet">
<style>body{{background:#0a0c10;color:#e8edf5;font-family:'Noto Sans KR',sans-serif;max-width:680px;margin:0 auto;padding:40px 20px;}}
h1{{font-size:22px;}}a{{color:#7fb4ff;text-decoration:none;}}ul{{list-style:none;padding:0;}}
li{{padding:10px 0;border-bottom:1px solid #232936;font-family:'JetBrains Mono',monospace;}}
.back{{display:inline-block;margin-bottom:20px;}}</style></head><body>
<a class="back" href="../index.html">← 최신 리포트</a>
<h1>🧭 지난 리포트</h1><ul>{rows}</ul></body></html>""".format(rows="".join(rows) or "<li>아직 없음</li>")
    with open(os.path.join(ARCHIVE, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(body)


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else None
    if not src:
        src = "data.json" if os.path.exists(os.path.join(ROOT, "data.json")) else "sample_data.json"
    src_path = src if os.path.isabs(src) else os.path.join(ROOT, src)
    with open(src_path, encoding="utf-8") as f:
        data = json.load(f)

    os.makedirs(ARCHIVE, exist_ok=True)
    page = build_page(data)

    with open(os.path.join(DOCS, "index.html"), "w", encoding="utf-8") as f:
        f.write(page)

    date = str(data.get("date", "")).strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        with open(os.path.join(ARCHIVE, date + ".html"), "w", encoding="utf-8") as f:
            f.write(page)

    build_archive_index()
    print("built: docs/index.html ({} bytes)".format(len(page.encode("utf-8"))))
    if date:
        print("archived: docs/archive/{}.html".format(date))


if __name__ == "__main__":
    main()
