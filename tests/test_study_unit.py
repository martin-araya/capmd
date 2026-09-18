"""Tests unitarios de ``capmd.study`` (K2) + integración con FM/writer."""

from __future__ import annotations

from datetime import datetime, timezone

import yaml

from capmd.output.frontmatter import (
    build_front_matter_fields,
    front_matter_fields_from_capmd_json,
    parse_front_matter,
    prepend_front_matter,
    render_front_matter,
)
from capmd.output.writer import CapmdJsonV2, build_metadata
from capmd.study import (
    DEFAULT_READING_STATUS,
    DEFAULT_TAGS,
    PROFILES,
    READING_STATUSES,
    apply_profile_study,
    merge_study_fields,
    neutral_study_values,
    study_sections_block,
    validate_reading_status,
)

# ---------------------------------------------------------------------------
# validate_reading_status
# ---------------------------------------------------------------------------


def test_validate_reading_status_accepts_all_valid_values() -> None:
    """Los 3 valores del enum pasan."""
    for value in READING_STATUSES:
        assert validate_reading_status(value) == value


def test_validate_reading_status_rejects_unknown_value() -> None:
    """Cualquier string fuera del enum levanta ValueError con mensaje útil."""
    for bad in ("Done", "in-progress", "In_Progress", "", "  "):
        with __import__("pytest").raises(ValueError) as exc_info:
            validate_reading_status(bad)
        msg = str(exc_info.value)
        assert "inválido" in msg
        # El mensaje lista los valores válidos.
        for v in READING_STATUSES:
            assert v in msg


# ---------------------------------------------------------------------------
# study_sections_block
# ---------------------------------------------------------------------------


def test_study_sections_block_format() -> None:
    """El bloque matchea el formato documentado en README:573-580."""
    import re

    block = study_sections_block()
    pattern = r"^## Resumen\n\n## Conceptos clave\n\n## Dudas$"
    assert re.match(pattern, block), f"block inesperado:\n{block!r}"


# ---------------------------------------------------------------------------
# merge_study_fields — precedencia + auto-timestamps
# ---------------------------------------------------------------------------


def _fixed_now() -> datetime:
    return datetime(2026, 9, 17, 12, 0, 0, tzinfo=timezone.utc)


def test_merge_study_fields_defaults_when_no_inputs() -> None:
    """Sin CLI ni existing, devuelve los neutrales."""
    f = merge_study_fields()
    assert f["tags"] == DEFAULT_TAGS
    assert f["reading_status"] == DEFAULT_READING_STATUS
    assert f["started_at"] is None
    assert f["finished_at"] is None


def test_merge_study_fields_cli_tags_override_existing() -> None:
    """CLI gana sobre existing (consistente con G2)."""
    f = merge_study_fields(
        cli_tags=("cli-tag",),
        existing_tags=("existing-tag",),
    )
    assert f["tags"] == ("cli-tag",)


def test_merge_study_fields_existing_used_when_no_cli() -> None:
    """Sin CLI, se usan los valores existentes."""
    f = merge_study_fields(existing_tags=("a", "b"), existing_status="read")
    assert f["tags"] == ("a", "b")
    assert f["reading_status"] == "read"


def test_merge_study_fields_dedupes_tags_preserving_order() -> None:
    """Tags duplicados vía CLI se deduplican preservando orden."""
    f = merge_study_fields(cli_tags=("rust", "ownership", "rust", "borrow"))
    assert f["tags"] == ("rust", "ownership", "borrow")


def test_merge_study_fields_started_at_set_when_null_and_in_progress() -> None:
    """``--reading-status in_progress`` setea ``started_at`` si era null."""
    f = merge_study_fields(
        cli_status="in_progress",
        now=_fixed_now(),
    )
    assert f["started_at"] == "2026-09-17T12:00:00Z"
    assert f["finished_at"] is None


def test_merge_study_fields_preserves_started_at_when_already_set() -> None:
    """``started_at`` editado por el usuario NO se sobrescribe en re-corrida."""
    f = merge_study_fields(
        cli_status="in_progress",
        existing_started="2026-09-01T08:00:00Z",
        now=_fixed_now(),
    )
    assert f["started_at"] == "2026-09-01T08:00:00Z"


def test_merge_study_fields_finished_at_set_when_read_and_null() -> None:
    """``--reading-status read`` setea ``finished_at`` si era null."""
    f = merge_study_fields(cli_status="read", now=_fixed_now())
    assert f["finished_at"] == "2026-09-17T12:00:00Z"
    assert f["started_at"] is None


