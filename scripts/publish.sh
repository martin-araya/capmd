#!/usr/bin/env bash
# publish.sh — sube el sdist + wheel a PyPI / TestPyPI.
#
#   Uso:  scripts/publish.sh X.Y.Z --to {testpypi|pypi} [--dry-run] [WORKDIR]
#
#   WORKDIR  opcional; default el repo root. Útil para tests que no quieren
#            tocar el pyproject.toml real.
#
# Pre-requisitos:
#   - dist/capmd-X.Y.Z.{tar.gz,whl} construido (correr scripts/release.sh antes)
#   - UV_PUBLISH_TOKEN en env (token de PyPI o TestPyPI segun --to)
#   - uv instalado en PATH (lee UV_PUBLISH_TOKEN nativamente)
#
# Workflow recomendado:
#   1. bash scripts/release.sh 0.2.0   # construye sdist + wheel + bottles
#   2. UV_PUBLISH_TOKEN=$TESTPYPI_TOKEN bash scripts/publish.sh 0.2.0 --to testpypi
#   3. UV_PUBLISH_TOKEN=$TESTPYPI_TOKEN bash scripts/verify-pypi-install.sh 0.2.0 --target testpypi
#   4. Si smoke OK, rep. con --to pypi
#
# NO subir el token al repo. Mantenerlo en ~/.config/capmd/pypi.env (chmod 600)
# o un keychain (1Password, macOS Keychain).

set -euo pipefail

if [ $# -lt 1 ]; then
  echo "Uso: $0 X.Y.Z --to {testpypi|pypi} [--dry-run] [WORKDIR]" >&2
  exit 64
fi

VERSION="$1"
shift

if ! [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "ERROR: '$VERSION' no parece semver (esperado X.Y.Z)" >&2
  exit 65
fi

TO="testpypi"  # safe default
DRY_RUN="false"
WORKDIR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --to)
      TO="$2"
      shift 2
      ;;
    --to=*)
      TO="${1#*=}"
      shift
      ;;
    --dry-run)
      DRY_RUN="true"
      shift
      ;;
    --help|-h)
      echo "Uso: $0 X.Y.Z --to {testpypi|pypi} [--dry-run] [WORKDIR]" >&2
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

if [[ "$TO" != "testpypi" && "$TO" != "pypi" ]]; then
  echo "ERROR: --to debe ser testpypi o pypi (got: $TO)" >&2
  exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "ERROR: uv no esta en PATH. brew install uv" >&2
  exit 1
fi

# Resolver WORKDIR (default = repo root al lado de scripts/).
if [ -z "$WORKDIR" ]; then
  WORKDIR="$(cd "$(dirname "$0")/.." && pwd)"
fi
cd "$WORKDIR"

# 1. Validar version contra pyproject.toml
PYPROJECT_VER="$(grep -E '^version\s*=' pyproject.toml | head -1 | sed -E 's/.*"([0-9.]+)".*/\1/')"
if [ -z "$PYPROJECT_VER" ]; then
  echo "ERROR: no se pudo parsear version actual de pyproject.toml" >&2
  exit 1
fi
if [ "$PYPROJECT_VER" != "$VERSION" ]; then
  echo "ERROR: pyproject.toml version '$PYPROJECT_VER' != '$VERSION'" >&2
  exit 1
fi

# 2. Validar artefactos (los construye scripts/release.sh)
SDIST="dist/capmd-${VERSION}.tar.gz"
WHEEL="dist/capmd-${VERSION}-py3-none-any.whl"
if [ ! -f "$SDIST" ] || [ ! -f "$WHEEL" ]; then
  echo "ERROR: artefactos faltan. Correr scripts/release.sh $VERSION primero." >&2
  echo "  esperaba: $SDIST y $WHEEL" >&2
  exit 1
fi

# 3. Token requerido salvo en --dry-run
if [ "$DRY_RUN" != "true" ] && [ -z "${UV_PUBLISH_TOKEN:-}" ]; then
  echo "ERROR: UV_PUBLISH_TOKEN no esta seteado. Para dry-run use --dry-run." >&2
  exit 1
fi

# 4. URL segun target
case "$TO" in
  testpypi) PUBLISH_URL="https://test.pypi.org/legacy/" ;;
  pypi)     PUBLISH_URL="https://upload.pypi.org/legacy/" ;;
esac

# 5. Dry-run: listar artefactos y abortar antes de tocar red
if [ "$DRY_RUN" = "true" ]; then
  echo "[publish] DRY RUN a $TO ($PUBLISH_URL):"
  ls -lh "$SDIST" "$WHEEL"
  exit 0
fi

echo "[publish] subiendo a $TO ($PUBLISH_URL)"
uv publish "$SDIST" "$WHEEL" --publish-url "$PUBLISH_URL"

echo
echo "[publish] OK — $VERSION publicado en $TO"
echo "Próximo paso: bash scripts/verify-pypi-install.sh $VERSION --target $TO"
