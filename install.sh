#!/usr/bin/env bash
# Descarga la última release de idiAuto desde el repo privado.
# Pide el token GitHub (actúa como "contraseña" de acceso).
#
# Uso:
#   ./install.sh
#   REPO=usuario/idiauto GITHUB_TOKEN=ghp_xxx ./install.sh
set -e

REPO="${REPO:-}"
DEST="${DEST:-$HOME/.local/bin}"

if [ -z "$REPO" ]; then
  read -rp "Repo (usuario/idiauto): " REPO
fi
if [ -z "$GITHUB_TOKEN" ]; then
  echo "Introduce tu GitHub Personal Access Token (scope: repo)."
  echo "Crea uno en: https://github.com/settings/tokens"
  read -srp "Token: " GITHUB_TOKEN
  echo
fi

echo "Buscando última release de $REPO..."
API="https://api.github.com/repos/$REPO/releases/latest"
JSON=$(curl -fsSL -H "Authorization: Bearer $GITHUB_TOKEN" \
             -H "Accept: application/vnd.github+json" "$API")

TAG=$(printf '%s' "$JSON" | grep -oP '"tag_name":\s*"\K[^"]+' | head -1)
URL=$(printf '%s' "$JSON" | grep -oP '"url":\s*"\K[^"]+' | grep '/assets/' | head -1)
NAME=$(printf '%s' "$JSON" | grep -oP '"name":\s*"idiauto[^"]*"' | head -1 | cut -d'"' -f4)

if [ -z "$URL" ]; then
  echo "ERROR: no se encontró asset en la release."
  exit 1
fi

mkdir -p "$DEST"
TARGET="$DEST/${NAME:-idiauto}"
echo "Descargando $NAME ($TAG) → $TARGET"
curl -fL -H "Authorization: Bearer $GITHUB_TOKEN" \
         -H "Accept: application/octet-stream" \
         -o "$TARGET" "$URL"
chmod +x "$TARGET"

echo
echo "============================================"
echo " Instalado en: $TARGET"
echo " Ejecuta con:  $TARGET"
echo "============================================"
case ":$PATH:" in
  *":$DEST:"*) ;;
  *) echo "TIP: añade a tu PATH:  export PATH=\"$DEST:\$PATH\"" ;;
esac