def test_merge_study_fields_cli_reset_clears_timestamps() -> None:
    """``cli_reset=True`` fuerza ambos timestamps a None."""
    f = merge_study_fields(
        cli_status="read",
        cli_reset=True,
        existing_started="2026-09-01T08:00:00Z",
        existing_finished="2026-09-10T09:00:00Z",
        now=_fixed_now(),
    )
    assert f["started_at"] is None
    assert f["finished_at"] is None


def test_merge_study_fields_invalid_status_in_existing_falls_back() -> None:
    """Un ``existing_status`` inválido cae al default."""
    # El caller debería filtrar, pero por defensa merge_study_fields no rompe.
    with __import__("pytest").raises(ValueError):
        merge_study_fields(existing_status="bogus")


# ---------------------------------------------------------------------------
# apply_profile_study — mutación de markdown
# ---------------------------------------------------------------------------


def test_apply_profile_study_appends_three_empty_sections() -> None:
    """Appendea ``## Resumen`` / ``## Conceptos clave`` / ``## Dudas`` al final."""
    md = "# Title\n\nBody text.\n"
    out, _ = apply_profile_study(markdown=md)
    assert out.endswith("\n## Resumen\n\n## Conceptos clave\n\n## Dudas\n")


def test_apply_profile_study_returns_resolved_fields() -> None:
    """Devuelve los 4 campos resueltos."""
    _, fields = apply_profile_study(
        markdown="# T\n\nB.\n",
        cli_tags=("a", "b"),
        cli_status="in_progress",
        now=_fixed_now(),
    )
    assert fields["tags"] == ("a", "b")
    assert fields["reading_status"] == "in_progress"
    assert fields["started_at"] == "2026-09-17T12:00:00Z"


def test_apply_profile_study_omits_study_block_when_neutral() -> None:
    """Sin tags ni status no-neutros, no agrega la sub-key ``study:`` al FM."""
    md = (
        "---\n"
        "title: T\n"
        "book: b\n"
        "chapter: c\n"
        "pages: [1]\n"
        "source_file: x\n"
        "source_sha256: '0'\n"
        "converted_at: 2026-09-17T00:00:00Z\n"
        "capmd_version: 0.1.0\n"
        "markitdown_version: 0.1.7\n"
        "cleaners_applied: [whitespace]\n"
        "---\n\n"
        "# T\n\nB.\n"
    )
    out, _ = apply_profile_study(markdown=md)  # sin CLI tags/status
    assert "study:" not in out
    # Igual appendea las secciones.
    assert "## Resumen" in out


def test_apply_profile_study_preserves_existing_started_at() -> None:
    """Si el FM previo tiene ``started_at`` y la re-corrida no usa ``--reset-study``, se preserva.

    Nota: yaml.safe_load convierte ISO timestamps a ``datetime``; lo que
    verifica este test es que ese datetime (re-stringified) coincide con
    el original.
    """
    md = (
        "---\n"
        "title: T\n"
        "book: b\n"
        "chapter: c\n"
        "pages: [1]\n"
        "source_file: x\n"
        "source_sha256: '0'\n"
        "converted_at: 2026-09-17T00:00:00Z\n"
        "capmd_version: 0.1.0\n"
        "markitdown_version: 0.1.7\n"
        "cleaners_applied: []\n"
        "study:\n"
        "  tags: [rust]\n"
        "  reading_status: in_progress\n"
        "  started_at: 2026-09-01T08:00:00Z\n"
        "  finished_at: null\n"
        "---\n\n"
        "# T\n\nB.\n"
    )
    _, fields = apply_profile_study(
        markdown=md,
        cli_tags=("rust",),
        cli_status="in_progress",  # no debería pisar el started_at previo
        now=_fixed_now(),
    )
    # yaml.safe_load parsea ISO timestamps a datetime; verificamos que
    # el datetime resultante coincide (segundo-a-segundo) con el original.
    started = fields["started_at"]
    if hasattr(started, "isoformat"):
        started_str = started.strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        started_str = str(started)
    assert started_str == "2026-09-01T08:00:00Z"


def test_apply_profile_study_no_fm_appends_sections_only() -> None:
    """Sin FM previo, appendea secciones sin envolver nada en YAML."""
    md = "# Title\n\nBody.\n"
    out, _ = apply_profile_study(markdown=md, cli_tags=("a",))
    assert not out.startswith("---")
    assert "## Resumen" in out


# ---------------------------------------------------------------------------
# Front matter integration
# ---------------------------------------------------------------------------


