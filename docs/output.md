# Output

`capmd convert` produce, en el directorio configurado:

```
<out-dir>/
└── <book-slug>/
    └── <chapter-slug>/
        ├── <chapter-slug>.md      # markdown final
        ├── capmd.json              # metadata estructurada
        └── images/                 # solo si --no-images=false
            ├── fig-<chapter>-01.png
            ├── fig-<chapter>-02.png
            └── ...
```

Con `--flat`: `<out-dir>/<book-slug>-<chapter-slug>.md` (un solo archivo).

Con `--split h2`: además de `cap-<N>.md`, se generan `cap-<N>-sec-<NN>.md` por cada `## H2`.

## Estructura del .md

```markdown
---
title: "Chapter 4: Ownership"
book: "Rust Handbook"
chapter_index: 4
chapter_title: "Ownership"
pages: "87-124"
pages_count: 38
words: 12031
figures: 2
source_file: "rust-handbook.pdf"
source_sha256: "abc123..."
converted_at: "2026-09-17T00:30:00Z"
capmd_version: "0.1.0"
markitdown_version: "0.1.7"
generated_by: "capmd"
---

# Chapter 4: Ownership

> Front-matter injectada por `capmd convert`.

## 4.1 What Is Ownership?

Body content...

![Figure 4.1 — Memory layout](./images/fig-04-01.png)

More body...

## 4.2 References and Borrowing

...

[^1]: Footnote at the end.
```

## capmd.json schema

```json
{
  "schema_version": 2,
  "book_slug": "rust-handbook",
  "chapter_slug": "cap-04-ownership",
  "source": {
    "path": "/Users/.../rust-handbook.pdf",
    "sha256": "abc123...",
    "format": "pdf",
    "size_bytes": 3500000
  },
  "chapter": {
    "index": 4,
    "title": "Ownership",
    "level": 1,
    "start_page": 87,
    "end_page": 124
  },
  "stats": {
    "pages": 38,
    "words": 12031,
    "figures": 2,
    "tables": 0,
    "headings": {"h1": 1, "h2": 4, "h3": 6, "h4": 0, "h5": 0, "h6": 0},
    "cleaners": [
      {"name": "whitespace", "changes": 42, "enabled": true},
      {"name": "hyphens", "changes": 3, "enabled": true},
      ...
    ]
  },
  "figures": [
    {
      "chapter_index": 4,
      "index": 1,
      "path": "images/fig-04-01.png",
      "page": 92,
      "width": 1024,
      "height": 768,
      "bbox": [0.1, 0.2, 0.5, 0.7]
    }
  ],
  "warnings": [],
  "converted_at": "2026-09-17T00:30:00Z",
  "capmd_version": "0.1.0"
}
```

`capmd.json` lo lee `capmd inspect` y `capmd batch`. La schema version
incrementa con breaking changes; ver [Quality](quality.md#schema-versioning).

## Front matter

La YAML al inicio del `.md` es opcional pero default. Contiene metadata
estructurada que editores (VS Code, Obsidian) pueden indexar.

Para deshabilitar:

```toml
[output]
no_front_matter = true
```

o vía CLI:

```bash
capmd convert book.pdf --chapter 1 --no-front-matter
```

## Tree vs flat

```bash
# Tree (default) — buena para atomicidad por capítulo, fácil de limpiar
capmd convert book.pdf --chapter 4 --out ~/Estudio

# Flat — buena para LLMs que quieren un solo .md
capmd convert book.pdf --chapter 4 --out ~/Estudio --flat
```

En modo flat, el archivo es `<book-slug>-<chapter-slug>.md` y no hay
subcarpeta por capítulo.

## Split por H2

```bash
capmd convert book.pdf --chapter 4 --split h2
```

Genera `cap-04-ownership.md` (full) + `cap-04-ownership-sec-4.1.md` +
`cap-04-ownership-sec-4.2.md` etc. El front matter y el TOC van sólo en el
full; los splits referencian al principal con link relativo.

Útil cuando el capítulo tiene 50+ páginas y querés indexar H2s individuales.

## Inject TOC

```bash
capmd convert book.pdf --chapter 4 --toc --toc-depth 3
```

Inyecta un bloque al inicio del `.md`:

```markdown
## Tabla de contenidos

- [4.1 What Is Ownership?](#41-what-is-ownership)
- [4.2 References and Borrowing](#42-references-and-borrowing)
- [4.3 The Slice Type](#43-the-slice-type)
```

`--toc-depth N` controla cuántos niveles incluye (1 = solo H1, 2 = H1+H2, etc.).

## Determinismo

Dos corridas sobre el mismo source producen el mismo markdown y
`capmd.json`, **excepto** por `converted_at` (timestamp) y `pages_total`
(puede variar si MarkItDown agrega/quita páginas por updates). Para
correr `--batch` con idempotencia, `capmd batch` skip-ea capítulos ya
convertidos con el mismo sha256.

Ver [development.md](development.md#golden-files-j2) sobre golden files
para regresiones visuales.
