#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
마켓 나침반 (Market Compass) — 리포트 빌더 (v2: editorial dark theme)
data.json -> docs/index.html (+ docs/archive/<date>.html + docs/archive/index.html)

표준 라이브러리만 사용 (pip 의존성 없음). 히트맵은 순수 SVG 트리맵으로 직접 계산.

사용법:
    python3 build_report.py [data.json]     # 기본값: data.json (없으면 sample_data.json)
"""

import sys
import os
import re
import json
import html
import glob
import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(ROOT, "docs")
ARCHIVE = os.path.join(DOCS, "archive")

WEEK = ["월", "화", "수", "목", "금", "토", "일"]
THEME_ICON = {
    "반도체": "🧠", "자동차": "🚗", "2차전지": "🔋", "대형기술주": "💻",
    "소프트웨어": "⚙️", "양자컴퓨터": "⚛️", "비트코인": "₿", "국내증시 종합": "🇰🇷",
    "국내증시": "🇰🇷", "에너지": "🛢️", "금융": "🏦", "헬스케어": "💊",
}
MACRO_META = {
    "ust10y": ("🏦", "미 10년물 국채금리"),
    "fed": ("🪙", "연준 · FOMC"),
    "usdkrw": ("💱", "원/달러 환율"),
    "wti": ("🛢️", "WTI 유가"),
    "kospi": ("📉", "코스피 동향"),
}


# ---------------------------------------------------------------- helpers
def esc(s):
    return html.escape(str(s), quote=True)


def to_float(p, default=0.0):
    try:
        return float(p)
    except (TypeError, ValueError):
        return default


def fmt_pct(p):
    if p is None or (isinstance(p, str) and not p.strip()):
        return ""
    v = to_float(p, None)
    if v is None:
        return esc(p)
    return "{}{:.2f}%".format("+" if v > 0 else "", v)


def arrow(p):
    v = to_float(p, 0.0)
    return "▲" if v > 0 else ("▼" if v < 0 else "▬")


def dir_of(p):
    v = to_float(p, 0.0)
    return "up" if v > 0 else ("down" if v < 0 else "neu")


def weekday_kr(iso):
    try:
        y, m, d = map(int, str(iso).split("-"))
        return WEEK[datetime.date(y, m, d).weekday()]
    except Exception:
        return ""


def _hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def _rgb_to_hex(rgb):
    return "#{:02x}{:02x}{:02x}".format(*(max(0, min(255, int(round(c)))) for c in rgb))


def _lerp(a, b, t):
    ca, cb = _hex_to_rgb(a), _hex_to_rgb(b)
    return _rgb_to_hex(tuple(ca[i] + (cb[i] - ca[i]) * t for i in range(3)))


# finviz 스타일 컬러 스케일 (적색 -> 회색 -> 녹색)
_SCALE = [
    (-3.0, "#b3261e"), (-1.5, "#a13d36"), (-0.5, "#7a4d4a"),
    (0.0, "#414b56"), (0.8, "#3f6f5b"), (2.5, "#2f9d6c"), (5.0, "#16c47e"),
]


def color_for_pct(p):
    v = max(-3.0, min(5.0, to_float(p, 0.0)))
    for i in range(len(_SCALE) - 1):
        lo, lc = _SCALE[i]
        hi, hc = _SCALE[i + 1]
        if lo <= v <= hi:
            t = (v - lo) / (hi - lo) if hi != lo else 0
            return _lerp(lc, hc, t)
    return _SCALE[-1][1] if v > 0 else _SCALE[0][1]


def tile_text_color(p):
    d = dir_of(p)
    return "#eafff5" if d == "up" else ("#ffe9ec" if d == "down" else "#e7ecf5")


# ---------------------------------------------------------------- squarified treemap
def _normalize(sizes, area):
    total = float(sum(sizes)) or 1.0
    return [s * area / total for s in sizes]


def _layout(sizes, x, y, dx, dy):
    covered = sum(sizes)
    rects = []
    if dx >= dy:
        width = covered / dy if dy else 0
        yy = y
        for s in sizes:
            h = s / width if width else 0
            rects.append({"x": x, "y": yy, "dx": width, "dy": h})
            yy += h
    else:
        height = covered / dx if dx else 0
        xx = x
        for s in sizes:
            w = s / height if height else 0
            rects.append({"x": xx, "y": y, "dx": w, "dy": height})
            xx += w
    return rects


def _leftover(sizes, x, y, dx, dy):
    covered = sum(sizes)
    if dx >= dy:
        w = covered / dy if dy else 0
        return (x + w, y, dx - w, dy)
    h = covered / dx if dx else 0
    return (x, y + h, dx, dy - h)


def _worst(sizes, x, y, dx, dy):
    worst = 0.0
    for r in _layout(sizes, x, y, dx, dy):
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
    while i < len(sizes) and _worst(sizes[:i], x, y, dx, dy) >= _worst(sizes[: i + 1], x, y, dx, dy):
        i += 1
    cur, rem = sizes[:i], sizes[i:]
    lx, ly, ldx, ldy = _leftover(cur, x, y, dx, dy)
    return _layout(cur, x, y, dx, dy) + squarify(rem, lx, ly, ldx, ldy)


def _svg_text(x, y, cls, fill, size, anchor, txt):
    return ('<text x="{:.1f}" y="{:.1f}" class="{}" fill="{}" font-size="{}" '
            'text-anchor="{}">{}</text>').format(x, y, cls, fill, size, anchor, esc(txt))


def render_treemap(heatmap, W=1000, H=520, gap=4, header_h=26):
    sectors = []
    for sec in heatmap or []:
        stocks = [s for s in sec.get("stocks", []) if to_float(s.get("weight"), 0) > 0]
        if not stocks:
            continue
        total = sum(to_float(s["weight"]) for s in stocks)
        wavg = sum(to_float(s["weight"]) * to_float(s.get("change_pct", 0)) for s in stocks) / (total or 1)
        sectors.append({"sector": sec.get("sector", ""), "stocks": stocks, "total": total, "wavg": wavg})
    if not sectors:
        return '<div style="color:#7c8493;padding:40px;text-align:center">히트맵 데이터 없음</div>'

    sectors.sort(key=lambda s: s["total"], reverse=True)
    sec_rects = squarify(_normalize([s["total"] for s in sectors], W * H), 0, 0, W, H)

    p = ['<svg class="heat-treemap" viewBox="0 0 {} {}" preserveAspectRatio="xMidYMid meet" role="img" aria-label="미국 증시 시가총액 가중 히트맵">'.format(W, H)]
    p.append('<rect x="0" y="0" width="{}" height="{}" fill="#05070c"/>'.format(W, H))

    for sec, r in zip(sectors, sec_rects):
        x = r["x"] + gap / 2
        y = r["y"] + gap / 2
        w = max(0.0, r["dx"] - gap)
        h = max(0.0, r["dy"] - gap)
        if w < 8 or h < 8:
            continue
        p.append('<g>')
        p.append('<rect x="{:.1f}" y="{:.1f}" width="{:.1f}" height="{:.1f}" fill="#0a0f18" stroke="#1c2536" stroke-width="2"/>'.format(x, y, w, h))
        hh = min(header_h, h * 0.42)
        if w > 60:
            p.append(_svg_text(x + 12, y + hh - 8, "tm-sechead", "#cdd6ea", 13, "start", sec["sector"]))
            wd = dir_of(sec["wavg"])
            wcol = "#1ed98a" if wd == "up" else ("#ff5468" if wd == "down" else "#f0b24a")
            p.append(_svg_text(x + w - 10, y + hh - 8, "tm-secsub", wcol, 10, "end",
                               "{} {}".format(arrow(sec["wavg"]), fmt_pct(sec["wavg"]))))
        bx, by = x + 2, y + hh
        bw, bh = w - 4, max(0.0, h - hh - 2)
        if bw < 6 or bh < 6:
            p.append('</g>')
            continue
        stocks = sorted(sec["stocks"], key=lambda s: to_float(s["weight"]), reverse=True)
        trects = squarify(_normalize([to_float(s["weight"]) for s in stocks], bw * bh), bx, by, bw, bh)
        for st, tr in zip(stocks, trects):
            tx = tr["x"] + gap / 2
            ty = tr["y"] + gap / 2
            tw = max(0.0, tr["dx"] - gap)
            th = max(0.0, tr["dy"] - gap)
            if tw < 4 or th < 4:
                continue
            cp = st.get("change_pct", 0)
            p.append('<rect class="tm-tile" x="{:.1f}" y="{:.1f}" width="{:.1f}" height="{:.1f}" rx="2" fill="{}"/>'.format(tx, ty, tw, th, color_for_pct(cp)))
            cx = tx + tw / 2
            cy = ty + th / 2
            tcol = tile_text_color(cp)
            if tw >= 50 and th >= 34:
                fs = 13 + min(11, (tw * th) / 2600)
                p.append(_svg_text(cx, cy - 3, "tm-tick", tcol, round(fs), "middle", st["ticker"]))
                p.append(_svg_text(cx, cy + round(fs) - 1, "tm-pct", tcol, round(fs * 0.66), "middle", fmt_pct(cp)))
            elif tw >= 30 and th >= 16:
                p.append(_svg_text(cx, cy + 4, "tm-tick", tcol, 12, "middle", st["ticker"]))
        p.append('</g>')
    p.append("</svg>")
    return "".join(p)


# ---------------------------------------------------------------- section renderers
def sec_head(num, title_html, en, sub):
    return ('<div class="sec-head"><div class="sec-num">{n}</div>'
            '<h2 class="sec-title">{t}</h2><div class="sec-en">{e}</div>'
            '<div class="sec-sub">{s}</div></div><div class="rule"></div>').format(
        n=num, t=title_html, e=esc(en), s=esc(sub))


def render_ticker(d):
    items = []
    short = {"DOW JONES": "DJIA", "S&P 500": "S&P 500", "NASDAQ": "NASDAQ"}
    for r in d.get("indices_us", []):
        cp = r.get("change_pct", 0)
        items.append((short.get(r["name"], r["name"]), "{} {}{}".format(esc(r.get("value", "")), arrow(cp), fmt_pct(cp).lstrip("+")), dir_of(cp)))
    for r in d.get("indices_extra", []):
        nm = re.sub(r"\s*\(.*?\)", "", r["name"])
        m = re.search(r"\(([^)]+)\)", r["name"])
        label = m.group(1) if m else nm[:8]
        cp = r.get("change_pct", 0)
        items.append((label, "{} {}".format(esc(r.get("value", "")), arrow(cp)), dir_of(cp)))
    for m in (d.get("movers_up", [])[:2] + d.get("movers_down", [])[:2]):
        cp = m.get("change_pct", 0)
        items.append((m.get("ticker", ""), "{}{}".format(arrow(cp), fmt_pct(cp).lstrip("+")), dir_of(cp)))
    run = "".join('<span><b>{l}</b><span class="{c}">{t}</span></span>'.format(l=esc(l), c=c, t=t) for l, t, c in items)
    return '<div class="strip" aria-hidden="true"><div class="run">{r}{r}</div></div>'.format(r=run)


def render_hero(d):
    date_disp = esc(d.get("date_display", d.get("date", "")))
    wd = weekday_kr(d.get("date", ""))
    wd_html = ' <span>({})</span>'.format(wd) if wd else ""
    us = d.get("indices_us", [])
    avg = sum(to_float(x.get("change_pct", 0)) for x in us) / (len(us) or 1)
    if avg > 0.3:
        senti_word, senti_dir, risk = "강세", "up", "RISK-ON · 위험선호"
    elif avg < -0.3:
        senti_word, senti_dir, risk = "약세", "down", "RISK-OFF · 경계 모드"
    else:
        senti_word, senti_dir, risk = "혼조", "neu", "MIXED · 방향 탐색"
    risk_cls = senti_dir

    pills = ['<span class="pill">미장 마감 <span class="v {d}">{w}</span></span>'.format(d=senti_dir, w=senti_word)]
    up0 = (d.get("movers_up") or [None])[0]
    if up0:
        pills.append('<span class="pill">{n} <span class="v up">▲ {p}</span></span>'.format(
            n=esc(up0.get("ticker", "")), p=esc(fmt_pct(up0.get("change_pct", 0)))))
    dn0 = (d.get("movers_down") or [None])[0]
    if dn0:
        pills.append('<span class="pill">{n} <span class="v down">▼ {p}</span></span>'.format(
            n=esc(dn0.get("ticker", "")), p=esc(fmt_pct(dn0.get("change_pct", 0)))))
    sidecar = ""
    for r in d.get("indices_extra", []):
        if "사이드카" in str(r.get("note", "")):
            sidecar = '<span class="sidecar-flag">⚠ {}</span>'.format(esc(re.sub(r"\s*\(.*?\)", "", r["name"]) + " 사이드카 발동"))
            break
    senti = '<span class="sentiment" style="{st}">{a} {r}</span>'.format(
        st=("" if risk_cls == "down" else "color:var(--{c});border-color:var(--{c});background:rgba(0,0,0,.18)".format(c={"up": "up", "neu": "neutral"}.get(risk_cls, "down"))),
        a=arrow(avg), r=esc(risk))

    return """<header class="hero"><div class="hero-in"><div class="hero-top">
