# Opciones del CLI

Cada comando acepta `--help` con ejemplos. Acá la referencia completa.

## Globales (todos los comandos)

| Flag                | Descripción                                               | Default |
|---------------------|-----------------------------------------------------------|---------|
| `-v, --verbose`     | Imprime logs a stderr (DEBUG, INFO, WARNING)             | off     |
| `--quiet`           | Sólo errores a stderr                                     | off     |
| `--no-color`        | Desactiva colores ANSI (CI, logs)                        | auto    |
| `--profile NAME`    | Usa perfil `[profile.NAME]` del config.toml               | "default" |
| `-h, --help`        | Muestra ayuda del comando y exit                          |         |
| `--version`         | Imprime versión y exit                                   |         |

## `capmd toc`

| Flag            | Descripción                                         | Default |
|-----------------|-----------------------------------------------------|---------|
| `SRC`           | Path al PDF/EPUB/DOCX                              | required |
| `--json`        | Output en JSON (uno por chapter)                   | off     |
| `--max-depth N` | Limita jerarquía (1 = top, 2 = top+second)         | 3       |
| `--no-recursive` | Flat list, no nesting                              | off     |

## `capmd convert`

| Flag                  | Descripción                                                          | Default |
|-----------------------|----------------------------------------------------------------------|---------|
| `SRC`                 | Path al archivo                                                      | required |
| `--chapter NAME_OR_N` | Capítulo por nombre o número                                        | (output completo) |
| `--pages SPEC`        | Rango o lista de páginas (`87-124`, `12,15,20-25`)                   | (todas) |
| `--page-offset N`     | Offset entre páginas impresas y físicas                              | 0       |
| `-o, --out PATH`      | Output `.md` (default: stdout)                                      | stdout  |
| `--out-dir DIR`       | Output directorio + `--book-slug`/`--chapter-slug` filenames        | cwd     |
| `--book-slug SLUG`    | Override slug del libro                                              | derive  |
| `--chapter-slug SLUG` | Override slug del capítulo                                          | derive  |
| `--keep-raw`          | Escribe raw.md junto al limpio (debug del cleaner)                  | off     |
| `--no-images`         | No extraer imágenes                                                  | off     |
| `--no-anchor`         | No re-ancorar referencias a imágenes en el texto                     | off     |
| `--images-dir NAME`   | Subcarpeta dentro de `out-dir`                                       | images/ |
| `--image-format EXT`  | Formato (`png`, `webp`)                                              | png     |
| `--image-max-width N` | Max ancho en pixels (downscale)                                     | 1400    |
| `--split h2`          | Divide el output en archivos por cada `## H2`                        | off     |
| `--toc`               | Inyecta TOC al inicio del markdown                                  | off     |
| `--no-front-matter`   | Sin YAML header en el output                                        | off     |
| `--flat`              | Output como flat `.md` (no tree)                                    | off     |
| `--strict`            | Exit 8 si hay warnings de calidad                                   | off     |
| `--dry-run`           | Plan + stats sin escribir archivos                                  | off     |
| `--force`             | Sobrescribe output existente                                        | off     |
| `--suffix S`          | Suffix para no colisionar                                           | ""      |

## `capmd batch`

| Flag                  | Descripción                                          | Default |
|-----------------------|------------------------------------------------------|---------|
| `SRC`                 | Path al archivo                                      | required |
| `--chapters SPEC`     | Rango o lista de capítulos                          | required |
| `-j, --jobs N`        | Procesamiento en paralelo (0 = auto)               | 0       |
| `--out-dir DIR`       | Directorio base del output                          | cwd     |
| (más flags heredados de `convert`) |                                              |         |

## `capmd inspect`

| Flag          | Descripción                                              | Default |
|---------------|----------------------------------------------------------|---------|
| `SRC`         | Path al archivo                                          | required |
| `--format`    | Output format (`text`, `json`)                          | text    |
| `--sample N`  | Inspecciona solo N páginas                              | (all)   |
| `--include-outlines` | Incluye outline detallado en JSON                 | off     |

## `capmd open`

| Flag           | Descripción                                       | Default |
|----------------|---------------------------------------------------|---------|
| `PATH`         | Path al `.md` (default: el último convertido)    | (last)  |
| `--editor CMD` | Editor a invocar (default: `$EDITOR` o `open`)    | auto    |

## `capmd watch`

| Flag              | Descripción                                            | Default       |
|-------------------|--------------------------------------------------------|---------------|
| `--inbox DIR`     | Directorio a vigilar                                  | required      |
| `--out-dir DIR`   | Directorio de output                                  | required      |
| `--move-to DIR`   | Destino post-conversión                               | required      |
| `--pattern GLOB`  | Glob para filtrar PDFs (e.g. `*.pdf`)                | `*.pdf`       |
| `--poll N`        | Segundos entre polls                                  | 5             |

## `capmd config`

| Sub   | Descripción                            |
|-------|----------------------------------------|
| `init` | Genera starter config en `~/.config/capmd/config.toml` |
| `show` | Muestra la config efectiva resuelta con source attribution |

| Flag (ambos) | Descripción                                       | Default |
|--------------|---------------------------------------------------|---------|
| `--format`   | Output format (`toml`, `json`)                   | toml    |

## `capmd setup`

| Sub              | Descripción                                              |
|------------------|----------------------------------------------------------|
| `quick-action`   | Setup del Finder Quick Action (macOS)                   |
| `launch-agent`   | Setup del LaunchAgent watcher (macOS)                   |

## Exit codes

| Code | Significado                                          |
|------|------------------------------------------------------|
| 0    | OK                                                    |
| 1    | Error genérico (excepción no categorizada)            |
| 2    | Argumento inválido (`typer.BadParameter`)             |
| 3    | Source no encontrado / no legible                     |
| 4    | Formato no soportado                                  |
| 5    | Outline vacío (PDF sin outline + heuristic)           |
| 6    | Disk full / permission denied / IO error                |
| 7    | Config error                                          |
| 8    | Quality warning (con `--strict`)                      |

Ver [Quality](quality.md) para detalles.
