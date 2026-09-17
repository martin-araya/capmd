#!/usr/bin/env bash
# Smoke test del install como tool (I1).
# Buildea el wheel, lo instala en un venv efímero y verifica que el binario
# corre sin un venv activo. Útil para correr en una máquina limpia (macOS/Linux).
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"

PYTHON_BIN="${PYTHON_BIN:-python3.12}"
VENV_DIR="$(mktemp -d -t capmd-verify-XXXXXX)/venv"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  PYTHON_BIN=""
  # Buscar un Python >= 3.10 disponible (cualquier 3.10/3.11/3.12/3.13/3.14)
  for candidate in python3.14 python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      version="$("$candidate" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
      major="${version%.*}"
      minor="${version#*.}"
      if [ "$major" = "3" ] && [ "$minor" -ge 10 ]; then
        PYTHON_BIN="$candidate"
        echo "[verify-install] python3.12 no encontrado, usando $candidate ($("$candidate" --version 2>&1))"
        break
      fi
    fi
  done
  if [ -z "$PYTHON_BIN" ]; then
    echo "[verify-install] ERROR: no hay Python >= 3.10 disponible" >&2
    echo "[verify-install]        instalá 3.10+ (brew install python@3.12) o fijá PYTHON_BIN=/ruta/al/binario" >&2
    exit 1
  fi
fi

cleanup() {
  rm -rf "$(dirname "$VENV_DIR")"
}
trap cleanup EXIT

ORIGINAL_PATH="$PATH"

echo "[verify-install] 1/5  creando venv efímero en $VENV_DIR"
"$PYTHON_BIN" -m venv "$VENV_DIR"

echo "[verify-install] 2/5  instalando build + pip (upgrade)"
"$VENV_DIR/bin/pip" install --quiet --upgrade pip build

echo "[verify-install] 3/5  construyendo wheel"
DIST_DIR="$(mktemp -d -t capmd-dist-XXXXXX)"
"$VENV_DIR/bin/python" -m build --wheel --outdir "$DIST_DIR" "$HERE" >/dev/null

echo "[verify-install] 4/5  instalando el wheel en el venv"
"$VENV_DIR/bin/pip" install --quiet "$DIST_DIR"/capmd-*.whl

if [ ! -x "$VENV_DIR/bin/capmd" ]; then
  echo "[verify-install] ERROR: $VENV_DIR/bin/capmd no existe o no es ejecutable" >&2
  exit 1
fi

echo "[verify-install] 5/5  corriendo capmd sin venv activo (VIRTUAL_ENV='')"
export PATH="$VENV_DIR/bin"
export VIRTUAL_ENV=""

"$VENV_DIR/bin/capmd" --help
"$VENV_DIR/bin/capmd" version

echo
echo "OK: capmd instala y corre sin un venv activo."

# Restaurar PATH antes del cleanup (la función usa rm, dirname, etc.)
unset VIRTUAL_ENV
export PATH="$ORIGINAL_PATH"
