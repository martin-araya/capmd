#!/usr/bin/env bash
# verify-pypi-install.sh — smoke test del contrato PyPI/J4.
#
#   Uso:  scripts/verify-pypi-install.sh X.Y.Z [--target pypi|testpypi] [WORKDIR]
#
# Crea un venv limpio, hace `pip install capmd==X.Y.Z` desde el target (PyPI
# o TestPyPI), genera un PDF de prueba y corre `capmd convert` para
# verificar que exit 0 y el markdown output no este vacio.
#
# Implementa el test del roadmap J4: "pip install capmd en un venv limpio
# convierte un PDF". Skip-able con CAPMD_SKIP_PYPI_VERIFY=1 (util en CI o
# sandbox sin red).
#
# NO pytest: requiere red + venv + PyPI. Mantenerlo como script manual.

set -euo pipefail

if [ $# -lt 1 ]; then
  echo "Uso: $0 X.Y.Z [--target pypi|testpypi] [WORKDIR]" >&2
  exit 64
fi

VERSION="$1"
shift

if [ "${CAPMD_SKIP_PYPI_VERIFY:-0}" = "1" ]; then
  echo "[verify] skip por CAPMD_SKIP_PYPI_VERIFY=1"
  exit 0
fi

TARGET="pypi"
WORKDIR=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --target)
      TARGET="$2"
      shift 2
      ;;
    --target=*)
      TARGET="${1#*=}"
      shift
      ;;
    --help|-h)
      echo "Uso: $0 X.Y.Z [--target pypi|testpypi] [WORKDIR]" >&2
      exit 0
      ;;
    -*)
      echo "ERROR: arg desconocido: $1" >&2
      exit 1
      ;;
    *)
      WORKDIR="$1"
      shift
      ;;
  esac
done

if [[ "$TARGET" != "pypi" && "$TARGET" != "testpypi" ]]; then
  echo "ERROR: --target debe ser pypi o testpypi (got: $TARGET)" >&2
  exit 1
fi

# Resolver WORKDIR (default = repo root al lado de scripts/).
if [ -z "$WORKDIR" ]; then
  WORKDIR="$(cd "$(dirname "$0")/.." && pwd)"
fi

if ! command -v python3 >/dev/null; then
  echo "ERROR: python3 no esta en PATH" >&2
  exit 1
fi

# Resolver PKG: 'capmd==X.Y.Z' para version explicita, o 'capmd' (latest) si no.
if [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  PKG="capmd==$VERSION"
else
  PKG="capmd"
fi

# Setup directorio de trabajo temporal (no /tmp; mktemp propio).
WORK="$(mktemp -d -t capmd-pypi-verify.XXXXXX)"
trap "rm -rf '$WORK'" EXIT
VENV="$WORK/venv"
PDF="$WORK/sample.pdf"
MARKDOWN="$WORK/out.md"

echo "[verify] target: $TARGET, package: $PKG, workdir: $WORK"

# 1. venv limpio
python3 -m venv "$VENV"
# shellcheck source=/dev/null
. "$VENV/bin/activate"

# 2. pip install capmd
case "$TARGET" in
  testpypi)
    PIP_INDEX="--index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/"
    ;;
  pypi)
    PIP_INDEX=""
    ;;
esac

echo "[verify] pip install $PKG desde $TARGET"
# shellcheck disable=SC2086
pip install --quiet $PIP_INDEX "$PKG"

# 3. Verificar que el entry point queda registrado.
if ! command -v capmd >/dev/null; then
  echo "ERROR: capmd no esta en PATH despues de pip install" >&2
  exit 1
fi

# 4. Generar PDF de prueba usando los fixtures del repo (uno chico).
echo "[verify] generando PDF de prueba"
PYTHONPATH="$WORKDIR:${PYTHONPATH:-}" python3 - <<EOF
from tests.fixtures import build
build.build_headings_pdf("$PDF")
EOF

# 5. capmd convert sobre el PDF.
echo "[verify] capmd convert $PDF -> $MARKDOWN"
capmd convert "$PDF" -o "$MARKDOWN"

# 6. Verificar output.
if [ ! -s "$MARKDOWN" ]; then
  echo "ERROR: markdown output vacio o no existe" >&2
  exit 1
fi

echo "[verify] OK — $VERSION instalado y funcional desde $TARGET"
echo "  venv: $VENV (limpieza en exit via trap)"
