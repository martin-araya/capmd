# Abrir el resultado en el editor

Tres vías para abrir el `.md` generado:

## `capmd open PATH`

Abre un `.md` existente (por default: el último convertido).

```bash
capmd open                              # el último del registry
capmd open /tmp/cap-04-ownership.md     # path específico
capmd open --editor "code --wait"       # custom editor
```

## `--open` durante `convert`

```bash
capmd convert book.pdf --chapter 4 -o /tmp/x.md --open
capmd convert book.pdf --chapter 4 -o /tmp/x.md --open --open-cmd "code --wait"
```

Después de escribir el output, `capmd` invoca el editor y exit (no espera).

## Editor por default

`capmd open` decide en este orden:

1. `--editor CMD` flag (override explícito).
2. `$EDITOR` env var.
3. `open` en macOS (default; abre con la app default para `.md`).
4. `xdg-open` en Linux.
5. `cmd /c start ""` en Windows.
6. Si nada: error human "no editor found, set $EDITOR or pass --editor".

## Edge cases

- Sin `$EDITOR` y fuera de macOS: el comando falla con un mensaje claro.
  Fijar `export EDITOR=vim` en tu `.bashrc`/`.zshrc` o usar `--editor`.
- Editor que no existe: `FileNotFoundError` capturado con exit 1.
- Editor que sale con error: no aborta el convert (fire-and-forget).

## `--open` vs `capmd open`

| Modo                | Cuándo usar                              |
|---------------------|------------------------------------------|
| `capmd convert --open` | Inmediatamente después de convertir    |
| `capmd open PATH`   | Re-abrir un `.md` ya existente           |

Ambos son fire-and-forget (no esperan al editor).