<div class="brand"><div class="compass">🧭</div><div><h1>마켓 나침반</h1><div class="en">Market&nbsp;Compass</div></div></div>
<div class="hero-meta"><div class="hero-date">{date}{wd}</div><span class="tag"><span class="dot"></span>DAILY · 07:00 KST</span></div>
</div></div>
<div class="hero-strip">{pills}{sidecar}{senti}</div></header>""".format(
        date=date_disp, wd=wd_html, pills="".join(pills), sidecar=sidecar, senti=senti)


def render_idx_card(r, four=False):
    cp = r.get("change_pct", 0)
    d = dir_of(cp)
    name = r.get("name", "")
    m = re.search(r"^(.*?)\s*\(([^)]+)\)\s*$", name)
    if m:
        kr, sym = m.group(1).strip(), m.group(2).strip()
        nm = '{sym} <span class="kr">{kr}</span>'.format(sym=esc(sym), kr=esc(kr))
    else:
        nm = '<span class="kr">{}</span>'.format(esc(name))
    note = r.get("note", "")
    badge = ""
    if note:
        bcls = "est" if "추정" in note else ("alert" if "사이드카" in note else "note")
        badge = ' <span class="badge {c}">{n}</span>'.format(c=bcls, n=esc(note))
    chg = '{a} {p}{badge}'.format(a=arrow(cp), p=esc(fmt_pct(cp) or "—"), badge=badge)
    return ('<div class="idx {d}"><div class="nm">{nm}</div>'
            '<div class="val">{val}</div><div class="chg">{chg}</div></div>').format(
        d=d, nm=nm, val=esc(r.get("value", "")), chg=chg)


def render_indicators(d):
    us = "".join(render_idx_card(r) for r in d.get("indices_us", []))
    extra = "".join(render_idx_card(r, four=True) for r in d.get("indices_extra", []))
    return """<section class="sec">{head}
