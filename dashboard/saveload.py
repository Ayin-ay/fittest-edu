"""Persist and restore The Fittest runs.

Saves go through :mod:`evolution_archive`, so there is exactly one on-disk
format: ``archive/runs/*.tev.json``, stamped with both the schema version and
the engine version. This module only keeps the dashboard's vocabulary
(``save_simulation`` / ``list_saved_simulations`` / ...) and still accepts the
older share-summary and full-save payloads when a user uploads one.
"""

from __future__ import annotations

import json
from pathlib import Path

try:  # Import works both as ``dashboard.saveload`` and as a flat module.
    from evolution_archive import (
        ARCHIVE_DIR,
        FILE_SUFFIX,
        RUNS_DIR,
        delete_run,
        list_runs,
        load_document,
        load_run,
        rename_run,
        reproduce_run,
        save_run,
    )
    from trust_evolution_simulation import (
        ENGINE_VERSION,
        RUN_SCHEMA_VERSION,
        TrustEvolution,
    )
except ImportError:  # pragma: no cover
    from ..evolution_archive import (  # type: ignore[no-redef]
        ARCHIVE_DIR,
        FILE_SUFFIX,
        RUNS_DIR,
        delete_run,
        list_runs,
        load_document,
        load_run,
        rename_run,
        reproduce_run,
        save_run,
    )
    from ..trust_evolution_simulation import (  # type: ignore[no-redef]
        ENGINE_VERSION,
        RUN_SCHEMA_VERSION,
        TrustEvolution,
    )

# Kept for callers that still reference the historical location. New saves never
# appear here; the folder is archived into ``archive/legacy/``.
SAVE_DIR = RUNS_DIR


def save_simulation(
    sim: TrustEvolution,
    name: str,
    seed: int | None = None,
    initial_encodings: list[str] | None = None,
    initial_sizes: dict[str, int] | None = None,
    note: str | None = None,
) -> dict:
    """Write the canonical archive file and return a ``meta`` summary."""
    path = save_run(
        sim,
        seed=seed,
        name=name,
        note=note,
        initial_encodings=initial_encodings,
        initial_sizes=initial_sizes,
    )
    doc = load_document(path)
    return {
        "name": doc["name"],
        "filename": path.name,
        "file": str(path),
        "saved_at": doc["created_at"],
        "created_at": doc["created_at"],
        "seed": doc["summary"].get("seed"),
        "generations": doc["summary"].get("generations", 0),
        "surviving_species": doc["summary"].get("surviving_species"),
        "terminated_by": doc["summary"].get("terminated_by"),
        "engine_version": doc.get("engine_version"),
        "schema_version": doc.get("schema_version"),
    }


def list_saved_simulations() -> list[dict]:
    """List canonical runs, newest first."""
    return list_runs()


def load_simulation_from_file(filename: str) -> TrustEvolution:
    """Load ``archive/runs/<filename>`` (a bare name or a full path)."""
    path = Path(filename)
    if not path.exists():
        candidate = RUNS_DIR / filename
        if not candidate.name.endswith(FILE_SUFFIX):
            candidate = RUNS_DIR / f"{filename}{FILE_SUFFIX}"
        path = candidate
    return load_run(path)


def rename_saved(filename: str, new_name: str) -> Path:
    path = Path(filename)
    if not path.exists():
        candidate = RUNS_DIR / filename
        if not candidate.name.endswith(FILE_SUFFIX):
            candidate = RUNS_DIR / f"{filename}{FILE_SUFFIX}"
        path = candidate
    return rename_run(path, new_name)


def delete_saved(filename: str) -> None:
    path = Path(filename)
    if not path.exists():
        candidate = RUNS_DIR / filename
        if not candidate.name.endswith(FILE_SUFFIX):
            candidate = RUNS_DIR / f"{filename}{FILE_SUFFIX}"
        path = candidate
    delete_run(path)