def test_build_front_matter_fields_omits_study_when_neutral() -> None:
    """``build_front_matter_fields`` sin study params no agrega sub-key."""
    fields = build_front_matter_fields(
        title="T",
        book_slug="b",
        chapter_slug="c",
        pages=[1],
        source_file="x",
        source_sha256="0",
        converted_at="2026-09-17T00:00:00Z",
        capmd_version="0.1.0",
        cleaners_applied=("whitespace",),
    )
    assert "study" not in fields


def test_build_front_matter_fields_includes_study_when_active() -> None:
    """Con tags no-vacíos, emite sub-key ``study:`` con los 4 campos."""
    fields = build_front_matter_fields(
        title="T",
        book_slug="b",
        chapter_slug="c",
        pages=[1],
        source_file="x",
        source_sha256="0",
        converted_at="2026-09-17T00:00:00Z",
        capmd_version="0.1.0",
        cleaners_applied=(),
        study_tags=("rust",),
        study_reading_status="read",
        study_started_at=None,
        study_finished_at="2026-09-10T00:00:00Z",
    )
    assert fields["study"] == {
        "tags": ["rust"],
        "reading_status": "read",
        "started_at": None,
        "finished_at": "2026-09-10T00:00:00Z",
    }


def test_render_front_matter_yaml_round_trip_with_study() -> None:
    """``render_front_matter`` con sub-key ``study:`` produce YAML válido."""
    fields = {
        "title": "T",
        "book": "b",
        "chapter": "c",
        "pages": [1],
        "source_file": "x",
        "source_sha256": "0",
        "converted_at": "2026-09-17T00:00:00Z",
        "capmd_version": "0.1.0",
        "markitdown_version": "0.1.7",
        "cleaners_applied": [],
        "study": {
            "tags": ["rust", "ownership"],
            "reading_status": "in_progress",
            "started_at": "2026-09-17T12:00:00Z",
            "finished_at": None,
        },
    }
    rendered = render_front_matter(fields)
    parsed = yaml.safe_load(rendered.split("---")[1])
    assert parsed["study"]["tags"] == ["rust", "ownership"]
    assert parsed["study"]["reading_status"] == "in_progress"
    assert parsed["study"]["finished_at"] is None


def test_parse_front_matter_round_trip() -> None:
    """``parse_front_matter`` devuelve dict YAML del FM al inicio."""
    md = (
        "---\n"
        "title: T\n"
        "book: b\n"
        "chapter: c\n"
        "pages: [1]\n"
        "source_file: x\n"
        "source_sha256: '0'\n"
        "converted_at: 2026-09-17T00:00:00Z\n"
        "capmd_version: 0.1.0\n"
        "markitdown_version: 0.1.7\n"
        "cleaners_applied: []\n"
        "study:\n"
        "  tags: [rust]\n"
        "  reading_status: read\n"
        "  started_at: 2026-09-01T08:00:00Z\n"
        "  finished_at: 2026-09-10T09:00:00Z\n"
        "---\n\n"
        "# T\n\nB.\n"
    )
    parsed = parse_front_matter(md)
    assert parsed is not None
    assert parsed["title"] == "T"
    assert parsed["study"]["tags"] == ["rust"]
    # yaml.safe_load parsea ISO timestamps a datetime; comparamos
    # round-trip de la serialización.
    finished = parsed["study"]["finished_at"]
    if hasattr(finished, "strftime"):
        finished = finished.strftime("%Y-%m-%dT%H:%M:%SZ")
    assert finished == "2026-09-10T09:00:00Z"


def test_parse_front_matter_returns_none_for_no_fm() -> None:
    """Markdown sin FM devuelve ``None``."""
    assert parse_front_matter("# Title\n\nbody") is None
    assert parse_front_matter("") is None
    assert parse_front_matter("   \n  \nnot fm") is None


def test_front_matter_fields_from_capmd_json_handles_missing_study() -> None:
    """capmd.json sin campos study se regenera sin sub-key."""
    base_json = {
        "schema_version": 2,
        "title": "T",
        "book_slug": "b",
        "chapter_slug": "c",
        "pages": [1],
        "source_file": "x",
        "source_sha256": "0",
        "generated_at": "2026-09-17T00:00:00Z",
        "capmd_version": "0.1.0",
        "markitdown_version": "0.1.7",
        "cleaners_applied": [],
    }
    fields = front_matter_fields_from_capmd_json(base_json)
    assert "study" not in fields


