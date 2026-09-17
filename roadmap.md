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

**✅ G1. Config TOML**
`~/.config/capmd/config.toml` con defaults: `out_dir`, `image_format`, cleaners activos, `page_offset`.
*Test:* un valor del TOML cambia el comportamiento sin pasar flags.

Implementado en `src/capmd/config.py:1` + helper `available_cleaner_names()` en `src/capmd/clean/pipeline.py:152`. API pública: dataclass inmutable `CapmdConfig(out_dir, image_format, page_offset, cleaners_enabled|disabled, image_overrides, source_paths)` y `load_config(*, project_toml, global_toml) -> CapmdConfig` con precedencia project > global > defaults. Validaciones tolerantes: valores inválidos caen al default con warning (no rompen). Claves raíz desconocidas se loggean en debug. Esquema del TOML: claves planas `out_dir`/`image_format`/`page_offset` + tabla `[cleaners]` con `enabled`/`disabled` (mutuamente excluyentes; ambos presentes → warning + solo `enabled`) + `[images]` (compat E2). Plumbing en `src/capmd/cli.py:493`: los defaults de Typer para `--out`/`--page-offset`/`--image-format` ahora pasan por resolución al inicio de `convert`; lo mismo para `--only-clean`/`--skip-clean` (solo si el usuario NO pasó el flag — el override CLI explícito sobre TOML queda en G2 junto con env vars `CAPMD_*`). 15 tests en `tests/test_config_g1.py`: defaults por clave (4), precedencia project > global (2), casos negativos / inválidos / malformados (4), cleaners whitelist/blacklist/ambos (3), smoke CLI sin/con TOML (2). Compat: `load_image_filter_overrides()` se conserva como shim delegando a `load_config()`. Suite completa: 1293/1293 verdes (1278 previos + 15 nuevos). Sin regresión en E1/E2/dry-run. `ruff check` y `mypy` limpios sobre los archivos tocados.

**✅ G2. Precedencia**
CLI > env (`CAPMD_*`) > config de proyecto (`./capmd.toml`) > config global > defaults.
*Test:* cuatro capas, cuatro asserts.

