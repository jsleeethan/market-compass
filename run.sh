#!/usr/bin/env bash
# 마켓 나침반 — 매일 1회 cron 실행 스크립트
#   1) 헤드리스 Claude Code 로 data.json 생성 (웹검색)
#   2) data.json 검증 -> build_report.py 로 HTML 생성
#   3) GitHub 에 push -> GitHub Pages 자동 배포
set -uo pipefail

cd "$(dirname "$0")" || exit 1
REPO="$(pwd)"
LOG="$REPO/run.log"

# cron 최소 환경 대비: PATH 보강 (claude 는 node, git/gh/python3 는 /usr/bin)
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
for d in "$HOME"/.nvm/versions/node/*/bin; do [ -d "$d" ] && PATH="$d:$PATH"; done
export PATH

exec >>"$LOG" 2>&1

echo "===== $(date '+%F %T %Z') :: run start ====="

CLAUDE_BIN="${CLAUDE_BIN:-$HOME/.local/bin/claude}"
[ -x "$CLAUDE_BIN" ] || CLAUDE_BIN="$(command -v claude)"

DATE_ISO="$(date '+%F')"
DATE_DISP="$(date '+%Y년 %-m월 %-d일')"

# 최신 상태 동기화(웹에서 직접 수정했을 수도 있으니)
git pull --quiet --rebase 2>/dev/null || true

PROMPT="오늘 날짜(KST): ${DATE_ISO}.
data.json 의 \"date\" 는 정확히 \"${DATE_ISO}\", \"date_display\" 는 \"${DATE_DISP}\" 로 채워라.

$(cat "$REPO/prompt.md")"

echo "--- generating data.json via headless Claude Code (sonnet) ---"
timeout 900 "$CLAUDE_BIN" -p "$PROMPT" \
  --model sonnet \
  --permission-mode bypassPermissions \
  --allowedTools "WebSearch WebFetch Write Read" \
  --max-budget-usd 1.00 \
  --output-format text \
  --no-session-persistence
echo "claude exit: $?"

# data.json 검증 (유효 JSON + 오늘 날짜)
if ! python3 -c "
import json,sys
d=json.load(open('data.json',encoding='utf-8'))
assert d.get('date')=='${DATE_ISO}', 'date mismatch: %r' % d.get('date')
assert d.get('indices_us'), 'missing indices_us'
print('data.json OK (%d themes, %d movers_up)' % (len(d.get('themes',[])), len(d.get('movers_up',[]))))
"; then
  echo "ERROR: data.json 검증 실패 — 발행 건너뜀(이전 리포트 유지)"
  echo "===== run end (skipped) ====="
  exit 1
fi

echo "--- patching exact quotes from Yahoo (비치명적) ---"
python3 fetch_quotes.py data.json || echo "WARN: 야후 정량 보정 실패 — 생성값으로 진행"

echo "--- building HTML ---"
python3 build_report.py data.json || { echo "ERROR: build 실패"; exit 1; }

echo "--- publishing ---"
git add -A
if git diff --cached --quiet; then
  echo "변경 없음 — push 생략"
else
  git commit -q -m "report ${DATE_ISO}" && git push -q \
    && echo "published ${DATE_ISO}" || echo "ERROR: git push 실패"
fi

echo "===== run end ====="
