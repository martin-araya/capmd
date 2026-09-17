# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [unreleased]

### Chores

- bootstrap J3: add `cliff.toml`, `CHANGELOG.md`, `scripts/hooks/post-tag`, `scripts/bump-version.sh`.

## [0.1.0] - Initial alpha

First tagged release of `capmd`. Phase A through J2 closed.

### Features

- **A** Project scaffold: `pyproject.toml` (hatchling, Python ≥3.10, entry point `capmd`),
  editable install via `uv pip install -e '.[dev]'`.
- **A** Typer CLI with `version`, `--verbose`, exit codes 1–5 via `CapmdError` hierarchy.
- **B** `markitdown` engine wrapper with `convert_path` / `convert_stream` (no `convert()`).
- **B** Format detection and extras validation (PDF, EPUB, DOCX, PPTX, XLSX, HTML).
- **B** `capmd convert` end-to-end: stdout or `-o`, stdin via `convert_stream` with `--ext`.
- **B** Size + page-count limits, timeout via `signal.alarm`, raw snapshot via `--keep-raw`.
- **C** Outline parsing (`pypdf`), chapter slicing (`--pages`, `--chapter`, `--page-offset`).
- **C** Heuristic chapter detection when no outline present.
- **C** EPUB chapter slicing via spine/nav.
- **D** Cleaner pipeline: whitespace → dehyphenation → headers → page numbers → headings →
  single-h1 → code blocks → lists → tables → footnotes → paragraph joins.
- **E** Image extraction (pypdfium2) with filtering (logo dedup, background coverage).
- **E** Stable naming (`fig-CC-NN.<ext>`), caption detection, `markitdown-ocr` plugin.
- **F** Output tree (book/chapter), YAML front matter, per-section `--split h2` split,
  inline `--toc` injection, quality report (`--strict` exits 8 on warnings),
  `--dry-run`, F8 `--force` / `--suffix`.
- **G** TOML config in `~/.config/capmd/config.toml` with project-global precedence,
  `CAPMD_*` env vars, per-book profiles with sha256 auto-match.
- **G** `capmd config init` (starter TOML with `[cleaners]` and `[books]` blocks) and
  `capmd config show` (effective config with source attribution).
- **G** Auto-registry of converted books by sha256 with cached outline.
- **H** Progress bars via rich, `capmd batch` with subprocess parallelism,
  `capmd inspect` (text vs scanned, outline, fonts, headers),
  `--install-completion` for zsh/bash/fish/pwsh, `--open` for editor launch.
- **I** `uv tool install capmd` (verified via `scripts/verify-install.sh`).
- **I** macOS Finder Quick Action (`capmd setup quick-action`).
- **I** LaunchAgent watcher (`capmd watch` + `capmd setup launch-agent`) for inbox folders.
- **I** Homebrew tap (`Formula/capmd.rb`) with `scripts/build-bottles.sh` and
  `scripts/release.sh` for one-shot Homebrew bottle releases.

### Quality

- **J1** Coverage gate at 90% (`--cov-fail-under=90`); 1732 tests pass.
- **J2** Golden file regression suite (14 `.md` snapshots in `tests/golden/`).

[unreleased]: https://github.com/martin-araya/capmd/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/martin-araya/capmd/releases/tag/v0.1.0
