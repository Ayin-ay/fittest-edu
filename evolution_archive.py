"""The single place a run of The Fittest is written to or read from disk.

One run equals one file: ``archive/runs/<name>_s<seed>_g<gen>_<stamp>.tev.json``.
There is no second format and no side-car report. Markdown and CSV are *views*
rendered from that one file on demand (``document_to_markdown`` /
``document_to_csv``); they are never stored separately, so they can never drift
out of sync with the data.

The document is written to serve two readers at once:

* an **AI or analyst** reads ``summary`` + ``rules`` + ``analysis`` and gets the
  parameters, the strategy encoding reference, per-generation population and
  fitness matrices, the event timeline, lineages and derived diversity /
  dominance metrics without recomputing anything;
* a **replay** uses ``reproduce`` (seed plus initial conditions) to re-simulate,
  or ``state`` -- which carries the RNG state and every recorded generation --
  to rebuild the exact run and continue it.

Two versions are stamped on every document:

``schema_version``
    the layout of this file, used to decide how to read it;
``engine_version``
    which engine produced the trajectory. A seed only reproduces within one
    engine version, so an archive saved before a rule or bookkeeping change is
    marked as such instead of silently failing to replay.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

try:  # Works as a top-level module and as ``dashboard.evolution_archive``.
    from trust_evolution_simulation import (
        ALPHA_ALLOCATE,
        ALPHA_INVASION,
        ENGINE_VERSION,
        EXTINCTION_FITNESS_RATIO,
        EXTINCTION_SIZE,
        EXTINCTION_STREAK,
        MAX_MUTATION_ATTEMPTS,
        MUTATION_MIN_SIZE,
        MUTATION_WEIGHTS,
        PAYOFFS,
        RUN_SCHEMA_VERSION,
        STAGNATION_GENERATIONS,
        STAGNATION_SEATS,
        SUBSPECIES_EXTINCTION_STREAK,
        SUBSPECIES_MIN_RATIO,
        SUBSPECIES_MIN_SIZE,
        SUBSPECIES_STALL_GENERATIONS,
        TOTAL_CAPACITY,
        TURNS_PER_MATCH,
        EvolutionEvent,
        GenerationRecord,
        Species,
        Subspecies,
        TrustEvolution,
        mutation_probability,
    )
except ImportError:  # pragma: no cover
    from ..trust_evolution_simulation import (
        ALPHA_ALLOCATE,
        ALPHA_INVASION,
        ENGINE_VERSION,
        EXTINCTION_FITNESS_RATIO,
        EXTINCTION_SIZE,
        EXTINCTION_STREAK,
        MAX_MUTATION_ATTEMPTS,
        MUTATION_MIN_SIZE,
        MUTATION_WEIGHTS,
        PAYOFFS,
        RUN_SCHEMA_VERSION,
        STAGNATION_GENERATIONS,
        STAGNATION_SEATS,
        SUBSPECIES_EXTINCTION_STREAK,
        SUBSPECIES_MIN_RATIO,
        SUBSPECIES_MIN_SIZE,
        SUBSPECIES_STALL_GENERATIONS,
        TOTAL_CAPACITY,
        TURNS_PER_MATCH,
        EvolutionEvent,
        GenerationRecord,
        Species,
        Subspecies,
        TrustEvolution,
        mutation_probability,
    )

FORMAT_NAME = "trust-evolution-run"
FILE_SUFFIX = ".tev.json"

ROOT = Path(__file__).resolve().parent
ARCHIVE_DIR = ROOT / "archive"
RUNS_DIR = ARCHIVE_DIR / "runs"
LEGACY_DIR = ARCHIVE_DIR / "legacy"


STRATEGY_REFERENCE = """\
一条策略编码由最多四个槽位用 "+" 拼接：[默认槽]+[触发槽1]+[触发槽2]+[修正槽]。
- 默认槽：S{N} 前 N 轮背叛随后合作（S0 永久合作，SM 永久背叛）；F{N}-{M} 合作 N 轮、背叛 M 轮循环；
  T{N}-{M} 背叛 N 轮、合作 M 轮循环；D{N} 跟随对手历史多数（参数 0/1 为平局默认）；
  AD{N} 反向跟随；W 赢留输变；BS{N} 最后 N 轮背叛。