def build_summary(
    sim: TrustEvolution,
    seed: int | None,
    initial_encodings: list[str] | None = None,
    initial_sizes: dict[str, int] | None = None,
) -> dict:
    """A small, portable summary that reproduces the run by re-simulating.

    Prefer the canonical archive file (``save_simulation``) -- it keeps the full
    state and the analysis views. This summary exists only for sharing a
    reproduction recipe, and is stamped with the engine version so the receiver
    can tell whether their engine will produce the same trajectory.
    """
    return {
        "format": "trust-evolution-share-summary",
        "schema_version": RUN_SCHEMA_VERSION,
        "engine_version": ENGINE_VERSION,
        "seed": seed,
        "generations": sim.generation,
        "initial_encodings": initial_encodings,
        "initial_sizes": initial_sizes,
    }


def load_simulation_from_data(data: dict) -> TrustEvolution:
    """Rebuild a run from any accepted payload.

    Order matters: the canonical archive is checked first, then the older full
    save shape, then a bare share summary which has to be re-simulated.
    """
    if data.get("format") == "trust-evolution-run":
        state = data["state"]
        from evolution_archive import _species_from_dict  # local: internal helper

        sim = TrustEvolution(seed=0)
        sim.generation = data["summary"]["generations"]
        from evolution_archive import _rng_state_from_list

        sim.rng.setstate(_rng_state_from_list(state["rng_state"]))
        sim.species = [_species_from_dict(item) for item in state["final_species"]]
        sim.history = state["history"]
        sim.fitness_history = state["fitness_history"]
        from trust_evolution_simulation import EvolutionEvent, GenerationRecord

        sim.events = [EvolutionEvent(**event) for event in state["events"]]
        sim.generation_records = [
            GenerationRecord(
                generation=item["generation"],
                species_data=item["species_data"],
                average_fitness=item["average_fitness"],
                events=[EvolutionEvent(**event) for event in item["events"]],
                matchup_matrix=item["matchup_matrix"],
            )
            for item in state["generation_records"]
        ]
        return sim
    if {"rng_state", "history", "generation_records", "final_species"} <= set(data):
        from evolution_archive import _rng_state_from_list, _species_from_dict
        from trust_evolution_simulation import EvolutionEvent, GenerationRecord

        sim = TrustEvolution(seed=0)
        sim.generation = data.get("meta", {}).get("generations", 0)
        sim.rng.setstate(_rng_state_from_list(data["rng_state"]))
        sim.species = [_species_from_dict(item) for item in data["final_species"]]
        sim.history = data["history"]
        sim.fitness_history = data["fitness_history"]
        sim.events = [EvolutionEvent(**event) for event in data["events"]]
        sim.generation_records = [
            GenerationRecord(
                generation=item["generation"],
                species_data=item["species_data"],
                average_fitness=item["average_fitness"],
                events=[EvolutionEvent(**event) for event in item["events"]],
                matchup_matrix=item["matchup_matrix"],
            )
            for item in data["generation_records"]
        ]
        return sim
    if data.get("format") == "trust-evolution-share-summary" or (
        "seed" in data and "generations" in data
    ):
        engine = data.get("engine_version")
        if engine and engine != ENGINE_VERSION:
            raise ValueError(
                f"该分享摘要由引擎 {engine} 生成，当前引擎为 {ENGINE_VERSION}，"
                "重跑不会得到相同轨迹。"
            )
        seed = data.get("seed")
        generations = int(data.get("generations") or 0)
        simulation = TrustEvolution(
            seed=seed,
            initial_encodings=data.get("initial_encodings"),
            initial_sizes=data.get("initial_sizes"),
        )
        for _ in range(generations):
            if not simulation.species:
                break
            simulation.step()
        return simulation
    raise ValueError(
        "无法识别的文件：请上传统一存档（archive/runs/*.tev.json）或旧版分享摘要 JSON。"
    )
