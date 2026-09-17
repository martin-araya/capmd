# Quality warnings y exit codes

`capmd` emite warnings cuando detecta anomalías en el output. Sin
`--strict` los warnings se loguean pero no cambian el exit code.
Con `--strict`, cualquier warning hace exit 8.

## Warnings

| Code                  | Descripción                                                    | Severidad |
|-----------------------|----------------------------------------------------------------|-----------|
| `empty_output`        | El markdown output está vacío                                  | error     |
| `over_cleanup`        | El cleaner removió >50% del texto (probable bug)               | error     |
| `no_headings`         | No detectó H1 en el output                                     | warning   |
| `pages_no_outline`    | PDF sin outline y la heurística no encontró nada              | warning   |
| `too_many_figures`    | >50 figuras extraídas (puede ser logos repetidos)              | warning   |
| `large_output`        | Output >10 MB (puede ser demasiado para LLMs)                  | warning   |
| `mixed_languages`     | Detectó mezcla En+Es en el cuerpo (puede ser libro técnico)   | info      |
| `unknown_format`      | Formato no soportado por markitdown                           | error     |

Los warnings se imprimen a stderr (formato human) y se incluyen en
`capmd.json: warnings: [...]`.

## Exit codes

| Code | Significado                                                       |
|------|-------------------------------------------------------------------|
| 0    | OK                                                                 |
| 1    | Error genérico (excepción no categorizada)                         |
| 2    | Argumento inválido (`typer.BadParameter`)                          |
| 3    | Source no encontrado / no legible                                  |
| 4    | Formato no soportado                                               |
| 5    | Outline vacío (PDF sin outline + heuristic da 0)                   |
| 6    | Disk full / permission denied / IO error                           |
| 7    | Config error (TOML malformado, key inválida)                       |
| 8    | Quality warning (con `--strict`)                                   |

Cada `CapmdError` mapea a uno de estos codes. Ver `capmd/errors.py`.

## --strict

```bash
capmd convert book.pdf --chapter 1 --strict
```

Exit 8 si hay cualquier warning. Útil en CI / batch donde querés saber
si el PDF se convirtió "limpio" o si hay que revisar.

Para customizar qué warnings importan:

```toml
[quality]
# Solo estos warnings hacen exit != 0 con --strict.
strict_warnings = ["empty_output", "over_cleanup", "unknown_format"]
```

Default: todos los warnings son strict.

## Schema versioning

`capmd.json` tiene `schema_version` (actualmente 2). Cuando cambia el
schema de manera incompatible (e.g. rename de campos), el número
incrementa y los consumidores (capmd inspect, capmd batch) detectan
versiones viejas y las migran.

Política:

- `schema_version`: incrementa con **breaking changes**.
- Aditivos: añadir campo opcional sin bump (consumidores lo ignoran).
- Rename: bump major + deprecation alias por 2 releases.

## Cleanup depth: too aggressive

Si el cleaner pipeline removió más del 50% del texto original, es
probable que algo salió mal (heurística agresiva o formato mal
reconocido). `capmd` emite `over_cleanup`.

Para diagnosticar:

```bash
capmd convert book.pdf --chapter 1 --keep-raw -o /tmp/x.md
# Mira /tmp/x-raw.md y /tmp/x.md side-by-side para ver qué se removió.
```

Deshabilitar cleaners uno a uno:

```toml
# ~/.config/capmd/config.toml
[clean]
skip = ["tables", "footnotes"]
```

Probar, ver si mejora, agregar de a uno.

## Sin outline

PDFs sin outline embebido (markitdown lo saltea) requieren heurística:

1. `capmd inspect book.pdf` para ver qué detecta.
2. Si la heurística falla, definir `[books.<name>].title_pattern` con regex custom:

```toml
[books."my-book"]
title_pattern = '^Partie (\d+)\s*:\s*(.+)$'
```

3. Si tampoco matchea, pasar `--pages N-M` y usar `--chapter N` con
   número explícito (omite la detección automática).
