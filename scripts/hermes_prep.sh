#!/bin/bash
# Hermes cron 사전 스크립트. 출력이 그대로 Hermes 지시문에 들어간다.
set -euo pipefail
cd /Users/jay/Agents/ConferenceManager
exec .venv/bin/python -m scripts.official_run prep
