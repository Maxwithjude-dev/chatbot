#!/usr/bin/env bash
# EC2(Amazon Linux 2023)에서 실행: 패키지 설치 → 저장소 받기/갱신 → 가상환경 → 데이터 적재 → 서비스 등록·재시작
# 처음 한 번은 공단 CSV를 ~/chatbot/taas_chatbot_poc/data/ 에 올려 둔 뒤 실행하세요 (deploy/README.md 참고).
# 다시 실행하면 최신 코드로 갱신하고 서비스를 재시작합니다.
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/Maxwithjude-dev/chatbot.git}"
BRANCH="${BRANCH:-main}"
APP_HOME="${APP_HOME:-$HOME/chatbot}"
PY=python3.11

echo "== 1. 패키지"
command -v "$PY" >/dev/null && command -v git >/dev/null || sudo dnf install -y "$PY" git

echo "== 2. 저장소 ($BRANCH)"
if [ -d "$APP_HOME/.git" ]; then
  git -C "$APP_HOME" fetch -q origin
  git -C "$APP_HOME" checkout -q "$BRANCH"
  git -C "$APP_HOME" pull -q --ff-only origin "$BRANCH"
else
  # data/ 를 먼저 올려 둔 경우에도 받을 수 있게 빈 저장소에 원격을 붙여 받음
  mkdir -p "$APP_HOME"
  git -C "$APP_HOME" init -q
  git -C "$APP_HOME" remote add origin "$REPO_URL"
  git -C "$APP_HOME" fetch -q origin "$BRANCH"
  git -C "$APP_HOME" checkout -q -b "$BRANCH" "origin/$BRANCH"
fi
git -C "$APP_HOME" log --oneline -1

echo "== 3. 가상환경"
[ -x "$APP_HOME/.venv/bin/python" ] || "$PY" -m venv "$APP_HOME/.venv"
"$APP_HOME/.venv/bin/pip" install -q --upgrade pip
"$APP_HOME/.venv/bin/pip" install -q -r "$APP_HOME/taas_chatbot_poc/requirements.txt"

echo "== 4. 데이터 적재"
cd "$APP_HOME/taas_chatbot_poc"
if [ ! -f data/DOCUMENT_SET.csv ] || [ ! -f data/KEYWORD_SET.csv ]; then
  echo "data/DOCUMENT_SET.csv, data/KEYWORD_SET.csv 가 없습니다. 올린 뒤 다시 실행하세요." >&2
  exit 1
fi
"$APP_HOME/.venv/bin/python" import_data.py

echo "== 5. 서비스"
sudo cp "$APP_HOME/deploy/taas-chatbot.service" /etc/systemd/system/taas-chatbot.service
sudo systemctl daemon-reload
sudo systemctl enable -q taas-chatbot
sudo systemctl restart taas-chatbot

echo "== 6. 확인"
for i in $(seq 1 30); do
  code=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/ || true)
  [ "$code" = "200" ] && break
  sleep 1
done
echo "HTTP $code"
sudo journalctl -u taas-chatbot -n 8 --no-pager
[ "$code" = "200" ]
