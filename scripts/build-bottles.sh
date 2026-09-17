#!/usr/bin/env bash
# Construye las botellas firmadas de capmd para macOS arm64 (I4).
#
#   Uso:  scripts/build-bottles.sh
#
# Asume que estás corriendo en un Mac arm64 con Homebrew + python@3.12
# instalados.  Genera la bottle del OS actual y aplica al Formula los
# sha256 correspondientes (los merge via `brew bottle`).
#
# Targets soportados (los que `sw_vers -productVersion` matchee):
#   - arm64_sequoia  (macOS 15)
#   - arm64_sonoma   (macOS 14)
#
# Para otra variante hay que correr esto en una VM con ese macOS, o via
# `brew test-bot` (más allá del MVP de I4; ver roadmap.md).
#
# El script aborta si `brew audit` falla: arreglá los issues antes de
# subir la botella.

set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"

if ! command -v brew >/dev/null 2>&1; then
  echo "ERROR: brew no está en PATH. Instalá Homebrew primero:" >&2
  echo '  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"' >&2
  exit 1
fi

# 1. Detectar el target (macOS × arch).
ARCH="$(/usr/bin/uname -m)"
if [ "$ARCH" != "arm64" ]; then
  echo "ERROR: bottles se generan en arm64; estás en $ARCH." >&2
  echo "       Para otra arch usá una VM o `brew test-bot`." >&2
  exit 1
fi

MACOS_VER="$(/usr/bin/sw_vers -productVersion)"
case "$MACOS_VER" in
  15.*) TARGET="arm64_sequoia" ;;
  14.*) TARGET="arm64_sonoma"  ;;
  *)
    echo "ERROR: macOS $MACOS_VER no soportado por el MVP de I4." >&2
    echo "       Targets actuales: arm64_sonoma, arm64_sequoia." >&2
    exit 1
    ;;
esac
echo "[bottles] target = $TARGET (macOS $MACOS_VER)"

# 2. Validar pyproject / formula antes de gastar tiempo compilando.
VERSION="$(grep -E '^version\s*=' pyproject.toml | head -1 | sed -E 's/.*"([0-9.]+)".*/\1/')"
if [ -z "$VERSION" ]; then
  echo "ERROR: no se pudo extraer la versión de pyproject.toml" >&2
  exit 1
fi
ROOT_URL="https://github.com/martin-araya/capmd/releases/download/v${VERSION}"
echo "[bottles] version = $VERSION, root_url = $ROOT_URL"

# 3. Build del wheel/sdist (si no existen ya).
mkdir -p dist
if [ ! -f "dist/capmd-${VERSION}.tar.gz" ] || [ ! -f "dist/capmd-${VERSION}-py3-none-any.whl" ]; then
  echo "[bottles] construyendo sdist+wheel para capmd $VERSION"
  uv pip install --system --quiet build || true
  /Users/martin/.local/share/uv/python/cpython-3.*/bin/python3 -m build --sdist --wheel --outdir dist/ 2>&1 \
    || python3 -m build --sdist --wheel --outdir dist/
else
  echo "[bottles] dist/capmd-${VERSION}.{tar.gz,whl} ya existen, skip build"
fi

# 4. `brew audit` antes de invertir tiempo en bottle.
echo "[bottles] corre `brew audit --strict` antes de generar bottles"
if ! brew audit --strict --new ./Formula/capmd.rb; then
  echo "ERROR: `brew audit` falló. Arreglá los issues de estilo y reintentá." >&2
  exit 1
fi

# 5. Build + bottle del target.
echo "[bottles] construyendo con `--build-bottle`"
brew install --formula ./Formula/capmd.rb --build-bottle

# `brew uninstall` deja el cellar limpio.
brew uninstall capmd >/dev/null 2>&1 || true

echo "[bottles] `brew bottle` generando $TARGET.bottle.tar.gz"
brew bottle --root-url "$ROOT_URL" --no-rebuild ./Formula/capmd.rb

# 6. El comando anterior emite un parche del estilo
#       `capmd--bottle-<random>.rb`
#    con un bloque `sha256 "<hash>"` por target compatible. Lo aplicamos al
#    Formula y borramos el parche.
PATCH_GLOB="capmd--bottle-*.rb"
shopt -s nullglob
PATCH_FILES=( $PATCH_GLOB )
shopt -u nullglob

if [ ${#PATCH_FILES[@]} -eq 0 ]; then
  echo "ERROR: `brew bottle` no produjo un parche." >&2
  echo "       (¿Cambiaste $TARGET a algo que no se compila?)" >&2
  exit 1
fi

echo "[bottles] parche(s) a aplicar:"
for f in "${PATCH_FILES[@]}"; do
  echo "  - $f"
done

# Aplicar todos los parches; cada uno contiene una sola línea `sha256 "<hash>"`.
# Orden estable: de mayor hash de bottle a menor (no importa realmente, son
# bloques separados).
for f in "${PATCH_FILES[@]}"; do
  cat "$f" >> Formula/capmd.rb
  rm "$f"
done

# 7. Resumen.
echo
echo "[bottles] OK. Listos para subir como assets del GitHub Release:"
echo "  dist/capmd-${VERSION}.tar.gz"
echo "  dist/capmd-${VERSION}-py3-none-any.whl"
for b in capmd-${VERSION}.${TARGET}.bottle.tar.gz \
         capmd-${VERSION}.*.bottle.tar.gz; do
  [ -f "$b" ] && echo "  $b"
done
echo
echo "Próximo paso: scripts/release.sh ${VERSION}"
