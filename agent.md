# agent.md — contexto para agentes en `capmd`

## Qué es este proyecto

CLI de Python para macOS que recorta el capítulo de un libro (PDF/EPUB/DOCX), lo convierte a Markdown con [MarkItDown](https://github.com/microsoft/markitdown) y lo limpia para que sirva para leer y estudiar. Es un **paquete independiente que consume `markitdown` desde PyPI**, no un fork.

El plan está en `roadmap.md`, organizado en bloques A–K con fases numeradas. Cada fase tiene un criterio de test explícito. **Se trabaja de a una fase por vez**: implementar, testear, commitear, siguiente.

## Lo que hay que saber de MarkItDown antes de tocar código

- API actual: `MarkItDown(enable_plugins=False)`, `md.convert_local(path)` → `result.markdown`.
  - `result.text_content` es de una versión vieja. Si ves eso en un ejemplo, está desactualizado.
  - Usar siempre la función más estrecha: `convert_local()` para archivos, `convert_stream()` para bytes, `convert_response()` para HTTP. `convert()` es permisivo a propósito y no lo queremos.
- Extras de instalación: `[pdf]`, `[docx]`, `[pptx]`, `[xlsx]`, `[xls]`, `[outlook]`, `[az-doc-intel]`, `[az-content-understanding]`, `[audio-transcription]`, `[youtube-transcription]`, `[all]`.
- CLI oficial (para passthrough): `-o`, `-d`, `-e <endpoint>`, `--use-cu`, `--cu-endpoint`, `--use-plugins`, `--list-plugins`. Env: `MARKITDOWN_DOCINTEL_ENDPOINT`, `MARKITDOWN_CU_ENDPOINT`.
- `llm_client` / `llm_model` / `llm_prompt` describen imágenes **solo en pptx e imágenes sueltas**. Para OCR dentro de PDF hace falta el plugin `markitdown-ocr` con `enable_plugins=True`.
- Lo que MarkItDown **no** hace y nosotros sí: recorte por capítulo, extracción de imágenes de PDF, marcadores de página, limpieza de maquetación, reconstrucción de headings.

## Stack

- Python 3.12 (mínimo 3.10), `uv` como gestor.
- `typer` + `rich` para CLI. `pypdf` para recorte y outline. `pypdfium2` para imágenes y texto posicional. `ebooklib` para EPUB (C9).
- **No usar PyMuPDF/fitz**: es AGPL y contamina la licencia del paquete. Si un ejemplo lo usa, portarlo a `pypdfium2`.
- **ebooklib es AGPL** (C9): si el proyecto busca relicensiar a algo más permisivo, reemplazar `ebooklib` por `zipfile` + `defusedxml` para parsear el spine/nav. ~150 LoC, factible.
- `pytest` + golden files. `ruff` para lint y format. `mypy --strict` sobre `src/capmd/core`.

## Arquitectura

```
src/capmd/
├── cli.py        # typer, solo parsing y presentación — sin lógica de negocio
├── config.py     # TOML + perfiles por libro + precedencia
├── errors.py     # CapmdError y subclases, exit codes 1–5
├── models.py     # dataclasses del dominio
├── sources/      # pdf.py, epub.py, office.py — leer y recortar
├── convert/      # engine.py (wrapper MarkItDown), plugins.py
├── clean/        # pipeline.py + un módulo por limpiador
├── images/       # extract.py, anchor.py
├── output/       # writer.py, frontmatter.py, split.py
└── report.py     # stats y warnings de la corrida
```

## Reglas de implementación

1. **Cada limpiador es una función pura.** Firma `(texto, ctx) -> (texto, stats)`. Sin I/O, sin estado global. Se registran en `clean/pipeline.py` con orden explícito.
2. **El orden del pipeline importa** y está fijado en el roadmap (D2 → D14). No reordenar sin actualizar los golden files y justificarlo.
3. **Nada toca el interior de los fences de código.** Cualquier limpiador nuevo debe respetar los bloques ``` ya detectados.
4. **stdout es solo el resultado.** Logs, progress y warnings van a stderr. `capmd convert x.pdf > out.md` tiene que producir un `.md` sin una línea de log.
5. **Errores con mensaje humano.** Nunca un traceback al usuario. Cada `CapmdError` dice qué pasó y qué hacer (ej: "falta `uv pip install 'markitdown[pdf]'`").
6. **Degradar, no fallar.** Sin API key → seguir sin descripción de imágenes, avisando una vez. Sin outline → heurística. Tabla dudosa → marcar, no inventar.
7. **Determinismo.** Dos corridas iguales producen los mismos nombres de archivo y el mismo contenido, salvo `converted_at`.
8. **Fixtures generados, no material con copyright.** Los PDFs de test se crean con `reportlab` en `tests/fixtures/build.py`.

## Tests

```bash
pytest                       # todo (corre coverage con --cov-fail-under=90)
pytest tests/clean           # un bloque
pytest --update-golden       # regenerar los golden files (J2)
pytest --cov=capmd.X --cov-fail-under=100 tests/test_X.py   # 100% en un módulo
ruff check . && mypy src/capmd
```

Coverage está wired en `pyproject.toml` (`[tool.coverage.run/report]`). `--cov-fail-under=90` falla el build si baja del umbral. Las excepciones defensivas inalcanzables se marcan con `# pragma: no cover` en el código. Los tests de J1 viven en `tests/test_j1_coverage_gaps.py` + `tests/test_j1_coverage_inspect.py`.

Los **golden files (J2)** viven en `tests/golden/test_golden_pipeline/*.md`. Cada uno es el output esperado de correr `Engine.convert_path(pdf) → default_pipeline.run(...)` sobre uno de los 14 fixtures de `tests/fixtures/build.py`. La mecanica usa [syrupy 4.x](https://github.com/syrupy-project/syrupy) con un `MarkdownSnapshotExtension` custom definido en `tests/conftest.py`. `--update-golden` es sinonimo de `--snapshot-update` (el conftest inyecta la traduccion). Si un cambio altera un golden, **revisar el diff a mano** antes de regenerarlo.

## Shell completion (zsh por default en macOS)

`capmd --install-completion <shell>` está habilitado vía Typer (H4). El
script queda en `~/.zfunc/_capmd` (zsh), `~/.bash_completions/capmd.sh`
(bash) o `~/.config/fish/completions/capmd.fish` (fish). En CI los tests
usan `_TYPER_COMPLETE_TEST_DISABLE_SHELL_DETECTION=1` para invocar
`--show-completion <shell>` y `HOME=$tmp` para no tocar el filesystem
del usuario. Si desactivás `add_completion`, rompes esos tests y H4
queda sin documentar en `--help`.

## Convenciones

- **Commits convencionales** (sin enforcement; documentados): `feat(clean): dehyphenation heuristic`, `fix(pdf): offset off-by-one`, `chore(release): bump 0.1.0 -> 0.2.0`. Tipos validos: `feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert`. Scope opcional. `BREAKING CHANGE:` en body o `!` despues del tipo -> major bump.
- Una fase del roadmap = una rama = un PR (o un commit si vas directo a main).
- Al cerrar una fase, marcarla en `roadmap.md`.

## Versionado y changelog (J3)

```bash
brew install git-cliff           # o cargo install git-cliff
bash scripts/install-hooks.sh    # git config core.hooksPath scripts/hooks
bash scripts/bump-version.sh     # sugiere próxima version y parchea pyproject.toml
git tag -a v0.2.0 -m "..."       # el hook dispara scripts/release.sh
```

- **`cliff.toml`**: parser de conventional commits. Tipos: `feat/fix/perf/refactor/docs/test/build/ci/style/chore/revert`. `BREAKING CHANGE:` en body o `!` despues del tipo -> bump major.
- **`scripts/hooks/post-tag`**: solo se dispara en annotated tags `vX.Y.Z`; tags lightweight y non-semver se ignoran. Invoca `scripts/release.sh` con el version extraido del ref.
- **`scripts/release.sh`**: ya NO tag-ea internamente (el tag es el trigger). En modo manual (`bash scripts/release.sh X.Y.Z`), skip-ea si el tag existe o lo crea si falta. Siempre: pytest + ruff + build sdist+wheel + sha256 + Formula/capmd.rb patch + build-bottles.sh + gh release create.
- **`scripts/bump-version.sh`**: wrapper sobre `git-cliff --bump` + sed a `pyproject.toml`. El maintainer revisa el diff antes de commit.
- **`CHANGELOG.md`**: bootstrap manual (Keep-a-Changelog format). git-cliff lo regenera en cada release desde `git log` + conventional commits.
- Pre-requisito: `brew install git-cliff` y `gh auth login`. Sin esto el hook falla o aborta.

## Publicación a PyPI (J4)

Tras el GitHub Release, el maintainer sube el wheel + sdist a TestPyPI primero, valida con el smoke test, y luego sube a PyPI real.

```bash
UV_PUBLISH_TOKEN=$TESTPYPI_TOKEN bash scripts/publish.sh 0.2.0 --to testpypi
UV_PUBLISH_TOKEN=$TESTPYPI_TOKEN bash scripts/verify-pypi-install.sh 0.2.0 --target testpypi
UV_PUBLISH_TOKEN=$PYPI_TOKEN bash scripts/publish.sh 0.2.0 --to pypi
UV_PUBLISH_TOKEN=$PYPI_TOKEN bash scripts/verify-pypi-install.sh 0.2.0
```

- **`scripts/publish.sh X.Y.Z --to {testpypi|pypi}`**: valida version + artefactos en `dist/`, requiere `UV_PUBLISH_TOKEN`, llama `uv publish` con el `--publish-url` correspondiente. `--dry-run` no toca red. Acepta `[WORKDIR]` opcional para tests.
- **`scripts/verify-pypi-install.sh X.Y.Z [--target ...]`**: smoke test del contrato J4. Crea venv limpio (`mktemp -t capmd-pypi-verify.*`), `pip install capmd==X.Y.Z`, genera PDF con `tests.fixtures.build`, `capmd convert`, valida exit 0 + markdown no vacio. Skip con `CAPMD_SKIP_PYPI_VERIFY=1`.
- **Tokens**: `pypi-...` para PyPI y TestPyPI, generados en sus respectivos websites. Mantener en `~/.config/capmd/pypi.env` (chmod 600) o keychain. **NUNCA commitear.**
- **markitdown** es runtime dependency declarada en `pyproject.toml` (no vendorizado) con extras `[pdf,docx,pptx,xlsx]`. PyPI resuelve la install via su index.
- **Trusted publishing (OIDC)** NO se usa: requiere CI runner; el proyecto veta GH Actions.
- **No re-upload**: PyPI no permite re-upload de la misma version. Yanking solo via UI web.

## Documentación (J5)

- **README.md** (PyPI long-description) cubre Quickstart + Instalación + Uso + Configuración. El primer bloque de cada user.
- **`docs/`** es el Sphinx site con detalles por módulo, cleaners, troubleshooting. Build via `make docs` (output en `docs/_build/html/`). Theme: Furo.
- **`docs/cleaners.md`** (~800 LoC, J5 emphasis) tiene tabla resumen arriba + 1 sección por cleaner con qué reescribe, qué NO toca, y cómo deshabilitarlo. El docstring de cada cleaner en `src/capmd/clean/` linkea aca.
- **`tests/test_docs.py`** parsea bloques `\`\`\`bash` del README y los ejecuta contra `capmd` instalado. Implementa el test contracto del roadmap J5: "alguien que nunca vio el proyecto convierte un capítulo siguiendo solo el README".
- **`make test-docs`** corre `tests/test_docs.py`. `make docs` rebuild el sitio Sphinx.

## Convenciones de docstrings (J5)

- **Cleaners**: el module docstring debe explicar (1) qué reescribe, (2) qué NO toca (false-positive guards), (3) link a [docs/cleaners.md](docs/cleaners.md). Sphinx + autodoc + napoleon extraen estos para el sitio.
- **Otros módulos**: Google o NumPy style (Args/Returns/Raises) para que napoleon los renderice.
- **No docstrings inline en el cuerpo de las funciones cortas**: preferí un buen nombre y un type hint.

## Qué no hacer
- No agregar dependencias nuevas sin justificarlo contra las que ya están.
- No vendorizar markitdown ni parchearlo en runtime; si algo le falta, se resuelve en `clean/` o en un plugin propio (fase K1).
- No implementar fases adelantadas "de paso". Si una fase necesita algo de otra, decirlo y detenerse.
- No escribir código de red que no sea el passthrough explícito a Azure. Todo lo demás es local.
- No asumir que el PDF tiene texto: siempre validar antes de convertir.
