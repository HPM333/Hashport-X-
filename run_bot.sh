#!/bin/bash
# Wrapper script for cron execution
# Loads .env and runs the bot with logging

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="$SCRIPT_DIR/logs/bot_$(date +%Y%m%d).log"

mkdir -p "$SCRIPT_DIR/logs"

# Load .env
set -a
source "$SCRIPT_DIR/.env"
set +a

echo "=== $(date '+%Y-%m-%d %H:%M:%S') ===" >> "$LOG_FILE"
/usr/bin/python3 "$SCRIPT_DIR/x_monitor_bot.py" >> "$LOG_FILE" 2>&1
echo "Exit code: $?" >> "$LOG_FILE"
