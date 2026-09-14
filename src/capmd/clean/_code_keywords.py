"""Keywords regex para inferencia de lenguaje en code blocks.

Cada entrada es una tupla de patrones. ``infer_language`` en
:mod:`capmd.clean.code_blocks` cuenta matches y devuelve el lenguaje
con más hits sobre las primeras líneas del bloque.
"""

from __future__ import annotations

import re

__all__ = ["LANGUAGE_KEYWORDS"]

LANGUAGE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "rust": (
        r"\bfn\b",
        r"\blet\s+mut\b",
        r"\bimpl\b",
        r"->",
        r"::",
        r"\bpub\b",
        r"\bmatch\b",
        r"\benum\b",
        r"\bstruct\b",
    ),
    "go": (
        r"\bfunc\b",
        r"\bpackage\b",
        r"\bimport\b",
        r":=",
        r"\bdefer\b",
        r"\bchan\b",
        r"\bgoroutine\b",
    ),
    "python": (
        r"\bdef\b",
        r"\bfrom\b",
        r"\bclass\b",
        r"\bprint\(",
        r"\bself\b",
        r"if __name__",
        r"\belif\b",
        r"\bpass\b",
    ),
    "javascript": (
        r"\bfunction\b",
        r"\bconst\b",
        r"\bvar\b",
        r"=>",
        r"\bconsole\.",
        r"\brequire\(",
        r"\bdocument\.",
    ),
    "typescript": (
        r"\binterface\b",
        r"\btype\b",
        r":\s*(string|number|boolean|void)\b",
        r"\bas\b",
        r"\benum\b",
    ),
    "c": (
        r"#include",
        r"\bprintf\(",
        r"\bint\s+main\b",
        r"\bvoid\b",
        r"#define",
        r"\bNULL\b",
    ),
    "cpp": (
        r"\bstd::",
        r"\bcout\b",
        r"\btemplate\b",
        r"\bnullptr\b",
        r"\bnamespace\b",
        r"->",
    ),
    "java": (
        r"\bpublic\s+class\b",
        r"\bpublic\s+static\b",
        r"\bvoid\s+main\b",
        r"System\.out",
        r"\bnew\s+\w+\(",
    ),
    "bash": (
        r"^#!.*sh",
        r"\becho\b",
        r"\bif\s*\[",
        r"\bfi\b",
        r"\bdone\b",
        r"\$\{?",
    ),
    "sql": (
        r"\bSELECT\b",
        r"\bFROM\b",
        r"\bWHERE\b",
        r"\bINSERT\s+INTO\b",
        r"\bUPDATE\b",
        r"\bCREATE\s+TABLE\b",
        r"\bJOIN\b",
    ),
}

_COMPILED_KEYWORDS: dict[str, tuple[re.Pattern[str], ...]] = {
    lang: tuple(re.compile(p) for p in patterns) for lang, patterns in LANGUAGE_KEYWORDS.items()
}


def get_compiled_keywords() -> dict[str, tuple[re.Pattern[str], ...]]:
    return _COMPILED_KEYWORDS
