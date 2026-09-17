# capmd

> Convierte el capítulo de un libro a Markdown limpio, listo para leer, resumir y estudiar.

`capmd` envuelve [MarkItDown](https://github.com/microsoft/markitdown) y le agrega lo que MarkItDown no hace: recortar un capítulo de un libro completo, limpiar la basura de maquetación del PDF (encabezados repetidos, guiones de corte, números de página sueltos), reconstruir la jerarquía de títulos y extraer las figuras con sus referencias en posición.

## Quickstart

```bash
# 1. Install (Homebrew tap)
brew install martin-araya/capmd/capmd

# 2. Convert a chapter (PDF / EPUB / DOCX / PPTX / XLSX supported)
capmd convert path/to/book.pdf --chapter "Ownership" --out ~/Estudio

# 3. Inspect the output
cat ~/Estudio/book/cap-04-ownership/cap-04-ownership.md
```

## Instalación

Tres vías soportadas. Ver [Installation](installation.md) para detalles.

```bash
# Homebrew tap (macOS, recommended)
brew install martin-araya/capmd/capmd

# uv tool
uv tool install capmd

# pip (PyPI)
pip install capmd
```

## Quick Action de Finder (opcional, macOS)

Click derecho sobre un PDF en Finder → **Convertir capítulo de capmd**. Ver [Setup Quick Action](#quick-action-de-finder-i2) en Installation.

## Uso

```bash
# Ver el índice del libro (outline)
capmd toc book.pdf

# Convertir un capítulo por nombre
capmd convert book.pdf --chapter "Ownership"

# Por número
capmd convert book.pdf --chapter 4

# Por páginas
capmd convert book.pdf --pages 87-124

# Batch: varios capítulos de un saque
capmd batch book.pdf --chapters 1-12 --out ~/Estudio

# Diagnóstico (antes de convertir)
capmd inspect book.pdf
```

Ver [Usage](usage.md) para el tour completo (capmd open, capmd setup, capmd config).

## Configuración

`capmd config init` genera `~/.config/capmd/config.toml`:

```toml
out_dir = "~/Estudio"
image_format = "png"
image_max_width = 1400

[clean]
# Por default, todos los cleaners corren. Deshabilitar por nombre:
# enabled = [n for n in default_cleaners if n != "tables"]
# o por libro:
[books."rust-handbook"]
page_offset = 18
clean_skip = ["tables"]
```

Para entender qué hace cada cleaner y cómo desactivarlo, ver [cleaners.md](cleaners.md).

## Documentación completa

| Documento                                    | Contenido                                           |
|----------------------------------------------|-----------------------------------------------------|
| [installation.md](installation.md)           | Homebrew, uv tool, pip, Quick Action, LaunchAgent   |
| [usage.md](usage.md)                         | capmd convert/toc/batch/inspect, opciones comunes   |
| [options.md](options.md)                     | Referencia de cada flag del CLI                     |
| [configuration.md](configuration.md)         | TOML completo, env vars, per-book profiles          |
| [cleaners.md](cleaners.md)                   | Qué hace cada limpiador y cómo deshabilitarlo      |
| [output.md](output.md)                       | Estructura del directorio + capmd.json              |
| [quality.md](quality.md)                     | Warnings, exit codes, `--strict`                    |
| [shell-completion.md](shell-completion.md)   | `capmd --install-completion` para zsh/bash/fish      |
| [editor.md](editor.md)                       | `capmd open` y `--open --open-cmd`                  |
| [formats.md](formats.md)                    | Formatos soportados + limitaciones                  |
| [development.md](development.md)             | Setup de dev, tests, golden files, coverage, release |

## API reference (autogenerado por sphinx-apidoc)

Para regenerar las paginas `modules/*.md`:

```bash
uv run sphinx-apidoc -o docs/modules/ src/capmd/ --separate --no-toc
make docs
```

Paginas resultantes:

- `capmd.clean` — pipeline + cleaners + CleanContext
- `capmd.convert` — Engine wrapper de MarkItDown
- `capmd.sources` — PDF / EPUB / Office readers
- `capmd.images` — extract + anchor + captions
- `capmd.output` — writer + frontmatter + split + toc
- `capmd.cli` — typer app + comandos
- `capmd.config` — TOML config + precedence
- `capmd.models` — SourceDoc / Chapter / Figure / etc

## Links externos

- Repositorio: <https://github.com/martin-araya/capmd>
- PyPI: <https://pypi.org/project/capmd/>
- MarkItDown: <https://github.com/microsoft/markitdown>

## Indices

```{eval-rst}
* :ref:`genindex`
* :ref:`search`
```
