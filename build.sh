#!/usr/bin/env bash
# Build de idiAuto para Linux (binario único en dist/idiauto)
set -e
cd "$(dirname "$0")"

if [ ! -d venv ]; then
  python3 -m venv venv
fi

./venv/bin/pip install --upgrade pip
./venv/bin/pip install playwright textual keyring html2text pyinstaller
./venv/bin/playwright install chromium

./venv/bin/pyinstaller idiauto.spec --noconfirm

echo
echo "============================================"
echo " Binario listo: dist/idiauto"
echo " Ejecuta con: ./dist/idiauto"
echo "============================================"
