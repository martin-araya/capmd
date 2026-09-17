# Development setup

Esta guía es para contributors (humanos y agentes IA). Cubre el setup
del dev environment, la suite de tests, y los workflows de release.

## Setup

```bash
# 1. Clone
git clone https://github.com/martin-araya/capmd
cd capmd

# 2. Editable install con dev + docs extras
uv pip install -e '.[dev,docs]'

# 3. Verify
pytest -q                  # debe pasar
ruff check .               # sin issues
mypy src/capmd             # sin errores
make docs                  # sphinx build (opcional)
```

Requiere Python 3.10+, `uv` (recomendado), `git`, `gh` (para releases).

## Tests

```bash
pytest                       # todo (corre coverage con --cov-fail-under=90)
pytest tests/clean           # un bloque (todos los cleaners)
pytest --update-golden       # regenera los golden files (J2)
pytest --cov=capmd.X --cov-fail-under=100 tests/test_X.py   # 100% en un módulo
pytest tests/test_docs.py -v # ejecuta bloques bash del README (J5)
```

Coverage está wired en `pyproject.toml` (`[tool.coverage.run/report]`).
`--cov-fail-under=90` falla el build si baja del umbral. Las excepciones
defensivas inalcanzables se marcan con `# pragma: no cover` en el código.

### Layout

- `tests/clean/` — un `test_clean_<nombre>.py` por cleaner.
- `tests/fixtures/build.py` — 14 PDF generators (reportlab).
- `tests/test_golden_pipeline.py` + `tests/golden/test_golden_pipeline/*.md` — golden files (J2).
- `tests/test_j1_coverage_*.py` — coverage de los huecos identificados (J1).
- `tests/test_publish.py`, `tests/test_verify_pypi_install.py` — J4 scripts.
- `tests/test_changelog.py`, `tests/test_bump_version.py`, `tests/test_release_script.py` — J3.
- `tests/test_docs.py` — J5 (parsea README y ejecuta bloques bash).
- `tests/test_install.py` — I1 (wheel + entry point).

### Golden files (J2)

Los golden files viven en `tests/golden/test_golden_pipeline/*.md`. Cada
uno es el output esperado de correr `Engine.convert_path(pdf) →
default_pipeline.run(...)` sobre uno de los 14 fixtures. La mecánica usa
[syrupy](https://github.com/syrupy-project/syrupy) con un
`MarkdownSnapshotExtension` custom definido en `tests/conftest.py`.
`--update-golden` es sinonimo de `--snapshot-update`. Si un cambio altera
un golden, **revisar el diff a mano** antes de regenerarlo.

### Test contracto (J5)

`tests/test_docs.py` parsea bloques `\`\`\`bash` del README y los ejecuta
contra el binario `capmd` instalado en el test venv, validando exit 0 +
output no vacío. Mantiene el README ejecutable.

## Conventions

- **Commits convencionales** (sin enforcement; documentados): `feat(clean): dehyphenation heuristic`, `fix(pdf): offset off-by-one`, `chore(release): bump 0.1.0 -> 0.2.0`. Tipos: `feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert`. Scope opcional. `BREAKING CHANGE:` o `!` → major bump.
- Una fase del roadmap = una rama = un PR (o un commit si vas directo a main).
- Al cerrar una fase, marcarla en `roadmap.md` con ✅ y un bloque detallado.

## Docstrings

- **Cleaners**: el module docstring debe explicar (1) qué reescribe, (2) qué NO toca (false-positive guards), (3) link a [docs/cleaners.md](cleaners.md). Sphinx + autodoc + napoleon extraen estos.
- **Otros módulos**: Google o NumPy style (Args/Returns/Raises) para que napoleon los renderice.
- **No docstrings inline en el cuerpo de las funciones cortas**: preferí un buen nombre y un type hint.

## Versionado y changelog (J3)

```bash
brew install git-cliff           # o cargo install git-cliff
bash scripts/install-hooks.sh    # git config core.hooksPath scripts/hooks
bash scripts/bump-version.sh     # sugiere proxima version y parchea pyproject.toml
git tag -a v0.2.0 -m "..."       # el hook dispara scripts/release.sh
```

`cliff.toml` parsea conventional commits. `scripts/release.sh` construye
sdist + wheel + bottles + crea GitHub Release. `scripts/hooks/post-tag`
es el trigger (sólo annotated tags `vX.Y.Z`).

## Publicación a PyPI (J4)

```bash
UV_PUBLISH_TOKEN=$TESTPYPI_TOKEN bash scripts/publish.sh 0.2.0 --to testpypi
UV_PUBLISH_TOKEN=$TESTPYPI_TOKEN bash scripts/verify-pypi-install.sh 0.2.0 --target testpypi
UV_PUBLISH_TOKEN=$PYPI_TOKEN bash scripts/publish.sh 0.2.0 --to pypi
UV_PUBLISH_TOKEN=$PYPI_TOKEN bash scripts/verify-pypi-install.sh 0.2.0
```

Tokens en `~/.config/capmd/pypi.env` (chmod 600), NUNCA commitearlos.

## Documentación Sphinx (J5)

```bash
make docs              # build HTML en docs/_build/html/
make docs-clean        # wipe _build
make test-docs         # corre tests/test_docs.py
```

Requiere `pip install 'capmd[docs]'` (sphinx + myst-parser + furo + sphinx-copybutton).

## Release checklist

Para un release end-to-end (de un cambio a un PyPI wheel):

1. Commit con conventional commit (alcanza para `feat:` → minor bump).
2. `bash scripts/bump-version.sh` — sugiere la próxima version.
3. Revisar el diff de `pyproject.toml`, commit.
4. `git tag -a vX.Y.Z -m "release: vX.Y.Z"` — el hook dispara `scripts/release.sh`.
5. `gh release view vX.Y.Z` — verificar que la release existe con assets.
6. `UV_PUBLISH_TOKEN=$TESTPYPI_TOKEN bash scripts/publish.sh X.Y.Z --to testpypi`.
7. `UV_PUBLISH_TOKEN=$TESTPYPI_TOKEN bash scripts/verify-pypi-install.sh X.Y.Z --target testpypi`.
8. Si OK, mismo con `--to pypi`.
9. `make docs && git checkout -b gh-pages && cp -r docs/_build/html/* . && git push` (si tenés branch gh-pages configurado).

## Tests que requieren red

`tests/test_docs.py` corre bloques bash del README; sin red no puede
instalar `capmd` desde PyPI. Para development local, asumí que `capmd`
está en PATH (lo cual es el caso con `uv pip install -e '.[dev]'`).

Tests que tocan PyPI real (`test_verify_pypi_install.py` end-to-end con
TestPyPI) están marcados para invocación manual vía `bash
scripts/verify-pypi-install.sh`, NO pytest.

## License y contribuciones

MIT. PRs bienvenidos via GitHub. Para cambios grandes, abrir un issue
primero. El maintainer es @martin-araya en GitHub.
