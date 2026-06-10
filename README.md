# 🧭 마켓 나침반 (Market Compass)

매일 오전 7시(KST) 자동 생성되는 **미국/글로벌 증시 모닝 브리핑** — 어느 PC에서나 웹으로 열람.

**🔗 라이브:** https://jsleeethan.github.io/market-compass/

## 구조 (올인원 리눅스)

```
[24시간 리눅스 박스] cron 07:00 KST
   │  run.sh → 헤드리스 Claude Code(sonnet) 가 웹검색으로 data.json 생성
   │         → build_report.py 가 자체완결 HTML 생성 (순수 SVG/CSS 트리맵)
   │         → git push
   ▼
[GitHub Pages] docs/index.html → 공개 URL (어느 PC에서나 열람)
```

- **생성**: 헤드리스 Claude Code(`claude -p`)가 매일 시장 데이터를 웹검색해 `data.json` 작성 → 기존 Claude 구독으로 처리(추가 과금 거의 0).
- **빌드**: `build_report.py` — 표준 라이브러리만 사용, pip 의존성 없음. finviz 스타일 트리맵을 SVG로 직접 계산.
- **발행/호스팅**: GitHub Pages 공개 repo(`/docs`) — 무료.

## 파일

| 파일 | 역할 |
|------|------|
| `run.sh` | cron 진입점. 생성→빌드→push 오케스트레이션 |
| `prompt.md` | 매일 데이터 수집 지시문 + JSON 스키마 |
| `build_report.py` | `data.json` → `docs/index.html` (+ 아카이브) 빌더 |
| `sample_data.json` | 테스트용 샘플 데이터 |
| `data.json` | 그날 생성된 실제 데이터(매일 갱신) |
| `docs/` | GitHub Pages 발행 디렉터리 |
| `마켓나침반_개발정리.md/.pdf` | 원개발 정리 문서 |

## 수동 실행 / 테스트

```bash
# 샘플로 빌드만
python3 build_report.py sample_data.json

# 전체 파이프라인 1회 실행(생성→빌드→push)
./run.sh
tail -f run.log
```

## cron (매일 07:00 KST)

시스템 타임존이 Asia/Seoul 이므로 그대로 한국시간:

```cron
0 7 * * * /home/jslee/Workspace/market_compass/run.sh
```

## 비고
- 생성은 이 리눅스 박스가 켜져 있을 때 동작. 꺼져 있던 날은 마지막 리포트가 그대로 유지됨.
- 데이터는 공개 뉴스 기반 자동 요약으로 투자 자문이 아님.
