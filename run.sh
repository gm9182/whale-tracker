#!/bin/bash
# Whale Tracker - クイックスタート
# 使い方: ./run.sh [us|jp|both|build]

set -e

cd "$(dirname "$0")"

case "${1:-both}" in
  us)
    echo "🇺🇸 Fetching US whale signals..."
    python3 scripts/fetch_us.py
    ;;
  jp)
    echo "🇯🇵 Fetching JP whale signals..."
    python3 scripts/fetch_jp.py
    ;;
  both)
    echo "🇯🇵 Fetching JP whale signals..."
    python3 scripts/fetch_jp.py
    echo ""
    echo "🇺🇸 Fetching US whale signals..."
    python3 scripts/fetch_us.py
    ;;
  build)
    ;;
  *)
    echo "Usage: $0 [us|jp|both|build]"
    exit 1
    ;;
esac

echo ""
echo "📊 Building HTML dashboard..."
python3 scripts/build_html.py

echo ""
echo "✅ Done. Open docs/index.html in your browser."
