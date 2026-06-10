# 마켓 나침반 — 아키텍처 (현재 버전)

> 이 문서는 **현재 운영 중인 시스템**을 설명합니다. 초기 Cowork 버전(v0)의 개발 과정은
> [마켓나침반_개발정리.md](마켓나침반_개발정리.md)를 참고하세요.

## 1. 개요

매일 07:00 KST에 미국/글로벌 증시 모닝 브리핑(자체완결 HTML)을 자동 생성해 GitHub Pages로 발행한다.
**올인원 리눅스** 구조: 한 대의 24시간 리눅스 박스가 생성·보정·빌드·발행을 모두 수행한다.

| 단계 | 담당 | 비용 |
|------|------|------|
| 생성(서술·종목·근사수치) | 헤드리스 Claude Code (`claude -p`, sonnet) | 기존 Claude 구독 |
| 정확화(등락률 정량 보정) | Finnhub `/quote` | 무료 티어 |
| 빌드(HTML) | `build_report.py` (stdlib only) | — |
| 호스팅 | GitHub Pages 공개 repo `/docs` | 무료 |
| 자동화 | 시스템 cron (KST) | 무료 |

## 2. 데이터 흐름

```
cron 07:00 KST → run.sh
 ├─ 1. git pull --rebase
 ├─ 2. claude -p (src/prompt.md, sonnet, WebSearch/WebFetch/Write/Read, bypassPermissions)
 │       → data/data.json 작성  [지수·종목·테마·매크로·일정 + 1차 등락률(웹검색 근사)]
 ├─ 3. 검증: 유효 JSON + date == 오늘(KST). 실패 시 발행 건너뜀(이전 리포트 유지)
 ├─ 4. src/fetch_quotes.py data/data.json
 │       → Finnhub 정규장 종가로 등락률·일부 종가 덮어쓰기 (비치명적)
 ├─ 5. src/build_report.py data/data.json
 │       → docs/index.html + docs/archive/<date>.html + docs/archive/index.html
 └─ 6. git add -A && commit && push → GitHub Pages 자동 배포
```

핵심 설계: **생성(비결정적, AI)과 정확화(결정적, 시세 API)를 분리**한다. AI는 서술·맥락·종목 선정에
강하지만 정확한 종가 %에는 약하므로, 수치는 Finnhub으로 덮어써 정확도를 확보한다.

## 3. 모듈

### `run.sh` (오케스트레이터, 루트)
- cron 진입점. `cd` repo root, cron 최소환경 대비 **PATH 보강**(`~/.local/bin`, nvm node).
- 날짜(KST) 계산 → 프롬프트에 주입 → claude 생성 → 검증 → 보정 → 빌드 → push.
- 모든 출력은 `run.log`로 리다이렉트. 검증 실패는 발행을 건너뛰어 **이전 리포트 보존**.

### `src/prompt.md` (생성 지시문)
- Claude가 채울 `data/data.json`의 **스키마와 수집 항목**을 정의.
- 미확보 수치는 `note`에 `"추정"` 표기를 지시.

### `src/fetch_quotes.py` (정량 보정)
- 키 로드: `FINNHUB_API_KEY` env → `<repo>/finnhub.key` → `~/.config/market-compass/finnhub.key`.
- 지수: 실심볼(`^GSPC` 등)은 무료티어 미지원 → **ETF 프록시**(SPY/DIA/ONEQ/SOXX, EWY/EEM)로 등락% 확보.
  실ETF(EWY/EEM)는 value도 갱신, 프록시는 등락%만(value·"추정" 유지).
- 종목(미국 티커): `dp`(등락%)로 보정. 한국 6자리 코드·`F-K200` 등은 미지원 → 건너뜀.
- **부호 뒤집힘 처리**: 등락 종목의 보정 후 부호가 원래와 다르면 잘못된 "이유" 서술을 제거하고
  상승/하락 칼럼으로 재배치.
- 실패 시 SKIP(비치명적) — 생성값 유지.

### `src/build_report.py` (빌더, stdlib only)
- `data/data.json` → 자체완결 HTML. pip 의존성 없음.
- **squarify 트리맵**: 2단(섹터 그룹 → 종목 타일) 순수 SVG 계산, finviz 컬러 스케일.
- 8개 섹션 렌더러: 티커 스트립 · 히어로 · 지표 · 히트맵 · 종목 · 테마 · 매크로 · 일정 · 푸터.
- `docs/index.html` + 일자별 아카이브 + 아카이브 목록 생성. 에디토리얼 다크 테마 CSS 내장.

## 4. `data.json` 스키마 (요약)

```jsonc
{
  "date": "YYYY-MM-DD", "date_display": "YYYY년 M월 D일",
  "indices_us":    [ {name, value, change_pct} ],            // 다우/S&P/나스닥
  "indices_extra": [ {name, value, change_pct, note} ],      // SOX/EWY/EEM/코스피200 야간선물
  "heatmap":       [ {sector, stocks:[{ticker, weight, change_pct}]} ],
  "movers_up":     [ {name_kr, ticker, change_pct, reason} ],
  "movers_down":   [ {name_kr, ticker, change_pct, reason} ],
  "themes":        [ {name, tag, comment} ],                 // tag: 강세/약세/중립/혼조/고변동
  "macro":         [ {emoji, label, value, delta, dir, text} ], // dir: up/down/neu (구버전 dict 도 호환)
  "schedule":      { today:[], this_week:[], this_month:[] },
  "disclaimer": "...", "sources": [ {title, url} ], "price_source": "finnhub"
}
```
전체 예시는 [data/sample_data.json](../data/sample_data.json).

## 5. 한계 / 알아둘 점

- **생성 가용성**: 리눅스 박스가 07:00에 켜져 있어야 갱신. 꺼진 날은 마지막 리포트 유지.
- **지수 등락%**: ETF 프록시라 다우(DIA)·S&P(SPY)는 거의 정확, 나스닥(ONEQ=종합 추종)·SOX(SOXX≈근사)는
  0.0~0.x% 차이 가능. SOX는 "추정" 배지 유지.
- **한국 자산**: Finnhub 무료티어 미지원 → 코스피200 야간선물·국내 종목 코드는 웹 수치 유지.
- **시점**: 리포트는 직전 미 정규장 *종가* 스냅샷. 야후 등 실시간 시세와 다른 시각에 비교하면
  애프터마켓·차기 세션 차이로 달라 보일 수 있음(오류 아님).

## 6. 키 발급 메모

- 정확도 보정엔 **무료 Finnhub 키** 필요 (finnhub.io 가입). `echo 'KEY' > finnhub.key` (gitignore 됨).
- 키 없거나 조회 실패 시 보정은 건너뛰고 생성값으로 발행(시스템은 정상 동작).