- 触发槽：P{A}-{B} 累计"自己 C 对手 D"达 A 次后背叛 B 轮；H{A}-{B} 累计"自己 D 未被报复"达 A 次后背叛 B 轮；
  R{A}-{B} 对手最近 A 轮全 D 则背叛 B 轮；B{A}-{B} 双方最近 A 轮全 D 则求和、输出 C 共 B 轮；
  K{A}-{B} 对手最近连续 A 轮全 C 则合作 B 轮；RC{A}-{B} 最近 A 轮出现对手 D→C 则合作 B 轮。
- 修正槽：M{N} 所有历史统计只看最近 N 轮；C{N} 以 N*10% 概率翻转（C{N}-D/C{N}-C 限定方向）；
  RPT{A}-{B} 自己最近 A 轮出过 D 则强制合作 B 轮。
- 参数 B/M：数字表示持续 B 轮，M 表示持续到本局结束。
策略只能读取双方已完成回合的实际行为（C/D），无法读取对手编码或内部状态。
"""

ANALYSIS_PROMPT = """\
你是一位演化博弈与复杂系统分析专家。下面是一份"信任演化"（迭代囚徒困境 + 物种/亚种分化）
模拟的完整存档。请基于数据完成：
1. 概括整体演化趋势（种群规模、适应度、多样性的变化方向与阶段）；
2. 找出关键转折点，并结合事件（亚种生成 ◇、亚种独立 ★、物种灭绝 ×、亚种淘汰 ✕、手动注入 ＋）解释成因；
3. 分析哪些策略或策略家族占据优势、其取胜机制（对局矩阵在 state.generation_records[].matchup_matrix），
   并与 Axelrod 经典结论（如"以牙还牙"的善意/报复/宽容）对照异同；
4. 评估"善意、报复、宽容"在本生态系统中的实际作用；
5. 指出值得进一步验证的假设、异常或数据局限。
注意：manual injection 事件表示该策略是人为注入的，不是演化产生的，分析时不可当作"演化胜出"。
请引用具体代数与策略编码作为证据，避免空泛结论。
"""

HOW_TO_READ = """\
这是一次迭代囚徒困境 + 物种/亚种分化的演化模拟存档（单一 JSON 主档）。
- summary：seed、代数、存活物种数、结束方式，以及产生该轨迹的引擎版本。
- reproduce：复现所需的最小输入（seed + 初始条件 + 代数），同 engine_version 下可完全重放。
- rules：全部规则常量与收益矩阵；strategy_encoding_reference 是编码词典。
- analysis：预派生视图，AI 可直接读取。
  · encodings 是列顺序；population_matrix 行=代数、列=encodings 下标，值为该代规模。
  · fitness_matrix 为对应混合适应度（亚种为其自身适应度）。所有规模之和恒为 100。
  · generation_summary 逐代给总规模/存活物种/平均适应度/事件标记。
  · lineages 给出每个编码的来源、父代、诞生/独立/灭绝代数、峰值与最终规模。
  · derived.diversity 为 Shannon/Simpson，derived.dominance 为逐代优势物种。
- state：完整可回放状态。generation_records[].matchup_matrix 是该代每对策略的平均得分
  （行=本方，列=对方）；rng_state 允许从当前代精确续跑。
