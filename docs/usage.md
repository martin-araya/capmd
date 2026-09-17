# Uso

`capmd` tiene 9 comandos. Cubren los casos comunes (`convert`, `toc`,
`batch`) más utilidades (`inspect`, `open`, `watch`, `setup`, `config`,
`version`).

## Ver el índice del libro

```bash
capmd toc book.pdf
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
capmd toc book.pdf --json   # para scriptear
```

El outline viene del PDF embebido (PDF) o del spine/nav (EPUB). Si el PDF
no tiene outline, `capmd` aplica la heurística (font size + keyword `Chapter`).

## Convertir un capítulo

Por nombre:

```bash
capmd convert book.pdf --chapter "Ownership"
```

Por número del índice:

```bash
capmd convert book.pdf --chapter 4
```

Por páginas:

```bash
capmd convert book.pdf --pages 87-124
capmd convert book.pdf --pages 87-          # hasta el final
capmd convert book.pdf --pages 12,15,20-25  # selección suelta
```

Si la numeración impresa no coincide con la física (prólogos, portadas):

```bash
capmd convert book.pdf --pages 87-124 --page-offset 18
```

## Varios capítulos de un saque

```bash
capmd batch book.pdf --chapters 1-12 --out ~/Estudio
```

`--chapters` acepta rango (`1-12`), lista (`1,3,5`), o mezcla (`1-3,5,10-12`).

## Diagnosticar un PDF antes de convertir

```bash
capmd inspect book.pdf
```

```
Source: book.pdf (PDF, 3.4 MB, sha256: ab12...)
Pages: 124, words: 87,432 (avg 705/page)
Format: scanned pages: 0; text pages: 124
Outline: 5 top-level chapters, 18 second-level
Fonts: Helvetica (Regular), Helvetica-Bold, Courier (Mono)
Headers: "Chapter N | Rust in Action" (repeats 124×)
Footers: "— N —" (repeats 124×)
Quality: OK
```

`--json` para scriptear; `--sample N` para inspeccionar N páginas en lugar de todas.

## Abrir el resultado en el editor

```bash
capmd convert book.pdf -o /tmp/x.md --open   # usa $EDITOR (o `open` en macOS)
capmd convert book.pdf -o /tmp/x.md --open --open-cmd "code --wait"
```

O re-abrir un `.md` ya existente:

```bash
capmd open /tmp/x.md
```

Fire-and-forget: no espera al editor. Sin `$EDITOR` y en Linux/macOS no-macOS,
fijalo en tu shell (`export EDITOR=vim` o pasá `--editor "<cmd>"`).

## Carpeta watch

```bash
capmd watch --inbox ~/Inbox/capmd --out-dir ~/Estudio
```

Loop infinito que detecta nuevos PDFs en el inbox, los convierte, y los
mueve. Para correrlo como daemon, usar [LaunchAgent](installation.md#carpeta-watch-i3-opcional).

## Configuración

```bash
# Genera starter config en ~/.config/capmd/config.toml
capmd config init

# Muestra la configuración efectiva (CLI > env > project > global)
capmd config show
```

Ver [Configuration](configuration.md) para la referencia completa.

## Setup del sistema

```bash
# Quick Action de Finder (macOS)
capmd setup quick-action [--stdout]

# LaunchAgent watcher (macOS)
capmd setup launch-agent --inbox ... --out-dir ...

# Shell completion
capmd --install-completion zsh
capmd --show-completion bash > ~/.bash_completions/capmd.sh
```

## Versión

```bash
capmd version
```

## Troubleshooting

| Error                                          | Causa                                                | Fix                                                  |
|------------------------------------------------|------------------------------------------------------|------------------------------------------------------|
| `ModuleNotFoundError: No module named 'markitdown'` | markitdown no instalado                          | `pip install 'markitdown[pdf,docx,pptx,xlsx]'` o `uv tool install capmd` lo trae |
| `PdfReadError: EOF marker not found`            | PDF corrupto o password                              | `pypdf` no puede leerlo; usar `qpdf --decrypt` primero |
| `UnsupportedFormatError`                       | Formato no soportado                                | Ver [formats.md](formats.md) para la lista            |
| `EmptyMarkdownError`                           | markitdown devolvió vacío                            | El PDF es raster (sin texto); activar OCR              |
| `Outline not found + heuristic gave 0`          | PDF sin outline ni keywords `Chapter`                | Definir `[books.<name>].title_pattern`                |
| `Permission denied: ~/Library/LaunchAgents`     | Setup launch-agent sin permisos                      | `sudo` o usar `capmd watch` directo en lugar de LaunchAgent |

Si ningún fix resuelve, abrir issue en <https://github.com/martin-araya/capmd/issues>
con la salida de `capmd --verbose convert book.pdf --chapter 1`.