<div style="margin-top:24px"><p class="grp-label">A · 미국 3대 지수 <span class="kr">US Indices · 전일 종가</span></p>
<div class="idx-grid">{us}</div></div>
<div style="margin-top:22px"><p class="grp-label">B · 한국 · 반도체 · 신흥국 프록시 <span class="kr">Semis &amp; EM Proxies</span></p>
<div class="idx-grid four">{extra}</div></div></section>""".format(
        head=sec_head("01", '시장 <em>지표</em>', "Indicators", "간밤 미국 마감 · 한국 관련 자산"), us=us, extra=extra)


def render_heatmap(d):
    legend = ("<i style=\"background:#b3261e\"></i><i style=\"background:#c4453b\"></i>"
              "<i style=\"background:#7a4d4a\"></i><i style=\"background:#414b56\"></i>"
              "<i style=\"background:#3f6f5b\"></i><i style=\"background:#2f9d6c\"></i><i style=\"background:#16c47e\"></i>")
    return """<section class="sec">{head}
<div class="heat-card" style="margin-top:24px">
<div class="heat-legend"><span class="lbl">등락률</span><div class="heat-scale">{legend}</div>
<span class="down" style="font-size:11px;font-family:var(--mono)">−</span>
<span class="neu" style="font-size:11px;font-family:var(--mono)">0</span>
<span class="up" style="font-size:11px;font-family:var(--mono)">+</span>
<span class="sp"></span><span class="lbl">타일 크기 = 시가총액 비중 · 색상 = 등락률</span></div>
{tm}</div></section>""".format(
        head=sec_head("02", '전체 시장 <em>히트맵</em>', "Heatmap", "미국 증시 · 시가총액 가중 · finviz-style"),
        legend=legend, tm=render_treemap(d.get("heatmap", [])))


def render_mover_col(items, direction):
    ic = "🔼" if direction == "up" else "🔽"
    title = "상승 종목" if direction == "up" else "하락 종목"
    en = "Top Gainers" if direction == "up" else "Top Losers"
    rows = []
    for m in items or []:
        cp = m.get("change_pct", 0)
        reason = str(m.get("reason", "") or "").strip()
        why = '<div class="mv-why">{}</div>'.format(esc(reason)) if reason else ""
        rows.append("""<div class="mv-row"><span class="mv-pc">{p}</span>
