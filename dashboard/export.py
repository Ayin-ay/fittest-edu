"""Compatibility shim over :mod:`evolution_archive`.

The archive module is the single implementation: one run is one
``archive/runs/*.tev.json`` file, and Markdown/CSV are views rendered from it.
This module keeps the old dashboard-facing names working so existing imports and
docs do not break, but it holds no logic of its own -- new code should import
``evolution_archive`` directly.
"""

from __future__ import annotations

try:  # Works both as ``dashboard.export`` and as a flat module.
    from evolution_archive import (
        ANALYSIS_PROMPT,
        ARCHIVE_DIR,
        FILE_SUFFIX,
        LEGACY_DIR,
        RUNS_DIR,
        STRATEGY_REFERENCE,
        build_document,
        delete_run,
        document_to_csv,
        document_to_json,
        document_to_markdown,
        latest_run,
        list_runs,
        load_document,
        load_run,
        rename_run,
        reproduce_run,
        save_run,
    )
except ImportError:  # pragma: no cover
    from ..evolution_archive import (  # type: ignore[no-redef]
        ANALYSIS_PROMPT,
        ARCHIVE_DIR,
        FILE_SUFFIX,
        LEGACY_DIR,
        RUNS_DIR,
        STRATEGY_REFERENCE,
        build_document,
        delete_run,
        document_to_csv,
        document_to_json,
        document_to_markdown,
        latest_run,
        list_runs,
        load_document,
        load_run,
        rename_run,
        reproduce_run,
        save_run,
    )

__all__ = [
    "ANALYSIS_PROMPT",
    "ARCHIVE_DIR",
    "FILE_SUFFIX",
    "LEGACY_DIR",
    "RUNS_DIR",
    "STRATEGY_REFERENCE",
    "build_document",
    "build_export_bundle",
    "bundle_to_csv",
    "bundle_to_json",
    "bundle_to_markdown",
    "delete_run",
    "document_to_csv",
    "document_to_json",
    "document_to_markdown",
    "latest_markdown_report",
    "latest_run",
    "list_runs",
    "load_document",
    "load_run",
    "rename_run",
    "reproduce_run",
    "save_markdown_report",
    "save_run",
]

# The canonical document is a superset of the old export bundle, so the old
# names simply forward to the archive implementation.
build_export_bundle = build_document
bundle_to_json = document_to_json
bundle_to_markdown = document_to_markdown
bundle_to_csv = document_to_csv
latest_markdown_report = latest_run


def save_markdown_report(
    sim,
    seed: int | None = None,
    generation: int | None = None,
    name: str | None = None,
    note: str | None = None,
):
    """Save the run as one canonical archive file and return its path.

    The Markdown report is no longer written to disk: it is a view of the
    archive file, rendered on demand via ``bundle_to_markdown``.
    """
    return save_run(sim, seed=seed, name=name, note=note)
