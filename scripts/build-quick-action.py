#!/usr/bin/env python3
"""Build the Quick Action ``.shortcut`` file from a Python definition.

Why this exists
---------------

``.shortcut`` files are binary plists with a hand-rolled action graph that
Shortcuts.app renders as a GUI.  No public CLI exposes ``create`` —
``shortcuts`` only knows ``run``/``list``/``view``/``sign`` — and Shortcuts.app's
AppleScript dictionary does not let us *insert* actions into a freshly created
shortcut.  So when the project needs a Quick Action it cannot be assembled at
install time: either the maintainer builds it once in the GUI and commits the
``shortcuts``-signed file, or we hand-roll the plist.

We hand-roll it.  The graph is intentionally small — a single ``Run Shell
Script`` whose body does *all* the UX work (prompts via ``osascript``, range
parsing, ``capmd`` invocation).  Keeping the action graph tiny avoids the
``is.workflow.actions.*`` schema-rot problem where each macOS release tweaks
the parameter shape of builtin actions.

Usage
-----
::

    python scripts/build-quick-action.py [output_path]

Default ``output_path`` is ``src/capmd/assets/Convert capmd chapter.shortcut``.

After running this script the file is a valid unsigned plist; Shortcuts.app
will install it on double-click.  Optionally::

    shortcuts sign --mode anyone --input <file> --output <signed_file>

produces a "anyone-can-install" signed variant.

Iteration tips
--------------

If you need to add actions (e.g. ``Set Variable``, ``Repeat with Each``):
build the analog shortcut in Shortcuts.app, then File → Export → Export as
File, then read the resulting plist with :mod:`plistlib` and diff against
what this script produces.  Don't try to guess the parameter shapes from
old GitHub gists — Apple has been known to add/rename keys between
shortcut versions and we want the action to keep working after macOS
updates.
"""

from __future__ import annotations

import argparse
import plistlib
import sys
import zlib
from pathlib import Path

# ---------------------------------------------------------------------------
# The embedded shell script invoked by the single Run Shell Script action.
# Keeps prompts, validation, and capmd invocation in one place so that the
# `.shortcut` plist stays trivial and the prompt UX is iterated in code, not
# in the GUI.
# ---------------------------------------------------------------------------

SHELL_SCRIPT = r'''#!/bin/zsh
# capmd Quick Action.
# Triggered from Finder's Quick Actions menu. Receives one or more file
# paths on stdin (one per line), prompts the user for a range and an
# output directory, then runs `capmd convert` for each PDF/EPUB/DOCX
# selected.

set -euo pipefail
emulate -L zsh

# Locate capmd (uv tool install puts it in ~/.local/bin; Homebrew in
# /opt/homebrew/bin or /usr/local/bin).
for candidate in "$HOME/.local/bin/capmd" /opt/homebrew/bin/capmd /usr/local/bin/capmd; do
  if [ -x "$candidate" ]; then
    capmd_cmd="$candidate"
    break
  fi
done
if [ -z "${capmd_cmd:-}" ]; then
  capmd_cmd="$(command -v capmd || true)"
fi
if [ -z "${capmd_cmd:-}" ]; then
  osascript <<'APPLESCRIPT' 2>/dev/null || true
display alert "capmd no encontrado" message "Instalalo con:
  uv tool install capmd

Luego corré de nuevo el Quick Action." as critical
APPLESCRIPT
  echo "ERROR: capmd no encontrado en PATH ni en ~/.local/bin, /opt/homebrew/bin, /usr/local/bin" >&2
  exit 127
fi

# Persist last values across runs (lives in the user's home; survives reboots).
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/capmd"
STATE_FILE="$STATE_DIR/quickaction-last.txt"
mkdir -p "$STATE_DIR" 2>/dev/null || true
last_range=""
last_dest=""
if [ -r "$STATE_FILE" ]; then
  last_range="$(sed -n '1p' "$STATE_FILE" 2>/dev/null || true)"
  last_dest="$(sed -n '2p' "$STATE_FILE" 2>/dev/null || true)"
fi
[ -z "$last_dest" ] && last_dest="$HOME/Downloads/capmd"

# Prompts via AppleScript (the only built-in modal that works from a
# non-foregrounded shell-script action).  Falls back to stdin if no GUI.
prompt_range() {
  local default="${1:-}"
  local r
  if command -v osascript >/dev/null 2>&1; then
    r="$(osascript -e "set T to text returned of (display dialog \"Rango o capítulo (ej: 3, 1-12, Ownership)\" default answer \"${default}\")" 2>/dev/null || true)"
    if [ -n "$r" ]; then print -r -- "$r"; return; fi
  fi
  printf "Rango o capítulo [%s]: " "$default" >&2
  IFS= read -r r || true
  print -r -- "$r"
}

prompt_dest() {
  local default="${1:-}"
  local d
  if command -v osascript >/dev/null 2>&1; then
    d="$(osascript -e "set T to text returned of (display dialog \"Carpeta de salida\" default answer \"${default}\")" 2>/dev/null || true)"
    if [ -n "$d" ]; then print -r -- "$d"; return; fi
  fi
  printf "Carpeta de salida [%s]: " "$default" >&2
  IFS= read -r d || true
  print -r -- "$d"
}

range="$(prompt_range "$last_range")"
dest="$(prompt_dest "$last_dest")"

# Persist (single line each).
{
  print -r -- "$range"
  print -r -- "$dest"
} > "$STATE_FILE" 2>/dev/null || true

mkdir -p "$dest" || { echo "ERROR: no pude crear $dest" >&2; exit 2; }

# Process each file passed on stdin (one path per line).
first_path=""
while IFS= read -r file; do
  [ -z "$file" ] && continue
  [ -z "$first_path" ] && first_path="$file"
  args=("$capmd_cmd" convert "$file" --out "$dest")
  if [ -n "$range" ]; then
    args+=(--pages "$range")
  fi
  echo "→ $("$capmd_cmd" "${args[@]}")" || { echo "capmd falló para $file" >&2; continue; }
done

# Reveal the output directory in Finder.
if [ -d "$dest" ]; then
  open -R "$dest" 2>/dev/null || open "$dest" 2>/dev/null || true
fi
osascript -e "display notification \"capmd: terminado\" with title \"capmd\"" 2>/dev/null || true
'''