<div class="mv-body"><div class="mv-name">{nm} <span class="tk">{tk}</span></div>{why}</div></div>""".format(
            p=esc(fmt_pct(cp)), nm=esc(m.get("name_kr", "")), tk=esc(m.get("ticker", "")), why=why))
    return """<div class="mv-col mv-{d}"><div class="mv-hd"><span class="ic">{ic}</span> {t} <span class="en">{en}</span></div>
{rows}</div>""".format(d=direction, ic=ic, t=title, en=en, rows="".join(rows))


def render_movers(d):
    return """<section class="sec">{head}
<div class="movers" style="margin-top:24px">{up}{down}</div></section>""".format(
        head=sec_head("03", '주요 <em>종목</em>', "Movers", "간밤 거래 기준 · 상승 🔼 / 하락 🔽"),
        up=render_mover_col(d.get("movers_up", []), "up"),
        down=render_mover_col(d.get("movers_down", []), "down"))


def render_themes(d):
    cmap = {"강세": "up", "약세": "down", "중립": "neu", "혼조": "neu", "고변동": "neu"}
    cards = []
    for t in d.get("themes", []):
        tag = t.get("tag", "중립")
        cc = cmap.get(tag, "neu")
        icon = THEME_ICON.get(t.get("name", ""), "📊")
        cards.append("""<div class="theme s-{cc}"><div class="th-ic">{icon}</div>
<div class="th-body"><div class="th-top"><span class="th-nm">{nm}</span><span class="chip {cc}">{tag}</span></div>
<div class="th-cmt">{cmt}</div></div></div>""".format(
            cc=cc, icon=icon, nm=esc(t.get("name", "")), tag=esc(tag), cmt=esc(t.get("comment", ""))))
    return """<section class="sec">{head}
<div class="themes" style="margin-top:24px">{cards}</div></section>""".format(
        head=sec_head("04", '테마별 <em>섹터</em> 코멘트', "Sectors", "핵심 테마 · 강세 / 약세 / 중립"),
        cards="".join(cards))


def _macro_items(macro):
    """구조화 리스트(신규) 또는 dict(구버전) 모두 처리해 카드 항목 리스트 반환."""
    out = []
    if isinstance(macro, list):
        for it in macro:
            out.append({
                "emoji": it.get("emoji", "•"), "label": it.get("label", ""),
                "value": it.get("value", ""), "delta": it.get("delta", ""),
                "dir": it.get("dir", "neu"), "text": it.get("text", ""),
            })
    elif isinstance(macro, dict):
        for key, (emoji, label) in MACRO_META.items():
            txt = macro.get(key)
            if not txt:
                continue
            d = "up" if re.search(r"상승|반등|강세|▲|\+", str(txt)) else ("down" if re.search(r"하락|급락|약세|▼|사이드카|-", str(txt)) else "neu")
            out.append({"emoji": emoji, "label": label, "value": "", "delta": "", "dir": d, "text": txt})
    return out


def render_macro(d):
    cards = []
    for it in _macro_items(d.get("macro", {})):
        dd = it["dir"] if it["dir"] in ("up", "down", "neu") else "neu"
        val = '<div class="mv">{}</div>'.format(esc(it["value"])) if it["value"] else ""
        delta = '<div class="md {d}">{x}</div>'.format(d=dd, x=esc(it["delta"])) if it["delta"] else ""
        text = '<div class="mt">{}</div>'.format(esc(it["text"])) if it["text"] else ""
        cards.append("""<div class="mac {d}"><div class="ml"><span class="e">{emoji}</span> {label}</div>
{val}{delta}{text}</div>""".format(d=dd, emoji=esc(it["emoji"]), label=esc(it["label"]), val=val, delta=delta, text=text))
    return """<section class="sec">{head}
<div class="macro" style="margin-top:24px">{cards}</div></section>""".format(
        head=sec_head("05", '경제 · 금리 · <em>환율</em>', "Macro", "매크로 핵심 변수 점검"),
        cards="".join(cards))


def render_schedule(d):
    sch = d.get("schedule", {}) or {}
    tiers = [("today", "now", "Today", "오늘"), ("this_week", "week", "This Week", "이번 주"),
             ("this_month", "month", "This Month", "이번 달")]
    cols = []
    for key, cls, badge, label in tiers:
        evs = sch.get(key, []) or []
        rows = "".join('<div class="ev"><span class="what">{}</span></div>'.format(esc(x)) for x in evs) \
            or '<div class="ev"><span class="what" style="color:var(--ink-ghost)">—</span></div>'
        cols.append("""<div class="tier {cls}"><div class="tier-hd"><span class="t-badge">{badge}</span><span class="t-k">{label}</span></div>
{rows}</div>""".format(cls=cls, badge=badge, label=label, rows=rows))
    return """<section class="sec">{head}
<div class="sched" style="margin-top:24px">{cols}</div></section>""".format(
        head=sec_head("06", '주목할 <em>일정</em>', "Calendar", "오늘 · 이번 주 · 이번 달"),
        cols="".join(cols))


def render_footer(d):
    sources = d.get("sources", []) or []
    src = " · ".join('<a href="{u}" target="_blank" rel="noopener" style="color:#9fb4ff;text-decoration:none">{t}</a>'.format(
        u=esc(s.get("url", "#")), t=esc(s.get("title", ""))) for s in sources)
    src_line = '<br>출처: {}'.format(src) if src else ""
    return """<footer><p class="disc">{disc}{src}</p>
