#!/usr/bin/env bash
# Publica dist/idiauto como asset de un GitHub Release (repo privado).
# Uso:  ./release.sh v1.0.0   "notas opcionales"
set -e
cd "$(dirname "$0")"

VERSION="${1:-}"
NOTAS="${2:-}"

if [ -z "$VERSION" ]; then
  VERSION="v$(date +%Y.%m.%d-%H%M)"
  echo "Sin tag indicado, usando $VERSION"
fi

if [ ! -f dist/idiauto ]; then
  echo "ERROR: dist/idiauto no existe. Corre primero ./build.sh"
  exit 1
fi

if ! command -v gh >/dev/null 2>&1; then
  echo "ERROR: gh (GitHub CLI) no está instalado."
  echo "Instálalo: https://cli.github.com/"
  exit 1
fi

REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || true)"
if [ -z "$REPO" ]; then
  echo "ERROR: Este directorio no es un repo GitHub."
  echo "Ejecuta primero:"
  echo "  gh repo create <usuario>/idiauto --private --source . --push"
  exit 1
fi

echo "Repo:    $REPO"
echo "Version: $VERSION"
echo "Asset:   dist/idiauto ($(du -h dist/idiauto | cut -f1))"
echo

gh release create "$VERSION" dist/idiauto \
  --repo "$REPO" \
  --title "idiAuto $VERSION" \
  --notes "${NOTAS:-Build de $(date -Is)}"

echo
echo "============================================"
echo " Release publicado"
echo " URL: https://github.com/$REPO/releases/tag/$VERSION"
echo "============================================"
