# Formatos soportados

`capmd` hereda el soporte de [MarkItDown](https://github.com/microsoft/markitdown) para la conversión, más recortes propios para PDF/EPUB.

## Conversión (markitdown)

| Formato | Soporte | Notas                                                                              |
|---------|---------|------------------------------------------------------------------------------------|
| PDF     | ✅      | Texto, outline, headings heuristicas, imágenes (pypdfium2)                          |
| EPUB    | ✅      | Texto, spine/nav, sin imágenes (ebooklib parsea XHTML pero no extrae media)         |
| DOCX    | ✅      | Texto + imágenes embebidas                                                          |
| PPTX    | ✅      | Texto + imágenes; OCR de imágenes vía `markitdown-ocr` plugin (J5 opt-in)          |
| XLSX    | ✅      | Solo texto (las sheets se concatenan)                                              |
| HTML    | ✅      | Local o remoto (URL HTTP); la descripción de imágenes via LLM es opcional            |
| CSV/JSON/XML | ✅ | Texto plano                                                                        |
| Imágenes (JPG/PNG) | ✅ | OCR via `markitdown-ocr` plugin                                                  |
| Audio (MP3/WAV) | ✅ | Transcripción via `markitdown[audio-transcription]`                              |
| YouTube URL | ✅ | Transcripción via `markitdown[youtube-transcription]`                              |
| ZIP     | ✅      | Recorre los archivos internos y aplica markitdown a cada uno                        |

## Recorte por capítulo

| Formato | Recorte           | Notas                                                                              |
|---------|-------------------|------------------------------------------------------------------------------------|
| PDF     | ✅ outline + heurística | Outline embebido (PDF spec); fallback heurístico por font size + keyword `Chapter` |
| EPUB    | ✅ spine/nav      | ebooklib parsea spine + nav para detectar capítulos                                 |
| DOCX/PPTX/XLSX | ❌         | Sin concepto de "capítulo". `capmd` convierte el archivo completo                 |
| HTML    | ❌                | Mismo, sin capítulo. Para long-form, pre-procesar con pandoc o similar             |
| Otros   | ❌                | Conversión full-file                                                               |

## Limitaciones

### PDF escaneados

Si el PDF es raster (sin texto embebido), el output será vacío. Soluciones:

1. **OCR via `markitdown-ocr`**: `uv pip install 'markitdown[all]'` + enable plugins (`--use-plugins`).
2. **`ocrmypdf` como pre-procesador**: `ocrmypdf in.pdf out.pdf --force-ocr` antes de `capmd convert`.
3. **Commercial OCR**: Google Document AI, AWS Textract, etc. Pre-procesar el PDF antes de capmd.

### EPUB con DRM

EPUBs con DRM (Adobe Digital Editions, etc.) NO se pueden convertir sin
des-protegerlos primero. `capmd` no incluye un DRM remover (legal issues).
Usar [dedrm](https://github.com/apprenticeharper/DeDRM_tools) o similar.

### Imágenes en EPUB

Ebooklib parsea el XHTML pero no extrae media embebido. Para capítulos de
EPUB con figuras, abrir el EPUB en Calibre y exportarlo a PDF primero.

### Tablas complejas

Markitdown maneja GFM tables razonablemente bien en PDFs con texto, pero
en escaneados las celdas se rompen. Activar `clean.tables` solo si es
necesario (es off por default).

### Code blocks con syntax highlighting

`capmd` envuelve el código en fences con el lenguaje detectado (python,
rust, bash, etc.) pero el highlighting final depende del renderer
(Obsidian, GitHub, VS Code). Sin hl por defecto — usar `pygmentize` o
`shiki` en el lado del consumidor.

### Lenguajes no-Inglés

Los cleaners D3 (hyphens) y D9 (lists) usan heurísticas calibradas para
Inglés + Español. Para libros en Francés, Alemán, Japonés, etc., el
cleaner puede sobre-corregir. Recomendación: test en un capítulo
chico y revisar `capmd.json:warnings`.

### Charset detection

Markitdown detecta charset via `chardet`. Para PDFs viejos con encoding
raro, el resultado puede tener caracteres mal interpretados. Pre-procesar
con `pdftotext -enc UTF-8 in.pdf out.txt` antes.