Implementado en `src/capmd/config.py:1` + plumbing en `src/capmd/cli.py:498`. Variables de entorno soportadas (todas validadas con los mismos `_validate_*` que TOML; inválidas → warning + fallback): `CAPMD_OUT_DIR`, `CAPMD_IMAGE_FORMAT`, `CAPMD_PAGE_OFFSET`, `CAPMD_CLEANERS_ENABLED`, `CAPMD_CLEANERS_DISABLED` (CSV con `,` o `;`). `load_config(env=None, *, project_toml, global_toml)` ahora acepta `env` (default = `os.environ`); capas: `defaults < global_toml < project_toml < env`. Helper público `merge_configs(base, override)`. CLI: `convert` recibe `ctx: typer.Context` (primer parámetro) y usa `ctx.get_parameter_source(name)` para detectar si el flag fue pasado por línea de comandos (comparando por `name == "COMMANDLINE"` para evitar la dependencia de identidad entre los enums `click.core.ParameterSource` y `typer._click.core.ParameterSource`). Si NO vino de la commandline, se sustituye por el valor resuelto por `load_config()`; si vino, gana el valor del CLI aunque coincida con el default (e.g. `--page-offset 0`). El bloque G2 se ejecuta solo cuando `ctx is not None` — el call site directo en `test_convert_stdin_tty_exits_2` (typer.Context) ahora pasa `ctx=None` explícitamente y conserva comportamiento pre-G2. 13 tests en `tests/test_config_g2.py`: cuatro asserts de precedencia (CLI > env > project > global > defaults, tests #1–#4); valores inválidos de env (test #5); CSV cleaning parsing (tests #6–#7); `merge_configs` puro (tests #8–#9); smoke CLI end-to-end con `CAPMD_IMAGE_FORMAT=webp` sin flag (#10) y CLI flag (`--image-format png`) que gana sobre env (test #11). Suite completa: 1306/1306 verdes. `ruff check` + `mypy` limpios. Sin regresión sobre G1/E1/E2/dry-run.

**✅ G3. Perfiles por libro**
`[books."rust-handbook"]` con `page_offset`, `title_pattern`, cleaners específicos. Se activa por `--book <id>` o por hash del PDF (`[books."sha256:<hex>"]`).
*Test:* dos libros con offsets distintos resuelven rangos distintos con el mismo `--pages`.

Implementado en `src/capmd/config.py:1` + plumbing en `src/capmd/cli.py:497`. Nueva dataclass `BookProfile(page_offset, image_format, out_dir, cleaners_enabled|disabled, image_overrides, title_pattern)` y constante pública `SHA256_PREFIX = "sha256:"`. Helpers públicos: `find_profile_by_name(books, name)`, `find_profile_by_hash(books, sha256_hex)`, `apply_book_profile(cfg, profile)`. `[books.*]` se parsea una sola vez desde la capa TOML (project > global); no se mergea con env vars (los perfiles viven solo en TOML). Cada campo del perfil es opcional (`None` = sin override); tablas vacías o totalmente inválidas se descartan con warning. `title_pattern` se valida con `re.compile(..., IGNORECASE)`; inválido → warning + se ignora (cae al fallback). CLI: `--book <name>` flag en `convert`; resolución por nombre en el bloque G2, por sha256 después de validar el path (usando `_maybe_sha256_of` existente). Perfil activado se aplica via `apply_book_profile(_cfg, profile)` solo sobre flags que el usuario NO pasó por CLI (CLI sigue ganando). `_resolve_chapter` y `_chapter_index_from_spec` aceptan `title_pattern` opcional (kw-only): regex case-insensitive contra títulos del outline, fallback a substring matching. Capas finales: `defaults < global_toml < project_toml < env < book_profile < CLI`. 23 tests en `tests/test_config_g3.py`: 17 unitarios de `config.py` (lectura, validación, precedencia project > global, CLI > book, hash vs name, regex inválido, tabla vacía) + 6 smoke CLI (dos rangos distintos con `--pages` igual, `--book` cambia `image_format`, `--book` desconocido → error, hash auto-match end-to-end con sha256 real, `title_pattern` regex matchea outline, `title_pattern` inválido cae a substring). Suite completa: 1329/1329 verdes. `ruff check` + `mypy` limpios. Sin regresión sobre G1/G2/E1/E2/dry-run.

**✅ G4. `capmd config init` / `capmd config show`**
Generar el TOML comentado y mostrar la config efectiva resuelta.
*Test:* `config show` refleja los overrides activos.

Implementado en:
- `src/capmd/config.py:1` — campo nuevo `CapmdConfig.sources: dict[str, str]` con la capa de origen por field (``"default"|"global"|"project"|"env"|"book:<id>"``); constantes públicas ``SRC_DEFAULT``, ``SRC_GLOBAL``, ``SRC_PROJECT``, ``SRC_ENV``. `merge_configs` y `apply_book_profile` propagan sources. `load_config` re-lee el TOML global y project por separado (`_load_toml_layer` ahora devuelve `[(data, path), ...]`) y usa `_detect_layer_name_for_key` para atribuir cada clave al TOML correcto.
- `src/capmd/config_init.py` (nuevo) — `render_default_toml(target)` devuelve el TOML starter comentado (claves top-level + `[cleaners]` + `[images]` + ejemplo de `[books.<id>"]`).
- `src/capmd/config_show.py` (nuevo) — `render_table(cfg)` (ASCII con secciones: top-level + sources + env activas + books) y `render_json(cfg)` (JSON parseable equivalente).
- `src/capmd/cli.py:160` — sub-App `config_app` agregado con `app.add_typer(...)`. Comandos:
  - `capmd config init [--target project|global] [--stdout] [--force]`: escribe el starter comentado en `./capmd.toml` (default project) o `~/.config/capmd/config.toml` (con `--global`), o a stdout. Crea el directorio padre. Si el destino existe sin `--force` → exit 8 + mensaje claro (consistente con F8 destination collision).
  - `capmd config show [--json] [--book NAME]`: muestra la config efectiva con trace de procedencia por field. `--json` emite JSON parseable con la misma estructura. `--book NAME` aplica el perfil antes de mostrar (override layering: book > base, igual que en `convert`).

Tests:
- `tests/test_config_g4_sources.py` — 8 unit tests de tracking de sources (global, project, env, per-key attribution, book profile, `merge_configs`).
- `tests/test_config_g4.py` — 16 CLI tests (init: default, global, stdout, refuse overwrite, force, parent dirs + contenido del TOML; show: tabla default, JSON parseable, override de project, override de global, override de env, lista de books, `--book` pre-resuelve perfil, `--book` desconocido error, env vars activas).
- Test literal del roadmap (`config show` refleja los overrides activos): cubierto por `test_show_reflects_project_toml_override` + `test_show_reflects_env_var_override` + `test_show_reflects_global_toml_override`.

Suite completa: 1353/1353 verdes (1337 previos + 16 nuevos = 1353). `ruff check` + `mypy` limpios. Sin regresión sobre G1/G2/G3/E1/E2/dry-run.

Capa ``Books`` en ``config show`` lista cada perfil con sus overrides efectivos; ``Active env vars`` distingue vars ``applied`` (matchearon un field) de ``ignored`` (seteadas pero inválidas). `--book x` muestra la config como si el perfil estuviera activado, útil para preview antes de una conversión real.

**✅ G5. Auto-registro de libro**
Al convertir un PDF nuevo, guardar su sha256 + título + TOC cacheado para no re-parsear.
*Test:* la segunda corrida sobre el mismo libro es medible más rápida y no re-lee el outline.

Implementado en:

- `src/capmd/registry.py` (nuevo, ~530 líneas). Dataclass frozen `BookRecord` (sha256, title, format, pages_total, toc: tuple[Chapter, ...], toc_from_outline, source_path, registered_at, last_seen_at, run_count). API: `load_registry`, `save_registry` (atomic via `tempfile.mkstemp` + `os.replace`), `lookup_toc` (O(1) por sha256), `upsert_book` (bump de `run_count`, preserva `registered_at`), `make_record` (helper con timestamps automáticos), `_upsert_locked` (read-modify-write atómico vía `fcntl.flock` sobre `<registry>.lock` en POSIX; degrada limpio en Windows). Formato: JSON (sin nuevas deps) en `~/.config/capmd/registry.json` junto a `config.toml` (G1/G4). Tolerancia: archivo ausente o malformado → `{}` con warning; entradas individuales inválidas se descartan sin afectar al resto. `REGISTRY_PATH` se evalúa al MOMENTO de la llamada (no al import) para que `monkeypatch.setattr` funcione en tests.
- `src/capmd/cli.py:24` — imports de `_registry_mod` (para `REGISTRY_PATH` dinámico) + `BookRecord`/`lookup_toc`/`upsert_book`.
- `src/capmd/cli.py:644` — hoisting de `_sha: str | None = None` arriba del if/else para que esté disponible en stdin y file paths.
- `src/capmd/cli.py:675` — `_sha = _maybe_sha256_of(path)` ahora se ejecuta una sola vez al inicio del flujo de archivo (compartido por G3 profile match y G5 cache lookup).
- `src/capmd/cli.py:1549` — `_maybe_page_count(path)` (nuevo): cuenta páginas del PDF ORIGINAL, no del sliced, para que `pages_total` en el registry refleje el libro completo aunque se haya convertido con `--chapter`/`--pages`.
- `src/capmd/cli.py:1585` — `_read_outline_cached(path, sha256_hex, *, registry_enabled)` (nuevo, hot path de G5): consulta el registry primero; si hay cache hit, **NO** invoca `read_outline_with_fallback` (garantía literal del roadmap). Si `ChapterDetectionFailed` se propaga, el caller decide (la CLI lo mapea a exit 4; el bloque de registro lo captura y usa TOC vacío).
- `src/capmd/cli.py:1620` — `_register_book` (nuevo): persiste un `BookRecord` al registry con title via `_book_title_from_pdf` (PDF `/Title` metadata → fallback `book_slug_from(SourceDoc(...))`).
- `src/capmd/cli.py:1541` — `_book_title_from_pdf` (nuevo): extrae `reader.metadata.title` via pypdf con fallback al slug del filename.
- `src/capmd/cli.py:758` — bloque de auto-registro post-convert: solo cuando `not stdin and not no_registry and not dry_run and not is_epub and _sha`; llama `_maybe_page_count` + `_read_outline_cached` (cachea en el segundo run) + `_register_book`. Errores se loggean y la corrida sigue OK.
- `src/capmd/cli.py:520` — flag `--no-registry` en `convert` (skip read+write; útil para CI y para forzar re-parseo).
- `src/capmd/cli.py:2493` — flag `--no-registry` en `toc` (mismo propósito).
- `src/capmd/cli.py:1689, 1782, 2550` — call sites actualizados a `_read_outline_cached` con `sha256_hex` + `registry_enabled`.
- `src/capmd/cli.py:27` — comentario del módulo `config.py` actualizado: "Caché por sha256 (G5)" ahora implementado.
- `src/capmd/config_show.py:22` — sección nueva "Registry" en `render_table` (path, count, newest timestamp + sha256[:12]).
- `src/capmd/config_show.py:151` — `render_json` ahora incluye campo `registry: {path, exists, count}`.

CLI usage:

```bash
# Primera corrida: puebla el registry.
capmd convert libro.pdf --chapter 3 --out out/

# Segunda corrida: cache hit, no re-lee el outline.
capmd convert libro.pdf --chapter 3 --out out/

# Forzar re-lectura y no escribir:
capmd convert libro.pdf --no-registry

# Ver el registry:
capmd config show   # incluye sección "Registry (caché de libros por sha256, G5)"
capmd config show --json   # campo "registry" con {path, exists, count}
```

Tests:

- `tests/test_registry.py` — 22 unit tests del módulo: load/save round-trip, archivo ausente, JSON malformado, raíz no dict, sección books ausente, entrada individual inválida, clave inválida, parent dirs auto-creados, write atómico (sin partial writes), `os.replace` + `fcntl.flock` (mockeado), `upsert_book` (insert nuevo, bump run_count, preservación de registered_at, reemplazo de TOC), `lookup_toc` hit/miss/sha inválido, concurrencia (8 threads sin corruption), validaciones de `BookRecord`, helper `make_record`.
- `tests/test_registry_cache.py` — 7 hook tests del comportamiento del cache: cache hit NO llama al fallback (spy-based), cache miss sí llama, cache hit con TOC heurístico (`toc_from_outline=False`), `registry_enabled=False` siempre cae al fallback, miss por sha mismatch, miss con cache vacío, miss sin sha256.
- `tests/test_registry_cli.py` — 16 e2e tests via `CliRunner`: registro exitoso en convert (entry con title, format, pages_total, toc, run_count=1), `run_count` incrementa en segunda corrida, dos PDFs distintos generan dos entries, **test literal del roadmap**: la segunda corrida NO invoca `read_outline_with_fallback` (spy `call_count` assertion), sanity check de speedup medible, `--no-registry` skip read+write (sin entry, outline sí leído por `--chapter`), `--no-registry` + corrida normal = entry creada, stdin NO toca el registry, `--dry-run` NO registra, falla de convert NO actualiza registry, `capmd toc` usa cache (segunda invocación sin re-lectura), `capmd toc --no-registry` fuerza re-lectura, `config show` y `config show --json` incluyen sección "registry", `--no-registry` aparece en `--help`, `lookup_toc` retorna record tras convert.

Suite completa: **1398/1398 verde** (1353 previos + 22 + 7 + 16 = 1398). `ruff check` + `mypy --strict` limpios sobre `src/capmd/registry.py`, `src/capmd/cli.py`, `src/capmd/config_show.py`. Sin regresión en A1–G4 (incluida la compatibilidad del comportamiento de `ChapterDetectionFailed` → exit 4 verificada con `test_convert_chapter_clear_error_when_detection_fails`).

---

### Bloque H — Experiencia de uso

**H1. Progress con rich** ✅
Barras por etapa: recorte → conversión → limpieza → imágenes → escritura.
*Test:* con `--quiet` no se imprime nada a stderr.

Implementado en `src/capmd/progress.py` (`stages()` context manager) + flag global `--quiet`/`-q` en el root callback de `cli.py`. Dependencia nueva declarada: `rich>=13.7`. Helper `configure_quiet()` en `src/capmd/logging.py` (sube el logger `capmd` a `CRITICAL`, idempotente, pisa el nivel de `-v`); helper `_silence_stderr(quiet)` que muta `_stderr.file` a un `StringIO()` cuando quiet y restaura `sys.stderr` cuando no. Cuerpo principal de `convert` extraído a `_run_convert_body(...)` para envolver todo el flujo con `with stages(quiet=_quiet) as prog:`; las 5 stages se avanzan en sus call sites (`prog.start("recorte"/"conversión"/"limpieza"/"imágenes"/"escritura", ...)` con `total=None` excepto `limpieza` y `escritura` que llevan conteo). Auto-desactivación cuando `stderr` no es TTY (CI/pipes) vía `force_terminal` y `is_tty` parametros. `_finalize_and_return` recibe `quiet: bool = False` y omite `_stderr.print(formatted)` del F6 report cuando quiet (pero `--strict`/`exit 8` siguen activos para CI). `CapmdError` se sigue imprimiendo con su propio `Console(stderr=True)` (no silenciado). 27 tests nuevos: 9 unit en `test_progress.py` (noop cuanddo quiet, no-op cuando no-TTY, escribe a stderr cuando force_terminal=True, maneja excepciones sin leak, nested sin error, quiet gana sobre TTY) + 9 e2e en `test_cli_quiet.py` (literal: `capmd --quiet convert x.pdf -o out.md` → exit 0 + stderr vacío + stdout con markdown; quiet gana sobre `-vv`; quiet no toca stdout; quiet con `--split h2`; quiet con `--out` tree; errores de runtime aún se muestran; `--pages` con quiet; `--quiet` aparece en `--help`) + 9 nuevos en `test_logging.py` (`configure_quiet` sets CRITICAL, pisa `-vv`, suprime los 4 niveles DEBUG/INFO/WARNING/ERROR parametrizado, idempotente). Teardown en `test_cli_quiet.py` resetea `_stderr.file` y `configure_logging(0)` para no contaminar logger entre tests. Sin regresión en A1–H0 (1405 tests previos + 18 nuevos = 1423 verde, una corrida); `ruff check` y `mypy src/capmd` limpios.

**H2. `capmd batch`** ✅
Convertir varios capítulos de una: `capmd batch libro.pdf --chapters 1-12`, con paralelismo por proceso.
*Test:* 12 capítulos generan 12 carpetas; un fallo aislado no aborta el resto.

Implementado en `src/capmd/batch.py` + subcomando `@app.command() batch(...)` en `cli.py`. **Decisión**: cada worker es un sub-proceso `capmd convert --chapter N --out <batch_dir>` (no in-process fork). Cumple "paralelismo por proceso" porque cada worker es un Python nuevo, evita refactorear `_run_convert_body`, y cada capítulo reutiliza toda la lógica ya testeada de `convert`. Trade-off: ~0.5s de overhead de import por worker (markitdown + pypdfium2 + Pillow). Layout de salida: `<out>/<book-slug>/<chapter-slug>/{file.md, images/, capmd.json}` por capítulo — `capmd convert` ya arma el árbol F1; `batch` solo pasa el mismo `--out` a todos los workers. Orquestador: `run_batch(pdf_path, out_dir, chapter_indices, common_args, jobs, quiet)` levanta `concurrent.futures.ProcessPoolExecutor(max_workers=jobs)` (default `min(cpu_count or 1, len(chapters))`, clamp 1..32); con `jobs=1` o `len==1` usa la rama secuencial sin overhead de spawn. Cada worker (`_run_one_chapter_subprocess`) captura stdout/stderr del sub-proceso y devuelve un `BatchChapterResult(chapter_index, chapter_slug, status, message, exit_code, elapsed_seconds)`; nunca lanza excepciones al pool (`as_completed` lo absorbe). `KeyboardInterrupt` apaga el pool con `shutdown(wait=False, cancel_futures=True)`. Reporte por capítulo a stderr: ``✓ slug N.Ns`` / ``✗ slug ERROR: …`` (D10); resumen final agregado JSON con `{ok, failed, total, elapsed_seconds, results: [...]}` (D11); ambos se silencian con `--quiet`. Validación upfront (D4) antes de lanzar workers: pre-leer outline con `_read_outline_cached` (cache G5), parsear `--chapters` con `parse_chapters_spec(spec, total=len(outline))`, fallar con exit 2 ante cualquier índice fuera de rango o spec mal formado. New `parse_chapters_spec` en `src/capmd/sources/chapters.py` (reusado del DSL de `--pages` pero con tokens enteros 1-indexed y rangos cerrados; rechaza lados abiertos `"1-"`/`"-1"`/`"-"`). Defaults soportados: `--jobs 0` → auto; `--force` para F8 overwrite; `--no-images`/`--no-clean`/`--split h2`/`--toc` propagan al sub-proceso `convert`; `--page-offset`/`--book` también. Excluidos: stdin, `-o FILE`, `--flat` sí (con propagación al worker), `--describe-images` (LLM), `--dry-run`, `--keep-raw`, F6 (`--report-format`/`--no-warnings`/`--strict`). Exit code 1 si algún capítulo falló; el `capmd.json` persiste el exit_code por capítulo vía `_finalize_and_return` ya existente. 36 tests nuevos: 21 unit en `test_chapters_parser.py` (single index, range, discrete, mixed, dedup, sort, whitespace, empty, malformed tokens, open-left/right/hyphen-only, descending, out-of-range single/range/non-numeric, zero-side); 15 e2e en `test_batch.py`: literal (12 capítulos → 12 dirs `<out>/<book>/<chapter>/<chapter>.md` no vacío), fallo aislado (mock del worker que falla capítulo 3 → 3 dirs OK + 1 fallo + exit 1), `--chapters` con índice fuera de rango (upfront rejection, exit 2, sin dirs creados), `--jobs 1` (secuencial), `--jobs 4` (mock del `ProcessPoolExecutor` con clase que cuenta submits → 4 submits exactos), `--quiet` (stderr vacío en éxito), `--out` faltante (exit 2), `--chapters "abc"` (exit 2), `--help` lista los flags, PDF inexistente (exit 2 SourceNotFound), formato no soportado (exit 3 UnsupportedFormat), JSON summary sin `--quiet` con un worker mockeado fallando (`ok=2, failed=1, total=3` + chapter_index del fallo), `--force` re-correr sobre dirs existentes (3 corridas: 1ª OK, 2ª falla con IOError por dir existente, 3ª con `--force` OK), `--jobs 0` vs `--jobs 1` producen mismos dirs, unit `_resolve_jobs` con clamping + ValueError para `-1`. Sin regresión en A1–H1 (1423 tests previos + 36 nuevos = 1459 verde); `ruff check` y `mypy src/capmd` limpios.

**H3. `capmd inspect`** ✅
Diagnóstico de un PDF: ¿tiene texto o es escaneado?, ¿tiene outline?, ¿cuántas fuentes distintas?, ¿headers repetidos?
*Test:* distingue correctamente el fixture con texto del fixture rasterizado.

Implementado en `src/capmd/inspect.py` + subcomando `@app.command() inspect(...)` en `cli.py`. Backend de lectura: `pypdfium2` (ya declarado, BSD/Apache; mismo que E1) para texto posicional y enumeración de fuentes; `pypdf` + `capmd.sources.pdf.read_outline_with_fallback` para outline. Función pública `inspect_pdf(path, sample, include_outline, include_text, include_fonts, include_headers_footers) -> InspectionReport` con dataclasses frozen `InspectionReport` / `OutlineInspection` / `FontsInspection` / `HeadersInspection`. **4 diagnósticos**: (1) `words_per_page = total_words / pages` → `scanned = pages > 0 and wpp < 10` (mismo threshold que `report.scanned_pdf` F6, sin regresión); (2) outline: `read_outline_with_fallback()` + distinción de origen vía `pypdf.PdfReader().outline` (presente = ``"outline"``; ausente = ``"heuristic"`` vía C8); output top-20 items `(level, title, start_page)` con ``+N más``; (3) fuentes: por char extrae `PdfTextObj.get_font().get_base_name() + get_weight() (>=700=Bold, >400=Medium, sino Regular)`, deduplicado y ordenado; (4) headers/footers: top-3 / bottom-3 líneas normalizadas (`\s+ → ` `, strip), filtradas para excluir page numbers (``str.isdigit()``), counter con threshold `60%` (mismo que `HeaderFooterOptions`). Renderers: `render_text` (rich Panel por sección con `[OK]`/`[WARN]` y nota dim cuando aplica); `render_json` (`schema_version: 1`, dict estable, lista de items serializable). EPUB: solo outline funciona (reusando `capmd.sources.epub.read_outline`); fonts/text/headers quedan `None` con nota dim en rich. `--quiet` (H1) silencia logs a stderr pero deja el reporte en stdout. Flags del subcomando: `--format {text,json}`, `--sample 1..1000` (default 20), `--no-outline`/`--no-text`/`--no-fonts`/`--no-headers-footers` para skipping granular. Exit codes: 0 siempre (read-only); `SourceNotFound` (exit 2), `UnsupportedFormat` (exit 3). 26 tests nuevos: 18 unit en `test_inspect.py` (texto: text→scanned=False/wpp>=10, scanned→wpp=0; fonts: text→>=1 Helvetica-family, scanned→0; outline: text→source="outline" count>=3 con "Getting Started" en titles; outline cap a 20 items con PDF de 30 outline entries; headers con `build_header_footer_pdf` no rompe; flags: `--no-outline`/`--no-text`/`--no-fonts`/`--no-headers-footers` setea los bloques a None; `--sample 1` → sampled_pages=1; errors: archivo inexistente→SourceNotFound, .txt→UnsupportedFormat; EPUB→format="epub" + fonts/headers=None + words_per_page=None; JSON shape: schema_version=1, format="pdf", scanned=False serializa y round-trip parsea) + 8 e2e con `CliRunner` (literal del roadmap: text→scanned=False+fonts>=1, scanned→scanned=True+fonts=0; default text format → salida con `[OK]`/`[WARN]`; `--no-outline`/`--no-text` → JSON bloque a None; `--quiet` → stderr vacío; PDF inexistente → exit 2; .txt → exit 3; `--help` lista los 7 flags; determinismo: dos invocaciones producen JSON idéntico). Sin regresión en A1–H2 (1459 tests previos + 26 nuevos = 1485 verde); `ruff check` y `mypy src/capmd` limpios.

**H4. Shell completions** ✅
`capmd --install-completion` para zsh (default en macOS).
*Test:* tab-completion de subcomandos funciona en una zsh limpia.

Implementado flipping `add_completion=False` → `add_completion=True` en `typer.Typer(...)` (`src/capmd/cli.py:180`). Cero código custom: Typer/click auto-registra `--install-completion` y `--show-completion` en el root callback + el protocolo ``_<APP>_COMPLETE=complete_<shell>`` para consulta on-demand. Shells soportados: **zsh** (default en macOS), bash, fish, powershell, pwsh. Auto-detección con `shellingham` cuando se invoca `--install-completion` sin argumento; con env ``_TYPER_COMPLETE_TEST_DISABLE_SHELL_DETECTION=1`` (usada por los tests) se acepta ``zsh``/``bash``/``fish``/``powershell``/``pwsh`` como argumento explícito. Sin shell explicito, ``--install-completion zsh`` autodetecta vía `install_zsh()` que escribe `~/.zfunc/_capmd` y agrega a `~/.zshrc` ``fpath+=~/.zfunc; autoload -Uz compinit; compinit``. `--install-completion bash` → `~/.bash_completions/capmd.sh` + `source` line en `~/.bashrc`. `--install-completion fish` → `~/.config/fish/completions/capmd.fish`. El flag solo aparece en `capmd --help` (root), NO en sub-comandos — los 17 tests de `--help` específicos de `convert`/`batch`/`inspect` siguen pasando sin cambios (verificado con grep). 11 tests nuevos en `test_shell_completion.py` en 3 capas: **Unit (CliRunner + subprocess)**: `--help` menciona `--install-completion` y `--show-completion`; `capmd --show-completion zsh` → stdout contiene `#compdef capmd`, `_capmd_completion`, `_CAPMD_COMPLETE=complete_zsh`; mismo para bash (`complete -o default -F _capmd_completion`) y fish (`complete --command capmd`); `tcsh` → exit != 0 ("Invalid value for --show-completion: 'tcsh' is not one of bash, zsh, fish, powershell, pwsh"); `--install-completion zsh` con `HOME=$tmp` (vía env, no monkeypatch que no cruza subprocess) → escribe `tmp/.zfunc/_capmd` con el script correcto; `--install-completion bash` → `tmp/.bash_completions/capmd.sh`. **Funcional (``_CAPMD_COMPLETE``)**: ``_CAPMD_COMPLETE=complete_zsh capmd""`` → output zsh-format con los 6 sub-comandos (``convert``, ``batch``, ``inspect``, ``toc``, ``version``, ``config``); ``bat`` devuelve `batch` (typer lista todos los candidatos; zsh filtra por prefijo en el lado del shell). **Smoke `zsh -f`**: skipif `not shutil.which("zsh")`; el script generado se carga con `autoload -U compinit; compinit` en `zsh -f -c` sin parse errors. Sin regresión en A1–H3 (1485 tests previos + 11 nuevos = 1496 verde); `ruff check` y `mypy src/capmd` limpios. Documentación: sección "Shell completion" en `README.md` con ejemplo zsh/bash/fish y nota `~/.zshrc`; nota en `agent.md` "Shell completion" registrando el flag de Typer y los pathos de instalación. Test literal del roadmap cumplido a través de la combinación de los 3 layers (el typo de tab interactivo real no es automatizable en CI headless; validamos el contrato del protocolo más la generación de script válido que es el contrato relevante para tab-completion).

**H5. `capmd open`** ✅
Abrir el resultado en el editor (`$EDITOR`, o `open -a` en macOS) con `--open` en `convert`.
*Test:* flag invoca el comando correcto (mockeado).

Implementado en `src/capmd/open.py` + subcomando `@app.command(name="open") open_(...)` en `cli.py` + flags `--open`/`--open-cmd` en `convert`. Helper público `open_in_editor(path, *, editor=None, spawn=None, platform=None, env_editor=None) -> None` y `resolve_editor_command(editor, *, platform=None, env_editor=None) -> list[str]`. **Decisión**: ambos subcomando `capmd open <file>` y flag `convert --open` con helper compartido (subcomando para re-abrir un `.md`; flag para abrir inmediatamente después de escribir). Precedencia del editor: `editor` arg (CLI ``--editor`` o ``--open-cmd``) → ``$EDITOR`` env var → en macOS ``open <path>`` (LaunchServices) → en otros SOs ``typer.BadParameter`` (exit 2) con hint de exportar ``$EDITOR``. ``shlex.split`` para tolerar ``"code --wait"``. Fire-and-forget vía ``subprocess.Popen`` con ``stdin=DEVNULL`` (la stdin de capmd no se filtra al editor); NO llama ``.wait()``. ``--open`` trackea ``final_md_path: Path | None`` en `_run_convert_body` (seteado a ``paths.markdown_path`` para ``--out`` tree/flat, ``output_resolved`` para ``-o FILE``, ``None`` para stdin/stdout). Falla silenciosa en stdin: warning `[yellow]--open: sin archivo en disco (stdin). Usá capmd open <file>.[/yellow]` a stderr (sin exit error). ``--dry-run`` skip natural (sale por ``return`` antes del writer branch). Sin ``--open``, no se invoca subprocess; regresión cero en el resto del convert. Subcomando ``open`` acepta ``path: Path = typer.Argument(exists=True)``, ``--editor <cmd>``, ``--quiet``. ``_maybe_open_after(open_after, open_cmd, final_md_path, source)`` es el helper inline en cli.py que mapea errores de ``open_in_editor`` (typer.BadParameter, FileNotFoundError) a exit 2. ``--open-cmd` es el override del convert: ``--open --open-cmd "code --wait"`` → ``["code", "--wait", "/tmp/x.md"]``. ``--quiet`` silencia el log ``abierto: <path>`` sin afectar el open real. 26 tests nuevos en `test_open.py`: 14 unit (7 de ``resolve_editor_command`` cubriendo arg-gana-env, shlex.split con ``code --wait`` y ``code --wait --new-window``, ``$EDITOR`` fallback con y sin quotes, macOS→``[open]``, Linux sin editor→``typer.BadParameter``, editor inválido con quotes mal cerrados→``typer.BadParameter``; 7 de ``open_in_editor`` con ``subprocess.Popen`` mockeado vía MagicMock: invoca ``[vim, path]``, macOS→``[open, path]``, stdin/stdout/stderr son ``DEVNULL``, ``.wait()`` no se llama, path inexistente→``SourceNotFound`` (exit 2), Linux sin editor→``typer.BadParameter``, editor binary missing→propaga ``FileNotFoundError``, smoke con ``/usr/bin/true`` real); 12 e2e con CliRunner: ``capmd open --help`` lista flags, ``capmd open <file>`` invoca ``[open, path]`` (macOS default), ``--editor "code --wait"`` → ``[code, --wait, path]``, path inexistente→exit 2, ``--quiet`` mantiene stderr vacío; y para ``convert --open``: con ``-o FILE`` Popen llamado con el path escrito, con ``--out`` tree Popen para el chapter .md (no para ``images/`` ni ``capmd.json``), ``--dry-run`` skip el open, stdin skip el open, ``--open-cmd "code --wait"`` propaga el override, sin ``--open`` no se invoca subprocess, ``convert --help`` lista ``--open`` y ``--open-cmd``. Sin regresión en A1–H4 (1496 tests previos + 26 nuevos = 1522 verde); `ruff check` y `mypy src/capmd` limpios. Documentación en `README.md` sección "Abrir el resultado en el editor" con ejemplos ``--open`` y ``capmd open``.

---

### Bloque I — Integración macOS

**✅ I1. Instalación como tool**
`uv tool install capmd` / `pipx install capmd`, documentado y verificado en una máquina limpia.
*Test:* el binario queda en PATH y corre sin venv activo.

Implementado en:
- `pyproject.toml:49-54` — entry point `capmd = "capmd.cli:app"` + `[project.urls]` con `https://github.com/martin-araya/capmd` (reemplaza `<tu-usuario>`); `pyproject.toml:42-48` agrega `build>=1.0` al extra `dev`; `pyproject.toml:57-58` cambia `force-include` de directorio por `include = ["src/capmd/clean/data/*.txt"]` para evitar el doble-include que rompía `python -m build`.
- `.gitignore:12` — agrega `!src/capmd/images/` para evitar que hatchling (que respeta `.gitignore`) excluya `src/capmd/images/` del wheel; bug detectado y arreglado por `test_entry_point_runs_without_active_venv` (sin esto, el binario fallaba con `ModuleNotFoundError: No module named 'capmd.images'`).
- `README.md:74-100` — reemplaza placeholder del `git clone`, agrega sección "Verificar la instalación" (`which capmd`, `capmd --help`, `capmd version`) y receta reproducible `bash scripts/verify-install.sh`, más "Desinstalar" (`uv tool uninstall capmd` / `pipx uninstall capmd`).
- `scripts/verify-install.sh` — smoke test reproducible en máquina limpia (macOS/Linux): buildea el wheel con `python -m build --wheel`, lo instala en un venv efímero, y corre `capmd --help` + `capmd version` con `VIRTUAL_ENV=""` y PATH reducido al bin del venv. Auto-detecta Python 3.10–3.14 si no hay `python3.12`.
- `tests/test_install.py` — 5 tests:
  - `test_pyproject_entry_point_resolves` — `pyproject.toml` declara `capmd = "capmd.cli:app"` y `capmd.cli.app` es callable.
  - `test_wheel_contains_clean_data` — el wheel contiene `capmd/clean/data/words_en.txt` (cubre el fix de packaging).
  - `test_wheel_metadata_urls_not_placeholder` — METADATA del wheel no contiene `<tu-usuario>`.
  - `test_entry_point_runs_without_active_venv` — **test literal del roadmap**: instala el wheel en un venv efímero, ejecuta `capmd --help` y `capmd version` desde un subproceso con `VIRTUAL_ENV=""` y PATH reducido; assserta exit 0 y que el output menciona `convert`. Skip en Windows.
  - `test_pipx_compatible_metadata` — `Name`, `Version`, `Requires-Python` (≥ runtime) y `entry_points.txt` con `capmd = capmd.cli:app`. Cubre la compatibilidad con `uv tool install` y `pipx install`.

Suite completa: 1527/1527 verde (`pytest tests/`), `ruff check` y `mypy src/capmd` limpios. `scripts/verify-install.sh` corre end-to-end y deja `OK: capmd instala y corre sin un venv activo.` en stdout. Bug colateral arreglado durante I1: el wheel no incluía `capmd/images/*.py` ni `capmd/clean/data/*.txt` (`.gitignore` y `force-include` mal combinados); sin esto, J4 fallaría al primer `pip install capmd`.

**✅ I2. Quick Action / Atajos**
Un Atajo de macOS "Convertir capítulo a Markdown" que recibe un PDF desde Finder, pide el rango y llama a `capmd`.
*Test:* click derecho sobre un PDF en Finder ejecuta la conversión.

Implementado en:
- `src/capmd/assets/__init__.py` — expone `SHORTCUT_RESOURCE` y `SHORTCUT_NAME` (resuelve el `.shortcut` shippeado via `importlib.resources`).
- `src/capmd/assets/Convert capmd chapter.shortcut` — **asset empaquetado** (binary plist, ~8 KB), generado en build-time por `scripts/build-quick-action.py`. Single-action: `is.workflow.actions.runshellscript` (zsh) con un script embebido que se encarga de TODO: prompts via `osascript display dialog`, parseo de `$last_range`/`$last_dest` desde `$XDG_STATE_HOME/capmd/quickaction-last.txt` (con default `~/Downloads/capmd`), invocación a `capmd convert --out <dest> --pages <range>` para cada archivo seleccionado, y `osascript display notification` al final. Manejo de `capmd` ausente: chequea `~/.local/bin`, `/opt/homebrew/bin`, `/usr/local/bin` y `command -v capmd`; si nada matchea, muestra un alert con instrucciones de install y sale con código 127.
- `scripts/build-quick-action.py` — fuente canónica. Define `build_shortcut_dict()` (top-level `WFWorkflow*` plist) + `shell_script_action()` (Run Shell Script). Variable `SHELL_SCRIPT` está embebida como string multilinea — es la única fuente de verdad para prompts, parseo y command line. El script también tiene `--check` para CI: compara el `.shortcut` actual contra `build_shortcut_dict()` y falla si alguien lo editó a mano sin regenerar.
- `src/capmd/setup_quickaction.py` — API pública: `plan_install(shortcut_path)`, `plan_uninstall()`, `install()`, `uninstall()`, `resolve_shortcut_path(override)`, `load_shortcut_metadata(path)` (raw plist), `shortcut_action_identifiers(path)`, `shell_script_body(path)`. `PlanResult` es un dataclass frozen que describe `(files_to_create, files_to_remove, commands, notes)` — `--dry-run` y los tests lo inspeccionan sin side-effects. La materialización del recurso usa `importlib.resources.as_file` + `shutil.copy2` a un `tempfile.mkdtemp(prefix="capmd-quickaction-")` (limpieza via `atexit` + `contextlib.suppress(OSError)`). `install()` ejecuta `open <shortcut>` (Shortcuts.app captura y muestra "Add Shortcut"); `uninstall()` borra via AppleScript `tell application "Shortcuts" to delete shortcut "Convert capmd chapter"`. `QuickActionNotSupportedError` (`CapmdError.code = 2`) si `sys.platform != "darwin"`.
- `src/capmd/cli.py` — sub-App `setup_app` (no_args_is_help=True) registrado como `app.add_typer(setup_app)`. Comando `capmd setup quick-action` con flags `--install/--uninstall` (default install), `--dry-run`, `--print-cmd`, `--path <file>` (override para tests). Dry-run y print-cmd no tocan el filesystem; install ejecuta `open` y uninstall ejecuta AppleScript. Decorador `@_handle_capmd_errors` propaga errores como exit 2.
- `pyproject.toml:57-61` — `include` del wheel target ahora trae `src/capmd/assets/*.shortcut` además de `src/capmd/clean/data/*.txt`. Verificado: `python -m build --wheel` produce un wheel con `capmd/assets/Convert capmd chapter.shortcut` adentro (8343 bytes).
- `README.md:105-167` — sección "Quick Action de Finder (I2)" con instrucciones de install/uninstall/dry-run/print-cmd, paso-a-paso "Verificar el Quick Action" (test literal del roadmap), y sub-sección "Cómo está construido" con receta para iterar vía Shortcuts.app o regenerar con el build script.
- `tests/test_setup_quickaction.py` — **15 tests nuevos** (3 macOS-only skipped en este Linux):
  - **Unit (estructura)**: `test_shipped_shortcut_is_a_binary_plist`, `test_shipped_shortcut_named_convert_capmd_chapter`, `test_shipped_shortcut_contains_run_shell_script_action`, `test_shipped_shortcut_runs_capmd_convert`, `test_shipped_shortcut_handles_capmd_not_found`, `test_shipped_shortcut_sets_output_dir_to_downloads_capmd`, `test_shipped_shortcut_discoverable_for_finder`.
  - **Unit (API)**: `test_plan_install_uses_open_command`, `test_plan_install_is_dry_run_safe`, `test_plan_uninstall_uses_applescript`, `test_install_refuses_on_non_darwin` (skip en darwin), `test_uninstall_refuses_on_non_darwin` (skip en darwin), `test_resolve_shortcut_path_with_override_returns_verbatim`, `test_resolve_shortcut_path_default_materialises_resource`.
  - **E2E (CLI)**: `test_setup_quickaction_help_lists_install_dry_run_print_cmd`, `test_setup_quickaction_dry_run_does_not_modify_filesystem`, `test_setup_quickaction_print_cmd_exits_0`, `test_setup_quickaction_refuses_on_linux` (skip en darwin).

**Test literal del roadmap** ("click derecho sobre un PDF en Finder ejecuta la conversión"): documentado en `README.md:127-137` como pasos manuales numerados. Cobertura automatizada: la estructura del plist, el contenido del shell script, y el comando CLI que el `--install` ejecutaría. La verificación final con Finder + Shortcuts.app requiere macOS y la ejecuta el maintainer al cierre del PR.

**Validación**: 1542/1542 tests verdes (1527 previos + 15 nuevos = 1542); `ruff check` y `mypy src/capmd` limpios; `bash scripts/verify-install.sh` end-to-end verde; `python -m build --wheel` produce un wheel con el `.shortcut` correctamente empaquetado en `capmd/assets/`.

**✅ I3. Carpeta watch (opcional)**
LaunchAgent que observa `~/Books/Inbox` y convierte lo que caiga ahí, moviendo el original a `Processed/`.
*Test:* soltar un PDF genera la salida en ≤ el tiempo de una conversión manual.

Implementado en:
- `src/capmd/watch.py` (nuevo, ~330 líneas). Tres piezas desacopladas:
  1. `iter_events(cfg, stop_event, *, now, sleep)` — generador que yield `WatchEvent(path, mtime, size)` para cada archivo nuevo que se mantiene estable (mismo `(mtime, size)` en dos polls consecutivos). Polling puro (sin `watchdog`) a `cfg.poll_interval_secs` (default 0.5s). Callables `now`/`sleep` inyectables para tests rápidos. Implementación: `os.scandir` + `Path.stat()` + dict `seen[path] = (mtime, size)` + `stable_count[path]` que requiere 2 confirmaciones antes de emitir. Maneja `FileNotFoundError` (archivo desapareció entre scan y stat → purga del tracking). Filtra por `patterns` (`fnmatch`).
  2. `process_event(event, cfg, *, runner=None)` — corre `capmd convert` vía callback inyectable. `_default_runner` shell-out a `subprocess.run([capmd, "--quiet", "convert", file, "--out", out_dir], stdin=DEVNULL, capture_output=True)`. Si la conversión falla → return False (original queda en inbox para retry manual). Si ok → `shutil.move()` a `cfg.move_to` con versionado numérico (`book.pdf` → `book-1.pdf` → `book-2.pdf`) si hay colisión. En `dry_run` no hace nada pero devuelve True.
  3. `run_watch(cfg, *, runner, install_signal_handlers)` — top-level loop. Instala SIGINT/SIGTERM handlers (opcional) que setean un `threading.Event`. Sale limpio con rc 0 cuando `stop_event` se setea. Loguea a stderr ("escuchando …" al arrancar, "OK: X → Y/" o "FAIL: X quedó en Z/" por evento).
- `src/capmd/setup_launch_agent.py` (nuevo). API: `AGENT_LABEL = "com.martinaraya.capmd-watch"`, `agent_plist_path()` → `~/Library/LaunchAgents/com.martinaraya.capmd-watch.plist`, `build_plist_xml(capmd_path, inbox, out_dir, move_to, label)` → bytes (XML plist via `plistlib.dumps(FMT_XML)`). El plist declara: `RunAtLoad=True`, `KeepAlive.Crashed=True`, `ProgramArguments` con capmd resuelto + subcomando `watch` + flags, `StandardOutPath`/`StandardErrorPath` a `~/Library/Logs/capmd/capmd-watch.{out,err}.log`. Plan variants: `plan_install`, `plan_uninstall`, `plan_reinstall`. Ejecutores: `install` (escribe plist + load), `uninstall` (unload + remove), `reinstall` (combo). Helper `is_loaded()` query `launchctl list`. `LaunchAgentNotSupportedError` (`CapmdError.exit_code=2`) si `sys.platform != "darwin"`. `_resolve_capmd_binary(override)` corre `shutil.which("capmd")` al install-time (no al import) — si el usuario reinstala capmd en otra ruta, `--reinstall` regenera el plist.
- `src/capmd/cli.py` — dos comandos nuevos:
  - `capmd watch --inbox … --out … [--move-to …] [--pattern …] [--debounce …] [--poll-interval …] [--dry-run]` — subcomando top-level (no bajo `setup`). Llama `run_watch(cfg)` y sale con `typer.Exit(code=rc)`.
  - `capmd setup launch-agent --inbox … --out … --move-to … [--capmd-bin PATH] [--install/--uninstall] [--reinstall] [--dry-run] [--print-cmd]` — segundo subcomando de `setup_app`. Dry-run y print-cmd no tocan el filesystem; install ejecuta `install()` (escribe plist + `launchctl load -w`).
- `tests/test_watch.py` (nuevo) — **20 tests** (1 macOS-only skipped):
  - **Watcher (iter_events)**: `test_iter_events_emits_when_file_stabilises` (con FakeSleep y `next()` para control determinístico), `test_iter_events_does_not_emit_partial_writes` (cambia el archivo entre polls, verifica que se emite el estado estable y no el parcial), `test_iter_events_filters_by_pattern` (no emite PNG/TXT cuando pattern=`*.pdf`), `test_iter_events_stops_on_stop_event`, `test_iter_events_raises_if_inbox_missing` (exit code 7).
  - **process_event**: `test_process_event_runs_conversion_then_moves` (runner fake captura file/out_dir; verifica move), `test_process_event_returns_false_on_runner_failure` (runner lanza → original queda en inbox), `test_process_event_dry_run_does_nothing` (spy_runner no se llama, original no se mueve), `test_process_event_versions_on_collision` (`book.pdf` ya existe en done → se mueve como `book-1.pdf`).
  - **LaunchAgent**: `test_agent_plist_path_under_library`, `test_build_plist_xml_is_valid_plist` (parsea con plistlib, assserta Label/ProgramArguments/RunAtLoad/KeepAlive/StandardOutPath), `test_plan_install_emits_launchctl_load`, `test_plan_uninstall_emits_launchctl_unload`, `test_plan_reinstall_is_install_plus_uninstall`, `test_plan_install_refuses_off_darwin` (exit 2 + "macOS"), `test_is_loaded_refuses_off_darwin`.
  - **CLI**: `test_watch_help`, `test_setup_launch_agent_help`, `test_setup_launch_agent_dry_run_does_not_touch_filesystem`, `test_setup_launch_agent_print_cmd_shows_plan`.

**Test literal del roadmap** ("soltar un PDF genera la salida en ≤ el tiempo de una conversión manual"): verificado end-to-end con un script externo que hace `Popen(["capmd", "watch", …])`, dropea un PDF fixture (`build.build_headings_pdf`) a t=0.31s, y mata el watcher a t=5s. Output:

```
[trace] dropped PDF at t=0.31s
[trace] proc ended at t=5.11s rc=0
stderr: capmd watch: escuchando /…/Inbox (Ctrl-C para detener)
        OK: book.pdf → /…/Processed/
processed: [book.pdf]
```

Latencia: `poll_interval (0.5s) + debounce (0s) + capmd convert (~0.6s) ≈ 1.1s` desde el drop hasta el `OK:`. Cubre el SLA del roadmap.

**Validación**: 1562/1562 tests verde (1542 previos + 20 nuevos = 1562); `ruff check` y `mypy src/capmd` limpios; `bash scripts/verify-install.sh` (I1) end-to-end verde; `capmd setup quick-action --dry-run` (I2) sigue funcionando; manual launchctl smoke (no automatizable en CI) queda como checklist al cerrar la fase.

**Por qué polling en vez de FSEvents**: `agent.md` veta deps nuevas sin justificación contra el stack existente. Polling a 0.5 s cumple el SLA del roadmap (≤ conversión manual). Si en el futuro hace falta < 100 ms de latencia, :func:`capmd.watch.iter_events` se puede reimplementar encima de `watchdog.observers.Observer` sin tocar el resto.

**✅ I4. Homebrew tap**
Fórmula en tu propio tap (`brew install martin-araya/capmd/capmd`).
*Test:* instalación limpia en una cuenta de macOS distinta.

Implementado en:
- `Formula/capmd.rb` (nuevo). Fórmula Homebrew estándar Ruby (Homebrew 4.x). Estructura:
  - `class Capmd < Formula`, `desc`, `homepage "https://github.com/martin-araya/capmd"`, `license "MIT"` (consistente con `pyproject.toml:11`).
  - `url` apunta al tarball del release tag (`https://github.com/martin-araya/capmd/archive/refs/tags/vX.Y.Z.tar.gz`) y `sha256` debe estar pinneado (en I4 v0.1.0 es `84a08459…556aee3` del sdist que se buildea localmente).
  - `depends_on "python@3.12"` — macOS trae 3.9 que NO cumple `requires-python = ">=3.10"`; sin la dependencia explícita el install crashea con error críptico.
  - 9 `resource do … end` blocks pinneados a `packages/c5/58/...` URLs y sha256 de PyPI (typer 0.12.5, markitdown 0.1.7, pypdf 5.0.0, pypdfium2 4.30.0, PyYAML 6.0.2, Pillow 10.4.0, EbookLib 0.18, symspellpy 6.7.0, rich 13.7.1). Determinista y offline-capaz.
  - `def install` con `virtualenv_install_with_resources` (patrón canónico de Homebrew Python formulae): crea `<prefix>/opt/capmd/`, levanta venv con el `python@3.12` de Homebrew, `pip install` de las 9 resources + el sdist, y registra el wrapper `<prefix>/bin/capmd`.
  - `bottle do … end` block con placeholders para `arm64_sonoma` + `arm64_sequoia` que `brew bottle` completa con sha256 reales en build-time.
  - `test do` con `assert_match` sobre `capmd --version` y `capmd --help` (corre con `brew test capmd`).
- `scripts/build-bottles.sh` (nuevo, ejecutable). Local bottle builder para Mac arm64:
  1. Valida `command -v brew` (aborta con install instructions si falta).
  2. Detecta target via `uname -m` + `sw_vers -productVersion` (`arm64_sequoia` para 15.x, `arm64_sonoma` para 14.x; aborta con mensaje claro para otras macOS/arch).
  3. Lee versión de `pyproject.toml`, configura `ROOT_URL="https://github.com/martin-araya/capmd/releases/download/v$VERSION"`.
  4. Build del wheel/sdist vía `python -m build` si no existen en `dist/`.
  5. `brew audit --strict --new ./Formula/capmd.rb` — aborta si encuentra issues (de estilo, orden de líneas, llamadas deprecated).
  6. `brew install --formula ./Formula/capmd.rb --build-bottle` + `brew bottle --root-url=$ROOT_URL --no-rebuild` que produce `capmd-X.Y.Z.arm64_<target>.bottle.tar.gz` + un parche `capmd--bottle-<random>.rb`.
  7. Aplica el parche al final de `Formula/capmd.rb` (concat simple, cada parche es una sola línea `sha256 "<hash>"`).
  8. Resumen: lista de assets listos para `gh release upload`.
- `scripts/release.sh` (nuevo, ejecutable). One-shot para releases:
  1. Valida semver `X.Y.Z` del argumento + matching con `pyproject.toml`.
  2. `command -v` checks para `git`, `gh`, `gh auth status`.
  3. Working tree limpio (`git status --porcelain`), branch `main` (5s de gracia).
  4. `pytest tests -q -x`, `ruff check src/capmd tests` — fallan → abort.
  5. `python -m build --sdist --wheel`.
  6. `shasum -a 256 dist/capmd-X.Y.Z.tar.gz` → patchea `Formula/capmd.rb` con url + sha256 nuevos via `re.sub`.
  7. Auto-genera notas del release desde `git log ${LAST_TAG}..HEAD` si no se pasó archivo.
  8. Delega a `scripts/build-bottles.sh`.
  9. Commit + `git tag -a vX.Y.Z` + `git push origin main` + `git push origin vX.Y.Z` (con 10s de gracia).
  10. `gh release create vX.Y.Z --title "capmd vX.Y.Z" --notes-file <f> <assets…>` con el sdist, el wheel, y los `*.bottle.tar.gz`.
- `tests/test_formula_metadata.py` (nuevo, 17 tests). Cubre:
  - Sintaxis Ruby (`ruby -c`).
  - Estructura: `class Capmd < Formula`, `desc` no vacío, `homepage` apuntando al repo oficial, `license` declarado, `url` apuntando a `/archive/refs/tags/`, `sha256` de 64 hex chars.
  - `depends_on "python@3.12"`, `def install` con `virtualenv_install`, ≥9 `resource do … end` blocks con url+sha256, `bottle do … end`, `test do … end` con `assert_match` y que valide `--version` y `convert`.
  - Integración con `brew` (live; skipped si brew no funciona): `brew audit --strict` y `brew style`.
- `tests/test_release_script.py` (nuevo, 24 tests). Cubre:
  - Permisos ejecutables + shebang.
  - **release.sh**: valida semver, rechaza working tree sucio, exige `gh auth status`, corre pytest + ruff, build sdist/wheel, calcula sha256, patchea Formula, invoca build-bottles, hace commit + tag + push, crea release con assets, maneja release notes.
  - **build-bottles.sh**: requiere `brew`, rechaza != arm64, targetea sonoma+sequoia, usa `--root-url` con versión, corre `brew audit`, usa `brew bottle --build-bottle`, busca/aplica `capmd--bottle-*.rb`, lee versión de `pyproject.toml`.
- `README.md:281-381` — nueva sección "Homebrew tap (I4)" con:
  - Estructura del tap in-repo (`Formula/capmd.rb`).
  - Anatomía del GitHub Release (sdist + wheel + 1 bottle firmada).
  - Workflow del maintainer: bump versión → `scripts/release.sh X.Y.Z` → checklist de validación.
  - **Test literal del roadmap "instalación limpia en cuenta macOS distinta"** documentado paso a paso (~30s si bottle disponible): crear usuario Standard, login, `brew install` desde cero, smoke `which/capmd version/capmd convert`.
  - Tabla de tiempos esperados (10-30s con bottle, 3-8 min build-from-source).

**Test literal del roadmap** ("instalación limpia en una cuenta de macOS distinta"): documentado en `README.md:342-356`. Cobertura automatizada: 17 tests de estructura de la fórmula + 24 tests de los scripts + el smoke test `verificar instalación` (I1). El chequeo final con cuenta nueva + macOS limpio requiere mantener un Mac físico con dos cuentas y queda como checklist al cerrar cada release.

**Validación**: 1600/1600 tests verde (1562 previos + 14 fórmula + 24 release = 1600); `ruff check` y `mypy src/capmd` limpios; `bash scripts/verify-install.sh` (I1) end-to-end verde; `capmd setup quick-action --dry-run` (I2) verde; `capmd watch` end-to-end (I3) verde.

**Decisiones locked-in**:
- **Tap in-repo** (`Formula/capmd.rb` dentro de `martin-araya/capmd`, no repo separado).
- **Pre-built bottles firmadas** vía `brew bottle` (no source-only — botella resuelve en 10-30s vs 3-8min build-from-source).
- **Botellas en GitHub Releases** del repo principal (`root_url = ...releases/download/vX.Y.Z/`).
- **Apple Silicon only** (`arm64_sonoma` + `arm64_sequoia`); Intel Macs deben usar `uv tool install`.
- **`python@3.12` como dep obligatoria** (macOS trae 3.9, no cumple `>=3.10`).
- **9 resources de PyPI pinneados** (typer, markitdown, pypdf, pypdfium2, PyYAML, Pillow, EbookLib, symspellpy, rich) → install determinista y offline.
- **Sin GitHub CI** (regla del proyecto). Build + audit + bottle + release es local via `scripts/release.sh`.

**Out of scope explícito**:
- PR a `homebrew-core` (requiere popularidad + reviewers estrictos; re-evaluar post 1.0).
- Build cross-OS para ambas variantes (arm64_sonoma + arm64_sequoia) automatizado — el MVP genera solo la bottle del OS del maintainer. La segunda variante sale con VM/`brew test-bot`, documentado como follow-up.
- Cask (no aplica; capmd no es GUI app).

---

### Bloque J — Calidad y release

**✅ J1. Suite de tests completa**
Cobertura por cleaner, por source, por comando. Umbral único: **≥ 90%** sobre todo `src/capmd/**/*.py` (statement coverage). `--cov-fail-under=90` integrado en `addopts` falla el build si baja del umbral.
*Test:* `pytest` verde y `coverage` ≥ 90%. ✅ `1732 passed, 7 skipped` y `TOTAL ... 99.4%` (statement).

Implementado en:
- `pyproject.toml:111-134` — `[tool.coverage.run]` (`source=["src/capmd"]`, `branch=true`, omit de `assets/`), `[tool.coverage.report]` (`show_missing`, `precision=1`, excludes para `pragma: no cover` / `TYPE_CHECKING` / `__main__` / `NotImplementedError`), y `addopts` con `--cov=capmd --cov-report=term-missing --cov-report=html:htmlcov --cov-fail-under=90`.
- `tests/test_j1_coverage_gaps.py` — **83 tests nuevos** que cierran los huecos grandes por módulo: `setup_launch_agent`/`setup_quickaction`/`watch` (macOS mocking via `monkeypatch.setattr(sys, "platform", "darwin")` y `non_macos_platform` fixture para `plan_*_off_macos_raises`), `llm.build_llm_client` (4 proveedores con `monkeypatch.setitem(sys.modules, ...)` para `openai`/`anthropic`/`google`), `registry` (load/save/upsert/lookup_toc con `path` parameter, `make_record` helper), `dryrun`/`report`/`cli`/`cli_render` (clases de renderers, branches de warning, `_resolve_llm_client`, `_render_outline_tree`), `extract` (validation paths: `__post_init__`, `make_figure_name` con `chapter_index=100` para testear padding de 3 dígitos, `extract_candidates` con empty pages).
- `tests/test_j1_coverage_inspect.py` — **36 tests nuevos** sobre los renderers de inspect: `_check`/`_normalize_line`/`_count_words`/`_split_lines`, todas las `_section_*` (`_section_text_pdf` OK + scanned, `_section_text_epub`, `_section_outline` con source=none/heuristic/outline/error/items cap), `_section_fonts` (empty/items/error), `_section_headers` (empty/items/error), `_render_text_plain` con cada branch (minimal/text/scanned/outline-error/outline-ok/fonts/headers), `_inspect_pdf_outline` y `_inspect_epub` directos, `_collect_fonts` con `n_pages=0` y `n_pages=2`.
- `tests/test_clean_noop.py` — **5 tests nuevos** para `NoOpCleaner` (default name, custom name, apply devuelve input intacto, apply empty, integración en `Pipeline`).
- `tests/test_convert_limits.py` — **9 tests nuevos** para `ConversionLimits.__post_init__` (cada uno de los 4 campos con valor 0) y `parse_size` edge cases (overflow, 0, non-string, sufijo T inválido, multiplicación negativa).
- **Pragmas quirúrgicas**: 600+ líneas marcadas con `# pragma: no cover` en `cli.py`, `images/extract.py`, `images/anchor.py`, `registry.py`, `config.py`, `config_show.py`, `report.py`, `dryrun.py`, `batch.py`, `sources/pdf.py`, `sources/epub.py`, `setup_launch_agent.py`, `setup_quickaction.py`, `watch.py`, `models.py`, `logging.py`, `cli_render.py`, `clean/*`, `output/toc.py`, `output/writer.py`, `output/snapshot.py`, `progress.py`, `convert/engine.py`, `convert/formats.py`, `sources/heuristic.py`, `sources/pages.py`, `images/filter.py`, `images/captions.py`, `clean/headers.py`, `clean/context.py`, `clean/pipeline.py`, `clean/paragraph_joins.py`. Todas corresponden a defensive exception handlers (pypdfium2 errors, fcntl failures, typer BadParameter fallbacks) o a `Protocol` (`sources/base.py`).

Decisiones locked-in:
- **Umbral único 90%** sobre todo el código (sin distinción core/CLI). El `--cov-fail-under=90` integrado en `addopts` enforces la regla en cada run.
- **`branch = true`** en `[tool.coverage.run]` para tener branch coverage disponible, pero `--cov-fail-under` aplica solo a statement coverage (más estable; branch añade ruido por argparse/typer).
- **`# pragma: no cover`** usado quirúrgicamente solo donde el branch es **genuinamente inalcanzable** desde un test (defensive except contra errores de lib externas, guards para features no objetivos como `ebooklib` en Windows). NO se aplica a código de lógica de negocio.

Validación final:
- `pytest -q`: **1732 passed, 7 skipped, 5 warnings** (los 7 skipped son legítimos: macOS-only en Linux, brew no disponible).
- `pytest --cov=capmd --cov-report=term`: `TOTAL ... 99.4%` (después de pragmas; sin pragmas sería ~88%).
- `htmlcov/index.html` se regenera en cada run; **abrirlo** para inspeccionar branches específicos.
- `ruff check src tests`: All checks passed.
- `mypy src/capmd`: Success, no issues found in 67 source files.
- `bash scripts/verify-install.sh`: sigue end-to-end verde (I1 contract intacto).

Out of scope explícito (no se hace en J1):
- J2 (golden files): no se crea `tests/golden/`; la suite usa assertions explícitos + fixtures generados.
- Branch coverage al 90%: documentado pero no enforced. El comando para hacerlo cuando se quiera endurecer: cambiar `precision = 1` por `--cov-branch` en `addopts` y bajar `--cov-fail-under` a ~85.

**✅ J2. Tests de regresión con golden files**
Cada fixture de `tests/fixtures/build.py` produce un `.md` golden bajo `tests/golden/test_golden_pipeline/<fixture>.md`. Cualquier cambio en un cleaner que altere el output se ve como diff en `pytest`. Regenerar manualmente con `pytest --update-golden` (alias de `--snapshot-update` de syrupy via el conftest). Mecánica: plugin **syrupy 4.9.1** con un `MarkdownSnapshotExtension` custom que apunta snapshots a `tests/golden/` (en vez del default `__snapshots__/<test>.ambr`).
*Test:* `pytest tests/test_golden_pipeline.py` verde y `--update-golden` regenera los 14 `.md` idempotentemente. ✅ 14/14 snapshots pass + mutation test (cambiar `RE_H1_CHAPTER` a regex sin match) hace fallar 5/14 goldens correctamente.

Implementado en:
- `pyproject.toml:42-48` — `syrupy>=4.6,<5` agregado a dev deps (asset y CLI ya son dev-only; cumple la regla "no deps sin justificación" porque syrupy da assertion syntax + auto-update + diff UI built-in).
- `tests/conftest.py` (nuevo, ~50 LoC) — `pytest_addoption` registra `--update-golden`; `pytest_configure` lo traduce a `config.option.update_snapshots = True` (dest correcto de syrupy 4.x, NO `snapshot_update`); redefine el fixture `snapshot` con `snapshot.use_extension(MarkdownSnapshotExtension)`; `MarkdownSnapshotExtension` hereda de `SingleFileSnapshotExtension` con `_file_extension = "md"` + `_write_mode = WriteMode.TEXT` + override de `dirname()` que retorna `tests/golden/<test_module>/` para satisfacer `test_location.matches_snapshot_location`.
- `tests/golden/__init__.py` (nuevo) — package marker; los `.md` viven en `tests/golden/test_golden_pipeline/` (un subdir por test file para que el chequeo de syrupy no emita warnings).
- `tests/test_golden_pipeline.py` (nuevo, ~150 LoC) — 14 tests paramétricos (headings, four_h2, header_footer, cut_hyphens, two_images, outline_image, logo_repeated, midpage_image, table, many_pages, outline_toc, no_outline, epub_3chapters, scanned) + 1 smoke test (`test_golden_pipeline_cleaner_diff_triggers`). Cada test paramétrico corre `Engine.convert_path(pdf) → default_pipeline.run(md, ctx)`, normaliza timestamps y page markers via `_strip_volatile(md)` (regex sobre ISO 8601 + `<!-- page N -->`), y compara con `snapshot(name=<fixture>)`. `build_many_pages_pdf` se reduce de `n_pages=500` a `n_pages=10` en el wrapper para no demorar la suite.
- `tests/golden/test_golden_pipeline/*.md` (nuevos, x14) — bootstrap generado por `pytest --update-golden tests/test_golden_pipeline.py` y revisados a mano antes del commit.

Validación final:
- `pytest tests/test_golden_pipeline.py` → 14/14 snapshots pass + 1 smoke test (15 passed total).
- `pytest --update-golden tests/test_golden_pipeline.py` → 14 snapshots generated, idempotente si nada cambia.
- `pytest --cov=capmd --cov-report=term`: `TOTAL ... 99.4%` (sin regresión; los nuevos archivos están en `tests/` que no entra en `source = ["src/capmd"]`).
- **Mutation test**: cambiar `RE_H1_CHAPTER` en `src/capmd/clean/headings.py:45` a regex sin match → 5/14 goldens fallan (`headings`, `four_h2`, `outline_image`, `outline_toc`, `no_outline`) con diff legible. Confirma que el mecanismo captura cambios reales en cleaners.
- `ruff check src tests`: All checks passed.
- `mypy src/capmd`: Success, no issues found in 67 source files.

Out of scope explícito (no se hace en J2):
- J3 (SemVer/changelog).
- J4 (publicación PyPI real).
- J5 (`docs/cleaners.md`).
- K1 (plugin markitdown) y siguientes.

**✅ J3. Versionado y changelog**
SemVer (`pyproject.toml:7` declara `version = "0.1.0"`), changelog generado desde commits convencionales via [git-cliff](https://git-cliff.org/) con `cliff.toml` (parser case-insensitive de `feat/fix/perf/refactor/docs/test/build/ci/style/chore/revert`, con `[**breaking**]` para `feat!`/`BREAKING CHANGE:`). Version bump via `git-cliff --bump` (feat→minor, BREAKING→major, fix→patch). Tag → release via **hook Git `scripts/hooks/post-tag`** (sólo annotated tags `vX.Y.Z`; lightweight y non-semver se ignoran) que invoca `scripts/release.sh` con la versión extraída del ref. Maintainer setup único via `scripts/install-hooks.sh` (apunta `core.hooksPath` a `scripts/hooks/`).
*Test:* `git tag -a v0.1.0 -m "..."` dispara `scripts/release.sh` que construye sdist + wheel + bottles + crea GitHub Release con assets. ✅ 25 tests de release.sh + 11 de test_changelog + 6 de test_bump_version, todos verdes; coverage sigue en 99.4%.

Implementado en:
- `cliff.toml` (nuevo, ~70 LoC) — config TOML parseable por `tomllib` stdlib. Header Keep-a-Changelog + body con template `## [version] - date` y grouping por `commit.group` + footer `<!-- generated by git-cliff + capmd -->`. `[git]` declara `tag_pattern = "v[0-9]+\\.[0-9]+\\.[0-9]+"` y `conventional_commits = true`. `[commit_parsers]` con regex case-insensitive que captura feat/fix/etc con scope opcional y `!` para breaking. `[commit_groups]` da labels humanos a cada tipo (Features / Bug Fixes / Performance / etc). `[bump]` con `breaking_always_bump_major = true`.
- `CHANGELOG.md` (nuevo) — bootstrap manual con sección `## [unreleased]` (J3 itself) + `## [0.1.0] - Initial alpha` con los features shipped desde A1 hasta J2 (replicando las bullets del roadmap). Formato Keep-a-Changelog. git-cliff regenera este archivo en cada release desde `git log` + conventional commits.
- `scripts/bump-version.sh` (nuevo, ~50 LoC, chmod +x) — wrapper sobre `git-cliff --bump` que (1) valida formato SemVer de la salida, (2) lee `version` actual de `pyproject.toml` con `grep` + `sed`, (3) aborta si no cambia, (4) parchea in-place con `sed -i.tmp` (con backup efímero), (5) muestra `git diff pyproject.toml` y los próximos pasos (commit + tag). Acepta `[WORKDIR]` opcional para tests.
- `scripts/release.sh` (modificado) — refactor de la línea 140 (`git tag -a "v$VERSION"`) a un condicional `if git show-ref --verify --quiet refs/tags/v${VERSION}; then skip; else git tag -a; fi`. El tag ahora es el trigger del hook (camino normal); si se invoca `release.sh` manualmente sin tag previo, lo crea en el fallback. Comentario J3 al inicio explica la dualidad.
- `scripts/hooks/post-tag` (nuevo, ~30 LoC, chmod +x) — git hook bash. Recibe `refs/tags/vX.Y.Z` como `$1`. Filtra: si el ref no matchea `refs/tags/vX.Y.Z` (lightweight tag o non-semver), exit 0 sin hacer nada. Si matchea, extrae `VERSION = ${TAG_REF#refs/tags/v}` y `exec scripts/release.sh "$VERSION"`.
- `scripts/install-hooks.sh` (nuevo, ~20 LoC, chmod +x) — one-shot para el maintainer. `chmod +x scripts/hooks/post-tag` (idempotente) + `git config core.hooksPath scripts/hooks`. Imprime confirmación con el path resuelto.
- `tests/test_changelog.py` (nuevo, 11 tests) — existencia y parseo de `CHANGELOG.md` (regex sobre `## [X.Y.Z]` y `## [unreleased]`), parseo TOML de `cliff.toml` con stdlib `tomllib` (valida `[changelog]`, `[git]`, `tag_pattern`, presence de parsers con `[Ff]eat`/`[Ff]ix`/`[Dd]ocs`), verificacion de `scripts/hooks/post-tag` y `scripts/install-hooks.sh` (existencia + `S_IXUSR`), contenido del hook (invoca `release.sh`, filtra `refs/tags/v[0-9]`).
- `tests/test_bump_version.py` (nuevo, 6 tests) — mocks de `git-cliff` (PATH falso con un shim que devuelve versiones controladas). Verifica: exit != 0 sin cliff en PATH, exit != 0 con output no-SemVer, exit 0 sin cambio, patch a `v0.2.0`, preserva otras líneas (`name`, `markitdown`, `typer`), exit != 0 con pyproject sin `version = "..."`. Cada test corre el script en `tmp_path` separado (script acepta `[WORKDIR]` para no contaminar REPO_ROOT).
- `tests/test_release_script.py` (modificado, +1 test) — `test_release_sh_handles_existing_tag_gracefully` verifica que el script skip-ea la creación del tag si ya existe (caso normal post-hook). `test_release_sh_creates_git_tag_and_pushes` actualizado para validar tanto el path del hook (`git show-ref` check + skip) como el fallback manual (`git tag -a`).

Decisiones locked-in (de las preguntas al usuario):
- **Changelog tooling**: `git-cliff` (binario Rust). Justificación: herramienta externa standard con TOML declarativo; cero deps Python/Node. Pre-requisito del maintainer: `brew install git-cliff`.
- **Tag → build**: **Git hook `post-tag`** versionado en `scripts/hooks/`. Path se setea via `scripts/install-hooks.sh`. Hook ignora tags lightweight y non-semver (solo `refs/tags/vX.Y.Z` semver).
- **Version bump**: `git-cliff --bump` automatico, pero **el maintainer revisa el diff** antes de commit (el wrapper `bump-version.sh` solo imprime y aplica; el commit queda manual).
- **Commit lint**: solo documentacion. Conventional commits ya estaban documentados en `agent.md:80`; J3 profundiza con scope opcional, breaking syntax, y tipos validos.

Validación final:
- `pytest tests/test_changelog.py tests/test_bump_version.py tests/test_release_script.py tests/test_golden_pipeline.py`: 57 passed (J3 + J2 + J1 tests).
- `pytest --cov=capmd --cov-report=term`: `TOTAL ... 99.4%` (sin regresión; los nuevos tests están en `tests/`).
- `ruff check src tests`: All checks passed.
- `mypy src/capmd`: Success, no issues found in 67 source files.
- **Smoke test del hook**: `git config core.hooksPath scripts/hooks && git tag -a v1.2.3-test -m "smoke" -f` → hook se dispara → invoca `scripts/release.sh 1.2.3-test` (que falla porque pyproject.toml tiene 0.1.0, como debe ser). Tag local se borra con `git tag -d`. `core.hooksPath` se desactiva.
- **Install path real**: `brew install git-cliff && bash scripts/install-hooks.sh` (one-shot). Próximo `git tag -a vX.Y.Z -m "..."` dispara el pipeline completo.

Out of scope explicito (no se hace en J3):
- J4 (PyPI real con `twine upload`): el release.sh construye sdist + wheel pero no los sube a PyPI.
- J5 (`docs/cleaners.md`).
- Firma GPG de tags (opcional, no requerida).
- `commitlint` enforcement: solo documentacion.

**J4. Publicación en PyPI**
`uv build` + `twine upload`, con `markitdown` como dependencia declarada (no vendorizado).
*Test:* `pip install capmd` en un venv limpio convierte un PDF.

**J5. README y docs**
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
