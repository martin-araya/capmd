#!/usr/bin/env bash
# Release script para capmd.  Prepara sdist + bottles + tag + GitHub Release
# assets en un solo comando.  Pensado para correr localmente (no hay GH CI por
# restricciones del proyecto).
#
#   Uso:  scripts/release.sh X.Y.Z [release-notes-file]
#
#   X.Y.Z  La versión que se va a publicar (debe coincidir con pyproject.toml).
#   release-notes-file  Path a un .md con notas.  Si no se pasa, lo genera
#                       automáticamente desde los commits desde el último tag.
#
# Pre-requisitos:
#   - brew, git, gh autenticado (`gh auth status` verde), uv o python con build/
#   - Working tree limpio (sin cambios sin commitear)
#   - main branch al día con origin/main

set -euo pipefail

if [ $# -lt 1 ]; then
  echo "Uso: $0 X.Y.Z [notas.md]" >&2
  exit 64
fi

VERSION="$1"
NOTES_FILE="${2:-}"

# Validar formato semver simple
if ! [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "ERROR: '$VERSION' no parece semver (esperado X.Y.Z)" >&2
  exit 65
fi

HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"

# 0. Pre-flight
if ! command -v git >/dev/null; then
  echo "ERROR: git no está instalado" >&2
  exit 1
fi
if ! command -v gh >/dev/null; then
  echo "ERROR: gh (GitHub CLI) no está instalado. brew install gh" >&2
  exit 1
fi
if ! gh auth status >/dev/null 2>&1; then
  echo "ERROR: gh no está autenticado. Corré `gh auth login` primero." >&2
  exit 1
fi

# Working tree limpio
if [ -n "$(git status --porcelain)" ]; then
  echo "ERROR: working tree tiene cambios sin commitear. Commit/stash primero." >&2
  git status --short >&2
  exit 1
fi

# En main
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [ "$BRANCH" != "main" ]; then
  echo "WARN: estás en branch '$BRANCH', no 'main'. Ctrl-C en los próximos 5s para abortar."
  sleep 5
fi

# 1. Verificar versión en pyproject.toml
PYPROJECT_VER="$(grep -E '^version\s*=' pyproject.toml | head -1 | sed -E 's/.*"([0-9.]+)".*/\1/')"
if [ "$PYPROJECT_VER" != "$VERSION" ]; then
  echo "ERROR: la versión en pyproject.toml es '$PYPROJECT_VER', no coincide con $VERSION" >&2
  exit 1
fi

# 2. Correr tests (suite completa + lint rápido)
echo "[release] corriendo pytest"
if ! python3 -m pytest tests -q --no-header -x >/tmp/release-pytest.log 2>&1; then
  tail -50 /tmp/release-pytest.log >&2
  echo "ERROR: pytest falló. Arreglá y reintentá." >&2
  exit 1
fi
echo "[release] pytest OK"

echo "[release] corriendo ruff check"
if ! ruff check src/capmd tests >/tmp/release-ruff.log 2>&1; then
  cat /tmp/release-ruff.log >&2
  echo "ERROR: ruff encontró issues. Arreglá y reintentá." >&2
  exit 1
fi
echo "[release] ruff OK"

# 3. Build sdist + wheel
echo "[release] construyendo sdist + wheel"
mkdir -p dist
python3 -m build --sdist --wheel --outdir dist/

# 4. Calcular sha256 del sdist
SDIST_SHA="$(shasum -a 256 "dist/capmd-${VERSION}.tar.gz" | awk '{print $1}')"
echo "[release] sha256 sdist = $SDIST_SHA"

# 5. Actualizar Formula/capmd.rb con url + sha256 frescos
python3 - <<EOF
import re, pathlib
p = pathlib.Path("Formula/capmd.rb")
text = p.read_text()
text = re.sub(r'^(\s*url\s+)"[^"]+"', rf'\1"https://github.com/martin-araya/capmd/archive/refs/tags/v${VERSION}.tar.gz"', text, flags=re.MULTILINE)
text = re.sub(r'^(\s*sha256\s+)"[a-fA-F0-9]+"', rf'\1"${SDIST_SHA}"', text, flags=re.MULTILINE)
p.write_text(text)
print("[release] Formula/capmd.rb actualizado")
EOF

# 6. Generar notas (si no se pasó archivo)
if [ -z "$NOTES_FILE" ]; then
  NOTES_FILE="$(mktemp -t capmd-release-notes.XXXXXX.md)"
  LAST_TAG="$(git describe --tags --abbrev=0 2>/dev/null || echo "")"
  if [ -n "$LAST_TAG" ]; then
    {
      echo "# capmd v$VERSION"
      echo
      echo "## Cambios desde $LAST_TAG"
      echo
      git log --oneline "${LAST_TAG}..HEAD" || true
    } > "$NOTES_FILE"
  else
    {
      echo "# capmd v$VERSION"
      echo
      echo "Primera release con bottles del tap."
    } > "$NOTES_FILE"
  fi
fi
echo "[release] notas en: $NOTES_FILE"

# 7. Llamar build-bottles.sh para producir las botellas firmadas
echo "[release] corriendo scripts/build-bottles.sh"
scripts/build-bottles.sh

# 8. Commit + tag
echo "[release] comiteando cambios de release"
git add Formula/capmd.rb dist/ pyproject.toml 2>/dev/null || true
if [ -n "$(git status --porcelain)" ]; then
  git commit -m "release: v$VERSION"
fi
git tag -a "v$VERSION" -F "$NOTES_FILE"

# 9. Push tag
echo "[release] pusheando tag v$VERSION (confirmá en 10s o Ctrl-C)"
sleep 10
git push origin main
git push origin "v$VERSION"

# 10. Crear GitHub Release + upload assets
echo "[release] creando GitHub Release v$VERSION"
ASSETS=(
  "dist/capmd-${VERSION}.tar.gz"
  "dist/capmd-${VERSION}-py3-none-any.whl"
)
shopt -s nullglob
for bottle in capmd-${VERSION}.*.bottle.tar.gz; do
  ASSETS+=( "$bottle" )
done
shopt -u nullglob

gh release create "v$VERSION" \
  --title "capmd v$VERSION" \
  --notes-file "$NOTES_FILE" \
  "${ASSETS[@]}"

echo
echo "[release] OK — GitHub Release v$VERSION creada con ${#ASSETS[@]} asset(s):"
for a in "${ASSETS[@]}"; do
  echo "  - https://github.com/martin-araya/capmd/releases/download/v${VERSION}/$(basename "$a")"
done
echo
echo "Próximo paso: en otra macOS limpia, correr el checklist de"
echo "'instalación limpia' (ver README.md sección Homebrew + I4)."
