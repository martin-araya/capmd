# capmd

Convierte el capítulo de un libro a Markdown limpio, listo para leer, resumir y estudiar.

`capmd` es un wrapper de [MarkItDown](https://github.com/microsoft/markitdown) que resuelve lo que MarkItDown deliberadamente no hace: recortar un capítulo de un libro completo, limpiar la basura del PDF (headers repetidos, guiones de corte, números de página sueltos), reconstruir la jerarquía de títulos y sacar las figuras a una carpeta con las referencias en su posición real.

```bash
capmd convert rust-handbook.pdf --chapter "Ownership" --out ~/Estudio
```

```
~/Estudio/rust-handbook/cap-04-ownership/
├── cap-04-ownership.md
├── images/
│   ├── fig-04-01.png
│   └── fig-04-02.png
└── capmd.json
```

---

## Por qué existe

MarkItDown es excelente en lo suyo: convierte archivos a Markdown pensando en LLMs, preservando headings, listas, tablas y links. Pero:

- convierte **el archivo completo**, no tiene idea de qué es un capítulo;
- su converter de PDF es **extracción de texto**: no exporta imágenes ni marca páginas;
- el ruido de maquetación (encabezado en cada página, `— 47 —`, palabras cortadas con guion) pasa tal cual al Markdown.

Para indexar documentos eso da igual. Para leer y estudiar un capítulo, no. `capmd` pone el pre y el post procesamiento alrededor.

---

## Instalación

Requiere macOS y Python ≥ 3.10.

```bash
# recomendado
uv tool install capmd

# o
pipx install capmd
```

Desde el código:

```bash
git clone https://github.com/<tu-usuario>/capmd.git
cd capmd
uv venv --python=3.12 .venv
source .venv/bin/activate
uv pip install -e '.[dev]'
```

`capmd` instala `markitdown` con los extras de documentos (`pdf`, `docx`, `pptx`, `xlsx`). Si necesitas audio o YouTube:

```bash
uv pip install 'markitdown[all]'
```

### OCR opcional

Para PDFs escaneados o con figuras que contienen texto:

```bash
uv pip install markitdown-ocr openai
export OPENAI_API_KEY=...
capmd convert escaneado.pdf --chapter 3 --describe-images
```

Sin cliente LLM configurado, `capmd` avisa una vez y sigue con el converter estándar.

---

## Uso

### Ver el índice del libro

```bash
capmd toc rust-handbook.pdf
```

```
Rust Handbook
├── 1  Getting Started              p. 1–24
├── 2  Cargo and Crates             p. 25–48
├── 3  Common Concepts              p. 49–86
├── 4  Ownership                    p. 87–124
│   ├── 4.1 What Is Ownership?      p. 87
│   ├── 4.2 References and Borrowing p. 99
│   └── 4.3 The Slice Type          p. 115
└── 5  Structs                      p. 125–150
```

```bash
capmd toc rust-handbook.pdf --json   # para scriptear
```

### Convertir un capítulo

Por nombre:

```bash
capmd convert rust-handbook.pdf --chapter "Ownership"
```

Por número del índice:

```bash
capmd convert rust-handbook.pdf --chapter 4
```

Por páginas:

```bash
capmd convert rust-handbook.pdf --pages 87-124
capmd convert rust-handbook.pdf --pages 87-          # hasta el final
capmd convert rust-handbook.pdf --pages 12,15,20-25  # selección suelta
```

Si la numeración impresa no coincide con la física (prólogos, portadas):

```bash
capmd convert rust-handbook.pdf --pages 87-124 --page-offset 18
```

### Varios capítulos de una

```bash
capmd batch rust-handbook.pdf --chapters 1-12 --out ~/Estudio
```

### Diagnosticar un PDF antes de convertir

```bash
capmd inspect escaneado.pdf
```

```
Archivo      escaneado.pdf
Páginas      312
Texto        ✗ sin capa de texto (PDF rasterizado)
Outline      ✗ sin índice embebido
Fuentes      —
Sugerencia   usa --describe-images con markitdown-ocr, o --use-cu
```

---

## Opciones

### Selección

| Flag | Descripción |
|---|---|
| `--chapter <n\|texto>` | Capítulo por número de índice o por coincidencia de título |
| `--pages <rango>` | Rango explícito: `45-78`, `45-`, `-30`, `12,15,20-25` |
| `--page-offset <n>` | Diferencia entre numeración impresa y física |
| `--ext <fmt>` | Hint de formato cuando la entrada viene por stdin |

### Salida

| Flag | Descripción |
|---|---|
| `-o, --out <ruta>` | Directorio (o archivo con `--flat`) de destino |
| `--flat` | Un solo `.md`, sin carpeta de capítulo |
| `--split h2` | Partir el capítulo en un archivo por sección + `index.md` |
| `--toc` | Insertar índice de anclas al inicio del documento |
| `--page-markers` | Conservar los comentarios `<!-- page N -->` |
| `--force` | Sobrescribir si el destino existe |
| `--dry-run` | Mostrar qué se haría, sin escribir nada |

### Imágenes

| Flag | Descripción |
|---|---|
| `--no-images` | No extraer figuras |
| `--image-format <png\|webp>` | Formato de salida (default: `png`) |
| `--image-max-width <px>` | Redimensionar figuras grandes |
| `--describe-images` | Alt text generado por LLM (requiere `markitdown-ocr` + API key) |

### Limpieza

| Flag | Descripción |
|---|---|
| `--no-clean` | Markdown crudo de MarkItDown, sin post-proceso |
| `--only-clean <lista>` | Aplicar solo estos limpiadores |
| `--skip-clean <lista>` | Aplicar todos menos estos |
| `--keep-raw` | Guardar también el markdown pre-limpieza en `.capmd/raw.md` |

Limpiadores disponibles: `whitespace`, `hyphens`, `headers`, `pagenums`, `headings`, `code`, `lists`, `tables`, `notes`, `paragraphs`.

### Motores alternativos

| Flag | Descripción |
|---|---|
| `-d`, `-e <endpoint>` | Azure Document Intelligence (passthrough a MarkItDown) |
| `--use-cu`, `--cu-endpoint` | Azure Content Understanding |

También se leen `MARKITDOWN_DOCINTEL_ENDPOINT` y `MARKITDOWN_CU_ENDPOINT` del entorno.

---

## Formato de salida

El `.md` generado lleva front matter YAML:

```yaml
---
title: Ownership
book: rust-handbook
chapter: 4
pages: 87-124
source_file: rust-handbook.pdf
source_sha256: 9f2a...
converted_at: 2026-09-12T14:02:11-03:00
capmd_version: 0.3.1
markitdown_version: 0.1.4
cleaners_applied: [whitespace, hyphens, headers, pagenums, headings, code]
---
```

Con `--profile study` se añaden secciones vacías listas para trabajar:

```markdown
## Resumen

## Conceptos clave

## Dudas
```

Y un `capmd.json` con la metadata completa, los stats de limpieza y el listado de figuras, para poder re-procesar sin volver a leer el PDF.

---

## Configuración

`capmd config init` genera `~/.config/capmd/config.toml`:

```toml
out_dir = "~/Estudio"
image_format = "png"
image_max_width = 1400
profile = "study"

[clean]
enabled = ["whitespace", "hyphens", "headers", "pagenums", "headings", "code", "lists", "notes"]

[books."rust-handbook"]
page_offset = 18
title_pattern = '^Chapter (\d+)\s+(.+)$'

[books."mastering-swift"]
page_offset = 22
clean_skip = ["tables"]
```

Precedencia: flags de CLI > variables `CAPMD_*` > `./capmd.toml` > config global > defaults.

`capmd config show` imprime la configuración efectiva ya resuelta.

---

## Integración con macOS

**Atajo / Quick Action.** Click derecho sobre un PDF en Finder → *Convertir capítulo a Markdown*. El Atajo pide el rango y llama a `capmd`.

**Carpeta observada.** Un LaunchAgent puede vigilar `~/Books/Inbox` y convertir todo lo que caiga ahí:

```bash
capmd watch ~/Books/Inbox --out ~/Estudio --move-to ~/Books/Processed
```

**Hook post-conversión.** En la config:

```toml
post_command = "mi-script-de-resumen {md_path}"
```

Se ejecuta con la ruta del `.md` generado, para encadenar `capmd` con lo que venga después.

---

## Formatos soportados

Heredados de MarkItDown: PDF, EPUB, DOCX, PPTX, XLSX/XLS, HTML, CSV/JSON/XML, imágenes, audio, ZIP, URLs de YouTube.

El recorte por capítulo funciona en **PDF** (outline o heurística) y **EPUB** (spine/nav). En el resto de formatos `capmd` convierte el archivo completo y aplica la limpieza igual.

---

## Limitaciones

- **PDFs sin capa de texto.** El converter built-in no hace OCR. `capmd inspect` lo detecta y sugiere `--describe-images` (plugin `markitdown-ocr`) o `--use-cu`.
- **Headings.** La reconstrucción de jerarquía es heurística. Si un libro tiene una maquetación rara, define `title_pattern` en su perfil.
- **Tablas complejas.** Si la confianza de detección es baja, `capmd` marca el bloque con `<!-- tabla no estructurada -->` en vez de inventar una tabla mal alineada.
- **Fidelidad.** El objetivo es Markdown legible y estudiable, no una reproducción tipográfica del original.

---

## Desarrollo

```bash
uv pip install -e '.[dev]'
pytest                      # suite completa
pytest --update-golden      # regenerar los golden files de los cleaners
ruff check . && ruff format .
mypy src/capmd/core
```

Los fixtures de test se **generan** con `reportlab` (PDFs sintéticos con headers repetidos, guiones de corte, figuras, tablas, TOC). El repo no incluye material con copyright.

Ver `roadmap.md` para el plan por fases y `agent.md` para el contexto de trabajo con agentes.

---

## Créditos

Construido sobre [MarkItDown](https://github.com/microsoft/markitdown) (MIT, Microsoft). `capmd` es un paquete independiente que lo consume desde PyPI — el repo de MarkItDown explícitamente prefiere que las aplicaciones vivan fuera de su árbol.

## Licencia

MIT.
