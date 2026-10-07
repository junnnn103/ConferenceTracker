#!/bin/bash
# Hermes cron 사전 스크립트. 출력이 그대로 Hermes 지시문에 들어간다.
set -euo pipefail
cd /Users/jay/Agents/ConferenceManager
if [ "$(git branch --show-current)" != "master" ]; then
  echo "git pull 실패 - master 브랜치가 아니어서 이번 주 확인을 건너뜁니다."
  exit 1
fi
exec .venv/bin/python -m scripts.official_run prep