"""


def _git_revision() -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    revision = completed.stdout.strip()
    return revision or None


def _rng_state_to_list(rng) -> list:
    return list(rng.getstate())


def _rng_state_from_list(state_list: list):
    def collapse(value):
        if isinstance(value, list):
            return tuple(collapse(item) for item in value)
        return value

    return tuple(collapse(item) for item in state_list)


def _safe_name(name: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\s]+', "_", (name or "").strip())
    cleaned = cleaned.strip("._")
    return cleaned or "run"


# --------------------------------------------------------------------------- #
# analysis views
# --------------------------------------------------------------------------- #
def ordered_encodings(sim: TrustEvolution) -> list[str]:
    all_encodings = {encoding for snapshot in sim.history for encoding in snapshot}
    birth = {
        encoding: next(
            (
                event.generation
                for event in sim.events
                if event.encoding == encoding
                and event.event in {"subspecies_birth", "subspecies_independent"}
            ),
            0,
        )
        for encoding in all_encodings
    }
    return sorted(all_encodings, key=lambda encoding: (birth[encoding], encoding))


def _fitness_row(record) -> dict[str, float]:
    row: dict[str, float] = {}
    for encoding, data in record.species_data.items():
        row[encoding] = round(float(data.get("mixed_fitness", 0.0)), 3)
        subspecies = data.get("subspecies")
        if subspecies:
            row[subspecies["encoding"]] = round(
                float(subspecies.get("fitness", 0.0)), 3
            )
    return row


def _lineages(sim: TrustEvolution, ordered: list[str]) -> list[dict]:
    birth: dict[str, int] = {}
    parent: dict[str, str | None] = {}
    independence: dict[str, int] = {}
    extinction: dict[str, int] = {}
    for event in sim.events:
        if event.event in {"subspecies_birth", "subspecies_independent"}:
            birth.setdefault(event.encoding, event.generation)
            parent.setdefault(event.encoding, event.parent_encoding)
        if event.event == "subspecies_independent":
            independence[event.encoding] = event.generation
        if event.event in {"extinction", "subspecies_extinction"}:
            extinction[event.encoding] = event.generation

    rows: list[dict] = []
    for encoding in ordered:
        sizes = [snapshot.get(encoding, 0) for snapshot in sim.history]
        present = [gen for gen, size in enumerate(sizes) if size > 0]
        rows.append(
            {
                "encoding": encoding,
                "origin": "subspecies" if encoding in birth else "initial",
                "parent": parent.get(encoding),
                "birth_generation": present[0] if present else birth.get(encoding, 0),
                "independence_generation": independence.get(encoding),
                "extinction_generation": extinction.get(encoding),
                "last_seen_generation": present[-1] if present else None,
                "peak_size": max(sizes) if sizes else 0,
                "final_size": sizes[-1] if sizes else 0,
                "currently_subspecies": encoding in birth
                and encoding not in independence,
            }
        )
    return rows


def _diversity(sim: TrustEvolution) -> list[dict]:
    rows: list[dict] = []
    for generation, snapshot in enumerate(sim.history):
        sizes = [size for size in snapshot.values() if size > 0]
        total = sum(sizes)
        if total == 0:
            rows.append(
                {"generation": generation, "species_count": 0, "shannon": 0.0, "simpson": 0.0}
            )
            continue
        proportions = [size / total for size in sizes]
        import math

        rows.append(
            {
                "generation": generation,
                "species_count": len(sizes),
                "shannon": round(-sum(p * math.log(p) for p in proportions), 4),
                "simpson": round(1 - sum(p * p for p in proportions), 4),
            }
        )
    return rows


def _dominance(sim: TrustEvolution, ordered: list[str]) -> list[dict]:
    rows: list[dict] = []
    for generation, snapshot in enumerate(sim.history):
        items = [
            (encoding, snapshot.get(encoding, 0))
            for encoding in ordered
            if snapshot.get(encoding, 0) > 0
        ]
        if not items:
            rows.append({"generation": generation, "dominant": None, "share": 0.0})
            continue
        dominant, size = max(items, key=lambda item: item[1])
        total = sum(value for _, value in items)
        rows.append(
            {"generation": generation, "dominant": dominant, "share": round(size / total, 4)}
        )
    return rows


def _event_marks(sim: TrustEvolution, generation: int) -> str:
    marks = {
        "subspecies_birth": "◇",
        "subspecies_independent": "★",
        "extinction": "×",
        "subspecies_extinction": "✕",
        "injection": "＋",
    }
    return "".join(
        marks.get(event.event, "") for event in sim.events if event.generation == generation
    )


def build_analysis(sim: TrustEvolution) -> dict:
    """Pre-derived, AI-friendly view of a run. Never stored as its own file."""
    ordered = ordered_encodings(sim)
    generation_summary = []
    for generation, snapshot in enumerate(sim.history):
        record = sim.generation_records[generation]
        living = sum(
            1
            for data in record.species_data.values()
            if data.get("population_size", 0) > 0
        )
        generation_summary.append(
            {
                "generation": generation,
                "total_population": int(sum(snapshot.values())),
                "species_count": living,
                "average_fitness": round(record.average_fitness, 3),
                "event_marks": _event_marks(sim, generation),
                "events": [
                    {
                        "event": event.event,
                        "encoding": event.encoding,
                        "parent_encoding": event.parent_encoding,
                    }
                    for event in sim.events
                    if event.generation == generation
                ],
            }
        )

    from collections import Counter

    return {
        "encodings": ordered,
        "population_matrix": [
            [int(snapshot.get(encoding, 0)) for encoding in ordered]
            for snapshot in sim.history
        ],
        "fitness_matrix": [_fitness_row(record) for record in sim.generation_records],
        "generation_summary": generation_summary,
        "events": [asdict(event) for event in sim.events],
        "lineages": _lineages(sim, ordered),
        "final_state": [asdict(item) for item in sim.species],
        "derived": {
            "diversity": _diversity(sim),
            "dominance": _dominance(sim, ordered),
            "event_counts": dict(Counter(event.event for event in sim.events)),
        },
    }


def build_rules() -> dict:
    return {
        "population_capacity": TOTAL_CAPACITY,
        "turns_per_match": TURNS_PER_MATCH,
        "payoffs": {
            "cooperate_cooperate": list(PAYOFFS[("C", "C")]),
            "cooperate_defect": list(PAYOFFS[("C", "D")]),
            "defect_cooperate": list(PAYOFFS[("D", "C")]),
            "defect_defect": list(PAYOFFS[("D", "D")]),
        },
        "allocation": {
            "ALPHA_ALLOCATE": ALPHA_ALLOCATE,
            "note": "下一代规模 = 当代规模 * (ALPHA_ALLOCATE + (1-ALPHA_ALLOCATE) * 适应度/平均适应度)",
        },
        "extinction": {
            "EXTINCTION_SIZE": EXTINCTION_SIZE,
            "EXTINCTION_STREAK": EXTINCTION_STREAK,
            "EXTINCTION_FITNESS_RATIO": EXTINCTION_FITNESS_RATIO,
            "note": "物种（亚种除外）规模不大于 EXTINCTION_SIZE 时淘汰；分配后与每代结束时各检查一次；"
            "连续 EXTINCTION_STREAK 代混合适应度低于平均值 EXTINCTION_FITNESS_RATIO 倍时淘汰",
        },
        "subspecies": {
            "SUBSPECIES_MIN_SIZE": SUBSPECIES_MIN_SIZE,
            "SUBSPECIES_MIN_RATIO": SUBSPECIES_MIN_RATIO,
            "SUBSPECIES_EXTINCTION_STREAK": SUBSPECIES_EXTINCTION_STREAK,
            "SUBSPECIES_STALL_GENERATIONS": SUBSPECIES_STALL_GENERATIONS,
            "ALPHA_INVASION": ALPHA_INVASION,
            "note": "亚种达到规模或占比阈值之一即独立；连续低适应度达阈值则淘汰并归还规模；"
            "规模恒为 1 达 SUBSPECIES_STALL_GENERATIONS 代则淘汰",
        },
        "mutation": {
            "MUTATION_MIN_SIZE": MUTATION_MIN_SIZE,
            "MAX_MUTATION_ATTEMPTS": MAX_MUTATION_ATTEMPTS,
            "MUTATION_WEIGHTS": dict(MUTATION_WEIGHTS),
            "probability_by_size": {
                "<=10": mutation_probability(10),
                "<=20": mutation_probability(20),
                "<=40": mutation_probability(40),
                "<=70": mutation_probability(70),
                ">70": mutation_probability(100),
            },
        },
        "stagnation": {
            "STAGNATION_SEATS": STAGNATION_SEATS,
            "STAGNATION_GENERATIONS": STAGNATION_GENERATIONS,
            "note": "当一代内换手的席位不超过 STAGNATION_SEATS 时累计静止计数，"
            "达到 STAGNATION_GENERATIONS 则按规模加权强制一次变异",
        },
    }


# --------------------------------------------------------------------------- #
# document
# --------------------------------------------------------------------------- #
def _injection_schedule(sim: TrustEvolution) -> list[dict]:
    """Recover each manual injection as ``(generation, encoding, seat delta)``.

    ``EvolutionEvent`` only records the generation, the encoding and the parent,
    not how many seats were added, so the size is recovered from the recorded
    snapshots: an injection rewrites its own generation via
    ``re_record_frontier``, so ``history[g]`` holds the post-injection total and
    ``history[g - 1]`` the total before it. Without this the reproduce recipe
    could only replay an untouched run -- a run with injections would silently
    diverge.
    """
    schedule: list[dict] = []
    for event in sim.events:
        if event.event != "injection":
            continue
        generation = event.generation
        after = sim.history[generation].get(event.encoding, 0) if generation < len(sim.history) else 0
        before = (
            sim.history[generation - 1].get(event.encoding, 0)
            if 0 < generation < len(sim.history)
            else 0
        )
        schedule.append(
            {
                "generation": generation,
                "encoding": event.encoding,
                "size": max(1, after - before),
                "size_source": "snapshot_delta",
            }
        )
    return schedule


def build_document(
    sim: TrustEvolution,
    *,
    seed: int | None = None,
    name: str | None = None,
    note: str | None = None,
    initial_encodings: list[str] | None = None,
    initial_sizes: dict[str, int] | None = None,
    include_matchups: bool = True,
) -> dict:
    """Assemble the canonical archive document for ``sim``."""
    generation_records = []
    for record in sim.generation_records:
        generation_records.append(
            {
                "generation": record.generation,
                "species_data": record.species_data,
                "average_fitness": record.average_fitness,
                "events": [asdict(event) for event in record.events],
                "matchup_matrix": record.matchup_matrix if include_matchups else {},
            }
        )

    injections = _injection_schedule(sim)

    return {
        "format": FORMAT_NAME,
        "schema_version": RUN_SCHEMA_VERSION,
        "engine_version": ENGINE_VERSION,
        "engine_git": _git_revision(),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "name": _safe_name(name or "run"),
        "note": note,
        "summary": {
            "seed": seed,
            "generations": sim.generation,
            "surviving_species": len(sim.species),
            "terminated_by": "全部物种灭绝" if not sim.species else "运行中（可继续推进）",
            "population_capacity": TOTAL_CAPACITY,
            "turns_per_match": TURNS_PER_MATCH,
            "injections": sum(1 for event in sim.events if event.event == "injection"),
            "matchups_included": include_matchups,
        },
        "reproduce": {
            "seed": seed,
            "initial_encodings": initial_encodings,
            "initial_sizes": initial_sizes,
            "generations": sim.generation,
            "injections": injections,
            "note": "同 engine_version 下用这些输入重跑可完全复现该轨迹；"
            "injections 记录手动注入的代数与增量席位，必须按顺序重放",
        },
        "rules": build_rules(),
        "strategy_encoding_reference": STRATEGY_REFERENCE,
        "analysis_prompt": ANALYSIS_PROMPT,
        "how_to_read": HOW_TO_READ,
        "state": {
            "rng_state": _rng_state_to_list(sim.rng),
            "history": sim.history,
            "fitness_history": sim.fitness_history,
            "events": [asdict(event) for event in sim.events],
            "final_species": [asdict(item) for item in sim.species],
            "generation_records": generation_records,
        },
        "analysis": build_analysis(sim),
    }


def _run_filename(doc: dict) -> str:
    summary = doc["summary"]
    seed = summary.get("seed")
    seed_part = f"s{seed}" if seed is not None else "sauto"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return (
        f"{_safe_name(doc['name'])}_{seed_part}"
        f"_g{summary['generations']}_{stamp}{FILE_SUFFIX}"
    )


def save_run(
    sim: TrustEvolution,
    *,
    seed: int | None = None,
    name: str | None = None,
    note: str | None = None,
    initial_encodings: list[str] | None = None,
    initial_sizes: dict[str, int] | None = None,
    include_matchups: bool = True,
) -> Path:
    """Write the one canonical file for this run and return its path."""
    doc = build_document(
        sim,
        seed=seed,
        name=name,
        note=note,
        initial_encodings=initial_encodings,
        initial_sizes=initial_sizes,
        include_matchups=include_matchups,
    )
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    path = RUNS_DIR / _run_filename(doc)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def document_to_json(doc: dict) -> str:
    return json.dumps(doc, ensure_ascii=False, indent=2)


def load_document(path: str | Path) -> dict:
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("format") != FORMAT_NAME:
        raise ValueError(
            f"不是统一存档（format={data.get('format')!r}）：{path.name}。"
            f"旧格式档案已移至 archive/legacy/。"
        )
    return data


def _species_from_dict(data: dict) -> Species:
    subspecies = None
    sub = data.get("subspecies")
    if sub:
        subspecies = Subspecies(
            encoding=sub["encoding"],
            size=sub["size"],
            fitness=sub["fitness"],
            age=sub["age"],
            low_fitness_streak=sub["low_fitness_streak"],
            birth_generation=sub["birth_generation"],
            is_independent=sub["is_independent"],
            stagnant=sub.get("stagnant", 0),
        )
    return Species(
        encoding=data["encoding"],
        population_size=data["population_size"],
        fitness=data["fitness"],
        low_fitness_streak=data["low_fitness_streak"],
        birth_generation=data["birth_generation"],
        subspecies=subspecies,
        parent_encoding=data["parent_encoding"],
        is_extinct=data["is_extinct"],
        extinct_generation=data["extinct_generation"],
    )


def load_run(path: str | Path) -> TrustEvolution:
    """Rebuild the exact run from a canonical file (can be continued)."""
    doc = load_document(path)
    state = doc["state"]
    sim = TrustEvolution(seed=0)
    sim.generation = doc["summary"]["generations"]
    sim.rng.setstate(_rng_state_from_list(state["rng_state"]))
    sim.species = [_species_from_dict(item) for item in state["final_species"]]
    sim.history = state["history"]
    sim.fitness_history = state["fitness_history"]
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


def reproduce_run(path: str | Path) -> TrustEvolution:
    """Re-simulate from the stored seed instead of restoring the state."""
    doc = load_document(path)
    if doc["engine_version"] != ENGINE_VERSION:
        raise ValueError(
            "该存档由引擎 {} 生成，当前引擎为 {}；重跑不会得到相同轨迹。"
            "请改用 load_run() 读取存档状态。".format(
                doc["engine_version"], ENGINE_VERSION
            )
        )
    spec = doc["reproduce"]
    sim = TrustEvolution(
        seed=spec.get("seed"),
        initial_encodings=spec.get("initial_encodings"),
        initial_sizes=spec.get("initial_sizes"),
    )
    target = int(spec.get("generations") or 0)
    schedule: dict[int, list[dict]] = {}
    for order, injection in enumerate(spec.get("injections") or []):
        schedule.setdefault(int(injection["generation"]), []).append(
            (order, injection)
        )
    for entries in schedule.values():
        entries.sort(key=lambda pair: pair[0])

    # Injections are applied to the state of their own generation, before the
    # step that advances past it -- the same order the dashboard used.
    guard = 0
    while sim.generation < target:
        for _, injection in schedule.get(sim.generation, []):
            sim.inject_strategy(injection["encoding"], int(injection["size"]))
            sim.events.append(
                EvolutionEvent(
                    sim.generation, "injection", injection["encoding"]
                )
            )
            sim.re_record_frontier()
        if not sim.species:
            break
        sim.step()
        guard += 1
        if guard > target + 10:  # defensive: never spin on a corrupt recipe
            break
    return sim


def list_runs() -> list[dict]:
    """Lightweight summaries of every canonical run, newest first."""
    if not RUNS_DIR.is_dir():
        return []
    items: list[dict] = []
    for path in sorted(RUNS_DIR.glob(f"*{FILE_SUFFIX}")):
        try:
            doc = load_document(path)
        except Exception:  # noqa: BLE001 - skip unreadable files
            continue
        summary = doc["summary"]
        items.append(
            {
                "file": path.name,
                "path": str(path),
                "name": doc.get("name", path.stem),
                "note": doc.get("note"),
                "created_at": doc.get("created_at", ""),
                "engine_version": doc.get("engine_version"),
                "engine_git": doc.get("engine_git"),
                "schema_version": doc.get("schema_version"),
                "seed": summary.get("seed"),
                "generations": summary.get("generations", 0),
                "surviving_species": summary.get("surviving_species"),
                "terminated_by": summary.get("terminated_by"),
                "injections": summary.get("injections", 0),
                "stale_engine": doc.get("engine_version") != ENGINE_VERSION,
            }
        )
    items.sort(key=lambda item: item["created_at"], reverse=True)
    return items


def latest_run() -> Path | None:
    runs = list_runs()
    return Path(runs[0]["path"]) if runs else None


def delete_run(path: str | Path) -> None:
    Path(path).unlink(missing_ok=True)


def rename_run(path: str | Path, new_name: str) -> Path:
    path = Path(path)
    doc = load_document(path)
    doc["name"] = _safe_name(new_name)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    target = RUNS_DIR / _run_filename(doc)
    target.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    if target != path:
        path.unlink(missing_ok=True)
    return target


# --------------------------------------------------------------------------- #
# derived views -- rendered on demand, never stored
# --------------------------------------------------------------------------- #
def _md_table(headers: list, rows: list[list]) -> str:
    lines = [
        "| " + " | ".join(str(header) for header in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join("" if cell is None else str(cell) for cell in row)
            + " |"
        )
    return "\n".join(lines)


def document_to_markdown(doc: dict) -> str:
    summary = doc["summary"]
    analysis = doc["analysis"]
    rules = doc["rules"]
    lines: list[str] = []
    lines.append(f"# The Fittest 模拟存档：{doc['name']}")
    lines.append("")
    lines.append(
        "格式版本 {}　引擎版本 {}　生成时间 {}".format(
            doc["schema_version"], doc["engine_version"], doc["created_at"]
        )
    )
    lines.append(
        "种子 {}　代数 {}　结束方式 {}　存活物种 {}　手动注入 {} 次".format(
            summary["seed"],
            summary["generations"],
            summary["terminated_by"],
            summary["surviving_species"],
            summary["injections"],
        )
    )
    if doc.get("note"):
        lines.append("")
        lines.append(f"> 备注：{doc['note']}")
    lines.append("")
    lines.append("> " + doc["how_to_read"].replace("\n", " "))
    lines.append("")

    lines.append("## 1. 规则与参数")
    lines.append("")
    payoffs = rules["payoffs"]
    lines.append(
        "- 种群容量 {}，每场对局 {} 回合。收益（本方/对方）：合作-合作 {}/{}，"
        "合作-背叛 {}/{}，背叛-合作 {}/{}，背叛-背叛 {}/{}。".format(
            rules["population_capacity"],
            rules["turns_per_match"],
            *payoffs["cooperate_cooperate"],
            *payoffs["cooperate_defect"],
            *payoffs["defect_cooperate"],
            *payoffs["defect_defect"],
        )
    )
    lines.append(
        "- 分配：{}（ALPHA_ALLOCATE={}）。".format(
            rules["allocation"]["note"], rules["allocation"]["ALPHA_ALLOCATE"]
        )
    )
    lines.append("- 淘汰：{}。".format(rules["extinction"]["note"]))
    lines.append("- 亚种：{}。".format(rules["subspecies"]["note"]))
    lines.append(
        "- 停滞：{}。".format(rules["stagnation"]["note"])
    )
    lines.append(
        "- 变异：门槛 MUTATION_MIN_SIZE={}，权重 {}。".format(
            rules["mutation"]["MUTATION_MIN_SIZE"], rules["mutation"]["MUTATION_WEIGHTS"]
        )
    )
    lines.append("")
    lines.append("### 策略编码参考")
    lines.append("")
    lines.append(doc["strategy_encoding_reference"].strip())
    lines.append("")

    lines.append("## 2. 分析请求")
    lines.append("")
    lines.append(doc["analysis_prompt"])
    lines.append("")

    lines.append("## 3. 逐代概览")
    lines.append("")
    lines.append(
        _md_table(
            ["代数", "总规模", "存活物种", "平均适应度", "事件"],
            [
                [
                    row["generation"],
                    row["total_population"],
                    row["species_count"],
                    row["average_fitness"],
                    row["event_marks"],
                ]
                for row in analysis["generation_summary"]
            ],
        )
    )
    lines.append("")

    lines.append("## 4. 演化事件时间线")
    lines.append("")
    events = analysis["events"]
    if events:
        lines.append(
            _md_table(
                ["代数", "事件", "编码", "父代"],
                [
                    [
                        event["generation"],
                        event["event"],
                        event["encoding"],
                        event["parent_encoding"] or "-",
                    ]
                    for event in events
                ],
            )
        )
    else:
        lines.append("（本次运行没有特殊事件。）")
    lines.append("")

    lines.append("## 5. 谱系")
    lines.append("")
    lines.append(
        _md_table(
            ["编码", "来源", "父代", "诞生", "独立", "灭绝", "峰值规模", "最终规模"],
            [
                [
                    row["encoding"],
                    row["origin"],
                    row["parent"] or "-",
                    row["birth_generation"],
                    row["independence_generation"]
                    if row["independence_generation"] is not None
                    else "-",
                    row["extinction_generation"]
                    if row["extinction_generation"] is not None
                    else "-",
                    row["peak_size"],
                    row["final_size"],
                ]
                for row in analysis["lineages"]
            ],
        )
    )
    lines.append("")

    lines.append("## 6. 衍生指标")
    lines.append("")
    lines.append("### 多样性")
    lines.append("")
    lines.append(
        _md_table(
            ["代数", "存活物种", "Shannon", "Simpson"],
            [
                [
                    row["generation"],
                    row["species_count"],
                    row["shannon"],
                    row["simpson"],
                ]
                for row in analysis["derived"]["diversity"]
            ],
        )
    )
    lines.append("")
    lines.append("### 优势物种更替")
    lines.append("")
    changes = []
    previous = object()
    for row in analysis["derived"]["dominance"]:
        if row["dominant"] != previous:
            changes.append([row["generation"], row["dominant"] or "-", row["share"]])
            previous = row["dominant"]
    lines.append(_md_table(["代数", "优势物种", "占比"], changes))
    lines.append("")
    lines.append("### 事件统计")
    lines.append("")
    lines.append(
        _md_table(
            ["事件", "次数"],
            [
                [name, count]
                for name, count in analysis["derived"]["event_counts"].items()
            ],
        )
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(
        "本文件为统一存档 {} 的 Markdown 视图，由该 JSON 确定性渲染，不单独存储。"
        "逐代种群矩阵与对局矩阵请直接读 JSON 的 analysis.population_matrix 与 "
        "state.generation_records[].matchup_matrix。".format(doc["name"])
    )
    return "\n".join(lines)


def document_to_csv(doc: dict) -> str:
    """Long-format table: one row per (generation, encoding)."""
    import csv
    import io

    analysis = doc["analysis"]
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["generation", "encoding", "population", "fitness", "average_fitness", "event_marks"]
    )
    ordered = analysis["encodings"]
    summary = {row["generation"]: row for row in analysis["generation_summary"]}
    for generation, row in enumerate(analysis["population_matrix"]):
        fitness = analysis["fitness_matrix"][generation]
        for index, encoding in enumerate(ordered):
            writer.writerow(
                [
                    generation,
                    encoding,
                    row[index],
                    fitness.get(encoding, ""),
                    summary[generation]["average_fitness"],
                    summary[generation]["event_marks"],
                ]
            )
    return buffer.getvalue()
