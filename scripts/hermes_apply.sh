#!/bin/bash
# Hermes cron 사후 작업(no-agent). 같은 날 10:00 추출 작업이 쓴 JSON을 검증·검토·반영한다.
# LLM이 apply를 실행하면 터미널 제한 시간(180초)에 걸려 중간에 끊긴다 - 그래서 스크립트가 직접 돈다.
# master 확인, prep 기록 확인, 실패 알림은 Python(apply_run)이 한다.
set -euo pipefail
cd /Users/jay/Agents/ConferenceManager
exec .venv/bin/python -m scripts.official_run apply
