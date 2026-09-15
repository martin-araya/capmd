# roadmap.md — `capmd`

CLI para macOS que toma el capítulo de un libro (PDF/EPUB/DOCX) y lo deja en Markdown limpio, listo para resumir y estudiar. Construida encima de [`microsoft/markitdown`](https://github.com/microsoft/markitdown).

---

## 0. Contexto técnico antes de empezar

Esto define por qué el roadmap tiene los bloques que tiene. Es lo que el repo de markitdown dice hoy, no lo que promete un post:

- **Instalación y extras.** `pip install 'markitdown[all]'`, o extras sueltos: `[pdf]`, `[docx]`, `[pptx]`, `[xlsx]`, `[xls]`, `[outlook]`, `[az-doc-intel]`, `[az-content-understanding]`, `[audio-transcription]`, `[youtube-transcription]`. Requiere Python ≥ 3.10.
- **CLI oficial.** `markitdown archivo.pdf > out.md`, `markitdown archivo.pdf -o out.md`, `cat archivo.pdf | markitdown`. Flags relevantes: `-d` + `-e <endpoint>` (Azure Document Intelligence), `--use-cu` + `--cu-endpoint` (Azure Content Understanding), `--use-plugins`, `--list-plugins`. Variables de entorno: `MARKITDOWN_DOCINTEL_ENDPOINT`, `MARKITDOWN_CU_ENDPOINT`.
- **API Python.** `MarkItDown(enable_plugins=False)` y `md.convert(...)` → `result.markdown` (el campo `.markdown` es el actual; `.text_content` aparece en READMEs viejos de forks). Métodos más estrechos y recomendados por seguridad: `convert_local()`, `convert_stream()`, `convert_response()`.
- **LLM para imágenes.** `MarkItDown(llm_client=..., llm_model=..., llm_prompt=...)` describe imágenes, pero **solo para pptx e imágenes sueltas**. Para OCR dentro de PDF/DOCX existe el plugin `markitdown-ocr` (`pip install markitdown-ocr`, `enable_plugins=True` + `llm_client`); si no hay cliente LLM, el plugin se salta silenciosamente.
- **Plugins de terceros.** markitdown soporta plugins (`packages/markitdown-sample-plugin` como base, tag `#markitdown-plugin`). El repo explícitamente **no acepta apps de escritorio ni servicios** dentro de su árbol: lo correcto es exactamente lo que vas a hacer, un paquete aparte que depende de `markitdown` desde PyPI.

**Las tres limitaciones que definen el diseño de `capmd`:**

1. markitdown convierte **el archivo completo**. No sabe qué es un "capítulo". El recorte por páginas/capítulo lo tiene que hacer `capmd` antes de llamarlo.
2. El converter de PDF es **extracción de texto plana**: no exporta imágenes, no marca páginas, y los headings salen como párrafos sueltos la mayoría de las veces. La reconstrucción de estructura es post-proceso de `capmd`.
3. Encabezados/pies de página repetidos, guiones de corte de línea y numeración se cuelan en el output. Limpiarlos es la diferencia entre un `.md` que sirve para estudiar y uno que no.

Por eso el roadmap es: **recorte → conversión → limpieza → reconstrucción → imágenes → empaquetado de salida**.

---

## 1. Stack y decisiones fijas

| Área | Elección | Nota |
|---|---|---|
| Lenguaje | Python 3.12 | mínimo real 3.10 por markitdown |
| Gestor | `uv` | `uv venv`, `uv pip install`, `uv tool install` para el binario |
| CLI | `typer` + `rich` | subcomandos, `--help` decente, progress bars |
| Conversión | `markitdown[pdf,docx,pptx,xlsx]` | `[all]` solo si quieres audio/youtube |
| Recorte PDF | `pypdf` | slicing de páginas sin re-render |
| Outline/TOC | `pypdf` (`reader.outline`) | fallback: heurística por texto |
| Imágenes + texto posicional | `pypdfium2` | **BSD/Apache**. PyMuPDF es AGPL — evítalo si algún día publicas |
| EPUB | markitdown `[all]` o `ebooklib` | markitdown ya soporta EPUB |
| Config | TOML en `~/.config/capmd/config.toml` | `tomllib` nativo |
| Tests | `pytest` + fixtures de PDFs generados | nada de PDFs con copyright en el repo |
| Lint/format | `ruff` | un solo tool |
| Tipos | `mypy --strict` en `core/` | CLI puede ir más suelto |
| Empaquetado | `hatchling` + `uv tool install` | Homebrew tap al final |

Estructura objetivo:

```
capmd/
├── pyproject.toml
├── README.md
├── roadmap.md
├── agent.md
├── src/capmd/
│   ├── __init__.py
│   ├── cli.py              # typer app, subcomandos
│   ├── config.py           # carga TOML + perfiles
│   ├── errors.py           # excepciones propias + exit codes
│   ├── models.py           # dataclasses: Chapter, Page, Figure, ConversionResult
│   ├── sources/
│   │   ├── base.py         # protocolo Source
│   │   ├── pdf.py          # recorte, outline, texto posicional
│   │   ├── epub.py
│   │   └── office.py
│   ├── convert/
│   │   ├── engine.py       # wrapper sobre MarkItDown
│   │   └── plugins.py      # enable_plugins, markitdown-ocr
│   ├── clean/
│   │   ├── pipeline.py     # orquesta los cleaners en orden
│   │   ├── headers.py      # header/footer repetidos
│   │   ├── hyphens.py      # de-hyphenation
│   │   ├── headings.py     # reconstrucción de jerarquía
│   │   ├── code.py         # bloques de código y listings
│   │   ├── tables.py
│   │   └── notes.py        # footnotes/endnotes
│   ├── images/
│   │   ├── extract.py
│   │   └── anchor.py       # insertar ![] en la posición real
│   ├── output/
│   │   ├── writer.py       # árbol de salida
│   │   ├── frontmatter.py
│   │   └── split.py        # partir por secciones
│   └── report.py           # stats de calidad de la conversión
└── tests/
```

---

## 2. Fases

Cada fase es una unidad cerrada: se implementa, se testea, se commitea. El criterio de test es lo que tiene que pasar para marcarla hecha.

### Bloque A — Esqueleto ejecutable

**A1. Repo + pyproject** ✅
Crear `pyproject.toml` con hatchling, `requires-python = ">=3.10"`, entry point `capmd = "capmd.cli:app"`.
*Test:* `uv pip install -e . && capmd --help` sale sin error.

**A2. App typer mínima** ✅
`capmd.cli` con `app = typer.Typer()`, comando `version`, flag global `--verbose`.
*Test:* `capmd version` imprime la versión de `importlib.metadata`.

**A3. Modelo de errores y exit codes** ✅
`errors.py`: `CapmdError` base, `SourceNotFound`, `UnsupportedFormat`, `RangeOutOfBounds`, `ConversionFailed`. Handler global en `cli.py` que imprime con `rich` y devuelve códigos 1–5.
*Test:* pasar un archivo inexistente → mensaje humano, exit code 2, sin traceback.

**A4. Logging** ✅
`--verbose` → INFO, `-vv` → DEBUG, por defecto solo warnings. Salida a stderr para no ensuciar stdout.
*Test:* `capmd convert x.pdf > out.md` con `-vv` deja `out.md` sin una sola línea de log.

**A5. Dataclasses del dominio** ✅
`models.py`: `SourceDoc`, `PageRange`, `Chapter`, `Figure`, `ConversionResult`, `QualityReport`.
*Test:* mypy strict pasa sobre `models.py`.

**A6. Fixtures de test generados** ✅
Script que genera PDFs sintéticos con `reportlab`: uno con headings, uno con header/footer repetido en cada página, uno con guiones de corte, uno con dos imágenes, uno con tabla, uno con outline/TOC.
*Test:* `pytest tests/test_fixtures.py` genera los 6 PDFs en `tmp_path`.

---

### Bloque B — Conversión base con markitdown

**B1. Wrapper del engine** ✅
`convert/engine.py`: clase `Engine` que instancia `MarkItDown(enable_plugins=...)` una sola vez y expone `convert_path(Path) -> str` usando **`convert_local()`**, no `convert()`.
*Test:* convierte el fixture de headings y devuelve un string no vacío.

**B2. Detección de formato** ✅
Mapear extensión → soporte, y validar que el extra de markitdown correspondiente está instalado (import lazy + mensaje claro: "falta `pip install 'markitdown[pdf]'`").
*Test:* `.xyz` → `UnsupportedFormat` con mensaje que nombra los formatos soportados.

**B3. Comando `capmd convert <archivo>`** ✅
Pasa el archivo entero por markitdown, escribe a stdout o a `-o`.
*Test:* `capmd convert fixture.pdf -o out.md` genera un `.md` con el texto del fixture.

**B4. Conversión desde stdin** ✅
`cat cap.pdf | capmd convert -` usando `convert_stream()` con `StreamInfo`/hint de extensión vía `--ext`.
*Test:* el pipe produce el mismo output que el archivo directo.

**B5. Timeouts y archivos grandes** ✅
Límite configurable de tamaño, aviso si el PDF supera N páginas, medición de tiempo de conversión.
*Test:* PDF de 500 páginas sintéticas convierte sin explotar la memoria y reporta el tiempo.

**B6. Snapshot del output crudo** ✅
Guardar opcionalmente el markdown pre-limpieza en `.capmd/raw.md` con `--keep-raw`, para poder diffear qué hizo la limpieza.
*Test:* `--keep-raw` deja el archivo y sin el flag no.

---

### Bloque C — Selección de capítulo

**C1. Lectura del outline del PDF** ✅
`sources/pdf.py`: leer `reader.outline` de pypdf y aplanarlo a `[(nivel, título, página)]`.
*Test:* fixture con TOC devuelve los títulos en orden y con la página correcta.

**C2. Comando `capmd toc <archivo>`** ✅
Imprimir el índice con números de página, indentado por nivel, con `rich.tree`.
*Test:* la salida lista los capítulos del fixture y el rango de páginas inferido de cada uno.

**C3. Inferencia de rangos desde el outline** ✅
Cada entrada de nivel 1 abarca hasta la página anterior de la siguiente entrada del mismo nivel; la última hasta el final.
*Test:* rangos contiguos, sin solapes, sin huecos.

**C4. Recorte por rango explícito** ✅
`--pages 45-78`, `--pages 45-` , `--pages -30`, listas `12,15,20-25`. Parser propio con validación contra el total.
*Test:* cada sintaxis produce el set de páginas esperado; fuera de rango → `RangeOutOfBounds`.

**C5. Recorte por capítulo** ✅
`--chapter 7` o `--chapter "Ownership"` (match por número de entrada del TOC o por substring case-insensitive).
*Test:* ambas formas resuelven al mismo rango en el fixture.

**C6. Slicing real del PDF** ✅ (absorbedo en C4)
Escribir un PDF temporal con solo esas páginas vía `pypdf.PdfWriter`, y pasarle ese temporal a markitdown.
*Test:* el temporal tiene exactamente N páginas y el markdown resultante no contiene texto de páginas vecinas.

**C7. Offset de numeración** ✅
Los libros suelen tener numeración impresa distinta a la física. `--page-offset N` para traducir "página 45 del libro" a índice físico.
*Test:* con offset 18, `--pages 45-50` recorta las físicas 63-68.

**C8. Detección heurística de capítulos sin outline** ✅
Si no hay outline: buscar páginas cuyo texto empiece con `Chapter N`, `Capítulo N`, `N. Título`, o con un salto de tamaño de fuente (vía pypdfium2).
*Test:* fixture sin TOC devuelve al menos los inicios de capítulo correctos; si falla, error claro sugiriendo `--pages`.

**C9. Capítulos en EPUB** ✅
Para EPUB usar el spine/nav: `--chapter` mapea a un item del manifiesto, y se convierte solo ese XHTML.
*Test:* EPUB fixture de 3 capítulos → `--chapter 2` devuelve solo el texto del segundo.

**C10. `capmd toc --json`** ✅
Salida machine-readable del índice, para poder scriptear conversiones masivas.
*Test:* el JSON valida contra un schema mínimo y es parseable con `jq`.

---

### Bloque D — Limpieza del Markdown

Cada cleaner es una función pura `str -> str` (o `list[str] -> list[str]` sobre líneas) registrada en `clean/pipeline.py` con un orden explícito y activable/desactivable por config.

**D1. Pipeline configurable** ✅
`Pipeline([...cleaners])` con `run(md, ctx) -> (md, list[CleanerStat])`, donde cada cleaner reporta cuántos cambios hizo.
*Test:* pipeline vacío devuelve el input intacto; con dos cleaners se aplican en orden.

**D2. Normalización de whitespace** ✅
Colapsar 3+ saltos de línea, trailing spaces, normalizar unicode (NFC), reemplazar ligaduras (`ﬁ`, `ﬂ`) y comillas tipográficas raras.
*Test:* input con 6 saltos y ligaduras sale normalizado.

**D3. De-hyphenation** ✅
Unir `pala-\nbra` → `palabra`, pero **no** romper compuestos legítimos (`well-known` al final de línea). Heurística: unir solo si la unión existe como palabra o si la segunda parte empieza en minúscula.
*Test:* casos positivos y negativos del fixture, incluidos términos técnicos.

**D4. Header/footer repetidos** ✅
Detectar líneas que aparecen en ≥60% de las páginas en posición inicial/final y eliminarlas. Requiere marcar los límites de página antes de convertir (ver D5).
*Test:* fixture con "Capítulo 3 | Rust in Action" en cada página → 0 ocurrencias en el output.

**D5. Marcadores de página** ✅
Convertir cada página a markdown por separado (o insertar centinelas `<!-- page N -->`) para que D4, las imágenes y las citas sepan de qué página vienen. Opción `--page-markers` para conservarlos en el output final.
*Test:* el número de centinelas coincide con el número de páginas recortadas.

**D6. Números de página sueltos** ✅
Líneas que son solo un número, o `— 47 —`, o `47 | Capítulo 3`.
*Test:* eliminados sin tocar listas numeradas ni referencias tipo "ver página 47".

**D7. Reconstrucción de headings** ✅
Usar tamaño/peso de fuente de pypdfium2 para clasificar líneas en H1–H4, y mapear a `#`/`##`/`###`. Fallback: regex de patrones (`^\d+\.\d+\s+[A-Z]`).
*Test:* fixture de headings produce la jerarquía exacta esperada.

**D8. Un solo H1** ✅
Forzar que el H1 sea el título del capítulo y degradar cualquier otro H1 a H2 (y así en cascada).
*Test:* documento con 3 H1 sale con 1 H1 y 2 H2.

**D9. Bloques de código** ✅
Detectar listings por fuente monoespaciada o por indentación consistente, envolver en ``` con lenguaje inferido (heurística por keywords: `fn`, `let mut` → rust; `func` → go; `def` → python).
*Test:* fixture con snippets de Rust y Python queda con los fences y el lenguaje correcto.

**D10. Preservar indentación dentro de código** ✅
Que los cleaners de whitespace no toquen el interior de los fences.
*Test:* snippet de 4 niveles de indentación sobrevive intacto al pipeline completo.

**D11. Listas** ✅
Reparar viñetas rotas (`•`, `‣`, `–` al inicio) y listas numeradas partidas en párrafos.
*Test:* fixture con lista de 5 items sale como lista markdown de 5 items.

**D12. Tablas** ✅
markitdown ya intenta tablas en docx/xlsx; para PDF, detectar filas alineadas y armar tabla GFM, o si la confianza es baja, dejar el texto en un bloque y marcarlo con `<!-- tabla no estructurada -->`.
*Test:* tabla simple del fixture → tabla GFM válida; tabla compleja → marcada, no inventada.

**D13. Footnotes** ✅
Detectar marcadores `¹`/`[1]` y el bloque de notas al pie, moverlos a formato `[^1]` al final del documento.
*Test:* 3 notas del fixture quedan enlazadas y sin duplicar.

**D14. Cortes de párrafo** ✅
Unir líneas que forman un mismo párrafo (rotas por ancho de columna) sin unir párrafos distintos. Señal: línea que no termina en `.`/`:`/`;` y la siguiente empieza en minúscula.
*Test:* párrafo de 8 líneas del fixture queda en una sola línea lógica.

**D15. Flags de control** ✅
`--no-clean`, `--only-clean headers,hyphens`, `--skip-clean tables`.
*Test:* `--no-clean` produce byte a byte lo mismo que `--keep-raw`.

---

### Bloque E — Imágenes y figuras

**✅ E1. Extracción de imágenes**
`images/extract.py` con pypdfium2: sacar las imágenes embebidas del rango de páginas a PNG/WebP, con `--image-format` y `--image-max-width`. Activada por default en `capmd convert` cuando el input es PDF; la carpeta `images/` queda junto al `-o` (o en `cwd/images/` si se escribe a stdout).
*Test:* fixture de 2 imágenes produce 2 archivos (`fig-001.png`, `fig-002.png`) con dimensiones correctas. Cobertura: 13/13 tests verdes en `tests/test_images_extract.py`; bytes exactos coinciden entre dos corridas; `--image-format webp` produce WebP; `--image-max-width 100` reescala con LANCZOS preservando aspect ratio.

**✅ E2. Filtro de basura**
Descartar imágenes < N px, logos repetidos en todas las páginas, y fondos de página completa. Pipeline E1+E2: `extract_candidates → filter_candidates → write_figures`. Defaults: `min_size=64x64`, `repeat_threshold=0.8`, `background_coverage=0.85`. Logo dedup conserva la primera aparición; el resto cae como `LOGO_REPEATED`. Override por CLI (`--filter-min-size`, `--filter-repeat-threshold`, `--filter-background-coverage`) y por TOML (`[images]` en `./capmd.toml` o `~/.config/capmd/config.toml`, precedencia project > global). Nuevo módulo `capmd.config` con `load_image_filter_overrides()` (stub mínimo; G1/G3 ampliarán).
*Test:* `build_logo_repeated_pdf` (4 páginas con logo idéntico + figuras reales en páginas 2 y 4) produce exactamente 2 archivos PNG por default. 19/19 tests verdes en `tests/test_images_filter.py`, 13/13 tests E1 sin regresión, 921/921 en suite completa.

**✅ E3. Nombres estables**
`fig-03-01.png` = capítulo 3, figura 1 (`fig-CC-NN.<ext>` con `:02d` que escala a 3+ dígitos automáticamente). Determinista entre corridas en nombres Y bytes: dos runs consecutivos producen SHA-256 idénticos por archivo (Pillow save con `info={}` limpio + WebP `exif=b""`/`icc_profile=None`). `chapter_index=1` por default, sube al `Chapter.index` resuelto cuando se pasa `--chapter N` (numérico o por substring del título). `Figure.index` ahora es índice dentro del capítulo.
*Test:* 16/16 tests verdes en `tests/test_images_naming.py`; `test_extract_figures_byte_identical_across_runs` es el caso literal del roadmap (mismos nombres y hashes en dos corridas); coverage del CLI para `--chapter 2`, `--chapter 3`, `--chapter "Ownership"` y default. 937/937 verde en suite completa.

**✅ E4. Anclaje posicional**
`images/anchor.py`: insertar `![](images/fig-CC-NN.png)` (alt vacío, E5 lo completará) en el punto del markdown correspondiente a la posición Y del bbox de la imagen en su página. Estrategia: cuando hay figuras y no se pasa `--no-anchor`, `convert` usa `Engine.convert_pages` + `insert_page_markers` y limpia cada página por separado (los cleaners no son estables con los centinelas insertados), reinserta markers, llama a `anchor_figures` con `page_areas` y luego `strip_page_markers` (a menos que `--page-markers`). Algoritmo de inserción: distribuye las líneas no-vacías de cada página uniformemente; inserta el anchor después de la `floor(y_frac * n_lines)`-ésima línea. Fallbacks: `bbox=None` o `page_height<=0` → final del bloque; figura en página fuera del rango → final del documento con warning. Flag nuevo: `--page-markers` (D5).
*Test:* el test literal del roadmap es `test_anchor_figures_inserts_image_in_middle_of_page_2` (imagen a Y=0.5 de página 2 → anchor después del párrafo 2 de 4, no al final). `build_text_with_midpage_image_pdf` (fixture nuevo: 2 páginas, narrativa + imagen embedida en Y≈0.37) verifica el caso end-to-end en `test_cli_anchor_inserts_image_in_final_markdown`. 14/14 tests verdes en `tests/test_images_anchor.py`; `--no-anchor` verificado, `--page-markers` verificado, anclaje con `--chapter 2` verificado. 951/951 verde en suite completa.

**✅ E5. Captions**
Detectar el texto `Figura N.N — ...` (o variantes `Figure`, `Fig.`, `Fig`, con separador `—`/`-`/`:`) bajo la imagen y usarlo como alt text del anchor `![…](images/…)` y como línea en cursiva `*Figura N.N — …*` debajo. Regex multi-idioma compilable (`CAPTION_RE`) en `capmd.images.captions`; `find_caption_in_window(lines, target, window=3)` busca en las próximas 3 líneas no-vacías debajo del target del anchor (saltando blank lines). `default_alt_text(fig)` lee `fig.caption or ""` para que el alt text se propague sin tocar el contrato E4. CLI: `_attribute_captions_by_page` hace un pre-pass por página después de limpiar y antes del anchor; matchea por número (`f"{chapter}.{fig.index}"`) con fallback posicional.
*Test:* el test literal del roadmap es `test_cli_alt_text_matches_caption`: el output contiene `![Figura 3.1 — Diagrama de la imagen central](images/fig-01-01.png)`. Fixture `build_text_with_midpage_image_pdf` extendido con `caption="Figura 3.1 — …"` (parametrizable via `caption=None`). 27/27 tests verdes en `tests/test_images_captions.py`; cobertura de regex multi-idioma, ventana de 3 líneas (incl. blank line skip), atributos `Figure.caption`, integración con `anchor_figures`, y CLI end-to-end. 978/978 verde en suite completa.

**✅ E6. Descripción por LLM (opcional)**
Flag `--describe-images`: activa `Engine(enable_plugins=True, llm_client=…, llm_model=…)` para que `markitdown-ocr` describa las imágenes embebidas. Multi-proveedor via factory (`openai` / `anthropic` / `google`) que detecta keys en `OPENAI_API_KEY`/`ANTHROPIC_API_KEY`/`GOOGLE_API_KEY` (auto por prioridad). Helper `capmd.llm.build_llm_client(provider, model)` es **inyectable** vía `monkeypatch.setattr("capmd.config.build_llm_client", …)`. Degradación limpia: singleton `_LLM_WARNED_ONCE` a nivel CLI emite UN warning si `--describe-images` se pide sin key disponible y la corrida continúa (E5 captions siguen funcionando). Nuevo helper CLI `_resolve_llm_client(...)` retorna `(client, model)` o `(None, None)`. Soporte `--describe-provider` (`auto`/`openai`/`anthropic`/`google`) y `--describe-model` (default por proveedor). Deuda técnica futura: pip-pin de `openai`/`anthropic`/`google-genai` como `[llm-*]` extras opcionales (hoy son opcionales por import lazy).
*Test:* el test literal del roadmap es `test_cli_describe_images_without_key_runs_anyway` (sin key + `--describe-images` → exit 0, output normal, warning visible). 22/22 tests verdes en `tests/test_images_describe.py`: 5 detect_env, 6 build_llm_client, 3 Engine, 7 _resolve_llm_client (incl. warn-once y provider inválido → typer.BadParameter), 3 CLI integración. 1000/1000 verde en suite completa (incluye regresión fixée en `test_convert_stdin_tty_exits_2` para incluir las nuevas flags).

**✅ E7. `--no-images`**
Saltar todo el bloque E (E1-E6) e insertar `<!-- figura omitida: Figura C.N -->` en la posición Y de cada imagen embebida. Sin escritura de PNGs (`images/` no se crea); sin anclaje `![]()`; sin detección de captions; sin LLM. Nueva API: `extract_figure_placeholders(pdf, pages, *, chapter_index, page_areas)` que reutiliza `extract_candidates` (E1) sin escribir; `FigurePlaceholder` dataclass; `format_placeholder(p)`; `insert_image_placeholders(markdown_with_markers, placeholders)` paralelo a `anchor_figures`. CLI: `_apply_no_images_marker(...)` que omite `_maybe_extract_images` cuando `--no-images` está activo y aplica el pipeline `convert_pages → per-page cleaning → markers → placeholders → strip`. Default `False` (consistente con E1-E6: imágenes ON por default).
*Test:* el test literal del roadmap es `test_cli_no_images_does_not_create_images_dir`: con `--no-images`, la carpeta `images/` NO existe (ni junto al `-o` ni en cwd); el output .md se genera normalmente con placeholders. 19/19 tests verdes en `tests/test_images_no_images.py`: 4 unitarios (`format_placeholder`, `extract_figure_placeholders`, `insert_image_placeholders`, marker preservation) + 11 CLI (literal, no anchor, no `images/`, flag en `--help`, interacción con otras flags E, `--page-markers` respetados, no-op para placeholders vacíos). 1019/1019 verde en suite completa.

---

### Bloque F — Salida

**✅ F1. Árbol de salida**
```
out/
└── rust-handbook/
    └── cap-03-ownership/
        ├── cap-03-ownership.md
        ├── images/
        └── capmd.json      # metadata de la corrida
```
`--out`, `--flat` (todo en un archivo, sin carpeta).
*Test:* la estructura se crea y `--flat` genera solo el `.md`.

Implementado en `src/capmd/output/writer.py` + rama nueva en `cli.py`. Slug del libro = kebab-case del stem del PDF (ASCII + dígitos; Unicode no-ASCII conservado; diacríticos normalizados a NFKD y dropeados); stdin → `"stdin"`. Slug del capítulo: `--chapter` resuelto → `cap-NN-<title-slug>` (NN = `Chapter.index` en `:02d`; prefijo `Chapter N:`/`Capítulo N:`/etc. se elimina para no duplicarlo); `--pages` → `pages-START-END` (sets no contiguos → `pages-N1-N2-...-more`); sin selección → `full`. `capmd.json` con `schema_version=1` y 13 campos (book/chapter/source/pages/range_label/chapter/generated_at/capmd_version/images_dir/layout/cleaners_applied + source_file y source_sha256). `-o FILE` y `--out` mutuamente excluyentes (typer.BadParameter); `--flat` requiere `--out`. En flat se suprime la extracción de imágenes E1-E7 (sin `images/`, sin anchors). Colisión del directorio destino → `IOError` exit 7 (F8 agrega `--force`/`--suffix`). 48 tests nuevos: 37 unit en `test_output_writer.py` (slugify, build_tree_paths, CapmdJsonV1 round-trip, build_metadata, write_output_tree/flat) + 11 CLI en `test_output_tree.py` (caso literal del roadmap con `--chapter 3` → `cap-03-ownership`, flat, colisión, stdin, validación de flags, regresión de `-o FILE`). 1067/1067 verde en suite completa; ruff y mypy limpios.

**✅ F2. Front matter YAML**
`title`, `book`, `chapter`, `pages`, `source_file`, `source_sha256`, `converted_at`, `capmd_version`, `markitdown_version`, `cleaners_applied`.
*Test:* el front matter parsea con `yaml.safe_load` y contiene las 10 claves.

Implementado en `src/capmd/output/frontmatter.py` + rama nueva de prepend en `cli.py`. Dependencia nueva: `pyyaml>=6.0`. Dump block-style (`safe_dump`, `default_flow_style=False`, `sort_keys=False`, `allow_unicode=True`) entre centinelas `---\n…\n---\n\n`. Orden de claves = orden del schema (el del roadmap). `title`: primer `# H1` del markdown limpio → `Chapter.title` (si `--chapter` resolvió) → `book_slug`. `chapter` = slug (`cap-03-ownership` / `pages-1-2` / `full` / `stdin`). `pages`: lista de ints o `null`. `converters_applied`: misma lista efectiva que `capmd.json` (`--no-clean` → `[]`). `markitdown_version` vía `importlib.metadata.version("markitdown")`, cache lazy. Prepende en **cualquier salida a archivo** (`-o FILE`, `--out` tree, `--out` flat); **stdout se queda limpio** (pipes no llevan metadata). Idempotencia: `strip_existing_front_matter` quita un FM previo antes de prepender el nuevo (regex `^---\n.*?\n---[ \t]*\n+`, anclada al inicio, blanks preservados), validado con test `prepend(prepend(md)) == prepend(md)`. Sin flag `--no-front-matter` en F2. 39 tests nuevos: 28 unit en `test_frontmatter.py` (extract_first_h1, strip_existing_front_matter con casos borde: leading whitespace, bloque sin cerrar, divider `---` interno NO se considera FM; render_front_matter round-trip con `yaml.safe_load`, escape de `:`, `None` como `null`, orden de claves; build_front_matter_fields; prepend_front_matter idempotente) + 11 CLI en `test_frontmatter_cli.py` (literal: 10 claves en árbol; sin front matter en stdout; `-o FILE` y `--flat` también prependen; `--no-clean` → `cleaners_applied: []`; `--only-clean`; `chapter` = slug; `pages` = list cuando `--pages`; stdin → `source_file`/`source_sha256`/`pages` null; título del H1 vs fallback). 3 tests existentes (D15 byte-equality con `--keep-raw`/`--no-clean`) actualizados para comparar *cuerpos* post-strip, ya que F2 prepende YAML arriba del archivo. Assert nuevo de FM en el test literal de F1 (regresión cruzada F2↔F1). 1106/1106 verde; ruff y mypy limpios.

**✅ F3. `capmd.json`**
Mismo metadata + stats de limpieza + lista de figuras, para poder re-procesar sin re-leer el PDF.
*Test:* el JSON permite regenerar el front matter sin tocar el original

Implementado en `src/capmd/output/writer.py` + `frontmatter.py` + propagación de stats/figures/elapsed/title en `cli.py`. Bump de `SCHEMA_VERSION` 1 → 2 (`CapmdJsonV2`, 20 keys, listas *siempre presentes*). Los 13 campos de F1 se preservan y se agregan: `title` (H1 → `Chapter.title` → `book_slug`), `markitdown_version` (lookup cacheado de `importlib.metadata`), `elapsed_seconds` (de `Engine.convert_path().elapsed_seconds`), `cleaner_stats` (lista de `{name, enabled, changes, duration_ms, error}`; con sufijo ` (page N)` en flujos E4/E7 donde el pipeline corre por página), `figures` (lista; cada uno `{chapter_index, index, path (relativo a chapter_dir), page, bbox, caption, alt_text, width, height}` vía `_figure_to_dict`), `warnings` (lista vacía, F6 los introducirá). Helper público `front_matter_fields_from_capmd_json(json_dict) -> dict` regenera los 10 campos del front matter desde el JSON (renombre explícito `book_slug→book`, `chapter_slug→chapter`, `generated_at→converted_at`); valida `schema_version == 2`; levanta `KeyError`/`ValueError` ante inconsistencias. Cambio de signatures en `_run_cleaning_pipeline`, `_apply_clean_pipeline`, `_apply_clean_pipeline_to_stdin`, `_apply_anchor`, `_apply_no_images_marker`: ahora devuelven `tuple[str, list[CleanerStat]]`. 29 tests nuevos: 17 unit en `test_capmd_json.py` (schema_version=2, 20-key invariant, listas always-present, fallbacks de `title`, `_figure_to_dict` path-relativo, round-trip de regeneración a nivel de YAML parseado, validación de schema_version y KeyError ante campos faltantes, stdin = null fields, re-render prepend funciona) + 12 e2e en `test_capmd_json_cli.py` (literal: `capmd.json` se regenera produciendo el mismo YAML que el del `.md`; coverage de las 20 keys end-to-end, `cleaner_stats == []` con `--no-clean`, `cleaner_stats` poblado para el flujo normal, `elapsed_seconds ≥ 0`, stdin → null fields, `--flat` no genera `capmd.json`). Tests existentes migrados de `CapmdJsonV1` a `CapmdJsonV2` (`test_output_writer.py`, `test_output_tree.py`). 1136/1136 verde; ruff y mypy limpios..

**✅ F4. Split por secciones**
`--split h2` genera `01-introduccion.md`, `02-borrowing.md`... más un `index.md` con enlaces.
*Test:* un doc con 4 H2 produce 4 archivos + índice con 4 links válidos.

Implementado en `src/capmd/output/split.py` + helper `_write_split_sections` en `cli.py`. Subcarpeta `sections/` dentro del chapter dir (decidido con el usuario). El H1 inicial del markdown se strippea del preludio (ya está representado como `title` del chapter y del index). Contenido previo al primer H2 (si existe) va a `00-intro.md`; el `00-intro` solo se crea cuando el prelude no es vacío. Cada sección (`0N-<slug>.md`) y `index.md` llevan front matter con `title` = título del H2 (o `"Index"` para el index) y los otros 9 campos heredados del chapter padre. Slugify por título con dedup por colisión (`-2`, `-3`). Zero-padding del nombre: 2 dígitos hasta 99 secciones, 3 desde 100 (intro `00` sigue el mismo pad). Detección robusta: respeta code fences (```` ``` ```` y `~~~`) vía `split_outside_fences`, ignora `##hashtag` (sin espacio) y `##` mid-line, strippea el front matter inicial con `strip_existing_front_matter` antes de contar. Parser principal `extract_h2_sections(md) -> SectionSlice(prelude, sections)`. `--split` solo funciona en tree mode: mutuamente excluyente con `--flat` y `-o FILE` (typer.BadParameter). Sin H2 detectados → warning por stderr y `sections/` no se crea. Soporta solo `h2` en F4 (`--split h3` → error). Nuevo fixture `build_four_h2_pdf` (1 H1 + 4 H2 sin prelude para el literal test). 26 unit tests en `test_split.py` (extract_h2_sections: happy paths, code fences con ``` y ~~~, fence sin cerrar, front matter inicial, `##hashtag` ignored, dedup, padding, escape de brackets en `build_index_markdown`, round-trip). 8 e2e tests en `test_split_cli.py`: literal (4 H2 → 4 files + index con 4 links), FM por sección con título del H2, intro `00` cuando hay prelude, links del index apuntan a archivos existentes, validaciones (`--split` sin `--out`, con `--flat`, con `-o FILE`, `--split h3` no soportado, sin `--split` no crea `sections/`). 1170/1170 verde; ruff y mypy limpios.

**✅ F5. Tabla de contenidos inline**
`--toc` inserta un índice de anclas al inicio del `.md`.
*Test:* cada ancla del TOC resuelve a un heading existente.

Implementado en `src/capmd/output/toc.py` + flags `--toc` y `--toc-depth` en `cli.py`. `--toc-depth` por default es 3 (incluye H2 + H3; el H1 chapter-title no se lista porque ya aparece arriba como heading). Inserción: después del primer H1 (convención GitHub); si no hay H1, al tope del body (después del FM block si existe). **Anclas estilo GitHub**: lowercase, conserva letras Unicode (acentos/CJK/cirílico) literales vía `unicodedata.category`, strip de puntuación ≠ `-`/`_`, colapsa runs de `-`, trim bordes; dedup con sufijos `-1`, `-2`. Respeta code fences (`split_outside_fences` reusado de F4). Idempotencia: el bloque TOC va envuelto en sentinels `<!-- capmd:toc:open -->` / `<!-- capmd:toc:close -->`; re-correr `--toc` reemplaza en lugar de duplicar. Sin headings en rango → log debug + skip (no error; es un caso válido de prosa sin estructura). Con `--split h2` (F4): TOC va SOLO al chapter `.md` raíz, NO a los section files (cada sección es corta y el `index.md` de F4 ya cubre navegación). Módulo público: `markdown_anchor`, `slugify_anchor` (con dedup), `extract_headings(min_level, max_level)`, `build_toc_block`, `strip_existing_toc`, `inject_toc(depth=3)`, dataclass `Heading`. 45 unit tests en `test_toc.py` (anchor parametrize con ASCII/Unicode/CJK; dedup; min_level/max_level; ignorar code fences (`  ``` ` y `~~~`); strip FM inicial; brackets escapados en `build_toc_block`; inject post-H1, sin H1, con FM, no headings → idéntico, idempotente vía sentinels, depth override). 9 e2e tests en `test_toc_cli.py` (literal: cada anchor en TOC existe como heading real; H1 chapter title NO aparece en TOC; `--toc` con `-o FILE`, `--flat`, `--split h2`; idempotencia: re-correr no duplica el bloque sentinels; `--toc-depth 2` filtra H3+; `--help` menciona los flags). 1203/1203 verde; ruff y mypy limpios.

**✅ F6. Reporte de calidad**
`report.py` → al final de la corrida imprime: páginas procesadas, palabras, headings detectados, figuras, líneas eliminadas por cada cleaner, y **warnings** (ej: "0 headings detectados, revisa `--headings-mode`").
*Test:* el fixture "malo" (PDF escaneado sin texto) dispara el warning de output vacío.

Implementado en `src/capmd/report.py` + integración de flags `--report-format {json|text}` (default JSON), `--strict` y `--no-warnings` en `cli.py`. Schema versionado con `REPORT_SCHEMA_VERSION=1` y `format` (json|text). Stats: `pages`, `words`, `headings` (`HeadingCounts` con `h1..h6` y `total`), `figures`, `cleaners` (`CleanerCounts` con `per_cleaner` y `total_changes`), `raw_chars`, `cleaned_chars`, `deletion_ratio`, `elapsed_seconds`, `source_format`. Heurísticas implementadas: `empty_output` (words == 0 con pages > 0), `scanned_pdf` (pdf + pages >= 2 + words_per_page < 10), `no_headings` (pdf + pages >= 2 + sin headings), `no_figures` (pdf + pages >= 5 + 0 figuras tras E5), `over_cleanup` (deletion_ratio > 0.5; se desactiva con `--no-clean`), `uniform_headings` (todos los headings del mismo nivel). Cada warning: `{code, message, suggestion}`. JSON parseable por default; texto human-readable con rich (fallback a texto plano si rich falta). Reporte se computa UNA vez y se inyecta a stderr Y a `capmd.json.warnings` (single source of truth, F3 schema v2 poblado). `--strict` → `typer.Exit(8)` si hay warnings. `--no-warnings` silencia stderr pero NO vacía `capmd.json.warnings` (contrato para tooling/CI). Reporte a stderr (no stdout). Nuevo fixture `build_scanned_pdf` (PDF con páginas de imágenes sin texto). Helper `_finalize_and_return` invocado antes de cada `return` del convert; precomputa stats y warnings una vez. 23 unit tests en `test_report.py` (HeadingCounts/CleanerCounts/collect_stats/collect_warnings/render_json/render_text: cada heurística dispara cuando corresponde y NO dispara cuando stats son normales; `--no-clean` desactiva `over_cleanup`; formato incorrecto deprecation). 12 e2e tests en `test_report_cli.py` (literal: scanned PDF dispara `empty_output` y `escaneado` en capmd.json.warnings; `--strict` exit 8 con warnings, 0 sin; `--report-format text` parseo JSON falla pero stats legibles; `--no-warnings` silencia stderr pero JSON completo; PDF normal no dispara warnings; reporte a stderr no stdout; `--help` menciona flags). Test legacy `test_convert_reports_timing_to_stderr` actualizado para chequear markers del reporte F6 (`elapsed_seconds`/`pages` JSON). 1238/1238 verde; ruff y mypy limpios.

**✅ F7. `--dry-run`**
Mostrar qué se haría (rango, páginas, archivos de salida) sin escribir nada.
*Test:* filesystem sin cambios después de correr.

Implementado en `src/capmd/dryrun.py` + flags `--dry-run` y `--dry-run-format {json,text}` en `cli.py`. `--dry-run` corre la conversión completa (markitdown + cleaners + figuras + TOC + split planning) pero redirige cualquier write a `tempfile.mkdtemp(prefix="capmd-dryrun-")`; al final se elimina el tmp con `shutil.rmtree`. El filesystem del destino que pasó el usuario queda intacto (literal verificado). El plan se emite a stdout en formato JSON parseable por default (`render_plan_json`) o human con rich (`render_plan_text`, `--dry-run-format text`). El plan NO incluye el markdown: stdout es solo el JSON de planificación. Estructura (`DryRunPlan`): `dry_run: true`, `schema_version: 1`, `input` (source, format, pages, size_bytes, sha256), `selection` (chapter, chapter_slug, pages, page_offset), `flags` (flat, split, toc, toc_depth, no_images, no_anchor, no_clean, only_clean, skip_clean, image_format), `output` (requested, kind ∈ {tree, flat, single-file, stdout}, tree_files con paths completos reales que se hubieran escrito), `report` embebido (F6 `ReportOutput` con stats + warnings). El helper `_compute_split_tree_paths` reproduce el layout que escribiría `--split h2` (`sections/0N-...md`, `sections/00-intro.md` si hay prelude, `sections/index.md`). Compatible con `--out`, `--flat`, `--split h2`, `--toc`, `--toc-depth`, todas las flags de cleaners, imágenes y anchors. `--no-warnings`/`--strict` de F6 son válidos dentro del dry-run pero el F6 report se incluye DENTRO del plan, no se imprime por separado a stderr. El único limpieza residuales son tmp dirs huérfanos si el proceso muere entre `mkdtemp` y `rmtree` (aceptable). 9 unit tests en `test_dry_run.py` (tree mode: 3 paths base + sections cuando --split; flat: 1 path; single-file; stdout: 0 paths; report embedding; renderers parseable). 9 e2e tests en `test_dry_run_cli.py` (literal: filesystem del destino intacto, out_dir no se crea; stdout parseable JSON con `dry_run: true`; `kind` correcto para cada modo; `--dry-run-format text` produce human-readable con rich; `--split h2` lista las secciones y el index.md en tree_files; stdout NO arranca con `#` (no es markdown); F6 report embebido en `report`; `--help` menciona los nuevos flags). 1256/1256 verde; ruff y mypy limpios.

**✅ F8. Sobrescritura segura**
Si el destino existe: fallar salvo `--force`, o `--suffix` para versionar.
*Test:* segunda corrida sin `--force` → exit code y mensaje claro.

Implementado en `src/capmd/output/writer.py` (`resolve_destination_collision` + `_next_versioned_path`) + flags `--force` y `--suffix` en `cli.py`. Por default, si el destino existe la corrida falla con `CapmdIOError` exit 7 y hint "usá --force para sobrescribir o --suffix para versionar" (mensaje claro, literal verificado). `--force` borra el destino existente (`shutil.rmtree` para chapter dir tree, `Path.unlink` para flat / `-o FILE`) y recrea desde cero. `--suffix` versiona el destino principal con sufijo numérico incremental: ``file.md → file-1.md → file-2.md`` para `-o FILE`; ``<out>/<book>/<chapter>/ → <out>/<book>/<chapter>-1/ → <chapter>-2/`` para `--out`. El nuevo filename dentro del dir versionado (ej: ``full-1.md``) refleja el chapter_slug versionado. `--force` y `--suffix` son mutuamente excluyentes (`typer.BadParameter` exit 2 si ambos se pasan). El resolver corre dentro de `_write_output_tree_or_flat` sobre el chapter_dir (`<out>/<book>/<chapter>/`) y sobre el `<book>.md` flat; el snapshot `.capmd/raw.md` de `--keep-raw` NO entra en la lógica de versionado (se sobreescribe siempre). El writers `write_output_tree` y `write_output_flat` aceptan `force: bool = False` y siguen una red de seguridad: si llegara una colisión sin resolver (error de integración), fallan con `CapmdIOError`. Compatibilidad: con `--flat`, `--split h2`, `--toc`, `--no-clean`, `--toc-depth`, `--strict`, `--no-warnings`, `--dry-run` (dry-run se combina: el dry-run genera todo el output a un tmpdir, dejando el destino intacto, así que `--suffix`/`--force` no se aplican dentro del dry-run). Comportamiento de 2 tests existentes actualizado: `test_convert_keep_raw_overwrites_existing_snapshot` ahora usa `--force` explícito (cambio de contrato documentado: sin flags, NO se sobrescribe; antes el `-o FILE`siempre sobreescribía sin aviso, eso es un breaking change que se beneficia de F8); `test_convert_stdin_tty_exits_2` agrega `force=False, suffix=False` como kwargs explícitos a la llamada directa a `cli_module.convert`. 12 unit tests en `test_destination_collision.py` (resolver: missing → mismo path; colisión + force/suffix/versionar; CapmdIOError con hint de `--force`/`--suffix`; file vs dir en el message; `write_output_tree`/`write_output_flat` con `force=True` sobrescriben y con `force=False` siguen lanzando la red de seguridad). 10 e2e tests en `test_force_suffix_cli.py` (literal: exit 7 + mensaje claro; `--force` sobrescribe; `--suffix` crea versionado y deja original intacto; cadenas `-1`/`-2`; `-o FILE --suffix` crea `<stem>-1.md`; `--force --suffix` BadParameter; compat con `--flat`, `--split h2`, `--keep-raw`; `--help` menciona flags). 1278/1278 verde; ruff y mypy limpios.

---

### Bloque G — Configuración y perfiles

**G1. Config TOML**
`~/.config/capmd/config.toml` con defaults: `out_dir`, `image_format`, cleaners activos, `page_offset`.
*Test:* un valor del TOML cambia el comportamiento sin pasar flags.

**G2. Precedencia**
CLI > env (`CAPMD_*`) > config de proyecto (`./capmd.toml`) > config global > defaults.
*Test:* cuatro capas, cuatro asserts.

**G3. Perfiles por libro**
`[books."rust-handbook"]` con `page_offset`, `title_pattern`, cleaners específicos. Se activa con `--book rust-handbook` o por hash del PDF.
*Test:* dos libros con offsets distintos resuelven rangos distintos con el mismo `--pages`.

**G4. `capmd config init` / `capmd config show`**
Generar el TOML comentado y mostrar la config efectiva resuelta.
*Test:* `config show` refleja los overrides activos.

**G5. Auto-registro de libro**
Al convertir un PDF nuevo, guardar su sha256 + título + TOC cacheado para no re-parsear.
*Test:* la segunda corrida sobre el mismo libro es medible más rápida y no re-lee el outline.

---

### Bloque H — Experiencia de uso

**H1. Progress con rich**
Barras por etapa: recorte → conversión → limpieza → imágenes → escritura.
*Test:* con `--quiet` no se imprime nada a stderr.

**H2. `capmd batch`**
Convertir varios capítulos de una: `capmd batch libro.pdf --chapters 1-12`, con paralelismo por proceso.
*Test:* 12 capítulos generan 12 carpetas; un fallo aislado no aborta el resto.

**H3. `capmd inspect`**
Diagnóstico de un PDF: ¿tiene texto o es escaneado?, ¿tiene outline?, ¿cuántas fuentes distintas?, ¿headers repetidos?
*Test:* distingue correctamente el fixture con texto del fixture rasterizado.

**H4. Shell completions**
`capmd --install-completion` para zsh (default en macOS).
*Test:* tab-completion de subcomandos funciona en una zsh limpia.

**H5. `capmd open`**
Abrir el resultado en el editor (`$EDITOR`, o `open -a` en macOS) con `--open` en `convert`.
*Test:* flag invoca el comando correcto (mockeado).

---

### Bloque I — Integración macOS

**I1. Instalación como tool**
`uv tool install capmd` / `pipx install capmd`, documentado y verificado en una máquina limpia.
*Test:* el binario queda en PATH y corre sin venv activo.

**I2. Quick Action / Atajos**
Un Atajo de macOS "Convertir capítulo a Markdown" que recibe un PDF desde Finder, pide el rango y llama a `capmd`.
*Test:* click derecho sobre un PDF en Finder ejecuta la conversión.

**I3. Carpeta watch (opcional)**
LaunchAgent que observa `~/Books/Inbox` y convierte lo que caiga ahí, moviendo el original a `Processed/`.
*Test:* soltar un PDF genera la salida en ≤ el tiempo de una conversión manual.

**I4. Homebrew tap**
Fórmula en tu propio tap (`brew install martin/tap/capmd`).
*Test:* instalación limpia en una cuenta de macOS distinta.

---

### Bloque J — Calidad y release

**J1. Suite de tests completa**
Cobertura por cleaner, por source, por comando. Objetivo: `core/` con cobertura alta; CLI con smoke tests.
*Test:* `pytest` verde y `coverage` sobre el umbral que fijes.

**J2. Tests de regresión con golden files**
Guardar el `.md` esperado de cada fixture; cualquier cambio de cleaner que altere el golden exige actualizarlo a mano.
*Test:* `pytest --update-golden` regenera; sin el flag, el diff falla.

**J3. CI en GitHub Actions**
matrix Python 3.10/3.12, ruff + mypy + pytest en macOS y ubuntu.
*Test:* PR de prueba pasa los tres jobs.

**J4. Versionado y changelog**
SemVer, changelog generado desde commits convencionales.
*Test:* tag `v0.1.0` dispara build y adjunta el wheel.

**J5. Publicación en PyPI**
`uv build` + `twine upload`, con `markitdown` como dependencia declarada (no vendorizado).
*Test:* `pip install capmd` en un venv limpio convierte un PDF.

**J6. README y docs**
El README de este mismo paquete, más `docs/cleaners.md` explicando qué hace cada limpiador y cómo desactivarlo.
*Test:* alguien que nunca vio el proyecto convierte un capítulo siguiendo solo el README.

---

### Bloque K — Extensiones

**K1. Plugin propio de markitdown**
Empaquetar los cleaners como plugin `#markitdown-plugin` para que también funcionen con el `markitdown` oficial.
*Test:* `markitdown --list-plugins` lo muestra y `--use-plugins` aplica la limpieza.

**K2. Salida para pipeline de estudio**
`--profile study`: front matter extra (tags, estado de lectura), secciones vacías `## Resumen` / `## Conceptos clave` / `## Dudas` listas para llenar.
*Test:* el output encaja directo en tu carpeta de documentación de libros.

**K3. Hook post-conversión**
`post_command` en config: comando arbitrario que recibe la ruta del `.md` generado (para encadenar con tus otras herramientas — resumen, export, indexado).
*Test:* el hook recibe la ruta correcta y su fallo se reporta sin corromper la salida.

**K4. Soporte Azure Doc Intelligence / Content Understanding**
Exponer `--use-cu` y `-d`/`-e` como passthrough para PDFs escaneados o con layout complejo, leyendo `MARKITDOWN_CU_ENDPOINT` / `MARKITDOWN_DOCINTEL_ENDPOINT`.
*Test:* con endpoint mockeado, la ruta CU se elige y el resto del pipeline no cambia.

**K5. Comparador de motores**
`capmd compare archivo.pdf --pages 45-50` corre built-in vs OCR vs CU y muestra métricas lado a lado (palabras, headings, tiempo).
*Test:* la tabla comparativa se imprime con al menos dos motores disponibles.

**K6. Caché de conversión**
Hashear (archivo + rango + config de cleaners); si nada cambió, no reconvertir.
*Test:* segunda corrida idéntica es un no-op con mensaje "cacheado".

---

## 3. Orden de ataque sugerido

El MVP usable es **A → B → C1-C7 → D1-D8 → F1-F3**. Con eso ya recortas un capítulo y obtienes un `.md` limpio con estructura. Todo lo demás es mejora incremental sobre una base que ya te sirve.

Bloque D es donde está el valor real y donde vas a iterar más: conviene hacerlo con los golden files (J2) desde temprano, no al final.

## 4. Riesgos técnicos conocidos

- **PDFs escaneados.** markitdown built-in no hace OCR. Sin `markitdown-ocr` o CU, el output es vacío. Detéctalo en H3 y falla temprano con un mensaje útil.
- **PyMuPDF es AGPL.** Si lo usas para imágenes y luego publicas el paquete, contamina la licencia. `pypdfium2` evita el problema.
- **Headings.** Es la parte más frágil. Si la heurística de tamaño de fuente no converge, el fallback de regex + `--headings-mode manual` (editar un mapa de patrones por libro en el perfil) es más confiable que insistir.
- **markitdown cambia.** `result.markdown` vs `result.text_content` ya cambió una vez. Pinea la versión en `pyproject.toml` y ten un test que falle si la API se mueve.
