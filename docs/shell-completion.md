# Shell completion

`capmd` soporta completion nativa para zsh, bash, fish, y pwsh via typer.

## zsh (macOS default)

```bash
# Una vez: instala el script de completion a ~/.zfunc/_capmd
capmd --install-completion zsh

# Recargá tu shell
exec zsh

# O agregalo a .zshrc:
echo 'fpath=(~/.zfunc $fpath); autoload -U compinit; compinit' >> ~/.zshrc
```

El script queda en `~/.zfunc/_capmd` (~3 KB, no toca tu `.zshrc`).

## bash

```bash
capmd --show-completion bash > ~/.bash_completions/capmd.sh

# Agregá a ~/.bashrc:
echo 'source ~/.bash_completions/capmd.sh' >> ~/.bashrc
```

## fish

```bash
capmd --install-completion fish

# El script queda en ~/.config/fish/completions/capmd.fish
```

## PowerShell

```pwsh
capmd --install-completion pwsh
```

## Verificar

```bash
capmd --help
capmd convert --help    # muestra flags con `<TAB>` para autocompletar
capmd <TAB>             # muestra subcommands disponibles
```

## CI / tests

`tests/test_shell_completion.py` corre `--show-completion <shell>` con
`_TYPER_COMPLETE_TEST_DISABLE_SHELL_DETECTION=1` y `HOME=$tmp` para no
tocar el filesystem del usuario. Si desactivás `--install-completion`,
rompes esos tests y H4 queda sin documentar en `--help`.
