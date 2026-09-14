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

**E1. Extracción de imágenes**
`images/extract.py` con pypdfium2: sacar las imágenes embebidas del rango de páginas a PNG/WebP, con `--image-format` y `--image-max-width`.
*Test:* fixture de 2 imágenes produce 2 archivos con dimensiones correctas.

**E2. Filtro de basura**
Descartar imágenes < N px, logos repetidos en todas las páginas, y fondos de página completa.
*Test:* fixture con logo en cada página extrae solo las figuras reales.

**E3. Nombres estables**
`fig-03-01.png` = capítulo 3, figura 1. Determinista entre corridas.
*Test:* dos ejecuciones seguidas producen exactamente los mismos nombres y hashes.

**E4. Anclaje posicional**
`images/anchor.py`: insertar `![Figura 3.1](images/fig-03-01.png)` en el punto del markdown correspondiente a la posición Y de la imagen en su página.
*Test:* en el fixture, la imagen de la mitad de la página 2 queda entre los párrafos correctos, no al final del documento.

**E5. Captions**
Detectar el texto `Figura N.N — ...` bajo la imagen y usarlo como alt text y como línea en cursiva bajo la imagen.
*Test:* el alt text del output es el caption real del fixture.

**E6. Descripción por LLM (opcional)**
Flag `--describe-images`: activar `enable_plugins=True` + `markitdown-ocr` con `llm_client`/`llm_model`, o llamar directo a la API para generar alt text de diagramas. Debe degradar limpio si no hay API key.
*Test:* sin key, corre igual y avisa una vez; con key mockeada, el alt text viene del mock.

**E7. `--no-images`**
Saltar todo el bloque E y dejar `<!-- figura omitida -->` donde iría.
*Test:* no se crea la carpeta `images/`.

---

### Bloque F — Salida

**F1. Árbol de salida**
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

**F2. Front matter YAML**
`title`, `book`, `chapter`, `pages`, `source_file`, `source_sha256`, `converted_at`, `capmd_version`, `markitdown_version`, `cleaners_applied`.
*Test:* el front matter parsea con `yaml.safe_load` y contiene las 10 claves.

**F3. `capmd.json`**
Mismo metadata + stats de limpieza + lista de figuras, para poder re-procesar sin re-leer el PDF.
*Test:* el JSON permite regenerar el front matter sin tocar el original.

**F4. Split por secciones**
`--split h2` genera `01-introduccion.md`, `02-borrowing.md`... más un `index.md` con enlaces.
*Test:* un doc con 4 H2 produce 4 archivos + índice con 4 links válidos.

**F5. Tabla de contenidos inline**
`--toc` inserta un índice de anclas al inicio del `.md`.
*Test:* cada ancla del TOC resuelve a un heading existente.

**F6. Reporte de calidad**
`report.py` → al final de la corrida imprime: páginas procesadas, palabras, headings detectados, figuras, líneas eliminadas por cada cleaner, y **warnings** (ej: "0 headings detectados, revisa `--headings-mode`").
*Test:* el fixture "malo" (PDF escaneado sin texto) dispara el warning de output vacío.

**F7. `--dry-run`**
Mostrar qué se haría (rango, páginas, archivos de salida) sin escribir nada.
*Test:* filesystem sin cambios después de correr.

**F8. Sobrescritura segura**
Si el destino existe: fallar salvo `--force`, o `--suffix` para versionar.
*Test:* segunda corrida sin `--force` → exit code y mensaje claro.

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
