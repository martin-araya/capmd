#!/usr/bin/env sh
# install-hooks.sh — apunta core.hooksPath al directorio versionado de hooks.
#
#   Uso:  scripts/install-hooks.sh
#
# Tras clonar el repo (o en cualquier momento), corre esto una vez para que
# `git tag` dispare el post-tag hook y por ende el release pipeline (J3).

set -e

HOOKS_DIR="$(cd "$(dirname "$0")/hooks" && pwd)"
REPO_ROOT="$(cd "$HOOKS_DIR/.." && pwd)"

cd "$REPO_ROOT"

# Marcar ejecutables (en caso de que el checkout los haya perdido).
chmod +x "$HOOKS_DIR/post-tag"

# Apuntar core.hooksPath al directorio versionado.
git config core.hooksPath "$HOOKS_DIR"

echo "[install-hooks] core.hooksPath → $HOOKS_DIR"
echo "[install-hooks] Próximo `git tag -a vX.Y.Z -m '...'` disparará scripts/release.sh."
