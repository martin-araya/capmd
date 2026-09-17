# Configuración

`capmd` lee configuración desde 4 fuentes, en orden de precedencia:

```
flags CLI > env vars CAPMD_* > ./capmd.toml > ~/.config/capmd/config.toml > defaults
```

Más alto gana. La resolución se imprime con `capmd config show` que indica
de dónde viene cada valor.

## Ubicaciones

| Archivo                                          | Scope             | Override              |
|--------------------------------------------------|-------------------|-----------------------|
| `~/.config/capmd/config.toml`                   | Global (todos los libros) | `--config <path>`     |
| `./capmd.toml` (cwd)                            | Proyecto          | `--project-config <path>` |
| `[profile.NAME]` (en cualquier archivo)          | Per-invocation     | `--profile NAME`        |
| `[books.<slug>]` (en cualquier archivo)          | Per-libro          | (auto-match por sha256) |

## Esquema

```toml
# ─── output ────────────────────────────────────────────────────
out_dir = "~/Estudio"            # default output dir
out_extension = "md"             # extension del output
flat = false                     # si true, single file en out_dir; si false, tree

# ─── images ──────────────────────────────────────────────────
image_format = "png"             # png | webp | jpg
image_max_width = 1400           # px, downscale si la imagen es mayor
images_dir = "images"            # subcarpeta dentro de out_dir
no_images = false                # si true, skip extracción
no_anchor = false                # si true, skip re-anchor

# ─── front matter ────────────────────────────────────────────
front_matter = true              # inyecta YAML al inicio del .md
no_front_matter = false          # override

# ─── TOC ─────────────────────────────────────────────────────
inject_toc = false               # inyecta TOC al inicio
toc_depth = 3                    # profundidad del TOC (1..6)

# ─── clean ───────────────────────────────────────────────────
[clean]
# Lista blanca: solo corren estos. Si está vacío, corre todo.
enabled = ["whitespace", "hyphens", "headers", "pagenums", "headings", "single_h1", "code", "lists", "notes", "paragraph_joins"]
# Lista negra: corren todos MENOS estos (alternativa a `enabled`).
skip = ["tables"]                # tables off por default (heuristica agresiva)

# ─── per-book ────────────────────────────────────────────────
[books."rust-handbook"]
title_pattern = '^Chapter (\d+)\s+(.+)$'   # regex para extraer title desde el chapter heading
page_offset = 18                            # pages impresas vs fisicas
clean_skip = ["tables"]                     # override per-libro

[books."mastering-swift"]
title_pattern = '^\d+\.\s+(.+)$'
page_offset = 22
```

## env vars

Cualquier flag CLI tiene un `CAPMD_*` equivalente:

| Flag                          | env var                    |
|-------------------------------|----------------------------|
| `--out-dir DIR`               | `CAPMD_OUT_DIR`            |
| `--flat`                      | `CAPMD_FLAT=1`             |
| `--no-images`                 | `CAPMD_NO_IMAGES=1`        |
| `--image-format png`          | `CAPMD_IMAGE_FORMAT=png`   |
| `--image-max-width 1400`      | `CAPMD_IMAGE_MAX_WIDTH=1400` |
| `--no-front-matter`           | `CAPMD_NO_FRONT_MATTER=1`  |
| `--strict`                    | `CAPMD_STRICT=1`           |
| `--profile NAME`              | `CAPMD_PROFILE=NAME`       |
| `--verbose`                   | `CAPMD_VERBOSE=1`          |
| `--quiet`                     | `CAPMD_QUIET=1`            |

Para los cleaners:

| Cleaner                       | env var                      |
|-------------------------------|------------------------------|
| `[clean].enabled`             | `CAPMD_CLEAN_ENABLED=a,b,c` (comma-separated) |
| `[clean].skip`                | `CAPMD_CLEAN_SKIP=a,b,c`     |
| `CAPMD_SKIP_PYPI_VERIFY=1`    | skip del smoke test post-publish (J4)        |

## Per-book detection

`capmd` reconoce automáticamente si un libro ya fue convertido:

1. Calcula `sha256` del source.
2. Busca en `capmd.json` (registry) si hay record con esa sha256.
3. Si hay: reusa el outline cacheado (no re-deriva).
4. Si no: deriva outline (PDF) o parsea spine (EPUB), persiste.

Para forzar re-derivar:

```bash
capmd config show --book "rust-handbook"   # ver config efectiva
capmd config show --json | jq '.books'     # lista todos
```

## Examples

### Per-profile: "study" vs "light"

```toml
# Modo "study": full cleaning + images
[profile.study]
[profile.study.clean]
enabled = []   # corre todos
flat = false

# Modo "light": solo whitespace + hyphens, sin imagenes, sin front matter
[profile.light]
flat = true
[profile.light.clean]
enabled = ["whitespace", "hyphens"]
[profile.light.output]
no_images = true
no_front_matter = true
```

Uso: `capmd convert book.pdf --chapter 1 --profile light`.

### Per-project override

```toml
# ./capmd.toml (en el repo donde organizas los libros)
out_dir = "."
page_offset = 4      # la edición tiene 4 páginas de prólogo
```

### Diagnóstico

```bash
capmd config show           # TOML con source attribution
capmd config show --json    # para scriptear
capmd config show --effective
```