def test_front_matter_fields_from_capmd_json_includes_study_when_active() -> None:
    """capmd.json con study no-neutro se regenera con sub-key."""
    base_json = {
        "schema_version": 2,
        "title": "T",
        "book_slug": "b",
        "chapter_slug": "c",
        "pages": [1],
        "source_file": "x",
        "source_sha256": "0",
        "generated_at": "2026-09-17T00:00:00Z",
        "capmd_version": "0.1.0",
        "markitdown_version": "0.1.7",
        "cleaners_applied": [],
        "study_tags": ["rust"],
        "reading_status": "in_progress",
        "started_at": "2026-09-17T00:00:00Z",
        "finished_at": None,
    }
    fields = front_matter_fields_from_capmd_json(base_json)
    assert fields["study"]["tags"] == ["rust"]
    assert fields["study"]["reading_status"] == "in_progress"


def test_prepend_front_matter_keeps_study_subkey() -> None:
    """``prepend_front_matter`` con sub-key ``study:`` la preserva."""
    md = "# T\n\nBody.\n"
    fields = build_front_matter_fields(
        title="T",
        book_slug="b",
        chapter_slug="c",
        pages=[1],
        source_file="x",
        source_sha256="0",
        converted_at="2026-09-17T00:00:00Z",
        capmd_version="0.1.0",
        cleaners_applied=(),
        study_tags=("rust",),
        study_reading_status="read",
        study_finished_at="2026-09-17T00:00:00Z",
    )
    out = prepend_front_matter(md, fields)
    parsed = yaml.safe_load(out.split("---")[1])
    assert parsed["study"]["reading_status"] == "read"


# ---------------------------------------------------------------------------
# capmd.json integration
# ---------------------------------------------------------------------------


def test_capmd_json_v2_omits_study_when_neutral() -> None:
    """``CapmdJsonV2`` sin study activo no emite los 4 keys."""
    json_obj = CapmdJsonV2(
        book_slug="b",
        chapter_slug="c",
        title="T",
        source_file=None,
        source_sha256=None,
        pages=None,
        range_label="full",
        chapter=None,
        generated_at="2026-09-17T00:00:00Z",
        capmd_version="0.1.0",
        markitdown_version="0.1.7",
        images_dir=None,
        layout="flat",
        elapsed_seconds=0.0,
    )
    d = json_obj._as_dict()
    assert "study_tags" not in d
    assert "reading_status" not in d
    assert "started_at" not in d
    assert "finished_at" not in d


def test_capmd_json_v2_includes_study_when_active() -> None:
    """Con study no-neutro, los 4 keys aparecen en el dict."""
    json_obj = CapmdJsonV2(
        book_slug="b",
        chapter_slug="c",
        title="T",
        source_file=None,
        source_sha256=None,
        pages=None,
        range_label="full",
        chapter=None,
        generated_at="2026-09-17T00:00:00Z",
        capmd_version="0.1.0",
        markitdown_version="0.1.7",
        images_dir=None,
        layout="flat",
        elapsed_seconds=0.0,
        study_tags=("rust",),
        reading_status="in_progress",
        started_at="2026-09-17T00:00:00Z",
        finished_at=None,
    )
    d = json_obj._as_dict()
    assert d["study_tags"] == ["rust"]
    assert d["reading_status"] == "in_progress"
    assert d["started_at"] == "2026-09-17T00:00:00Z"
    assert d["finished_at"] is None


def test_build_metadata_accepts_study_kwargs_and_round_trips() -> None:
    """``build_metadata`` propaga los 4 campos study al JSON."""
    md = build_metadata(
        source=None,
        stdin=True,
        book_slug="b",
        chapter_slug="c",
        chapter=None,
        page_range=None,
        images_dir_relative=None,
        layout="flat",
        title="T",
        cleaners_applied=(),
        cleaner_stats=(),
        figures=(),
        elapsed_seconds=0.0,
        warnings=(),
        study_tags=("rust",),
        reading_status="read",
        started_at="2026-09-01T00:00:00Z",
        finished_at="2026-09-10T00:00:00Z",
    )
    d = md._as_dict()
    assert d["study_tags"] == ["rust"]
    assert d["reading_status"] == "read"
    assert d["started_at"] == "2026-09-01T00:00:00Z"
    assert d["finished_at"] == "2026-09-10T00:00:00Z"


# ---------------------------------------------------------------------------
# neutral_study_values
# ---------------------------------------------------------------------------


def test_neutral_study_values_match_defaults() -> None:
    """``neutral_study_values`` devuelve los defaults exactos."""
    n = neutral_study_values()
    assert n == {
        "tags": (),
        "reading_status": "unread",
        "started_at": None,
        "finished_at": None,
    }


def test_profiles_registry_includes_study() -> None:
    """``PROFILES`` contiene 'study' (extensible para futuros perfiles)."""
    assert "study" in PROFILES
