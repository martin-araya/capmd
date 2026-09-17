"""Markdown golden files de capmd (J2).

Cada snapshot es un archivo ``.md`` literal en ``tests/golden/<name>.md``
(en lugar del ``__snapshots__/<name>.ambr`` default de syrupy).

El ``MarkdownSnapshotExtension`` y el fixture override viven en
``tests/conftest.py`` (junto al resto de plumbing J2). Este modulo se
mantiene como package para que ``tests/golden/*.md`` tenga su propio
directorio versionado.
"""
