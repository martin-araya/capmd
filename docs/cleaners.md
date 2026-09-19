# Cleaners

Cada limpiador es una función pura `(texto, ctx) -> (texto, stats)` que
reescribe el markdown para llevarlo a algo legible. No tienen estado, no
tocan I/O, y se registran en orden explícito en
[`src/capmd/clean/pipeline.py`](https://github.com/martin-araya/capmd/blob/main/src/capmd/clean/pipeline.py).

## Tabla resumen

| Nombre             | Posición | Default | Qué reescribe                                                    | Qué NO toca (false-positive guards)                  |
|--------------------|----------|---------|------------------------------------------------------------------|-------------------------------------------------------|
| `whitespace`       | D1       | on      | Tabs vs spaces, dobles espacios, line endings mixtos            | Bloques indentados (Markdown los respeta)            |
| `hyphens`          | D3       | on      | Palabras cortadas con `-` al final de línea (heurística + wordlist) | Compuestos (`well-known`), palabras no en wordlist   |
| `headers`          | D4       | on      | Texto repetido al inicio/fin de cada página                     | Footers con info útil, headers intencionales         |
| `page_numbers`     | D5       | on      | `"— 47 —"`, `"Página 47"`, `"47 \| Cap N"`, `"204  PART II  Title"` (FIX-7) | Referencias inline a números de página, lowercase keywords |
| `kerning`          | D9       | on      | Colapsa runs de letras/dígitos uppercase separados por 1-2 espacios (FIX-8) | Líneas mixtas, lowercase, con puntuación, code fences |
| `headings`         | D6       | on      | Detecta jerarquía via font size + regex de Chapter              | Subtitulos sin keyword (`Chapter N`)                 |
| `single_h1`        | D7       | on      | Múltiples H1 en el body → promueve uno                          | Documentos estructurados con varios H1 intencionales  |
| `code_blocks`      | D8       | on      | Snippets indentados y fences faltantes                          | Bloques ya fenceados, indentación dentro de listas   |
| `lists`            | D9       | on      | Bullets unicode → ASCII, listas partidas                       | Listas dentro de code fences                         |
| `paragraph_joins`  | D10      | on      | Párrafos partidos por `-` o wrap                               | Bloques en code fences, párrafos intencionalmente cortos |
| `tables`           | D11      | off     | Tablas GFM malformadas que markitdown rompe                     | Tablas que markitdown ya marcó como `|...|`         |
| `footnotes`        | D12      | on      | Footnotes `[^1]` orphans, `<sup>N</sup>` markup                 | Footnotes legítimamente referenciadas                 |

Pipeline order: `D1 → D12`. Si deshabilitás uno, los siguientes corren igual
(pero un cleaner upstream que asuma whitespace normalizado, por ejemplo,
puede degradarse). Mejor deshabilitar por la **izquierda** (los primeros).

### Cómo deshabilitar

```toml
# ~/.config/capmd/config.toml

# Opción A: lista blanca. Sólo corren estos cleaners.
[clean]
enabled = ["whitespace", "hyphens", "headers"]

# Opción B: lista negra. Corren todos MENOS estos.
[clean]
skip = ["tables", "footnotes"]

# Opción C: por libro.
[books."rust-handbook"]
clean_skip = ["tables"]
```

El nombre usado en estas listas es el `name` del cleaner (ver sección
por cleaner abajo). `capmd config show` imprime los cleaners activos.

---

## `whitespace` (D1)

**Objetivo**: normalizar whitespace sin tocar la semántica del Markdown.

**Input**:
```
Parrafo  uno.    Linea con trailing spaces.
		Tabs mezclados.

Otro párrafo.
```

**Output**:
```
Parrafo uno. Linea con trailing spaces.
Tabs mezclados.

Otro párrafo.
```

**Qué reescribe**:
- Dobles/triples espacios entre palabras → un espacio.
- Tabs al inicio de línea → 2 o 4 spaces (manteniendo el bloque de código
  si la indentación es ≥4).
- CRLF, CR → LF.
- Trailing whitespace por línea → vacío (preserva salto de línea).
- Line endings mixtos → uniforme.

**Qué NO toca** (false-positive guards):
- Bloques indentados con 4+ espacios (Markdown los preserva como code).
- Líneas que terminan con `\` (Markdown hard-break; respetar el trailing).
- Indentación relativa dentro de listas (`- ` vs `-    `).

**Razón de diseño**: el resto de cleaners asumen whitespace normalizado.
Si lo deshabilitás, `hyphens` puede dar falsos positivos (`-` final
confundido con bullet), `paragraph_joins` puede unir líneas que no debería.

**Test**: `tests/test_clean_whitespace.py`.

---

## `hyphens` (D3)

**Objetivo**: unir palabras cortadas por guion al final de línea
(justificación tipográfica).

**Input**:
```
The know-
ledge of programming helps.

The pala-
bra of pala-
bra-like words survives.

Compound well-known terms must NOT be joined.
```

**Output** (con wordlist En+Es) **puede ser**:
```
The knowledge of programming helps.

The palabra of palabra-like words survives.

Compound well-known terms must NOT be joined.
```

**Qué une**:
- par `lowercase-lowercase` al final de línea + la unión está en la
  wordlist (Inglés + Español, ~250k entradas combinadas).
- no toca los caracteres no-ASCII al final (`-` Unicode es el único usado).
- case-by-case: `Word-` + `word` no se une (cambia la capitalización).

**Qué NO une** (false-positive guards):
- Compuestos con guion (`well-known`, `twenty-one`, `self-contained`).
- Cualquier cosa dentro de code fences ``` ... ```.
- Palabras no en la wordlist: si duda, no une (non-greedy por diseño).
- Capitalización mixta (`Word-` + `word`).

**Cómo verificar la wordlist**: `capmd convert` no usa wordlist propia;
`capmd/symspellpy` (configurable via `[clean].hyphen_wordlists_path` en TOML).

**Test**: `tests/test_clean_hyphens.py`.

---

## `headers` (D4)

**Objetivo**: remover el header y footer repetidos en cada página
(encabezado `"Chapter 3 | Rust in Action"`, footer `"— 47 —"` antes de
que D5 los limpie, o peor, antes de que contaminen el markdown).

**Input**:
```
Chapter 3 | Rust in Action

Section A
Body line 1
Body line 2

Chapter 3 | Rust in Action

Section B
Body line 1
Body line 2

— 47 —
```

**Output**:
```
Section A
Body line 1
Body line 2

Section B
Body line 1
Body line 2
```

**Qué detecta**:
- Cualquier string que aparece como primera o última línea en ≥60% de
  las páginas → header / footer.
- Si el string tiene ≥3 palabras, es más probable header.
- Si el string es un número aislado o `"— N —"` → casi seguro footer.

**Qué NO toca** (false-positive guards):
- El **primer header** (lo que va antes del capítulo) — si tiene length
  diferente a los siguientes, se preserva.
- Headers con paginación tipo `"47 | Cap 3"` — esos los limpia `page_numbers`
  primero (D5), no D4.
- Headers en la primera/última página si difieren del resto (portada /
  colofón).

**Cuándo deshabilitar**: si tu PDF no tiene header/footer repetido (libros
generados digitalmente, no escaneados) — pero el costo del cleaner es
casi cero y solo se queja si hay repetición, así que rara vez vale
deshabilitar.

**Test**: `tests/test_clean_headers.py`.

---

## `page_numbers` (D5)

**Objetivo**: remover líneas sueltas con número de página que NO son
headers/footers (no tenían la repetición para que D4 los agarrara).

**Input**:
```
Section A

47

Section B
```

**Output**:
```
Section A

Section B
```

**Qué detecta**:
- Línea suelta (sin contexto, ≤4 chars) que es solo dígitos.
- `"— N —"`, `"—N—"`, `"Página N"`, `"Pág. N"`.
- `"47 | Cap 3"` (header-pagenum mezclado; combina con D4).
- Footer editorial `"<num>  <KEYWORD>  <title>"` (FIX-7 / D8) con
  keywords cerrados: `PART`, `Chapter`, `Section`, `APPENDIX`,
  `Volume`, `Module`, `Unit`. Típico de libros académicos en inglés:
  `"204  PART II  Requirements development"`.

**Qué NO toca** (false-positive guards):
- Línea con texto + número + texto (referencia inline al número de página).
- `"Section 47"` o `"Capítulo 47"` (heading con número).
- Números de página que el usuario marcó como `<!-- page N -->`
  (markitdown los preserva; no los tocamos).
- Inline: `"204 is the answer"` — la palabra `is` no está en la
  alternancia cerrada, así que el footer editorial no matchea
  (FIX-7 guard explícito contra false positives).
- Keywords lowercase: `"204  part ii  Title"` NO matchea (regex
  case-sensitive para mantener el guard).

**Test**: `tests/test_clean_page_numbers.py`.

---

## `kerning` (FIX-8 / D9)

**Objetivo**: colapsar artefactos visuales de kerning exagerado que
`markitdown`/`pypdfium2` extrae literalmente. Ejemplo: en lugar de
`CHAPTER 11` el motor emite `C H A P T E R   1 1`.

**Input**:
```
Intro

C H A P T E R   1 1

Requirements
```

**Output**:
```
Intro

CHAPTER   11

Requirements
```

**Política**: solo se procesan líneas que, tras `strip()`, son 100%
uppercase + dígitos + espacios. El regex `\b[A-Z0-9](?: {1,2}[A-Z0-9])+\b`
matchea cada run, colapsando los espacios 1-2 intermedios pero
preservando separadores más anchos (3+ espacios). El whitespace
residual lo normaliza `whitespace` (cleaner anterior en el pipeline).

**Posición en pipeline**: entre `whitespace` y `hyphens`. Corre
después de la normalización Unicode (NBSP→espacio, etc.) y antes de
operaciones más invasivas.

**Qué NO toca** (false-positive guards):
- Líneas mixtas: `"Section A B"` (contiene minúsculas).
- Lowercase: `"c h a p t e r 1 1"` (no es artefacto de kerning).
- Con puntuación: `"A B C, donde A=1"` (rompe uppercase-only-line).
- Code fences: `` ```bash\nA B C\n``` `` preservados por
  `split_outside_fences`.

**Upstream note**: si el PDF tiene `ActualText` en el `ToUnicode`
map, markitdown debería usarlo en lugar de exponer el kerning al
texto plano. Vale la pena abrir issue upstream si los PDFs afectados
son muchos; mientras tanto `kerning` cubre el caso.

**Test**: `tests/test_kerning.py`.

---

## `headings` (D6)

**Objetivo**: detectar la jerarquía H1/H2/H3 del PDF a partir de font size
y keywords (`Chapter`, `Capítulo`, `Section`), y prefijar con `#`/`##`/`###`.

**Input** (después de D1–D5):
```
Chapter 3: Ownership

Body under H1.

3.1 References

Body text under H2.
```

**Output**:
```
# Chapter 3: Ownership

Body under H1.

## 3.1 References

Body text under H2.
```

**Cómo decide el nivel**:
1. Regex `^Chapter N[:.]` / `^Capítulo N[:.]` / `^Chapter$` (all-caps) → H1.
2. Regex `^N\.M\.K? ` (numeric) → H2/H3 según profundidad.
3. Font size relative a body median: ≥1.05× → H1, ≥1.03× → H2, etc.
4. Heurística: line que matchea las regex anteriores con font body median
   no es heading; font ratio sin keyword tampoco.

**Qué NO toca** (false-positive guards):
- Subtítulos que NO matchean regex Y tienen font <1.05× — quedan como body.
- Líneas que ya tienen `#`/`##` (markdown pre-existente).
- Texto dentro de code fences.

**Razón de diseño**: muchos PDFs no tienen outline embebido. La
heurística font + regex cubre el 80% de los libros técnicos; el resto
se construye manualmente con `[books.<name>].title_pattern`.

**Test**: `tests/test_clean_headings.py`.

---

## `single_h1` (D7)

**Objetivo**: asegurar que el body tenga un único `#` (atributo `single_h1`
de Markdown limpio — un solo H1 por documento).

**Input**:
```
# Cap 1

Body.

# Another H1

Body 2.
```

**Output**:
```
# Cap 1

Body.

## Another H1   # demoted to H2

Body 2.
```

**Cómo decide**:
- Mantiene el primer `#`.
- Demota los siguientes `#` a `##`.

**Qué NO toca** (false-positive guards):
- Documentos que intencionalmente tienen varios `#` (ej. `capmd batch`).
  Para esos, `clean_skip = ["single_h1"]`.
- `#` dentro de code fences.

**Test**: `tests/test_clean_single_h1.py`.

---

## `code_blocks` (D8)

**Objetivo**: envolver código indentado o monolingüe en fences
```` ``` ```` (markitdown no siempre lo hace bien en PDFs escaneados).

**Input**:
```
Para introducir un Cargo project:

    $ cargo new hello
    $ cd hello
    $ cargo run

Y luego editar main.rs.
```

**Output**:
```
Para introducir un Cargo project:

```bash
$ cargo new hello
$ cd hello
$ cargo run
```

Y luego editar main.rs.
```

**Qué detecta**:
- Bloques indentados con 4+ spaces (markitdown los preserva; los envolvemos).
- Líneas donde todos los chars son monoespaciados (heurística font).
- Fences ``` existentes, sin duplicar.

**Lenguaje**: si el bloque matchea keywords (`def`, `$`, `fn`, `import`),
se etiqueta el fence (`python`, `bash`, `rust`). El lenguaje se infiere
con `infer_language()`; ver `capmd.clean.code_blocks.infer_language`.

**Qué NO toca** (false-positive guards):
- Indentación dentro de listas (NO son code, son sub-items).
- Fences ``` ya presentes.
- Líneas de código dentro de listas mezcladas (heurística non-greedy).

**Test**: `tests/test_clean_code_blocks.py`.

---

## `lists` (D9)

**Objetivo**: normalizar bullets unicode (`•`, `‣`, `–`) a ASCII (`-`),
unir listas partidas, normalizar listas numeradas que se cortaron.

**Input**:
```
• Item 1
• Item 2
‣ Item 3
– Item 4

1. First
2. Second
3. Third
```

**Output**:
```
- Item 1
- Item 2
- Item 3
- Item 4

1. First
2. Second
3. Third
```

**Qué reescribe**:
- `•`, `‣`, `–` → `-` (ASCII).
- Tabla mixta de bullets normalizada a `-`.
- Listas numeradas partidas (líneas en blanco intermedias).
- Sangría francesa (1 espacio vs 4) — se usa 2 spaces para sub-items.

**Qué NO toca** (false-positive guards):
- Listas dentro de code fences.
- Bullets intencionales en prosa (ej. `*emphasis*` vs `- list` — el `*` queda
  intacto, no es bullet).
- Numeración de capítulos fuera de contexto (`1.` en prosa).

**Test**: `tests/test_clean_lists.py`.

---

## `paragraph_joins` (D10)

**Objetivo**: unir párrafos partidos por line wrap o por `-` (sin hyphens
del D3 — D3 maneja guiones de palabras partidas, D10 maneja guiones de
párrafos partidos sin unión).

**Input**:
```
Este es un párrafo largo que
fue partido por line wrap
en el PDF original.

Párrafo intencionalmente
corto.
```

**Output**:
```
Este es un párrafo largo que fue partido por line wrap en el PDF original.

Párrafo intencionalmente corto.
```

**Qué une**:
- Líneas consecutivas sin blank entre ellas (line wrap).
- Línea que termina con `-`/`‐`/soft hyphen y la siguiente empieza lowercase
  (par de párrafo partido, NO word hyphen — eso lo hace D3).

**Qué NO une** (false-positive guards):
- Párrafos intencionalmente cortos (un blank line sí está entre ellos).
- Líneas que terminan con `.`, `!`, `?`, `:` — terminan oración, no wrap.
- Headings (`#`, `##`) no se unen con la línea anterior.
- Code fences (```).
- Listas.

**Test**: `tests/test_clean_paragraph_joins.py`.

---

## `tables` (D11)

> Default **off**. Si tu PDF tiene tablas rotas por markitdown, activalo.

**Objetivo**: arreglar tablas GFM malformadas que markitdown emite
cuando el PDF tenía celdas partidas por line wrap.

**Input** (markitdown output típico de un PDF escaneado):
```
Sample Table | Header A | Header B | Header C
| -------- | -------- | -------- |
| row 1 a | row 1 b | row 1 c |
| row 2 a | row 2 b | row 2 c |
```

**Output**:
```
| Sample Table | Header A | Header B | Header C |
| ----------- | -------- | -------- | -------- |
| row 1 a     | row 1 b | row 1 c |          |
| row 2 a     | row 2 b | row 2 c |          |
```

**Qué reescribe**:
- Header row incompleto (sin `|...|` al inicio) → completa.
- Separator row (`| --- | --- |`) si falta → añade.
- Padding inconsistente → normaliza.
- Cells con line wrap interno (`<br>` ya lo preserva, pero pad extra).

**Cuándo dejarlo off**: PDFs con tablas simples (markitdown ya las hace
bien) — activar D11 introduce riesgo de meter `|` literales en prosa.

**Test**: `tests/test_clean_tables.py`.

---

## `footnotes` (D12)

**Objetivo**: limpiar footnotes `[^1]` orphans y `<sup>N</sup>` markup
que markitdown emite inconsistente entre formatos.

**Input**:
```
Texto con referencia<sup>1</sup> y otra [^2] sin definir.

1 Primer footnote aqui.
2 Segunda footnote alla.
```

**Output**:
```
Texto con referencia[^1] y otra [^2] sin definir.

[^1]: Primer footnote aqui.
[^2]: Segunda footnote alla.
```

**Qué reescribe**:
- `<sup>N</sup>` → `[^N]` (GitHub Flavored Markdown).
- Block de footnotes al final → syntax `[^N]: ...` (GFM spec).
- Footnotes definidas pero no referenciadas → preservadas (no las inventa).

**Qué NO toca** (false-positive guards):
- `<sup>` no numérico (ej. superíndices químicos `H<sub>2</sub>O` → H<sub>2</sub>O,
  preservados).
- Texto en code fences.
- Inline `[^1]` legítimamente referenciado en otro lado — no se duplica.

**Test**: `tests/test_clean_footnotes.py`.

---

## Cómo escribir un cleaner nuevo

1. Crear `src/capmd/clean/<nombre>.py` con una clase que herede de
   `Cleaner` (en `capmd.clean.cleaner.Cleaner`). Definir `name` y
   `apply(texto, ctx)`.
2. Implementar `apply` como **función pura** — sin I/O, sin estado.
3. Docstring que explique qué reescribe y qué NO toca (falso positivo).
4. Agregar el test en `tests/test_clean_<nombre>.py`.
5. Si el cleaner debe correr por default, registrarlo en
   `capmd.clean.pipeline.default_pipeline()`.
6. Actualizar la tabla resumen en este documento.

Si el cleaner es **opt-in**, va en el módulo pero NO en
`default_pipeline()`; el usuario lo activa con
`enabled = [..., "<nombre>"]`.
