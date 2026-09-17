#!/usr/bin/env bash
# bump-version.sh — sugiere y aplica la siguiente versión SemVer.
#
#   Uso:  scripts/bump-version.sh [WORKDIR]
#
#   WORKDIR  opcional; default el repo root. Útil para tests que no quieren
#            tocar el pyproject.toml real.
#
# Requiere git-cliff en PATH. Parchea pyproject.toml con la nueva version,
# imprime el diff sugerido, y deja el commit al maintainer.
#
# El maintainer debe:
#   1. Revisar el cambio en pyproject.toml
#   2. Actualizar el header de CHANGELOG.md (cliff lo regenera en cada release)
#   3. Commit + git tag -a vX.Y.Z -m "release: vX.Y.Z"
#   4. El hook post-tag dispara el build + release completo (J3)

set -euo pipefail

WORKDIR="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$WORKDIR"

if ! command -v git-cliff >/dev/null 2>&1; then
  echo "ERROR: git-cliff no está instalado." >&2
  echo "  brew install git-cliff   # macOS" >&2
  echo "  cargo install git-cliff  # cross-platform" >&2
  exit 1
fi

NEXT_VER="$(git-cliff --bump)"
if ! [[ "$NEXT_VER" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "ERROR: git-cliff devolvió '$NEXT_VER', no parece SemVer." >&2
  exit 1
fi

CUR_VER="$(grep -E '^version\s*=' pyproject.toml | head -1 | sed -E 's/.*"([0-9.]+)".*/\1/')"
if [ -z "$CUR_VER" ]; then
  echo "ERROR: no se pudo parsear version actual de pyproject.toml" >&2
  exit 1
fi
echo "Versión actual: $CUR_VER"
echo "Próxima versión: $NEXT_VER"

if [ "$CUR_VER" = "$NEXT_VER" ]; then
  echo "Sin cambios: ya estás en $CUR_VER." >&2
  exit 0
fi

# Parcheo in-place con backup efímero.
cp pyproject.toml pyproject.toml.bak
sed -i.tmp "s/^version = \"${CUR_VER}\"/version = \"${NEXT_VER}\"/" pyproject.toml
rm -f pyproject.toml.tmp pyproject.toml.bak

echo
echo "Diff de pyproject.toml:"
git diff --no-color pyproject.toml || true
echo
echo "Próximo paso:"
echo "  1. Revisá el diff"
echo "  2. git add pyproject.toml && git commit -m \"chore(release): bump ${CUR_VER} -> ${NEXT_VER}\""
echo "  3. git tag -a v${NEXT_VER} -m \"release: v${NEXT_VER}\"   # el hook dispara el release"