# The same shell script, gzip-compressed, for embedding in the plist (keeps
# the file small + triggers Shortcuts.app's "detects a plain-text runner" UI
# hint that this shortcut is built around a shell script).
SHELL_SCRIPT_GZ = zlib.compress(SHELL_SCRIPT.encode("utf-8"))


def shell_script_action() -> dict:
    """Return the ``WFWorkflowAction`` dict for the single Run Shell Script.

    The action runs ``zsh`` and pipes the script body as the script.  Input
    comes from the Shortcut Input (magic variable); the script reads file
    paths on stdin which is how Shortcuts hands multi-file selections to
    shell actions.
    """
    return {
        "WFWorkflowActionIdentifier": "is.workflow.actions.runshellscript",
        "WFWorkflowActionParameters": {
            "WFShellActionShell": "/bin/zsh",
            "Script": {
                "Value": SHELL_SCRIPT,
                "WFSerializationType": "WFTextTokenAttachment",
                "WFTextTokenAttachment": {
                    "WFTextTokenType": "Text",
                },
            },
            "WFInput": {
                "Type": "Variable",
                "VariableName": "ShortcutInput",
                "VariableUUID": "01234567-89AB-CDEF-0123-456789ABCDEF",
                "WFSerializationType": "WFTextTokenAttachment",
            },
        },
    }


def build_shortcut_dict() -> dict:
    """Compose the top-level ``WFWorkflow*`` plist for the Quick Action."""
    return {
        "WFWorkflowClientVersion": "2300",
        "WFWorkflowClientRelease": "13.0",
        "WFWorkflowCompatibleVersions": ["13.0", "13.1", "13.2", "13.3", "13.4", "13.5", "14.0"],
        "WFWorkflowIcon": {
            "WFWorkflowIconStartColor": 1140850943,
            "WFWorkflowIconGlyphNumber": 59511,
        },
        "WFWorkflowInputContentItemClasses": [
            "WFAppStoreAppContentItem",
            "WFArticleContentItem",
            "WFContactContentItem",
            "WFiTunesProductContentItem",
            "WFLocationContentItem",
            "WFDictionaryContentItem",
            "WFMKMapItemContentItem",
            "WFNumberContentItem",
            "WFPhoneNumberContentItem",
            "WFRichTextContentItem",
            "WFSafariWebPageContentItem",
            "WFStringContentItem",
            "WFURLContentItem",
            "WFVCardContentItem",
            "WFWebArchiveContentItem",
        ],
        "WFWorkflowMinimumClientVersion": 600,
        "WFWorkflowMinimumClientRelease": "12.0",
        "WFWorkflowOutputContentItemClasses": [],
        "WFWorkflowTypes": [],
        "WFWorkflowHasIconInput": False,
        "WFWorkflowHasShortcutInputVariables": True,
        "WFWorkflowHasOutput": False,
        "WFWorkflowActions": [shell_script_action()],
        "WFWorkflowInputIdentifier": "ShortcutInput",
        "WFWorkflowImportQuestions": [],
        "WFWorkflowDisablesResultIndicators": False,
        "WFWorkflowIsDiscoverable": True,
        "WFWorkflowIsLatestVersion": True,
        "WFWorkflowNoInputIdentifier": "ShortcutInput",
        "WFWorkflowName": "Convert capmd chapter",
    }


def write_shortcut(path: Path) -> None:
    """Serialize :func:`build_shortcut_dict` to ``path`` as a binary plist."""
    d = build_shortcut_dict()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        plistlib.dump(d, fh, fmt=plistlib.FMT_BINARY)


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "output",
        nargs="?",
        default=str(
            Path(__file__).resolve().parent.parent
            / "src/capmd/assets/Convert capmd chapter.shortcut"
        ),
        help="Output .shortcut path (binary plist). Default: src/capmd/assets/...",
    )
    p.add_argument(
        "--check",
        action="store_true",
        help="Don't write; just assert the existing file equals what we'd build (smoke).",
    )
    args = p.parse_args(argv)
    out = Path(args.output)
    if args.check:
        if not out.exists():
            print(f"FAIL: {out} does not exist; nothing to check", file=sys.stderr)
            return 1
        expected = build_shortcut_dict()
        with out.open("rb") as fh:
            actual = plistlib.load(fh)
        if actual != expected:
            print(f"FAIL: {out} differs from build_shortcut_dict()", file=sys.stderr)
            return 2
        print(f"OK: {out} matches build_shortcut_dict()")
        return 0

    write_shortcut(out)
    size = out.stat().st_size
    print(f"wrote {out} ({size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
