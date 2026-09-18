# capmd

Convierte el capítulo de un libro a Markdown limpio, listo para leer, resumir y estudiar.

## Quickstart

```bash
# 1. Instalar (Homebrew tap, recomendado en macOS)
brew install martin-araya/capmd/capmd
# o: uv tool install capmd
# o: pip install capmd

# 2. Ver el índice del libro
capmd toc path/to/book.pdf

# 3. Convertir un capítulo
capmd convert path/to/book.pdf --chapter "Ownership" --out ~/Estudio

# 4. Leer el output
cat ~/Estudio/book/cap-NN-ownership/cap-NN-ownership.md
```

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

Para profundizar: [docs/](docs/index.md) tiene instalación detallada, tour de uso, referencia de flags, configuración TOML, lista de cleaners, troubleshooting, y la API reference autogenerada.

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
git clone https://github.com/martin-araya/capmd.git
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

### Verificar la instalación

El binario queda en `PATH` y corre sin un venv activo:

```bash
which capmd                  # ~/.local/bin/capmd (con uv tool) o ~/.local/bin/capmd (con pipx)
capmd version                # imprime la versión de importlib.metadata
capmd --help                 # usage con subcomandos: convert, toc, batch, config, ...
capmd --install-completion zsh   # opcional: instala completions del shell
```

Para reproducir el smoke test en una máquina limpia (macOS o Linux) desde el source:

```bash
git clone https://github.com/martin-araya/capmd.git
cd capmd
bash scripts/verify-install.sh
```

### Desinstalar

```bash
# con uv tool:
uv tool uninstall capmd

# con pipx:
pipx uninstall capmd

# con brew:
brew uninstall capmd
```

### Homebrew (alternativa recomendada en macOS)

```bash
brew tap martin-araya/capmd
brew install capmd
```

Resuelve en ~30 s en una Mac Apple Silicon limpia: Homebrew instala `python@3.12`,
la fórmula declara 9 recursos de PyPI (typer, markitdown, pypdf, pypdfium2,
pyyaml, pillow, ebooklib, symspellpy, rich) que se instalan dentro del venv de Homebrew,
y descarga el binario pre-compilado (.bottle.tar.gz) del release tag.

