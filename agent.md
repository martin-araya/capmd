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
pytest                       # todo
pytest tests/clean           # un bloque
pytest --update-golden       # regenerar expectativas de los cleaners
ruff check . && mypy src/capmd/core
```

Los golden files viven en `tests/golden/`. Si un cambio altera un golden, **revisar el diff a mano** antes de regenerarlo: el diff es la evidencia de si el cleaner mejoró o rompió algo.

## Convenciones

- Commits convencionales: `feat(clean): dehyphenation heuristic`, `fix(pdf): offset off-by-one`.
- Una fase del roadmap = una rama = un PR (o un commit si vas directo a main).
- Al cerrar una fase, marcarla en `roadmap.md`.
- Docstrings en los limpiadores explicando **qué patrón detectan y qué caso deliberadamente no tocan** (el falso positivo importa más que el positivo).

## Qué no hacer

- No agregar dependencias nuevas sin justificarlo contra las que ya están.
- No vendorizar markitdown ni parchearlo en runtime; si algo le falta, se resuelve en `clean/` o en un plugin propio (fase K1).
- No implementar fases adelantadas "de paso". Si una fase necesita algo de otra, decirlo y detenerse.
- No escribir código de red que no sea el passthrough explícito a Azure. Todo lo demás es local.
- No asumir que el PDF tiene texto: siempre validar antes de convertir.