<div class="foot-brand"><div class="b">🧭 마켓 나침반 · <span>Market Compass</span></div>
<div class="auto">매일 오전 7시 자동 생성 · Auto-generated Daily 07:00 KST · v{date}</div></div></footer>""".format(
        disc=esc(d.get("disclaimer", "")), src=src_line, date=esc(d.get("date", "")))


# ---------------------------------------------------------------- CSS (editorial dark theme)
CSS = """
  :root{
    --bg:#080a0e;--bg-2:#0c0f15;--panel:#11141c;--panel-2:#161a24;--panel-3:#0e1119;
    --glass:rgba(20,25,36,.62);--ink:#eef1f7;--ink-soft:#b4bccb;--ink-faint:#7c8493;--ink-ghost:#565e6d;
    --line:#212634;--line-soft:#1a1e29;--line-strong:#2c3344;
    --up:#1ed98a;--down:#ff5468;--neutral:#f0b24a;--gold:#cba45c;--accent:#5b8cff;
    --up-soft:rgba(30,217,138,.12);--down-soft:rgba(255,84,104,.12);--neu-soft:rgba(240,178,74,.12);
    --serif:"Playfair Display",Georgia,serif;--sans:"Inter","Noto Sans KR",system-ui,sans-serif;
    --kr:"Noto Sans KR","Inter",sans-serif;--mono:"JetBrains Mono",ui-monospace,monospace;
  }
  *{box-sizing:border-box;margin:0;padding:0}
  html{-webkit-text-size-adjust:100%;scroll-behavior:smooth}
  body{
    background:radial-gradient(1100px 620px at 84% -12%, rgba(91,140,255,.13), transparent 58%),
      radial-gradient(960px 640px at 4% 4%, rgba(123,107,255,.10), transparent 54%),
      radial-gradient(900px 760px at 50% 116%, rgba(30,217,138,.05), transparent 60%),var(--bg);
    color:var(--ink);font-family:var(--sans);font-size:14px;line-height:1.55;
    -webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility;background-attachment:fixed;
  }
  .wrap{max-width:1240px;margin:0 auto;padding:0 24px 76px}
  .up{color:var(--up)} .down{color:var(--down)} .neu{color:var(--neutral)}
  .strip{position:sticky;top:0;z-index:50;background:rgba(5,7,10,.92);backdrop-filter:blur(10px);
    border-bottom:1px solid var(--line-strong);overflow:hidden;white-space:nowrap;box-shadow:0 4px 22px rgba(0,0,0,.55)}
  .strip .run{display:inline-block;padding:8px 0;animation:scroll 48s linear infinite}
  .strip .run span{padding:0 20px;border-right:1px solid var(--line);font-family:var(--mono);font-size:12px;font-variant-numeric:tabular-nums;letter-spacing:.2px}
  .strip b{color:var(--ink-soft);font-weight:600;margin-right:8px;font-size:11px;letter-spacing:.6px}
  @keyframes scroll{from{transform:translateX(0)}to{transform:translateX(-50%)}}
  @media (prefers-reduced-motion:reduce){.strip .run{animation:none}}
  .sec{margin-top:54px}
  .sec-head{display:flex;align-items:baseline;gap:18px;margin-bottom:22px}
  .sec-num{font-family:var(--mono);font-size:.72rem;letter-spacing:.32em;color:var(--gold);font-weight:600;padding-top:5px;white-space:nowrap}
  .sec-title{font-family:var(--serif);font-weight:700;font-size:clamp(1.45rem,2.7vw,1.95rem);line-height:1.1;letter-spacing:-.01em;color:#fbfcfe}
  .sec-title em{font-style:italic;color:var(--gold);font-weight:600}
  .sec-sub{font-family:var(--kr);font-size:.8rem;color:var(--ink-faint);margin-left:auto;font-weight:400;letter-spacing:.02em;align-self:flex-end;text-align:right}
  .sec-en{font-family:var(--mono);font-size:.62rem;font-weight:600;letter-spacing:.24em;color:var(--ink-ghost);text-transform:uppercase;align-self:flex-end;padding-bottom:2px}
  .rule{height:1px;background:linear-gradient(90deg,var(--line-strong),transparent);margin-top:-6px}
  .hero{position:relative;overflow:hidden;margin:18px 0 6px;border:1px solid var(--line-strong);border-radius:24px;
    background:radial-gradient(640px 320px at 88% -34%, rgba(91,140,255,.30), transparent 60%),
      radial-gradient(560px 380px at 6% 124%, rgba(30,217,138,.13), transparent 56%),
      linear-gradient(140deg,#161a26 0%, #11131c 55%, #0c0e15 100%);
    box-shadow:0 32px 80px -42px rgba(0,0,0,.92), inset 0 1px 0 rgba(255,255,255,.05)}
  .hero::before{content:"";position:absolute;inset:0;pointer-events:none;
    background:radial-gradient(560px 260px at 86% -28%, rgba(255,255,255,.10), transparent 62%),
      repeating-linear-gradient(115deg, rgba(255,255,255,.022) 0 2px, transparent 2px 26px);
    mix-blend-mode:screen;opacity:.7}
  .hero-in{position:relative;z-index:2;padding:34px 38px 0}
  .hero-top{display:flex;justify-content:space-between;align-items:flex-start;gap:20px;flex-wrap:wrap}
  .brand{display:flex;align-items:center;gap:18px}
  .compass{width:64px;height:64px;flex:none;border-radius:19px;display:grid;place-items:center;font-size:33px;
    background:linear-gradient(145deg,rgba(255,255,255,.20),rgba(255,255,255,.03));border:1px solid rgba(255,255,255,.26);
    box-shadow:0 12px 34px -8px rgba(91,140,255,.62), inset 0 1px 0 rgba(255,255,255,.4);
    animation:bob 5.5s ease-in-out infinite;filter:drop-shadow(0 4px 12px rgba(91,140,255,.35))}
  @keyframes bob{50%{transform:translateY(-5px) rotate(-4deg)}}
  @media (prefers-reduced-motion:reduce){.compass{animation:none}}
  .brand h1{font-family:var(--kr);font-weight:900;font-size:clamp(1.7rem,4vw,2.05rem);letter-spacing:-.6px;line-height:1.08;color:#fff}
  .brand .en{font-family:var(--sans);font-weight:700;font-size:.72rem;letter-spacing:.46em;color:rgba(255,255,255,.6);margin-top:7px;text-transform:uppercase}
  .hero-meta{text-align:right;display:flex;flex-direction:column;align-items:flex-end;gap:11px}
  .hero-date{font-family:var(--serif);font-style:italic;font-size:1.32rem;color:#f1ead8;font-weight:600}
  .hero-date span{font-style:normal;font-family:var(--kr);color:var(--ink-faint);font-size:.92rem;font-weight:400}
  .tag{display:inline-flex;align-items:center;gap:8px;font-family:var(--mono);font-weight:700;font-size:11px;letter-spacing:1.4px;
    padding:7px 14px;border-radius:999px;color:#dfe7ff;background:rgba(255,255,255,.10);border:1px solid rgba(255,255,255,.22);backdrop-filter:blur(6px)}
  .tag .dot{width:7px;height:7px;border-radius:50%;background:var(--up);box-shadow:0 0 0 4px rgba(30,217,138,.24);animation:pulse 1.9s infinite}
  @keyframes pulse{50%{box-shadow:0 0 0 8px rgba(30,217,138,0)}}
  .hero-strip{position:relative;z-index:2;margin-top:26px;display:flex;flex-wrap:wrap;gap:10px;align-items:center;padding:18px 38px 32px;border-top:1px solid rgba(255,255,255,.10)}
  .pill{font-family:var(--kr);font-weight:700;font-size:12.5px;padding:8px 15px;border-radius:999px;background:rgba(8,11,17,.5);border:1px solid rgba(255,255,255,.11);display:flex;align-items:center;gap:9px}
  .pill .v{font-family:var(--mono);font-weight:700}
  .sidecar-flag{font-family:var(--kr);font-weight:700;font-size:12.5px;padding:8px 15px;border-radius:999px;color:#ffd2d8;background:rgba(255,84,104,.15);border:1px solid rgba(255,84,104,.4);display:flex;align-items:center;gap:8px}
  .sentiment{margin-left:auto;display:flex;align-items:center;gap:10px;font-family:var(--mono);font-size:.76rem;font-weight:700;letter-spacing:.06em;color:var(--down);border:1px solid rgba(255,84,104,.32);background:rgba(255,84,104,.08);padding:8px 15px;border-radius:999px}
  .grp-label{font-family:var(--mono);font-size:.66rem;letter-spacing:.26em;color:var(--ink-faint);text-transform:uppercase;font-weight:600;margin:0 0 13px;display:flex;align-items:center;gap:13px}
  .grp-label .kr{font-family:var(--kr);letter-spacing:.02em;text-transform:none;color:var(--ink-soft);font-weight:600;font-size:.78rem}
  .grp-label::after{content:"";flex:1;height:1px;background:var(--line-soft)}
  .idx-grid{display:grid;gap:13px;grid-template-columns:repeat(3,1fr)}
  .idx-grid.four{grid-template-columns:repeat(4,1fr)}
  .idx{position:relative;background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:18px 18px 16px 22px;overflow:hidden;transition:transform .25s cubic-bezier(.2,.8,.2,1),border-color .25s,background .25s,box-shadow .25s}
  .idx::before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:var(--ink-ghost)}
  .idx.up::before{background:linear-gradient(180deg,var(--up),#0f9c61)}
  .idx.down::before{background:linear-gradient(180deg,var(--down),#c0344a)}
  .idx:hover{transform:translateY(-4px);border-color:var(--line-strong);background:var(--panel-2);box-shadow:0 22px 44px -24px rgba(0,0,0,.85)}
  .idx .nm{font-family:var(--mono);font-size:.72rem;letter-spacing:.12em;font-weight:600;color:var(--ink-faint);text-transform:uppercase;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
  .idx .nm .kr{font-family:var(--kr);letter-spacing:.01em;color:var(--ink-soft);font-size:.76rem;text-transform:none;font-weight:600}
  .idx .val{font-family:var(--mono);font-weight:800;font-size:1.55rem;margin-top:12px;letter-spacing:-.02em;color:#fff;line-height:1.05}
  .idx .chg{font-family:var(--mono);font-size:.88rem;font-weight:700;margin-top:8px;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
  .up .chg{color:var(--up)} .down .chg{color:var(--down)} .neu .chg{color:var(--neutral)}
  .badge{font-family:var(--kr);font-size:.64rem;font-weight:700;letter-spacing:.02em;padding:3px 8px;border-radius:6px;white-space:nowrap;border:1px solid}
  .badge.est{background:var(--neu-soft);color:var(--neutral);border-color:rgba(240,178,74,.32)}
  .badge.note{background:rgba(91,140,255,.12);color:#9fb4ff;border-color:rgba(91,140,255,.32)}
  .badge.alert{background:var(--down-soft);color:#ffd2d8;border-color:rgba(255,84,104,.4)}
  .heat-card{background:var(--panel-3);border:1px solid var(--line);border-radius:20px;padding:16px;box-shadow:inset 0 0 60px rgba(0,0,0,.5), 0 26px 56px -36px #000}
  .heat-legend{display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin:2px 4px 14px;font-family:var(--kr);font-size:11.5px;color:var(--ink-faint)}
  .heat-legend .lbl{font-family:var(--mono);letter-spacing:.04em;font-size:10.5px}
  .heat-scale{display:flex;align-items:center;border-radius:6px;overflow:hidden;border:1px solid var(--line-strong)}
  .heat-scale i{width:23px;height:11px;display:block}
  .heat-legend .sp{flex:1}
  .heat-treemap{width:100%;height:auto;display:block;border-radius:13px;overflow:hidden;background:#05070c}
  .tm-sechead{font-family:var(--kr);font-weight:900;fill:#cdd6ea;letter-spacing:-.2px}
  .tm-secsub{font-family:var(--mono);font-weight:700}
  .tm-tick{font-family:var(--sans);font-weight:800;letter-spacing:-.3px}
  .tm-pct{font-family:var(--mono);font-weight:700;opacity:.92}
  .tm-tile{transition:opacity .2s} .tm-tile:hover{opacity:.82;cursor:default}
  .movers{display:grid;grid-template-columns:1fr 1fr;gap:16px}
  .mv-col{background:var(--panel);border:1px solid var(--line);border-radius:18px;overflow:hidden}
  .mv-hd{display:flex;align-items:center;gap:11px;padding:15px 22px;border-bottom:1px solid var(--line);font-family:var(--kr);font-weight:800;font-size:.94rem;letter-spacing:.02em}
  .mv-hd .ic{font-size:1.05rem}
  .mv-hd .en{font-family:var(--mono);font-size:.6rem;font-weight:600;letter-spacing:.2em;color:var(--ink-ghost);margin-left:auto;text-transform:uppercase}
  .mv-up .mv-hd{background:linear-gradient(90deg,rgba(30,217,138,.1),transparent);color:var(--up)}
  .mv-down .mv-hd{background:linear-gradient(90deg,rgba(255,84,104,.1),transparent);color:var(--down)}
  .mv-row{display:flex;align-items:flex-start;gap:14px;padding:13px 22px;border-bottom:1px solid var(--line-soft);transition:background .2s}
  .mv-row:last-child{border-bottom:none} .mv-row:hover{background:rgba(255,255,255,.025)}
  .mv-pc{font-family:var(--mono);font-weight:800;font-size:1rem;min-width:66px;text-align:right;flex:none;padding:4px 9px;border-radius:9px;line-height:1.1}
  .mv-up .mv-pc{color:var(--up);background:var(--up-soft)}
  .mv-down .mv-pc{color:var(--down);background:var(--down-soft)}
  .mv-body{min-width:0}
  .mv-name{font-family:var(--kr);font-weight:700;font-size:.95rem;color:#fff;display:flex;align-items:center;gap:7px;flex-wrap:wrap}
  .mv-name .tk{font-family:var(--mono);font-size:.72rem;color:var(--ink-faint);font-weight:600}
  .mv-why{font-family:var(--kr);font-size:.8rem;color:var(--ink-faint);margin-top:3px;line-height:1.5}
  .themes{display:grid;grid-template-columns:1fr 1fr;gap:13px}
  .theme{position:relative;background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:17px 18px 17px 20px;display:flex;gap:15px;align-items:flex-start;transition:transform .22s,border-color .22s;overflow:hidden}
  .theme::before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px}
  .theme.s-up::before{background:var(--up)} .theme.s-down::before{background:var(--down)} .theme.s-neu::before{background:var(--neutral)}
  .theme:hover{transform:translateY(-3px);border-color:var(--line-strong)}
  .th-ic{width:42px;height:42px;border-radius:13px;display:grid;place-items:center;font-size:21px;flex:none;background:rgba(255,255,255,.045);border:1px solid var(--line)}
  .th-body{flex:1;min-width:0}
  .th-top{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:5px;flex-wrap:wrap}
  .th-nm{font-family:var(--kr);font-weight:800;font-size:1rem;color:#fff}
  .chip{font-family:var(--kr);font-size:.68rem;font-weight:800;letter-spacing:.02em;padding:4px 11px;border-radius:999px;white-space:nowrap}
  .chip.up{color:var(--up);background:var(--up-soft);box-shadow:inset 0 0 0 1px rgba(30,217,138,.32)}
  .chip.down{color:var(--down);background:var(--down-soft);box-shadow:inset 0 0 0 1px rgba(255,84,104,.32)}
  .chip.neu{color:var(--neutral);background:var(--neu-soft);box-shadow:inset 0 0 0 1px rgba(240,178,74,.32)}
  .th-cmt{font-family:var(--kr);font-size:.84rem;color:var(--ink-soft);line-height:1.55}
  .macro{display:grid;grid-template-columns:repeat(5,1fr);gap:13px}
  .mac{position:relative;background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:17px 17px 15px;transition:transform .22s,border-color .22s;overflow:hidden}
  .mac::before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--ink-ghost)}
  .mac.up::before{background:var(--up)} .mac.down::before{background:var(--down)} .mac.neu::before{background:var(--neutral)}
  .mac:hover{transform:translateY(-3px);border-color:var(--line-strong)}
  .mac .ml{font-family:var(--kr);font-size:.76rem;color:var(--ink-faint);font-weight:600;letter-spacing:.01em;display:flex;align-items:center;gap:7px}
  .mac .ml .e{font-size:.95rem}
  .mac .mv{font-family:var(--mono);font-weight:800;font-size:1.32rem;color:#fff;margin-top:12px;line-height:1;letter-spacing:-.02em}
  .mac .md{font-family:var(--mono);font-size:.78rem;font-weight:700;margin-top:7px}
  .mac .mt{font-family:var(--kr);font-size:.73rem;color:var(--ink-ghost);margin-top:10px;line-height:1.5;padding-top:9px;border-top:1px solid var(--line-soft)}
  .md.up{color:var(--up)} .md.down{color:var(--down)} .md.neu{color:var(--neutral)}
  .sched{display:grid;grid-template-columns:repeat(3,1fr);gap:15px}
  .tier{background:var(--panel);border:1px solid var(--line);border-radius:18px;overflow:hidden}
  .tier-hd{padding:14px 19px;border-bottom:1px solid var(--line);display:flex;align-items:center;gap:11px}
  .tier-hd .t-badge{font-family:var(--mono);font-weight:800;font-size:9.5px;letter-spacing:1px;padding:4px 9px;border-radius:7px;text-transform:uppercase}
  .tier-hd .t-k{font-family:var(--kr);font-weight:800;font-size:.95rem;color:#fff}
  .tier.now .tier-hd{background:linear-gradient(90deg,rgba(91,140,255,.15),transparent)}
  .tier.now .t-badge{color:#bcd0ff;background:rgba(91,140,255,.2)}
  .tier.week .t-badge{color:var(--up);background:var(--up-soft)}
  .tier.month .t-badge{color:var(--neutral);background:var(--neu-soft)}
  .ev{padding:12px 19px;border-bottom:1px solid var(--line-soft);display:flex;gap:13px;align-items:flex-start;transition:background .2s}
  .ev:last-child{border-bottom:none} .ev:hover{background:rgba(255,255,255,.025)}
  .ev .what{font-family:var(--kr);font-size:.84rem;color:var(--ink-soft);line-height:1.5}
  footer{margin-top:60px;border-top:1px solid var(--line);padding-top:26px}
  .disc{font-family:var(--kr);font-size:.74rem;color:var(--ink-ghost);line-height:1.75;max-width:880px}
  .disc b{color:var(--neutral);font-weight:600}
  .foot-brand{display:flex;align-items:center;justify-content:space-between;gap:18px;margin-top:22px;flex-wrap:wrap}
  .foot-brand .b{font-family:var(--serif);font-style:italic;font-size:1.06rem;color:#dfe2e8;font-weight:600}
  .foot-brand .b span{color:var(--gold)}
  .foot-brand .auto{font-family:var(--mono);font-size:.68rem;letter-spacing:.13em;color:var(--ink-ghost);text-transform:uppercase}
  @media(max-width:900px){.idx-grid,.idx-grid.four{grid-template-columns:repeat(2,1fr)}.macro{grid-template-columns:repeat(2,1fr)}.movers,.themes{grid-template-columns:1fr}.sched{grid-template-columns:1fr}}
  @media(max-width:560px){.wrap{padding:0 14px 50px}.hero-in{padding:26px 22px 0}.hero-strip{padding:16px 22px 26px}.idx-grid,.idx-grid.four,.macro{grid-template-columns:1fr}.sec-head{flex-wrap:wrap;gap:6px}.sec-sub{margin-left:0;text-align:left;align-self:auto}.hero-meta{text-align:left;align-items:flex-start}.sentiment{margin-left:0}}
"""


def build_page(d):
    title_date = esc(d.get("date_display", d.get("date", "")))
    head = ('<!doctype html><html lang="ko"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>🧭 마켓 나침반 · ' + title_date + '</title>'
            '<meta name="description" content="마켓 나침반 — 매일 오전 7시 자동 생성되는 모닝 마켓 브리핑 (' + title_date + ')">'
            '<link rel="preconnect" href="https://fonts.googleapis.com">'
            '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
            '<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@300;400;500;600;700;900&family=Inter:ital,wght@0,300;0,400;0,500;0,600;0,700;0,800;1,400;1,500&family=JetBrains+Mono:wght@400;500;600;700;800&family=Playfair+Display:ital,wght@0,600;0,700;0,800;1,500;1,600&display=swap" rel="stylesheet">'
            '<style>' + CSS + '</style></head><body>')
    body = (render_ticker(d) + '<div class="wrap">' + render_hero(d) + render_indicators(d)
            + render_heatmap(d) + render_movers(d) + render_themes(d) + render_macro(d)
            + render_schedule(d) + render_footer(d) + '</div>')
    return head + body + "</body></html>"


def build_archive_index():
    files = sorted(glob.glob(os.path.join(ARCHIVE, "*.html")), reverse=True)
    rows = []
    for f in files:
        name = os.path.basename(f)
        if name == "index.html":
            continue
        rows.append('<li><a href="{n}">{d}</a></li>'.format(n=esc(name), d=esc(name[:-5])))
    body = ('<!doctype html><html lang="ko"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>마켓 나침반 · 지난 리포트</title>'
            '<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;700;800&family=JetBrains+Mono:wght@500;700&display=swap" rel="stylesheet">'
            '<style>body{background:#080a0e;color:#eef1f7;font-family:"Noto Sans KR",sans-serif;max-width:680px;margin:0 auto;padding:44px 22px}'
            'h1{font-size:22px}a{color:#9fb4ff;text-decoration:none}ul{list-style:none;padding:0}'
            'li{padding:11px 2px;border-bottom:1px solid #212634;font-family:"JetBrains Mono",monospace;font-size:15px}'
            '.back{display:inline-block;margin-bottom:22px;color:#cba45c}</style></head><body>'
            '<a class="back" href="../index.html">← 최신 리포트</a><h1>🧭 지난 리포트</h1><ul>'
            + ("".join(rows) or "<li>아직 없음</li>") + '</ul></body></html>')
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