Las botellas viven en el [GitHub Release de vX.Y.Z](https://github.com/martin-araya/capmd/releases)
con `root_url = https://github.com/martin-araya/capmd/releases/download/vX.Y.Z/`.
Targets soportados en este MVP: `arm64_sonoma` (macOS 14) y `arm64_sequoia` (macOS 15).
Intel Macs deben usar `uv tool install capmd` en su lugar.

---

## Quick Action de Finder (I2)

Click derecho sobre un PDF en Finder → *Quick Actions* → **Convert capmd chapter**.
El atajo te pide rango (capítulo o páginas) y carpeta de salida (default
`~/Downloads/capmd`), y corre `capmd convert` por cada PDF seleccionado. Soporta
multi-selección. Si `capmd` no está instalado, el atajo aborta con un mensaje
claro apuntando a esta sección del README.

### Instalar

```bash
capmd setup quick-action            # instala (default)
capmd setup quick-action --dry-run  # preview: muestra qué se haría
capmd setup quick-action --print-cmd
capmd setup quick-action --uninstall
```

`--install` corre `open` contra el `.shortcut` que viene empaquetado. macOS
Shortcuts.app muestra su hoja estándar "Add Shortcut"; hacé click en **Add** (o
**Configure** si querés revisar el grafo antes) y el atajo queda disponible en el
menú right-click.

### Verificar el Quick Action (test literal del roadmap)

1. Asegurate de tener un PDF a mano (cualquier PDF).
2. Click derecho sobre el PDF en Finder → *Quick Actions* → *Convert capmd chapter*.
3. Ingresá un rango (ej: `1-3`).
4. Confirmá la carpeta de salida (Enter para default `~/Downloads/capmd`).
5. Esperá la notificación "capmd: terminado".
6. La carpeta de salida tiene que contener un árbol `cap-XX-…/cap-XX-….md`.

El atajo recuerda el último rango y la última carpeta (persiste en
`$XDG_STATE_HOME/capmd/quickaction-last.txt` o `~/.local/state/capmd/`).

### Cómo está construido

El `.shortcut` se **hand-rolla** con `plistlib` desde
`scripts/build-quick-action.py` y se committea en
`src/capmd/assets/Convert capmd chapter.shortcut`. El grafo es deliberadamente
mínimo (un único Run Shell Script) para evitar el schema-rot de las acciones
built-in de Shortcuts entre versiones de macOS. Los prompts, el parseo de
rango y la invocación a `capmd` viven en `src/capmd/setup_quickaction.py`
(expuesto como `SHELL_SCRIPT` en `scripts/build-quick-action.py`).

Para iterar sobre el grafo en Shortcuts.app:

```bash
# 1. Abrilo en la app para edición visual
open src/capmd/assets/Convert\ capmd\ chapter.shortcut

# 2. Hacé cambios en la GUI

# 3. Exportalo y regenerá el asset con:
shortcuts view "Convert capmd chapter"   # abre el shortcut local
# … y exportarlo a File → Export, sobreescribiendo el asset committeado.

# 4. Rebuild defensivo (no necesario si lo exportás en binary plist):
python scripts/build-quick-action.py
```

Para regenerar el `.shortcut` desde Python sin tocar Shortcuts.app:

```bash
python scripts/build-quick-action.py
# por default escribe en src/capmd/assets/Convert capmd chapter.shortcut

# Opcional: firmar con `shortcuts sign --mode anyone` para evitar la hoja de firma
# al distribuir el archivo (sólo relevante fuera del wheel).
```

---

## Carpeta watch (I3, opcional)

`capmd watch` observa una carpeta y convierte automáticamente todo PDF/EPUB/DOCX
que caiga ahí, moviendo el original a `Processed/` cuando termina. Pensado para
"soltar el libro y olvidarse" — la conversión arranca en ≤ 1 s de polling (default
0.5 s) más la duración de la conversión manual.

### Uso directo

```bash
capmd watch \
    --inbox  ~/Books/Inbox \
    --out    ~/Estudio \
    --move-to ~/Books/Processed
```

Flags:

- `--inbox <dir>` — carpeta a observar (requerida).
- `--out <dir>` — donde `capmd convert` deja el markdown (requerida).
- `--move-to <dir>` — donde van los originales ya procesados (default: `<inbox>/Processed`).
- `--pattern <glob>` — uno o más globs aceptados (default: `*.pdf *.epub *.docx *.doc`). Repetible.
- `--debounce <secs>` — segundos a esperar antes de considerar 'estable' un archivo (default: 2.0).
- `--poll-interval <secs>` — intervalo del polling (default: 0.5).
- `--dry-run` — loguea qué se haría sin convertir ni mover.

Si una conversión falla, el original **queda en el inbox** para reintento manual
(el watcher no es agresivo: es mejor que un libro no se pierda a que se pierda
silenciosamente).

### LaunchAgent (auto-start al login)

Para que el watcher arranque solo cada vez que iniciás sesión:

```bash
capmd setup launch-agent \
    --inbox   ~/Books/Inbox \
    --out     ~/Estudio \
    --move-to ~/Books/Processed
```

Esto:

1. Resuelve la ruta al binario de `capmd` (via `shutil.which`).
2. Escribe `~/Library/LaunchAgents/com.martinaraya.capmd-watch.plist` con los
   args correctos.
3. Crea `~/Library/Logs/capmd/` para los logs.
4. Corre `launchctl load -w <plist>` (queda registrado para los próximos logins).

Flags adicionales:

- `--reinstall` — uninstall + install con el binario de capmd actual (útil si
  reinstalaste capmd en otra ruta).
- `--uninstall` — descarga y borra el agente.
- `--dry-run` / `--print-cmd` — preview sin tocar nada.

El `.plist` generado:

- `RunAtLoad = true` (arranca al login).
- `KeepAlive.Crashed = true` (si crashea, launchd lo levanta de nuevo; pero NO
  si sale con código 0, que es el caso normal cuando hacés `launchctl unload`).
- `StandardOutPath`/`StandardErrorPath` → `~/Library/Logs/capmd/capmd-watch.{out,err}.log`.

### Por qué polling en vez de FSEvents

Se evaluó `watchdog` (que usa FSEvents nativo en macOS) y se descartó: el
polling de 0.5 s cumple el SLA del roadmap ("≤ el tiempo de una conversión
manual") sin agregar dependencias, y `agent.md` veta deps nuevas sin justificación.
Si en el futuro hace falta reactividad < 100 ms, :func:`capmd.watch.iter_events`
se puede reimplementar encima de `watchdog.observers.Observer` sin tocar el resto.

### Verificar el Watch (test literal del roadmap)

1. Asegurate de tener `capmd watch` corriendo (en foreground o via LaunchAgent).
2. Soltá un PDF en la carpeta `--inbox`.
3. Esperá la notificación de macOS ("Application downloaded file") o revisá
   la carpeta `--move-to`.
4. El original aparece en `Processed/`; el markdown aparece bajo `--out`.

Tiempo esperado: `poll_interval + tiempo de conversión manual`. Con defaults
(0.5 s + ~0.6 s para un PDF de fixture): **~1.1 s** entre soltar y ver el markdown.

---

## Homebrew tap (I4)

`capmd` se distribuye también como fórmula de Homebrew en un tap in-repo:
`Formula/capmd.rb` dentro de `martin-araya/capmd`. Esto significa que un usuario
puede hacer `brew install martin-araya/capmd/capmd` y resolver todo (Python 3.12
+ 9 deps nativas + binario pre-compilado) en ~30 s en una Mac limpia.

### Estructura

```text
capmd/
└── Formula/
    └── capmd.rb          # la fórmula Homebrew
```

### Releases con botellas firmadas

Las botellas pre-compiladas viven en el GitHub Release de cada tag:

```text
vX.Y.Z
├── capmd-X.Y.Z.tar.gz                       # sdist (wheel/sdist son también assets)
├── capmd-X.Y.Z-py3-none-any.whl             # wheel
└── capmd-X.Y.Z.arm64_<sonoma|sequoia>.bottle.tar.gz   # bottle firmada
```

`Formula/capmd.rb` declara un `bottle do … end` block con el sha256 de cada
target; cuando `brew install` ve que target está disponible, descarga la bottle
y la descomprime; si no, hace `--build-from-source` (lo cual tarda minutos).

### Para el maintainer: hacer un release

```bash
# 1. Asegurate de que el working tree está limpio.
git status
git pull --rebase

# 2. Bump de versión (a mano o con tu editor de confianza).
$EDITOR pyproject.toml   # version = "0.1.1"

# 3. Corre el release script.  Hace todo: build, sdist sha256, Fórmula patch,
#    bottles, tag, push, GitHub Release.
scripts/release.sh 0.1.1

# 4. En otra macOS limpia, valida el test "instalación limpia" (§ siguiente).
```

### Test "instalación limpia en cuenta macOS distinta" (literal del roadmap)

Para validar la fórmula antes de un release:

1. En tu Mac, creá un usuario nuevo: **System Settings → Users & Groups → Add User**
   (rol: Standard, sin acceso admin).
2. **Log out** y logueate como el nuevo usuario (la sesión no comparte estado con
   la tuya — el `~/.cache`, `~/Library`, etc., están vacíos).
3. Instalá Homebrew (con el usuario nuevo):
   ```bash
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
   ```
4. Tapeá e instalá:
   ```bash
   brew tap martin-araya/capmd
   brew install capmd
   ```
5. Smoke test del binario:
   ```bash
   which capmd          # /opt/homebrew/bin/capmd
   capmd version        # capmd X.Y.Z
   capmd --help         # usage con subcomandos
   capmd convert <cualquier.pdf> -o /tmp/capmd-test  # exit 0
   head /tmp/capmd-test/<…>/full.md  # markdown generado
   ```
6. (Opcional) Probar las deps instaladas vía Homebrew:
   ```bash
   brew list capmd
   ls /opt/homebrew/Cellar/capmd/X.Y.Z/bin/capmd
   ```

Tiempos esperados en una Mac Apple Silicon limpia:

| Etapa | Tiempo | Notas |
|---|---|---|
| `brew install capmd` | 10–30 s | Si la bottle del target está disponible. |
| `brew install --build-from-source capmd` | 3–8 min | Si el target NO tiene bottle. |
| Primer `capmd --version` | < 1 s | Venv warm-up. |
| `capmd convert <pdf>` | ~0.6 s | PDF de 2 páginas. |

### Multi-target: arm64_sonoma + arm64_sequoia

La fórmula declara:

```ruby
bottle do
  sha256 arm64_sonoma:  "<sha>"
  sha256 arm64_sequoia: "<sha>"
end
```

El MVP del I4 genera la bottle del OS del maintainer. Para una segunda variante
(ej: maintainer corre en Sequoia, necesita bottles para Sonoma), usar una VM del
target macOS, o `brew test-bot` desde otra cuenta, y correr `build-bottles.sh`
allí. Documentado como follow-up.

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

### Motores alternativos (Azure Doc Intel / Content Understanding)

Para PDFs escaneados o con layout complejo, capmd enruta a Azure vía `markitdown` (subprocess) en lugar del extractor local. La integración expone los mismos flags que `markitdown` CLI:

| Flag | Backend | Notas |
|---|---|---|
| `-d`, `--use-docintel` | Azure Document Intelligence | Flag CLI requerido (no auto-activación) |
| `-e <url>`, `--endpoint <url>` | DocIntel endpoint | Si se omite, se lee de `MARKITDOWN_DOCINTEL_ENDPOINT` |
| `--use-cu`, `--use-content-understanding` | Azure Content Understanding | Mutuamente excluyente con `-d` |
| `--cu-endpoint <url>` | CU endpoint | Si se omite, se lee de `MARKITDOWN_CU_ENDPOINT` |
| `--cu-analyzer <id>` | CU analyzer ID | Ej: `prebuilt-documentAnalyzer` |
| `--cu-file-types <a,b,c>` | CU routing | Comma-separated; ej: `pdf,jpeg,mp4` |

Decisión K4: el routing solo se activa con **flag CLI explícito** (`-d` o `--use-cu`). Las env vars proveen endpoints pero no auto-activan el routing — evita llamadas a la API accidentales.

Ejemplo:

```bash
# DocIntel con endpoint explícito
capmd convert libro.pdf -d -e https://mi-docintel.cognitiveservices.azure.com -o out/

# Content Understanding con analyzer
capmd convert libro.pdf --use-cu \
  --cu-endpoint https://mi-cu.cognitiveservices.azure.com \
  --cu-analyzer prebuilt-documentAnalyzer \
  --cu-file-types pdf,jpeg \
  -o out/
```

El resto del pipeline (cleaners, `--profile study`, post_command hook, `--split h2`, images) corre **igual** sobre el markdown que devuelve Azure — el routing solo reemplaza el step de extracción inicial.

Si los extras de Azure no están instalados en `markitdown`, la instalación se queja con un ImportError claro:

```bash
pip install 'markitdown[docintel,cu]'   # solo los extras necesarios
pip install 'markitdown[all]'             # todos los extras
```

### Perfiles de output (K2)

| Flag | Descripción |
|---|---|
| `--profile study` | Activa el perfil de estudio: agrega sub-bloque `study:` al front matter y appendea 3 secciones vacías al cuerpo |
| `--tag <texto>` | Tag para el front matter de `--profile study` (repetible; deduplicado preservando orden) |
| `--reading-status <unread\|in_progress\|read>` | Estado de lectura inicial (default: `unread`). Auto-set `started_at` en `in_progress`, `finished_at` en `read` |
| `--reset-study` | Con `--profile study`, limpia `started_at`/`finished_at` del archivo previo (default: preserva fechas editadas a mano) |

Ejemplo:

```bash
capmd convert book.pdf \
  --profile study \
  --tag rust --tag ownership \
  --reading-status in_progress \
  --out ~/Estudio
```

Resultado en el `.md`:

```yaml
---
title: Ownership
# ... (10 claves de F2) ...
study:
  tags: [rust, ownership]
  reading_status: in_progress
  started_at: 2026-09-17T03:00:00Z
  finished_at: null
---

# Ownership

Contenido del capítulo…

## Resumen

## Conceptos clave

## Dudas
```

Los tags también se pueden prefijar desde el perfil del libro en `~/.config/capmd/config.toml`:

```toml
[books."rust-handbook"]
tags = ["rust", "ownership"]
reading_status = "unread"
```

`--tag X` en CLI gana sobre el TOML (precedencia consistente con G2). Sin `--profile study`, ni el front matter ni el cuerpo se modifican — la feature es opt-in.

---

## Plugin para el MarkItDown oficial

`capmd` se declara como entry-point en el grupo `markitdown.plugin`, así que sus cleaners también quedan disponibles si usás `markitdown` directamente con `--use-plugins`.

```bash
# Verificar que el plugin está instalado
markitdown --list-plugins
# → capmd-cleaners   (package: capmd.markitdown_plugin:CleanersMarkItDownPlugin)

# Limpiar un .md con la grilla oficial de markitdown
markitdown archivo.md --use-plugins -o limpio.md

# Flujo en dos pasadas para un PDF: convertir y luego limpiar
markitdown libro.pdf -o tmp.md
markitdown tmp.md --use-plugins -o limpio.md
```

El plugin acepta streams `.md`, `.markdown`, `.mkd`, `.mkdn` o con mimetype `text/markdown` y aplica el mismo `capmd.clean.default_pipeline()` (mismos 11 cleaners del bloque D). No consulta la config TOML ni las env vars: para control fino (`--only-clean`, `--skip-clean`, perfiles por libro) usá `capmd convert` directamente.

---

### Hooks post-conversión (K3)

`post_command` en el TOML invoca un comando después de escribir el `.md` final al chapter root (no se invoca en `--split h2` por cada section; una corrida = un fire):

```toml
# ~/.config/capmd/config.toml
[hooks]
post_command = "~/bin/notify-discord.sh"
post_command_timeout = 60   # opcional; default 60s; -1 = sin timeout

# Override por libro (gana sobre el global)
[books."rust-handbook"]
post_command = "~/bin/index-in-obsidian.sh"
```

El script recibe el path al `.md` como `$1` y metadata adicional vía env vars:

- `CAPMD_OUTPUT_PATH` (siempre)
- `CAPMD_CAPMD_JSON_PATH` (tree mode; vacío si no existe)
- `CAPMD_IMAGES_DIR` (tree mode; vacío si no existe)
- `CAPMD_BOOK_SLUG`, `CAPMD_CHAPTER_SLUG`
- `CAPMD_PROFILE` (perfil activo, p.ej. `study`; vacío si ninguno)
- `CAPMD_VERSION`

El timeout default es 60 segundos (`CAPMD_HOOK_TIMEOUT` env var para override global; `-1` desactiva el timeout). Si el hook devuelve exit code != 0, expira, o el binario no existe, `capmd` emite un warning a stderr pero la corrida termina con exit 0 (la salida del `.md` no se ve afectada).

El hook **no se invoca** cuando:

- No hay output a disco (stdout, sin `-o` ni `--out`).
- Se usa `--dry-run` (es un mode plan-only).
- La conversión falla antes de escribir el archivo.
- `--split h2`: el hook se dispara **una sola vez** con el path al root `.md` del capítulo (los `sections/0N-*.md` NO disparan fires individuales).

---

### Caché de conversión (K6)

La 2ª corrida idéntica es un **cache hit** (no-op):

```bash
# 1ª corrida (cache miss, normal convert + cleaners + cache save)
capmd convert book.pdf -o out.md

# 2ª corrida (cache hit — "cache hit: abcd1234" a stderr; el archivo
# se reescribe byte-a-byte con el cached body; no se invoca markitdown
# subprocess ni los 11 cleaners).
capmd convert book.pdf -o out.md
```

Cache key: `sha256(file_bytes + page_range + cleaner_config + capmd_version)`. Cualquier cambio en estos componentes invalida el cache:
- Archivo modificado → cache miss.
- `--pages "1-3"` vs `--pages "1-3,7"` → cache miss.
- `--only-clean X` vs `--only-clean Y` → cache miss.
- Upgrade de capmd → todos los caches viejos quedan stale.

Flags:

- `--cache-dir DIR` / `CAPMD_CACHE_DIR` — override del directorio de cache.
- `--no-cache` / `CAPMD_NO_CACHE=1` — desactiva cache (skip read + write).

Default location: `$XDG_CACHE_HOME/capmd/convert/` (o `~/.cache/capmd/convert/` si XDG no está set).

El cache guarda el markdown body post-cleaners + FM + imágenes extraídas. El resto del pipeline (split K4, profile study K2, hooks K3) opera sobre el cached body igual que en una corrida normal. El flag `--no-clean` (saltar cleaners) NO desactiva el cache — solo cambia qué se cachea (el cached body ya viene sin cleaners).

**Orden del pipeline con cache:** cache lookup → markitdown/cleaners → FM prepend → write output → **post_command hook** → cache save. Si tenés un hook K3 que modifica el `.md` (raro pero posible — ej: append "metadata: ..."), el hook corre ANTES del cache save, así que el archivo en disco difiere del cached body. La próxima corrida (cache hit) reproduce el cached body, no el archivo modificado. Si necesitás que el cache refleje post-hooks, abrí un feature request.

---

### Comparador de motores (`capmd compare`, K5)

```bash
capmd compare book.pdf --pages 45-50
capmd compare book.pdf --format json           # JSON estructurado
capmd compare book.pdf --ocr-engine tesseract  # forzar un OCR específico
```

Compara lado a lado los motores de extracción disponibles:

| Motor | Cuándo corre | Notas |
|---|---|---|
| `built-in` | siempre | markitdown local (PDF/EPUB/DOCX/PPTX/XLSX) |
| `docintel` | `MARKITDOWN_DOCINTEL_ENDPOINT` set | Azure Document Intelligence (vía K4) |
| `content-understanding` | `MARKITDOWN_CU_ENDPOINT` set | Azure Content Understanding (vía K4) |
| `ocr-tesseract` | `tesseract` en PATH | renderiza pages a PNG vía pypdfium2 + tesseract OCR |
| `ocr-ocrmypdf` | `ocrmypdf` en PATH | `ocrmypdf --skip-text` + extracción built-in |

Métricas: `palabras` (`len(text.split())`), `headings` (`^#{1,6} ` count), `tiempo` (subprocess wall-time), `estado` (`ok` | `skipped` | `error`).

Flags:

- `--pages <rango>`: rango 1-based (ej: `"45-50"` o `"1-3,7,10-12"`); default todo el archivo.
- `--timeout <seg>`: timeout por motor (default 600s).
- `--format <table|json>`: Rich table a stdout (default) o JSON pretty-print.
- `--ocr-engine <tesseract|ocrmypdf>`: forzar un OCR específico (default: auto-detect los que estén en PATH).

Exit codes: `0` (ok; o ≥1 motor disponible pero <2 ok), `8` (≥2 motores disponibles pero <2 ok — el compare imprime el estado honestamente), `7` (input inválido), `2` (args inválidos).

Si los motores Azure están configurados por env vars, el compare **gasta API quota automáticamente** sin pedir confirmación. Para un "dry-run" sin coste, dejá `MARKITDOWN_*_ENDPOINT` sin setear.

---

## Formato de salida

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

Ver la sección "Perfiles de output (K2)" arriba para los flags completos (`--tag`, `--reading-status`, `--reset-study`) y el sub-bloque `study:` que se agrega al front matter.

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

### ¿Qué hace cada cleaner?

Para entender qué reescribe y qué **deliberadamente NO toca** cada cleaner, y cómo deshabilitar uno para un libro puntual, ver [docs/cleaners.md](docs/cleaners.md).

---

## Shell completion

Tab-completion para zsh (default en macOS), bash, fish y PowerShell:

```bash
# Zsh (recomendado en macOS):
uv tool install capmd   # o: uv pip install capmd
capmd --install-completion zsh
# seguido de: eval "$(capmd --show-completion zsh)"

# Bash:
capmd --install-completion bash
# o: source <(capmd --show-completion bash)

# Fish:
capmd --install-completion fish
```

Sin argumentos, `--install-completion` autodetecta el shell desde `$SHELL` (vía `shellingham`). El script queda en `~/.zfunc/_capmd` (zsh), `~/.bash_completions/capmd.sh` (bash) o `~/.config/fish/completions/capmd.fish` (fish).

Para zsh, asegurate de tener en tu `~/.zshrc`:

```bash
fpath+=~/.zfunc
autoload -Uz compinit
compinit
```


**Atajo / Quick Action.** Click derecho sobre un PDF en Finder → *Quick Actions* → *Convert capmd chapter*. Instalalo con `capmd setup quick-action`. Detalle completo en la sección [Quick Action de Finder (I2)](#quick-action-de-finder-i2) más arriba.

**Carpeta observada.** Lanzá `capmd watch` (o instalalo como LaunchAgent) para que vigile `~/Books/Inbox` y convierta lo que caiga ahí. Detalle completo en la sección [Carpeta watch (I3)](#carpeta-watch-i3-opcional) más arriba.

**Hook post-conversión.** En la config:

```toml
post_command = "mi-script-de-resumen {md_path}"
```

Se ejecuta con la ruta del `.md` generado, para encadenar `capmd` con lo que venga después.

---

## Abrir el resultado en el editor (H5)

Tras convertir, podés abrir el `.md` automáticamente:

```bash
capmd convert tests/fixtures/x.pdf -o /tmp/x.md --open   # usa $EDITOR (o `open` en macOS)
capmd convert tests/fixtures/x.pdf -o /tmp/x.md --open --open-cmd "code --wait"
```

O re-abrir un `.md` ya existente:

```bash
capmd open /tmp/x.md
```

Fire-and-forget: no espera al editor. Sin `$EDITOR` y en Linux/macOS no-macOS, fijalo en tu shell (`export EDITOR=vim` o pasá `--editor "<cmd>"`).

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
pytest                      # suite completa (corre coverage + tests)
pytest --update-golden      # regenerar los golden files (J2)
ruff check . && ruff format .
mypy src/capmd
```

### Calidad de tests (J1)

`pytest` corre **coverage** automáticamente y **falla el build si baja del 90%** (configurado vía `--cov-fail-under=90` en `pyproject.toml`). El reporte HTML queda en `htmlcov/index.html`.

```bash
pytest                                # verde con ≥ 90% coverage
open htmlcov/index.html               # inspeccionar branches no cubiertos
pytest --no-cov                       # solo tests, sin coverage (más rápido)
pytest tests/test_clean_headers.py    # un módulo específico
pytest --cov=capmd.clean --cov-fail-under=100 tests/test_clean_headers.py   # 100% en un archivo
```

### Golden files (J2)

Cada fixture sintético de `tests/fixtures/build.py` produce un `.md` golden bajo `tests/golden/test_golden_pipeline/<fixture>.md`. Cualquier cambio en un cleaner que altere el output se ve como diff al correr `pytest`. Regenerar los 14 goldens:

```bash
pytest --update-golden tests/test_golden_pipeline.py     # alias de --snapshot-update de syrupy
```

Los `.md` son archivos versionados — **revisar el diff a mano** antes de regenerarlos: el diff es la evidencia de si el cleaner mejoró o rompió algo. El mecanismo usa [syrupy 4.x](https://github.com/syrupy-project/syrupy) con un `MarkdownSnapshotExtension` custom (`tests/conftest.py`) que apunta los snapshots a `tests/golden/` en lugar del `__snapshots__/` default.

### Versionado y changelog (J3)

Workflow completo del maintainer para publicar una release:

```bash
# 1. Setup único: hooks versionados + cliff en PATH
brew install git-cliff                      # o cargo install git-cliff
bash scripts/install-hooks.sh               # git config core.hooksPath scripts/hooks

# 2. Tras mergear a main y verificar que los tests verdes:
bash scripts/bump-version.sh                # sugiere v0.2.0 y parchea pyproject.toml
# (revisá el diff)

git add pyproject.toml
git commit -m "chore(release): bump 0.1.0 → 0.2.0"

# 3. Tag + push. El hook post-tag dispara el release pipeline.
git tag -a v0.2.0 -m "release: v0.2.0"
#    ↳ hook ejecuta scripts/release.sh: build sdist + wheel + bottles
#      + formula patch + push + gh release create v0.2.0 con assets
```

Mecánica:
- **SemVer**: `pyproject.toml:7` declara `version = "0.1.0"`; `scripts/release.sh:69` valida coincidencia con el tag.
- **`git-cliff --bump`**: computa la próxima versión desde commits convencionales (`feat:`→minor, `BREAKING CHANGE:`→major, `fix:`→patch).
- **`cliff.toml`**: parser de conventional commits (case-insensitive) que agrupa `feat/fix/perf/refactor/docs/test/build/ci/style/chore/revert` y etiqueta `[**breaking**]` para `feat!`/`fix!`/`BREAKING CHANGE:`.
- **`scripts/hooks/post-tag`**: solo dispara en annotated tags `vX.Y.Z`; invoca `scripts/release.sh`. Tags lightweight o non-semver se ignoran.
- **`scripts/release.sh`** ya no tag-ea internamente — el tag es el trigger del hook. Si se invoca manualmente (`bash scripts/release.sh X.Y.Z`), skip-ea si el tag existe o lo crea si falta.

Pre-requisitos del maintainer (documentados en el README y en `agent.md`):
- `git-cliff` en PATH (`brew install git-cliff`).
- `gh` autenticado (`brew install gh && gh auth login`).
- `brew` con tap `martin-araya/capmd` configurado (I1, I4).
- Working tree limpio al momento de tagear.

### Publicación a PyPI (J4)

Tras crear el GitHub Release, el maintainer sube el wheel + sdist a PyPI. La mecánica usa `uv publish` con `UV_PUBLISH_TOKEN`:

```bash
# 4. TestPyPI primero (validamos antes de pegar el salto a producción).
UV_PUBLISH_TOKEN=$TESTPYPI_TOKEN bash scripts/publish.sh 0.2.0 --to testpypi
UV_PUBLISH_TOKEN=$TESTPYPI_TOKEN bash scripts/verify-pypi-install.sh 0.2.0 --target testpypi

# 5. Si el smoke OK, mismo flujo a PyPI real.
UV_PUBLISH_TOKEN=$PYPI_TOKEN bash scripts/publish.sh 0.2.0 --to pypi
UV_PUBLISH_TOKEN=$PYPI_TOKEN bash scripts/verify-pypi-install.sh 0.2.0
```

Contrato del roadmap: "`pip install capmd` en un venv limpio convierte un PDF". `scripts/verify-pypi-install.sh` lo verifica con un venv fresco + un PDF generado por `tests.fixtures.build` + `capmd convert`.

Tokens: NUNCA commitearlos. Mantener en `~/.config/capmd/pypi.env` (chmod 600) o un keychain (1Password, macOS Keychain). Para generar tokens: PyPI `pypi-...` en https://pypi.org/manage/account/token/, TestPyPI en https://test.pypi.org/manage/account/token/.

Dry-run local sin gastar token:

```bash
bash scripts/publish.sh 0.2.0 --to testpypi --dry-run   # valida version + artefactos
```

Skip del smoke test (util en sandbox sin red):

```bash
CAPMD_SKIP_PYPI_VERIFY=1 bash scripts/verify-pypi-install.sh 0.2.0
```
```

Las excepciones defensivas (ej: `except Exception: pass` dentro de pools de pypdfium2 o file-locks de fcntl) se marcan con `# pragma: no cover` quirúrgicamente. El módulo está completo en `tests/test_j1_coverage_gaps.py`, `tests/test_j1_coverage_inspect.py`, `tests/test_clean_noop.py` y `tests/test_convert_limits.py`.

Los fixtures de test se **generan** con `reportlab` (PDFs sintéticos con headers repetidos, guiones de corte, figuras, tablas, TOC). El repo no incluye material con copyright.

Ver `roadmap.md` para el plan por fases y `agent.md` para el contexto de trabajo con agentes.

---

## Créditos

Construido sobre [MarkItDown](https://github.com/microsoft/markitdown) (MIT, Microsoft). `capmd` es un paquete independiente que lo consume desde PyPI — el repo de MarkItDown explícitamente prefiere que las aplicaciones vivan fuera de su árbol.

## Licencia

MIT.
