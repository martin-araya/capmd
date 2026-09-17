# Instalación

Tres vías soportadas. **Homebrew tap** es la recomendada en macOS (con bottles precompilados).

## Homebrew tap (macOS, recomendado)

```bash
# 1. Tap (una sola vez)
brew tap martin-araya/capmd https://github.com/martin-araya/capmd

# 2. Install
brew install capmd

# 3. Verificar
capmd --version
```

Las bottles se firman y publican en `Formula/capmd.rb`. El tap también
incluye el LaunchAgent watcher opcional (`brew services start capmd`).

## uv tool (Linux, macOS, cross-platform)

```bash
uv tool install capmd
```

`uv tool` instala `capmd` en un venv aislado, registra el entry point
en `~/.local/bin` (Linux) o el equivalente de macOS.

## pip / PyPI

```bash
pip install capmd
# o, en un venv:
python -m venv .venv && source .venv/bin/activate
pip install capmd
```

Las dependencias runtime (`markitdown[pdf,docx,pptx,xlsx]`, `pypdf`,
`pypdfium2`, etc.) se resuelven automáticamente. `markitdown` se descarga
de PyPI como paquete separado — **no se vendoriza**.

## Quick Action de Finder (I2, opcional, macOS)

Click derecho sobre un PDF en Finder → **Convertir capítulo de capmd**.

```bash
# Setup una vez:
capmd setup quick-action --stdout

# El script te da un comando `automator` para pegar en AppleScript;
# o bien:
capmd setup quick-action --install
```

Una vez instalada, la Quick Action aparece en *Servicios* del menu
contextual de Finder. Convierte el PDF seleccionado y guarda el output
junto al input (con suffix `-cap-<N>.md`).

(quick-action-de-finder-i2)=

## Carpeta watch (I3, opcional)

Inbox folder watcher con LaunchAgent (macOS):

```bash
# Setup una vez:
capmd setup launch-agent \
  --inbox ~/Inbox/capmd \
  --out-dir ~/Estudio \
  --move-to ~/Inbox/capmd/processed

# El comando:
# 1. Genera plist en scripts/launch-agent/com.martinaraya.capmd-watch.plist
# 2. Lo copia a ~/Library/LaunchAgents/
# 3. Lo carga con `launchctl bootstrap`
# 4. Verifica que quedó cargado

# Diagnosticar:
capmd watch --once  # corre una iteración sin daemon
```

Cualquier PDF que aparezca en `--inbox` se convierte con el último perfil
activo y se mueve a `--move-to`. Si dos PDFs colisionan en el destino, el
segundo se versiona (`book-1.pdf`, `book-2.pdf`).

## Homebrew tap (I4) — desde el repo

Para mantener el tap (en caso de fork o development local):

```bash
# 1. Editar Formula/capmd.rb con url + sha256 actualizados (scripts/release.sh lo hace).
# 2. Push a tu tap.
# 3. brew install --build-from-source capmd   # local build

# Si querés bottles firmadas:
scripts/build-bottles.sh   # corre brew bottle y produce .bottle.tar.gz firmadas
```

## Verificar la instalación

```bash
# Test completo end-to-end (incluye instalar wheel en un venv temporal,
# correr capmd convert sobre un PDF fixture, y validar exit 0).
bash scripts/verify-install.sh
```

El script debe exit 0. Si falla, ver [Troubleshooting](usage.md#troubleshooting).

## Setup de desarrollo

```bash
# Clone + install editable
git clone https://github.com/martin-araya/capmd
cd capmd
uv pip install -e '.[dev]'

# Verify dev setup
pytest -q
ruff check . && ruff format .
mypy src/capmd
```

Ver [Development](development.md) para detalles de tests + golden files + coverage + release.
