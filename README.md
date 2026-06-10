# 🧭 마켓 나침반 (Market Compass)

매일 오전 7시(KST) 자동 생성되는 **미국/글로벌 증시 모닝 브리핑** — 어느 PC에서나 웹으로 열람.

**🔗 라이브:** https://jsleeethan.github.io/market-compass/

## 한눈에

- 매일 **07:00 KST** cron이 리포트를 자동 생성·발행
- 24시간 리눅스 박스에서 **헤드리스 Claude Code**가 생성 → **Finnhub**으로 수치 정확화 → **GitHub Pages** 발행
- 추가 과금 거의 0 (생성 = 기존 Claude 구독, 호스팅·자동화 = 무료)

## 프로젝트 구조

```
market_compass/
├── run.sh                 cron 진입점 — 전체 오케스트레이션
├── src/                   파이프라인 코드
│   ├── prompt.md          생성 지시문 + data.json 스키마
│   ├── fetch_quotes.py    Finnhub 정량 보정 (등락률 정확화)
│   └── build_report.py    data.json → 자체완결 HTML 빌더 (순수 SVG 트리맵)
├── data/                  데이터
│   ├── data.json          당일 생성 데이터 (매일 갱신)
│   └── sample_data.json   디자인 미리보기용 샘플
├── docs/                  발행물 (GitHub Pages 가 /docs 서빙)
│   ├── index.html         최신 리포트(라이브)
│   └── archive/           일자별 아카이브 + 목록
├── dev-docs/              문서
│   ├── ARCHITECTURE.md    현재 시스템 상세 설계
│   └── 마켓나침반_개발정리.md / .pdf   개발 히스토리 (Cowork v0)
├── finnhub.key            Finnhub API 키 (gitignore — 비커밋)
└── run.log               실행 로그 (gitignore)
```

## 데이터 흐름

```
cron 07:00 KST → run.sh
  1. git pull
  2. claude -p (src/prompt.md · sonnet · 웹검색) → data/data.json   [생성: 서술 + 종목 + 근사 수치]
  3. data.json 검증 (유효 JSON + 오늘 날짜)
  4. src/fetch_quotes.py → Finnhub 정량 보정                        [정확화: 등락률 덮어쓰기]
  5. src/build_report.py → docs/index.html + docs/archive/         [빌드: SVG 트리맵 HTML]
  6. git commit + push → GitHub Pages 발행
```

자세한 설계·모듈·스키마는 **[dev-docs/ARCHITECTURE.md](dev-docs/ARCHITECTURE.md)** 참고.

## 운영

```bash
# 전체 파이프라인 1회 실행 (생성→보정→빌드→push)
./run.sh
tail -f run.log

# 디자인 미리보기 (생성·보정 없이 샘플로 빌드만)
python3 src/build_report.py data/sample_data.json

# 보정만 단독 실행
python3 src/fetch_quotes.py data/data.json
```

## 설정 (최초 1회)

- **Finnhub 키**: `echo '발급받은_키' > finnhub.key` (gitignore 됨, cron이 무인으로 읽음)
- **GitHub Pages**: 저장소 설정에서 `main` 브랜치 `/docs` 서빙
- **무인 git push 인증**: `gh auth setup-git`
- **cron** (시스템 타임존 Asia/Seoul → 그대로 한국시간):
  ```cron
  0 7 * * * /home/jslee/Workspace/market_compass/run.sh
  ```

## 확장

| 바꾸고 싶은 것 | 수정 파일 |
|----------------|-----------|
| 수집 항목·종목·테마 | `src/prompt.md` |
| 디자인(색·폰트·레이아웃) | `src/build_report.py` (`CSS` 및 렌더러) |
| 정확도 소스·심볼 매핑 | `src/fetch_quotes.py` |

## 비고

- 생성은 이 리눅스 박스가 켜져 있을 때 동작. 꺼진 날은 웹에 마지막 리포트가 유지됨.
- 지수 등락%는 ETF 프록시(Finnhub 무료티어 한계) — 다우(DIA)·S&P(SPY)는 거의 정확, 나스닥(ONEQ)·SOX(SOXX)는 근사. 한국 종목 코드·코스피200 야간선물은 웹 수치 유지.
- 데이터는 공개 정보 기반 자동 요약으로 **투자 자문이 아님**.
