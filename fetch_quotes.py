#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_quotes.py — data.json 의 등락률·종가를 Finnhub 정규장 종가로 정량 보정.

웹검색 기반 근사치를 거래소 종가(전일 종가 대비 등락%)로 덮어쓴다.
표준 라이브러리만 사용(urllib). 무료 Finnhub API 키 필요.

API 키 우선순위:
  1) 환경변수 FINNHUB_API_KEY
  2) <repo>/finnhub.key  (gitignore 됨)
  3) ~/.config/market-compass/finnhub.key
키가 없거나 조회 실패 시 → 보정 건너뜀(비치명적, 생성값 유지).

- 지수: 실심볼(^GSPC 등) 우선, 미지원 시 ETF 프록시(SPY 등)로 등락%만 보정
- 히트맵/등락 종목(미국 티커): change_pct 보정
- 부호 바뀐 등락 종목은 상승/하락 칼럼으로 재배치
- 한국 코드·야간선물 등 미지원 항목은 기존 값 유지

사용법: python3 fetch_quotes.py [data.json]
"""

import sys
import os
import re
import json
import time
import urllib.request
import urllib.parse
import urllib.error

ROOT = os.path.dirname(os.path.abspath(__file__))
UA = "market-compass/1.0"

# 지수 이름 -> [(finnhub 심볼, patch_value)]  patch_value=True 면 value 도 덮어씀(실심볼/실ETF)
INDEX_CANDIDATES = [
    (r"DOW|다우",          [("^DJI", True), ("DIA", False)]),
    (r"S&P|에스앤피",       [("^GSPC", True), ("SPY", False)]),
    (r"NASDAQ|나스닥",      [("^IXIC", True), ("ONEQ", False), ("QQQ", False)]),
    (r"SOX|필라델피아",      [("^SOX", True), ("SOXX", False)]),
    (r"\bEWY\b|MSCI 한국",  [("EWY", True)]),
    (r"\bEEM\b|MSCI 신흥국", [("EEM", True)]),
]
DOLLAR_INDEX = {"EWY", "EEM"}

_cache = {}


def load_key():
    k = os.environ.get("FINNHUB_API_KEY", "").strip()
    if k:
        return k
    for p in (os.path.join(ROOT, "finnhub.key"),
              os.path.expanduser("~/.config/market-compass/finnhub.key")):
        try:
            if os.path.exists(p):
                v = open(p, encoding="utf-8").read().strip()
                if v:
                    return v
        except Exception:
            pass
    return None


def fh_quote(sym, key):
    """Finnhub /quote -> {'last','chg','prev'} 또는 None. (c<=0 = 미지원)"""
    if sym in _cache:
        return _cache[sym]
    url = "https://finnhub.io/api/v1/quote?" + urllib.parse.urlencode({"symbol": sym, "token": key})
    res = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=12) as r:
                j = json.load(r)
            c = j.get("c")
            if c and c > 0:
                res = {"last": float(c), "chg": j.get("dp"), "prev": j.get("pc")}
            break
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(1.2 * (attempt + 1))
                continue
            break
        except Exception:
            time.sleep(0.5 * (attempt + 1))
    _cache[sym] = res
    time.sleep(0.22)   # 60/min 무료한도 여유
    return res


def index_candidates(name):
    for pat, cands in INDEX_CANDIDATES:
        if re.search(pat, str(name), re.IGNORECASE):
            return cands
    return None


def us_ticker(ticker):
    t = str(ticker).strip().upper()
    if re.fullmatch(r"[A-Z][A-Z.\-]{0,6}", t):   # 미국 티커만 (한국 6자리코드·F-K200 제외)
        return t
    return None


def fmt_val(x, dollar=False):
    return ("$" if dollar else "") + "{:,.2f}".format(x)


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "data.json"
    path = src if os.path.isabs(src) else os.path.join(ROOT, src)
    with open(path, encoding="utf-8") as f:
        d = json.load(f)

    key = load_key()
    if not key:
        print("quote patch: SKIPPED (Finnhub API 키 없음 — finnhub.key 또는 FINNHUB_API_KEY)")
        return

    # 1) 지수 보정
    ni = 0
    for r in (d.get("indices_us", []) or []) + (d.get("indices_extra", []) or []):
        cands = index_candidates(r.get("name", ""))
        if not cands:
            continue
        for sym, patch_value in cands:
            q = fh_quote(sym, key)
            if q and q.get("chg") is not None:
                r["change_pct"] = round(q["chg"], 2)
                if patch_value:
                    r["value"] = fmt_val(q["last"], dollar=(sym in DOLLAR_INDEX))
                    note = str(r.get("note", ""))
                    if "추정" in note:
                        r["note"] = re.sub(r"\s*[·,]?\s*추정\s*", "", note).strip(" ·,")
                ni += 1
                break

    # 2) 종목 보정 (히트맵 + 등락)
    for m in d.get("movers_up", []) or []:
        m["_orig"] = "up"
    for m in d.get("movers_down", []) or []:
        m["_orig"] = "down"
    tick_items = []
    for sec in d.get("heatmap", []) or []:
        tick_items += sec.get("stocks", []) or []
    movers = list(d.get("movers_up", []) or []) + list(d.get("movers_down", []) or [])
    tick_items += movers
    nt = 0
    for it in tick_items:
        sym = us_ticker(it.get("ticker", ""))
        if not sym:
            continue
        q = fh_quote(sym, key)
        if q and q.get("chg") is not None:
            it["change_pct"] = round(q["chg"], 2)
            nt += 1

    # 3) 부호 뒤집힌 등락 종목: 생성 당시 '이유' 서술이 틀려지므로 제거
    for m in movers:
        cp = float(m.get("change_pct", 0) or 0)
        nd = "up" if cp > 0 else ("down" if cp < 0 else "flat")
        if m.get("_orig") and nd != "flat" and nd != m["_orig"]:
            m["reason"] = ""
        m.pop("_orig", None)

    # 4) 등락 종목 부호 기준 재배치
    ups = sorted([m for m in movers if float(m.get("change_pct", 0) or 0) > 0],
                 key=lambda m: float(m.get("change_pct", 0) or 0), reverse=True)
    downs = sorted([m for m in movers if float(m.get("change_pct", 0) or 0) < 0],
                   key=lambda m: float(m.get("change_pct", 0) or 0))
    flats = [m for m in movers if float(m.get("change_pct", 0) or 0) == 0]
    if ups or downs:
        d["movers_up"] = ups
        d["movers_down"] = downs + flats

    # 4) 출처 명시
    srcs = d.get("sources") or []
    if not any("finnhub" in str(s.get("url", "")).lower() for s in srcs):
        srcs.append({"title": "Finnhub (정규장 종가)", "url": "https://finnhub.io"})
    d["sources"] = srcs
    d["price_source"] = "finnhub"

    with open(path, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    print("quote patch: indices={} tickers={} | movers up={} down={}".format(
        ni, nt, len(d.get("movers_up", [])), len(d.get("movers_down", []))))


if __name__ == "__main__":
    main()
