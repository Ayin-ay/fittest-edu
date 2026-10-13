"""Main The Fittest simulation with species, subspecies, and visual reports.

Run from the repository root with:

    python trust_evolution_simulation.py

The generated PNG and JSON report are written to ``results/trust_evolution``.
"""

from __future__ import annotations

import json
import math
import random
import re
import argparse
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.colors import to_rgba
from matplotlib.patches import Patch
from matplotlib.transforms import Bbox

from strategy_engine.strategy_engine import (
    C_RE,
    DEFAULT_RE,
    M_RE,
    RPT_RE,
    TRIGGER_RE,
    StrategyState,
    parse_strategy,
    random_strategy,
)


TOTAL_CAPACITY = 100
# Engine identity, stamped into every saved run by ``evolution_archive``.
# ``ENGINE_VERSION`` must be bumped whenever a change alters the trajectory of a
# run -- a rule value, the order of the steps, the mutation weights, or a fix to
# seat bookkeeping. A seed only reproduces inside one engine version, so an
# archive written by 1.0.0 can be replayed faithfully but will not match a run
# produced by a later engine. ``RUN_SCHEMA_VERSION`` is separate: it describes
# the on-disk archive layout and is only bumped when the JSON shape changes.
ENGINE_VERSION = "1.2.0"
RUN_SCHEMA_VERSION = 1
# Fitness now carries a little more weight when the next generation is sized.
ALPHA_ALLOCATE = 0.4
ALPHA_INVASION = 0.4
# A species (subspecies are exempt) whose population is this small or smaller
# is removed, both right after allocation and again at the end of the step.
EXTINCTION_SIZE = 3
EXTINCTION_FITNESS_RATIO = 0.5
EXTINCTION_STREAK = 3
SUBSPECIES_MIN_SIZE = 10
SUBSPECIES_MIN_RATIO = 0.35
SUBSPECIES_EXTINCTION_STREAK = 3
MUTATION_MIN_SIZE = 10
# A mutation may hand back the parent's own encoding (swapping two identical
# modules, for instance). A subspecies that shares its parent's encoding cannot
# be told apart from it in the size tables, so the mutation is retried; if every
# attempt is a no-op the mutation is skipped for this generation.
MAX_MUTATION_ATTEMPTS = 4
# A subspecies that keeps a size of exactly 1 for this many generations is
# retired and its seat is returned to the parent species.
SUBSPECIES_STALL_GENERATIONS = 10
# Stagnation breaker: a population is "frozen" when at most STAGNATION_SEATS
# seats change hands in a generation, for STAGNATION_GENERATIONS generations in
# a row.
#
# This used to be measured as "no single encoding moved by more than
# STAGNATION_TOLERANCE seats". That is a per-species measure, so it stops
# working exactly where it matters: in a dense field of a dozen-plus species,
# individual encodings shuffle constantly and the largest single move is
# routinely above the threshold even though the population as a whole is
# static. A traced 16-species run went 100 generations with zero events and the
# breaker never fired once. Counting the seats that actually changed hands is
# scale-free: one species or twenty, "almost nothing moved" means the same thing.
STAGNATION_SEATS = 2
STAGNATION_GENERATIONS = 20
TURNS_PER_MATCH = 20

OUTPUT_DIR = Path(__file__).resolve().parent / "results" / "trust_evolution"

_CJK_FONT_PREFERENCES = (
    "Microsoft YaHei",
    "Microsoft YaHei UI",
    "SimHei",
    "Noto Sans CJK SC",
    "Source Han Sans CN",
    "Arial Unicode MS",
    "DejaVu Sans",
)
_installed_fonts = {font.name for font in font_manager.fontManager.ttflist}
plt.rcParams["font.sans-serif"] = [
    font for font in _CJK_FONT_PREFERENCES if font in _installed_fonts
] or ["DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

PAYOFFS = {
    ("C", "C"): (3.0, 3.0),
    ("C", "D"): (0.0, 5.0),
    ("D", "C"): (5.0, 0.0),
    ("D", "D"): (1.0, 1.0),
}


@dataclass
class Subspecies:
    encoding: str
    size: int
    fitness: float = 0.0
    age: int = 0
    low_fitness_streak: int = 0
    birth_generation: int = 0
    is_independent: bool = False
    # Consecutive generations spent at size 1; retired once it reaches
    # SUBSPECIES_STALL_GENERATIONS.
    stagnant: int = 0


@dataclass
class Species:
    encoding: str
    population_size: int
    fitness: float = 0.0
    low_fitness_streak: int = 0
    birth_generation: int = 0
    subspecies: Subspecies | None = None
    parent_encoding: str | None = None
    is_extinct: bool = False
    extinct_generation: int | None = None

    @property
    def total_size(self) -> int:
        return self.population_size + (
            self.subspecies.size if self.subspecies is not None else 0
        )

    @property
    def mixed_fitness(self) -> float:
        if self.subspecies is None or self.total_size == 0:
            return self.fitness
        return (
            self.population_size * self.fitness
            + self.subspecies.size * self.subspecies.fitness
        ) / self.total_size


@dataclass
class EvolutionEvent:
    generation: int
    event: str
    encoding: str
    parent_encoding: str | None = None


@dataclass
class GenerationRecord:
    """每一代的完整快照，供可视化层使用。

    ``species_data`` 以物种编码为键，值包含规模、适应度与嵌套的亚种信息；
    ``matchup_matrix`` 记录该代评估时每对策略的平均得分（行=本方，列=对方）。
    """

    generation: int
    species_data: dict[str, dict]
    average_fitness: float
    events: list[EvolutionEvent]
    matchup_matrix: dict[str, dict[str, float]]


def mutation_probability(size: int) -> float:
    if size <= 10:
        return 0.0
    if size <= 20:
        return 0.05
    if size <= 40:
        return 0.10
    if size <= 70:
        return 0.15
    return 0.20


def match_repetitions(species_count: int) -> int:
    return 5 if species_count <= 10 else 3


def _round_robin_sizes(values: dict[str, float], total: int) -> dict[str, int]:
    """Largest-remainder allocation, preserving exactly ``total`` places."""
    if not values or total <= 0:
        return {key: 0 for key in values}
    positive = {key: max(value, 0.0) for key, value in values.items()}
    denominator = sum(positive.values())
    if denominator <= 0:
        share = total / len(positive)
        positive = {key: share for key in positive}
        denominator = total
    raw = {key: value * total / denominator for key, value in positive.items()}
    result = {key: math.floor(value) for key, value in raw.items()}
    remainder = total - sum(result.values())
    order = sorted(
        raw,
        key=lambda key: (raw[key] - result[key], key),
        reverse=True,
    )
    for key in order[:remainder]:
        result[key] += 1
    return result


def _play_once(first: str, second: str, turns: int, rng: random.Random) -> tuple[float, float]:
    first_state = StrategyState(parse_strategy(first), turns, rng=rng)
    second_state = StrategyState(parse_strategy(second), turns, rng=rng)
    first_score = second_score = 0.0
    first_history: list[str] = []
    second_history: list[str] = []
    for _ in range(turns):
        first_action = first_state.decide(second_history)
        second_action = second_state.decide(first_history)
        first_history.append(first_action)
        second_history.append(second_action)
        first_points, second_points = PAYOFFS[(first_action, second_action)]
        first_score += first_points
        second_score += second_points
    # Keep the parameter explicit so independent match repetitions remain clear.
    rng.random()
    return first_score / turns, second_score / turns


def _fitness_table(
    species: list[Species], turns: int, rng: random.Random
) -> tuple[dict[str, float], dict[str, dict[str, float]]]:
    """Return per-encoding fitness and the pairwise average-score matrix.

    The matrix is recorded purely for visualization; the decision flow and the
    order of random draws are identical to the original implementation.
    """
    encodings = [item.encoding for item in species]
    repetitions = match_repetitions(len(encodings))
    scores = {encoding: [] for encoding in encodings}
    pair_scores = {
        first: {second: [] for second in encodings} for first in encodings
    }
    for first in encodings:
        for second in encodings:
            for _ in range(repetitions):
                first_score, second_score = _play_once(first, second, turns, rng)
                scores[first].append(first_score)
                scores[second].append(second_score)
                pair_scores[first][second].append(first_score)
    fitness = {
        encoding: sum(values) / len(values) for encoding, values in scores.items()
    }
    matchup = {
        first: {
            second: (sum(values) / len(values) if values else 0.0)
            for second, values in row.items()
        }
        for first, row in pair_scores.items()
    }
    return fitness, matchup


#: Weights of the documented mutation families. Module-removing mutations
#: ("delete") are deliberately over-weighted so diversification tends to yield
#: *simplified* derivatives of the parent rather than only parameter noise.
MUTATION_WEIGHTS = {
    "parameter": 25,
    "jump": 8,
    "replace": 15,
    "add": 10,
    "delete": 30,
    "swap": 4,
    "fresh": 4,
    "inherit": 4,
}


def _is_default_module(token: str) -> bool:
    return bool(DEFAULT_RE.fullmatch(token))


def _is_trigger_module(token: str) -> bool:
    return bool(TRIGGER_RE.fullmatch(token))


def _is_modifier_module(token: str) -> bool:
    return bool(M_RE.fullmatch(token) or C_RE.fullmatch(token) or RPT_RE.fullmatch(token))


def _random_trigger(rng: random.Random) -> str:
    kind = rng.choice(("P", "H", "R", "B", "K", "RC"))
    burst_choices = ("2", "3", "M") if kind == "B" else ("1", "2", "3", "M")
    return f"{kind}{rng.randint(1, 3)}-{rng.choice(burst_choices)}"


def _random_modifier(rng: random.Random) -> str:
    choice = rng.randint(0, 4)
    if choice == 0:
        return f"M{rng.randint(1, 3)}"
    if choice in (1, 2):
        return f"C{rng.randint(1, 4)}"
    if choice == 3:
        return f"C{rng.randint(1, 4)}-D"
    return f"RPT{rng.choice(('1', '2', '3', 'M'))}-{rng.choice(('1', '2', '3', 'M'))}"


def _drop_one_module(tokens: list[str], rng: random.Random) -> list[str]:
    """Remove a single module, preferring trigger/modifier slots.

    Keeping the default slot (when present) guarantees the simplified mutant
    still owns a base behaviour instead of silently inheriting the implicit S0.
    """
    removable = [i for i, token in enumerate(tokens) if not _is_default_module(token)]
    if not removable:
        removable = list(range(1, len(tokens)))
    if not removable:
        removable = [0]
    index = rng.choice(removable)
    return tokens[:index] + tokens[index + 1 :]


def _insert_one_module(tokens: list[str], rng: random.Random) -> list[str] | None:
    """Add one trigger/modifier module while keeping the slot order valid."""
    if len(tokens) >= 4:
        return None
    has_modifier = any(_is_modifier_module(token) for token in tokens)
    trigger_count = sum(1 for token in tokens if _is_trigger_module(token))
    if not has_modifier:
        return tokens + [_random_modifier(rng)]
    if trigger_count < 2:
        module = _random_trigger(rng)
        insert_at = len(tokens)
        for index, token in enumerate(tokens):
            if _is_modifier_module(token):
                insert_at = index
                break
        return tokens[:insert_at] + [module] + tokens[insert_at:]
    return None


def _mutate_encoding(encoding: str, rng: random.Random) -> str:
    """Apply one of the documented mutation families and return valid code."""
    tokens = encoding.split("+")
    operation = rng.choices(
        list(MUTATION_WEIGHTS),
        weights=list(MUTATION_WEIGHTS.values()),
        k=1,
    )[0]
    if operation in {"fresh", "inherit"}:
        candidate = random_strategy(rng).code
    elif operation == "delete" and len(tokens) > 1:
        candidate = "+".join(_drop_one_module(tokens, rng))
    elif operation == "add":
        extended = _insert_one_module(tokens, rng)
        candidate = "+".join(extended) if extended is not None else random_strategy(rng).code
    elif operation == "swap" and len(tokens) >= 3:
        swapped = list(tokens)
        swapped[-1], swapped[-2] = swapped[-2], swapped[-1]
        candidate = "+".join(swapped)
    else:
        candidate = random_strategy(rng).code
        if operation in {"parameter", "jump", "replace"}:
            match = re.search(r"([1-3])(?=$|-)", encoding)
            if match:
                value = "M" if operation == "jump" else str((int(match.group(1)) % 3) + 1)
                candidate = encoding[: match.start(1)] + value + encoding[match.end(1) :]
                try:
                    parse_strategy(candidate)
                except ValueError:
                    candidate = random_strategy(rng).code
    try:
        parse_strategy(candidate)
    except ValueError:
        candidate = random_strategy(rng).code
    if candidate == encoding:
        candidate = random_strategy(rng).code
    return candidate


class TrustEvolution:
    def __init__(
        self,
        seed: int | None = None,
        initial_encodings: Iterable[str] | None = None,
        initial_sizes: dict[str, int] | None = None,
    ) -> None:
        self.rng = random.Random(seed)
        if initial_encodings is None:
            encodings = []
            while len(encodings) < 7:
                candidate = random_strategy(self.rng).code
                if candidate not in encodings:
                    encodings.append(candidate)
        else:
            encodings = list(initial_encodings)
        self.species = [
            Species(encoding=encoding, population_size=0)
            for encoding in dict.fromkeys(encodings)
        ]
        if initial_sizes is None:
            initial_sizes = _round_robin_sizes(
                {
                    item.encoding: self.rng.uniform(0.5, 1.5)
                    for item in self.species
                },
                TOTAL_CAPACITY,
            )
        for item in self.species:
            item.population_size = initial_sizes[item.encoding]
        self.generation = 0
        self.events: list[EvolutionEvent] = []
        self.history: list[dict[str, int]] = []
        self.fitness_history: list[dict[str, float]] = []
        self.generation_records: list[GenerationRecord] = []
        self._stagnation_streak = 0
        self._evaluate_initial()
        self._record_generation()
        self._record_snapshot()

    def _evaluate_initial(self) -> None:
        """Give the starting population meaningful fitness without touching rng.

        The first real ``evaluate`` (during ``step``) draws from ``self.rng``.
        We clone that state so the generation-0 overview matches what the first
        step will actually use, while leaving the simulation's own stream intact.
        """
        if not self.species:
            return
        clone = random.Random()
        clone.setstate(self.rng.getstate())
        fitness, _ = _fitness_table(self.species, TURNS_PER_MATCH, clone)
        for item in self.species:
            item.fitness = fitness[item.encoding]

    def _current_evaluation(
        self,
    ) -> tuple[dict[str, float], dict[str, dict[str, float]]]:
        """Fitness and pairwise scores for the current species and subspecies.

        Computed from a cloned rng so recording never perturbs the simulation.
        The result matches the next ``evaluate`` call exactly. This also gives
        newly born subspecies a meaningful fitness in the generation they first
        appear, instead of the placeholder ``0``.
        """
        encodings = list(
            dict.fromkeys(
                [item.encoding for item in self.species]
                + [
                    item.subspecies.encoding
                    for item in self.species
                    if item.subspecies is not None
                ]
            )
        )
        if not encodings:
            return {}, {}
        clone = random.Random()
        clone.setstate(self.rng.getstate())
        proxies = [Species(encoding, 1) for encoding in encodings]
        fitness, matchup = _fitness_table(proxies, TURNS_PER_MATCH, clone)
        return fitness, matchup

    def _record_snapshot(self) -> None:
        snapshot: dict[str, int] = {}
        for item in self.species:
            # Sum instead of overwriting: a subspecies and some other entry may
            # legitimately share an encoding, and overwriting would drop seats
            # from the recorded population.
            snapshot[item.encoding] = snapshot.get(item.encoding, 0) + item.population_size
            if item.subspecies is not None:
                child = item.subspecies.encoding
                snapshot[child] = snapshot.get(child, 0) + item.subspecies.size
        self.history.append(snapshot)
        self.fitness_history.append(
            {item.encoding: item.mixed_fitness for item in self.species}
        )

    def _compute_average_fitness(self) -> float:
        total = sum(item.total_size for item in self.species)
        if total == 0:
            return 0.0
        return (
            sum(item.total_size * item.mixed_fitness for item in self.species) / total
        )

    def _record_generation(self) -> None:
        fitness_table, matchup = self._current_evaluation()
        species_data: dict[str, dict] = {}
        for item in self.species:
            child = item.subspecies
            species_data[item.encoding] = {
                "population_size": item.population_size,
                # A species injected into the current generation (or otherwise not
                # yet evaluated) would report fitness 0; use the freshly computed
                # table so the display is meaningful. This only affects the record.
                "fitness": item.fitness
                if item.fitness > 0
                else fitness_table.get(item.encoding, item.fitness),
                "mixed_fitness": item.mixed_fitness,
                "low_fitness_streak": item.low_fitness_streak,
                "subspecies": (
                    {
                        "encoding": child.encoding,
                        "size": child.size,
                        # A subspecies is only evaluated on the next step; use
                        # the freshly computed table so the birth generation is
                        # not reported as fitness 0.
                        "fitness": child.fitness
                        if child.fitness > 0
                        else fitness_table.get(child.encoding, child.fitness),
                        "age": child.age,
                        "low_fitness_streak": child.low_fitness_streak,
                        "stagnant": child.stagnant,
                    }
                    if child is not None
                    else None
                ),
            }
        record = GenerationRecord(
            generation=self.generation,
            species_data=species_data,
            average_fitness=self._compute_average_fitness(),
            events=[event for event in self.events if event.generation == self.generation],
            matchup_matrix=matchup,
        )
        self.generation_records.append(record)

    def evaluate(self) -> float:
        original_fitness, _ = _fitness_table(self.species, TURNS_PER_MATCH, self.rng)
        for item in self.species:
            item.fitness = original_fitness[item.encoding]
            if item.subspecies is not None:
                item.subspecies.fitness = _fitness_table(
                    [Species(item.subspecies.encoding, 1)] + self.species,
                    TURNS_PER_MATCH,
                    self.rng,
                )[0][item.subspecies.encoding]
                item.subspecies.age += 1
        total = sum(item.total_size for item in self.species)
        average = (
            sum(item.total_size * item.mixed_fitness for item in self.species) / total
            if total
            else 0.0
        )
        for item in self.species:
            if item.mixed_fitness < average * EXTINCTION_FITNESS_RATIO:
                item.low_fitness_streak += 1
            else:
                item.low_fitness_streak = 0
            child = item.subspecies
            if child is not None:
                if child.fitness < average * EXTINCTION_FITNESS_RATIO:
                    child.low_fitness_streak += 1
                else:
                    child.low_fitness_streak = 0
        return average

    def allocate(self, average: float) -> None:
        if not self.species:
            return
        baseline = average if average > 0 else 1.0
        # Keyed by position, never by encoding: two species that share an
        # encoding would collapse into a single key and then be handed the same
        # quota twice, pushing the population past TOTAL_CAPACITY.
        projected = {
            position: item.population_size
            * (ALPHA_ALLOCATE + (1 - ALPHA_ALLOCATE) * item.mixed_fitness / baseline)
            for position, item in enumerate(self.species)
        }
        allocation = _round_robin_sizes(projected, TOTAL_CAPACITY)
        for position, item in enumerate(self.species):
            item.population_size = allocation[position]

    def remove_extinct(self) -> None:
        survivors: list[Species] = []
        for item in self.species:
            if item.population_size <= EXTINCTION_SIZE or item.low_fitness_streak >= EXTINCTION_STREAK:
                item.is_extinct = True
                item.extinct_generation = self.generation
                self.events.append(EvolutionEvent(self.generation, "extinction", item.encoding))
                promoted = self.promote_subspecies(item)
                if promoted is not None:
                    survivors.append(promoted)
            else:
                survivors.append(item)
        self.species = survivors

    def reproduce(self) -> None:
        total = sum(item.total_size for item in self.species)
        if total == 0:
            return
        if total != TOTAL_CAPACITY:
            # ``allocate`` hands out exactly TOTAL_CAPACITY seats to the parent
            # populations, so the subspecies (which are not part of that
            # allocation) have to be paid for out of the same budget.
            reserved = sum(
                item.subspecies.size if item.subspecies is not None else 0
                for item in self.species
            )
            target = max(TOTAL_CAPACITY - reserved, 0)
            # Keyed by position, never by encoding -- see allocate().
            scales = {
                position: item.population_size * target / total
                for position, item in enumerate(self.species)
            }
            allocation = _round_robin_sizes(scales, target)
            for position, item in enumerate(self.species):
                item.population_size = allocation[position]

    def promote_subspecies(self, item: Species) -> Species | None:
        """Detach a dying species' subspecies into a species of its own.

        ``remove_extinct`` and ``remove_undersized`` drop the whole ``Species``
        object. When that object still carries a subspecies its seats used to
        disappear with it, quietly shrinking the population below
        ``TOTAL_CAPACITY``. The subspecies instead outlives its parent, keeping
        its seats, its size and a recorded ``subspecies_independent`` event.
        The caller is responsible for adding the result to the survivor list.
        """
        child = item.subspecies
        if child is None or child.size <= 0:
            item.subspecies = None
            return None
        item.subspecies = None
        self.events.append(
            EvolutionEvent(
                self.generation,
                "subspecies_independent",
                child.encoding,
                item.encoding,
            )
        )
        # If the encoding is already a species, hand the seats to that one
        # instead of creating a second object with the same encoding. A
        # duplicate would later be collapsed by merge_duplicate_species, which
        # conserves the seats -- but the dict-keyed quota tables used to hand
        # both copies the same allocation and inflate the population, so the
        # duplicate is never allowed to exist in the first place.
        existing = next(
            (
                other
                for other in self.species
                if other is not item and other.encoding == child.encoding
            ),
            None,
        )
        if existing is not None:
            existing.population_size += child.size
            return None
        return Species(
            child.encoding,
            child.size,
            child.fitness,
            birth_generation=self.generation,
            parent_encoding=item.encoding,
        )

    def merge_duplicate_species(self) -> bool:
        """Collapse ``Species`` objects that share an encoding into one.

        ``allocate``, ``reproduce`` and every recorded table are keyed by
        encoding, so two objects with the same encoding collapse into a single
        key and both are later assigned the same seat count -- the population
        then grows past ``TOTAL_CAPACITY`` once per generation. Subspecies
        independence can no longer create duplicates, but simulations restored
        from older saves may still contain them, so this pass runs at the top of
        every step. Seats are conserved: they are summed onto the first
        occurrence, which keeps the best fitness and the healthiest streak.
        """
        if len(self.species) < 2:
            return False
        merged: list[Species] = []
        by_encoding: dict[str, Species] = {}
        changed = False
        for item in self.species:
            keeper = by_encoding.get(item.encoding)
            if keeper is None:
                by_encoding[item.encoding] = item
                merged.append(item)
                continue
            changed = True
            keeper.population_size += item.population_size
            if item.fitness > keeper.fitness:
                keeper.fitness = item.fitness
            keeper.low_fitness_streak = min(
                keeper.low_fitness_streak, item.low_fitness_streak
            )
            if keeper.subspecies is None:
                keeper.subspecies = item.subspecies
            elif item.subspecies is not None:
                keeper.subspecies.size += item.subspecies.size
        self.species = merged
        return changed

    def assert_capacity(self) -> None:
        """Fail loudly when the seat budget is broken.

        ``reproduce`` is the single place that normalises the population back to
        ``TOTAL_CAPACITY``. A violation here means seats were created or lost
        somewhere else, so it is raised rather than silently carried forward.
        """
        if not self.species:
            return
        total = sum(item.total_size for item in self.species)
        if total != TOTAL_CAPACITY:
            raise RuntimeError(
                "population invariant violated at generation {}: {} seats vs "
                "capacity {}".format(self.generation, total, TOTAL_CAPACITY)
            )

    def remove_undersized(self) -> None:
        """Remove species (not subspecies) that ended the generation too small.

        ``remove_extinct`` only sees the sizes produced by ``allocate``; the
        later ``reproduce`` and mutation steps can still push a species down to
        ``EXTINCTION_SIZE``. This pass catches those lingering tiny species so
        they cannot survive into the recorded snapshot.
        """
        survivors: list[Species] = []
        for item in self.species:
            if item.population_size <= EXTINCTION_SIZE:
                item.is_extinct = True
                item.extinct_generation = self.generation
                self.events.append(
                    EvolutionEvent(self.generation, "extinction", item.encoding)
                )
                promoted = self.promote_subspecies(item)
                if promoted is not None:
                    survivors.append(promoted)
            else:
                survivors.append(item)
        self.species = survivors

    def inject_strategy(self, encoding: str, size: int) -> None:
        """Manually inject a strategy with ``size`` seats at the current frontier.

        Existing species (and their subspecies) are scaled down proportionally
        so the total population returns to capacity. If the encoding already
        exists as a species, its population is grown by ``size`` instead.
        """
        size = max(1, min(int(size), TOTAL_CAPACITY - 1))
        index = next(
            (i for i, item in enumerate(self.species) if item.encoding == encoding),
            None,
        )
        if index is None:
            self.species.append(Species(encoding, 0, birth_generation=self.generation))
            index = len(self.species) - 1
        self.species[index].population_size += size

        others = [item for i, item in enumerate(self.species) if i != index]
        current_other = sum(item.total_size for item in others)
        target_other = max(TOTAL_CAPACITY - self.species[index].total_size, 0)
        if current_other > 0 and target_other < current_other:
            factor = target_other / current_other
            for item in others:
                item.population_size = max(0, round(item.population_size * factor))
                if item.subspecies is not None:
                    item.subspecies.size = max(0, round(item.subspecies.size * factor))
            drift = TOTAL_CAPACITY - sum(item.total_size for item in self.species)
            if drift:
                for item in others:
                    if item.population_size > 0:
                        item.population_size = max(0, item.population_size + drift)
                        break

    def mutate_and_evolve_subspecies(self) -> None:
        for item in list(self.species):
            if item.subspecies is not None or item.population_size <= MUTATION_MIN_SIZE:
                continue
            if self.rng.random() >= mutation_probability(item.population_size):
                continue
            child = _mutate_encoding(item.encoding, self.rng)
            for _ in range(MAX_MUTATION_ATTEMPTS):
                if child != item.encoding:
                    break
                child = _mutate_encoding(item.encoding, self.rng)
            if child == item.encoding:
                continue
            item.population_size -= 1
            item.subspecies = Subspecies(child, 1, birth_generation=self.generation)
            self.events.append(
                EvolutionEvent(self.generation, "subspecies_birth", child, item.encoding)
            )

        for item in list(self.species):
            child = item.subspecies
            if child is None:
                continue
            # A newly created subspecies must survive one full generation
            # before it can be evaluated for invasion or independence.
            if child.birth_generation >= self.generation:
                continue
            if child.low_fitness_streak >= SUBSPECIES_EXTINCTION_STREAK:
                item.population_size += child.size
                item.subspecies = None
                self.events.append(
                    EvolutionEvent(
                        self.generation,
                        "subspecies_extinction",
                        child.encoding,
                        item.encoding,
                    )
                )
                continue
            # A subspecies that never grows past a single seat is retired and
            # its seat goes back to the parent species.
            child.stagnant = child.stagnant + 1 if child.size == 1 else 0
            if child.stagnant >= SUBSPECIES_STALL_GENERATIONS:
                item.population_size += child.size
                item.subspecies = None
                self.events.append(
                    EvolutionEvent(
                        self.generation,
                        "subspecies_extinction",
                        child.encoding,
                        item.encoding,
                    )
                )
                continue
            # Subspecies share the parent's niche and are protected from
            # immediate removal; sustained low fitness is handled above.
            if child.fitness <= item.fitness:
                continue
            total = item.population_size + child.size
            current_ratio = child.size / total
            ideal_ratio = child.fitness / max(child.fitness + item.fitness, 1e-9)
            ratio = ALPHA_INVASION * current_ratio + (1 - ALPHA_INVASION) * ideal_ratio
            child.size = max(1, int(total * ratio))
            item.population_size = total - child.size
            meets_size_requirement = child.size >= SUBSPECIES_MIN_SIZE
            meets_ratio_requirement = child.size / total >= SUBSPECIES_MIN_RATIO
            if meets_size_requirement or meets_ratio_requirement:
                child.is_independent = True
                item.population_size = total - child.size
                item.subspecies = None
                # A mutation can land on an encoding that is already a species.
                # Appending it would leave two objects sharing one encoding, and
                # every encoding-keyed table downstream (allocate / reproduce /
                # records) would then hand both copies the same seat count, so
                # the population would silently grow past TOTAL_CAPACITY. Merge
                # the seats into the existing species instead.
                existing = next(
                    (
                        other
                        for other in self.species
                        if other is not item and other.encoding == child.encoding
                    ),
                    None,
                )
                if existing is None:
                    self.species.append(
                        Species(
                            child.encoding,
                            child.size,
                            child.fitness,
                            birth_generation=self.generation,
                            parent_encoding=item.encoding,
                        )
                    )
                else:
                    existing.population_size += child.size
                self.events.append(
                    EvolutionEvent(self.generation, "subspecies_independent", child.encoding, item.encoding)
                )

    def re_record_frontier(self) -> None:
        """Refresh the recorded frontier (used after a manual injection)."""
        self.generation_records.pop()
        self.history.pop()
        self.fitness_history.pop()
        self._record_generation()
        self._record_snapshot()

    def _current_totals(self) -> dict[str, int]:
        totals: dict[str, int] = {}
        for item in self.species:
            totals[item.encoding] = totals.get(item.encoding, 0) + item.population_size
            if item.subspecies is not None:
                child = item.subspecies.encoding
                totals[child] = totals.get(child, 0) + item.subspecies.size
        return totals

    def _stagnation_delta(self) -> int:
        """Seats that changed hands since the last generation.

        Gaining and losing seats always cancel out, so the sum of absolute
        differences counts every reassignment twice; halving it gives the number
        of seats that actually moved owners. Counting seats rather than
        measuring the largest single species is what makes the test independent
        of how many species the field happens to contain.
        """
        if not self.history:
            return 0
        previous = self.history[-1]
        current = self._current_totals()
        keys = set(previous) | set(current)
        moved = sum(
            abs(current.get(key, 0) - previous.get(key, 0)) for key in keys
        )
        return int(moved / 2)

    def _force_stagnation_mutation(self) -> bool:
        """Force one mutation among the eligible species, weighted by size.

        This deliberately does *not* require ``population_size >
        MUTATION_MIN_SIZE``. That gate makes sense for ordinary mutation, where
        a species has to be big enough to afford losing a seat, but it disables
        the breaker entirely in the case it exists for: a frozen dense field
        where a dozen strategies share 100 seats and none of them exceeds ten.
        Requiring two seats is enough -- one to donate, one to keep.
        """
        candidates = [
            item
            for item in self.species
            if item.subspecies is None and item.population_size >= 2
        ]
        if not candidates:
            return False
        chosen = self.rng.choices(
            candidates, weights=[item.population_size for item in candidates], k=1
        )[0]
        child = _mutate_encoding(chosen.encoding, self.rng)
        chosen.population_size -= 1
        chosen.subspecies = Subspecies(child, 1, birth_generation=self.generation)
        self.events.append(
            EvolutionEvent(self.generation, "subspecies_birth", child, chosen.encoding)
        )
        return True

    def _update_stagnation(self) -> None:
        """Break long freezes by forcing one size-weighted mutation."""
        if self._stagnation_delta() <= STAGNATION_SEATS:
            self._stagnation_streak += 1
        else:
            self._stagnation_streak = 0
            return
        if self._stagnation_streak >= STAGNATION_GENERATIONS:
            if self._force_stagnation_mutation():
                self._stagnation_streak = 0

    def step(self) -> None:
        # Advance the counter first so every event and record produced by this
        # step carries the generation it creates.
        self.generation += 1
        self.merge_duplicate_species()
        average = self.evaluate()
        self.allocate(average)
        self.remove_extinct()
        self.reproduce()
        self.mutate_and_evolve_subspecies()
        self.remove_undersized()
        self._update_stagnation()
        # ``remove_undersized`` can delete a species after ``reproduce`` already
        # ran, so the seats it frees have to be returned to the pool here or the
        # population ends the generation short of TOTAL_CAPACITY.
        self.reproduce()
        # Promoting a subspecies out of a dying parent can land on an encoding
        # that is already taken, so normalise once more before the state is
        # validated and recorded.
        self.merge_duplicate_species()
        self.assert_capacity()
        self._record_generation()
        self._record_snapshot()

    def run(self, generations: int = 40) -> None:
        for _ in range(generations):
            if not self.species:
                break
            self.step()


def _family_color(encoding: str) -> tuple[float, float, float, float]:
    palette = {
        "S": "#d95f5f", "P": "#4f81bd", "F": "#55a868", "T": "#e5ae38",
        "D": "#8064a2", "W": "#4fb3bf", "B": "#e67e22", "R": "#9b59b6",
        "A": "#8c564b", "K": "#2ca02c", "C": "#7f7f7f",
    }
    return to_rgba(palette.get(encoding[:1], "#999999"))


def _independent_color(encoding: str) -> tuple[float, float, float, float]:
    """Use a distinct saturated color for a subspecies after independence."""
    palette = [
        "#e41a1c", "#377eb8", "#4daf4a", "#984ea3",
        "#ff7f00", "#a65628", "#f781bf", "#17becf",
    ]
    return to_rgba(palette[sum(ord(char) for char in encoding) % len(palette)])


def plot_results(
    simulation: TrustEvolution,
    generations: int,
    output_figure: Path,
) -> None:
    output_figure.parent.mkdir(parents=True, exist_ok=True)
    all_encodings = sorted(
        {encoding for snapshot in simulation.history for encoding in snapshot}
    )
    birth_by_encoding = {
        encoding: next(
            (
                event.generation
                for event in simulation.events
                if event.encoding == encoding
                and event.event in {"subspecies_birth", "subspecies_independent"}
            ),
            next(
                (item.birth_generation for item in simulation.species if item.encoding == encoding),
                0,
            ),
        )
        for encoding in all_encodings
    }
    ordered = sorted(
        all_encodings,
        key=lambda encoding: (
            birth_by_encoding[encoding],
            encoding,
        ),
    )
    fig, (area_axis, tree_axis, stats_axis) = plt.subplots(
        3,
        1,
        figsize=(15, 13),
        gridspec_kw={"height_ratios": [2.2, 1.5, 0.8]},
    )
    fig.subplots_adjust(hspace=0.4, top=0.95, bottom=0.05)
    x = list(range(len(simulation.history)))
    bottom = [0] * len(x)
    boundaries: dict[str, list[float]] = {}
    for encoding in ordered:
        values = [snapshot.get(encoding, 0) for snapshot in simulation.history]
        lower = list(bottom)
        area_axis.fill_between(
            x, lower, [base + value for base, value in zip(lower, values)],
            color=_family_color(encoding), alpha=0.85, label=encoding,
            step="mid",
        )
        bottom = [base + value for base, value in zip(bottom, values)]
        boundaries[encoding] = lower

    # Overlay non-independent subspecies with a strong hatch so they remain
    # visible even when their population is small.
    independent = {
        event.encoding
        for event in simulation.events
        if event.event == "subspecies_independent"
    }
    subspecies_encodings = {
        event.encoding
        for event in simulation.events
        if event.event == "subspecies_birth"
    } - independent
    for encoding in ordered:
        if encoding not in subspecies_encodings or encoding not in boundaries:
            continue
        values = [snapshot.get(encoding, 0) for snapshot in simulation.history]
        lower = boundaries[encoding]
        hatch = area_axis.fill_between(
            x, lower, [base + value for base, value in zip(lower, values)],
            facecolor="none", edgecolor=_family_color(encoding),
            linewidth=0.0, hatch="////", step="mid",
        )
        hatch.set_alpha(0.85)
    area_axis.set_ylim(0, TOTAL_CAPACITY)
    area_axis.set_ylabel("Population size")
    area_axis.set_title("The Fittest - Population by Generation")
    area_axis.grid(alpha=0.2)
    area_axis.legend(
        handles=[
            *[Patch(facecolor=_family_color(encoding), label=encoding) for encoding in ordered],
            Patch(facecolor="white", edgecolor="#555555", hatch="////", label="Subspecies"),
            *[
                Patch(facecolor=_independent_color(encoding), label=f"{encoding} (独立)")
                for encoding in ordered
                if encoding in independent
            ],
        ],
        ncol=5,
        fontsize=8,
        loc="upper left",
        bbox_to_anchor=(0, -0.08),
        borderaxespad=0,
    )
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    occupied_boxes = [
        text.get_window_extent(renderer).expanded(1.08, 1.18)
        for text in area_axis.texts
    ]
    legend = area_axis.get_legend()
    if legend is not None:
        occupied_boxes.append(legend.get_window_extent(renderer).expanded(1.05, 1.1))

    def area_anchor(event: EvolutionEvent) -> tuple[float, float] | None:
        """Return the center of an event's own stacked-area band."""
        anchor_encoding = event.encoding
        # A subspecies can be evaluated and rejected in the same generation
        # in which it is created, so it may not appear in the next snapshot.
        # In that case anchor the label to the parent's band instead of
        # dropping the event entirely.
        if anchor_encoding not in boundaries:
            anchor_encoding = event.parent_encoding or event.encoding
        if anchor_encoding not in boundaries:
            return None
        # Events now carry the generation they created, which is exactly the
        # snapshot index where the new band appears.
        generation = max(0, min(event.generation, len(x) - 1))
        value = simulation.history[generation].get(anchor_encoding, 0)
        if value <= 0 and generation > 0:
            generation -= 1
            value = simulation.history[generation].get(anchor_encoding, 0)
        lower = boundaries[anchor_encoding][generation]
        height = max(float(value), 1.0)
        return float(generation), lower + height / 2

    annotation_boxes: list[Bbox] = []

    def place_event_annotation(
        text: str,
        anchor: tuple[float, float],
        color: str,
        box: dict[str, object],
        arrow: dict[str, object],
        candidates: list[tuple[int, int]],
    ) -> None:
        """Place a label while avoiding all previously rendered text boxes."""
        annotation = area_axis.annotate(
            text,
            xy=anchor,
            xytext=candidates[0],
            textcoords="offset points",
            color=color,
            fontsize=7,
            ha="left",
            va="bottom",
            bbox=box,
            arrowprops=arrow,
        )
        # Expand the supplied positions with a grid of increasingly distant
        # offsets. This guarantees that dense event clusters get a readable
        # placement instead of forcing labels on top of one another.
        expanded_candidates = list(candidates)
        for distance in (72, 108, 144, 192, 240):
            expanded_candidates.extend(
                [
                    (distance, distance // 2),
                    (distance, -distance // 2),
                    (-distance, distance // 2),
                    (-distance, -distance // 2),
                    (0, distance),
                    (0, -distance),
                ]
            )
        for offset in expanded_candidates:
            annotation.set_position(offset)
            fig.canvas.draw()
            current_box = annotation.get_window_extent(renderer).expanded(1.04, 1.12)
            if not any(
                current_box.overlaps(previous_box)
                for previous_box in [*occupied_boxes, *annotation_boxes]
            ):
                annotation_boxes.append(current_box)
                return
        # The expanded grid should normally find a free position. If the
        # canvas is genuinely full, retain the farthest tested position.
        annotation_boxes.append(current_box)

    for event in simulation.events:
        anchor = area_anchor(event)
        if anchor is None:
            continue
        anchor_x, anchor_y = anchor
        if event.event in {"extinction", "subspecies_extinction"}:
            area_axis.axvline(
                event.generation, color="#555555", linestyle=":", linewidth=0.8, alpha=0.7
            )
            label = "灭绝" if event.event == "extinction" else "亚种淘汰"
            color = "#d62728" if event.event == "extinction" else "#ff7f0e"
            place_event_annotation(
                f"× {event.encoding}\n{label} G{event.generation}",
                (anchor_x, anchor_y),
                color,
                {"boxstyle": "round,pad=0.25", "fc": "#fff5f5", "ec": color, "alpha": 0.9},
                {"arrowstyle": "->", "color": color, "lw": 0.8},
                [(8, -18), (8, -48), (80, -18), (-130, -18)],
            )
        elif event.event == "subspecies_birth":
            place_event_annotation(
                f"◇ 亚种生成\n{event.encoding}\nG{event.generation}",
                (anchor_x, anchor_y),
                "#1f77b4",
                {"boxstyle": "round,pad=0.2", "fc": "#f0f7ff", "ec": "#1f77b4", "alpha": 0.9},
                {"arrowstyle": "->", "color": "#1f77b4", "lw": 0.8},
                [(8, 10), (8, 40), (80, 10), (-130, 10)],
            )
        elif event.event == "subspecies_independent":
            area_axis.axvline(
                event.generation, color="#d62728", linestyle="--", linewidth=1.0, alpha=0.7
            )
            place_event_annotation(
                f"★ 亚种独立为新物种\n{event.encoding}\nG{event.generation}",
                (anchor_x, anchor_y),
                "#d62728",
                {"boxstyle": "round,pad=0.25", "fc": "#fff5f5", "ec": "#d62728", "alpha": 0.9},
                {"arrowstyle": "->", "color": "#d62728", "lw": 0.9},
                [(8, 12), (8, 44), (80, 12), (-130, 12)],
            )

    # Redraw independent populations with a new color so the transition is
    # immediately visible in the area chart.
    for encoding in independent:
        values = [snapshot.get(encoding, 0) for snapshot in simulation.history]
        if not any(values):
            continue
        area_axis.fill_between(
            x,
            boundaries[encoding],
            [
                lower + value
                for lower, value in zip(boundaries[encoding], values)
            ],
            color=_independent_color(encoding),
            alpha=0.18,
            step="mid",
            zorder=2,
        )

    live = {item.encoding: item for item in simulation.species}
    parent_events = [
        event for event in simulation.events
        if event.parent_encoding
        and event.event in {"subspecies_birth", "subspecies_independent"}
    ]
    child_encodings = {event.encoding for event in parent_events}
    tree_order = sorted(
        (set(ordered) - child_encodings)
        | {event.parent_encoding for event in parent_events if event.parent_encoding},
        key=lambda encoding: (birth_by_encoding.get(encoding, 0), encoding),
    )
    # Keep one fixed row per base strategy. Subspecies use small offsets around
    # that row, so adding branches never expands the tree's vertical scale.
    tree_y = {
        encoding: len(tree_order) - index
        for index, encoding in enumerate(tree_order)
    }
    child_positions: dict[tuple[str, str, int], float] = {}
    child_counts: dict[str, int] = {}
    for event in parent_events:
        parent = event.parent_encoding
        if parent not in tree_y:
            continue
        child_index = child_counts.get(parent, 0)
        child_counts[parent] = child_index + 1
        offsets = (0.28, -0.28, 0.48, -0.48, 0.68, -0.68)
        child_positions[(parent, event.encoding, event.generation)] = (
            tree_y[parent] + offsets[child_index % len(offsets)]
        )
        child_y = child_positions[(parent, event.encoding, event.generation)]
        independent_child = event.event == "subspecies_independent"
        tree_axis.plot(
            [event.generation - 0.35, event.generation],
            [tree_y[parent], child_y],
            color="#333333" if independent_child else "#888888",
            linewidth=2.0 if independent_child else 1.2,
            linestyle="-" if independent_child else "--",
            zorder=1,
        )
        tree_axis.scatter(
            event.generation,
            child_y,
            s=55,
            color=_independent_color(event.encoding)
            if independent_child
            else _family_color(event.encoding),
            edgecolor="black",
            zorder=3,
        )
        event_label = (
            f"★ {event.encoding} 独立 G{event.generation}"
            if independent_child
            else f"◇ {event.encoding} 生成 G{event.generation}"
        )
        tree_axis.text(
            event.generation + 0.12,
            child_y,
            event_label,
            color="#d62728" if independent_child else "#1f77b4",
            va="center",
            fontsize=7,
            bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.8, "pad": 1.5},
        )
    for encoding in tree_order:
        item = live.get(encoding)
        birth = birth_by_encoding.get(encoding, 0)
        y = tree_y[encoding]
        tree_axis.scatter(
            birth,
            y,
            s=max(30, (item.population_size if item else 8) * 10),
            color=_independent_color(encoding)
            if encoding in independent
            else _family_color(encoding),
            edgecolor="black",
            zorder=3,
        )
        tree_axis.text(
            birth + 0.12,
            y,
            encoding,
            va="center",
            fontsize=8,
            bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.8, "pad": 1.5},
        )
        for event in simulation.events:
            if event.encoding != encoding:
                continue
            if event.event in {"extinction", "subspecies_extinction"}:
                label = "灭绝" if event.event == "extinction" else "亚种淘汰"
                color = "#d62728" if event.event == "extinction" else "#ff7f0e"
                tree_axis.text(
                    event.generation + 0.12,
                    y - 0.18,
                    f"× {label} G{event.generation}",
                    color=color,
                    va="top",
                    fontsize=7,
                    bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.8, "pad": 1.5},
                )
    tree_axis.set_title("Evolution tree (solid = independent species, dashed = subspecies)")
    tree_axis.set_xlabel("Generation")
    tree_axis.set_yticks([])
    tree_axis.set_ylim(0.2, len(tree_order) + 0.8)
    tree_axis.grid(alpha=0.2)

    current_average = (
        sum(item.total_size * item.mixed_fitness for item in simulation.species)
        / max(sum(item.total_size for item in simulation.species), 1)
        if simulation.species else 0
    )
    best = max(simulation.species, key=lambda item: item.mixed_fitness, default=None)
    recent_extinction = next(
        (event for event in reversed(simulation.events) if event.event == "extinction"), None
    )
    recent_birth = next(
        (event for event in reversed(simulation.events) if event.event == "subspecies_independent"), None
    )
    stats_axis.axis("off")
    stats_axis.text(
        0.01, 0.75,
        f"Generation: {simulation.generation}/{generations}    "
        f"Surviving species: {len(simulation.species)}    "
        f"Average fitness: {current_average:.2f}",
        fontsize=11,
    )
    stats_axis.text(
        0.01, 0.35,
        f"Best: {best.encoding if best else '-'} ({best.total_size if best else 0}, {best.mixed_fitness if best else 0:.2f})    "
        f"Recent extinction: {recent_extinction.encoding if recent_extinction else '-'}    "
        f"Recent birth: {recent_birth.encoding if recent_birth else '-'}",
        fontsize=11,
    )
    fig.savefig(output_figure, dpi=160)
    plt.close(fig)


def build_report(simulation: TrustEvolution) -> dict:
    return {
        "parameters": {
            "TOTAL_CAPACITY": TOTAL_CAPACITY,
            "ALPHA_ALLOCATE": ALPHA_ALLOCATE,
            "ALPHA_INVASION": ALPHA_INVASION,
            "EXTINCTION_SIZE": EXTINCTION_SIZE,
            "EXTINCTION_FITNESS_RATIO": EXTINCTION_FITNESS_RATIO,
            "EXTINCTION_STREAK": EXTINCTION_STREAK,
            "SUBSPECIES_MIN_SIZE": SUBSPECIES_MIN_SIZE,
            "SUBSPECIES_MIN_RATIO": SUBSPECIES_MIN_RATIO,
            "SUBSPECIES_EXTINCTION_STREAK": SUBSPECIES_EXTINCTION_STREAK,
            "MUTATION_MIN_SIZE": MUTATION_MIN_SIZE,
            "MUTATION_WEIGHTS": MUTATION_WEIGHTS,
            "SUBSPECIES_STALL_GENERATIONS": SUBSPECIES_STALL_GENERATIONS,
            "STAGNATION_SEATS": STAGNATION_SEATS,
            "STAGNATION_GENERATIONS": STAGNATION_GENERATIONS,
            "TURNS_PER_MATCH": TURNS_PER_MATCH,
        },
        "history": simulation.history,
        "fitness_history": simulation.fitness_history,
        "events": [asdict(event) for event in simulation.events],
        "final_species": [asdict(item) for item in simulation.species],
        "generation_records": [
            {
                "generation": record.generation,
                "species_data": record.species_data,
                "average_fitness": record.average_fitness,
                "events": [asdict(event) for event in record.events],
                "matchup_matrix": record.matchup_matrix,
            }
            for record in simulation.generation_records
        ],
    }


def write_report(simulation: TrustEvolution, output_report: Path) -> None:
    output_report.write_text(
        json.dumps(build_report(simulation), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def configure_simulation(
    default_seed: int | None = None,
    default_generations: int = 40,
) -> tuple[int | None, list[str] | None, dict[str, int] | None, int] | None:
    """Show the run configuration window and return validated settings."""
    import tkinter as tk
    from tkinter import messagebox, scrolledtext

    result: dict[str, object] = {}
    root = tk.Tk()
    root.title("The Fittest - 进化模拟设置")
    root.geometry("650x560")
    root.resizable(False, False)

    mode = tk.StringVar(value="random")
    seed_var = tk.StringVar(value="" if default_seed is None else str(default_seed))
    generations_var = tk.StringVar(value=str(default_generations))
    custom_text = scrolledtext.ScrolledText(root, width=64, height=12)
    custom_text.insert(
        "1.0",
        "S1,25\nS2,20\nF1-1,15\nF2-3,15\nT1-2,10\nD0,10\nW,5",
    )

    tk.Label(root, text="选择初始种群生成方式", font=("Microsoft YaHei UI", 12, "bold")).pack(
        anchor="w", padx=20, pady=(18, 8)
    )
    for value, label in (
        ("random", "随机生成（每次不同）"),
        ("seed", "使用种子（可复现）"),
        ("custom", "自定义策略和规模"),
    ):
        tk.Radiobutton(root, text=label, variable=mode, value=value).pack(
            anchor="w", padx=35
        )

    form = tk.Frame(root)
    form.pack(fill="x", padx=35, pady=8)
    tk.Label(form, text="种子（仅种子模式）:").grid(row=0, column=0, sticky="w")
    tk.Entry(form, textvariable=seed_var, width=18).grid(row=0, column=1, sticky="w", padx=8)
    tk.Label(form, text="进化代数:").grid(row=1, column=0, sticky="w", pady=6)
    tk.Entry(form, textvariable=generations_var, width=18).grid(row=1, column=1, sticky="w", padx=8)

    tk.Label(
        root,
        text="自定义格式：每行一个“策略编码,规模”，规模总和必须为 100。",
        fg="#555555",
    ).pack(anchor="w", padx=35)
    custom_text.pack(padx=35, pady=(4, 8))

    def submit() -> None:
        try:
            generations = int(generations_var.get())
            if generations <= 0:
                raise ValueError("进化代数必须大于 0")
            selected_seed: int | None = None
            encodings: list[str] | None = None
            sizes: dict[str, int] | None = None
            if mode.get() == "seed":
                selected_seed = int(seed_var.get())
            elif mode.get() == "custom":
                encodings = []
                sizes = {}
                for line in custom_text.get("1.0", "end").splitlines():
                    if not line.strip():
                        continue
                    encoding, size_text = [part.strip() for part in line.split(",", 1)]
                    parse_strategy(encoding)
                    size = int(size_text)
                    if size <= 0 or encoding in sizes:
                        raise ValueError("策略编码不能重复，规模必须为正整数")
                    encodings.append(encoding)
                    sizes[encoding] = size
                if not encodings or sum(sizes.values()) != TOTAL_CAPACITY:
                    raise ValueError("自定义策略规模总和必须正好为 100")
            result.update(
                seed=selected_seed,
                encodings=encodings,
                sizes=sizes,
                generations=generations,
            )
            root.destroy()
        except (ValueError, IndexError) as error:
            messagebox.showerror("设置无效", str(error))

    def cancel() -> None:
        root.destroy()

    buttons = tk.Frame(root)
    buttons.pack(pady=8)
    tk.Button(buttons, text="开始模拟", width=14, command=submit).pack(side="left", padx=8)
    tk.Button(buttons, text="取消", width=14, command=cancel).pack(side="left", padx=8)
    root.protocol("WM_DELETE_WINDOW", cancel)
    root.mainloop()
    if not result:
        return None
    return (
        result["seed"],  # type: ignore[return-value]
        result["encodings"],  # type: ignore[return-value]
        result["sizes"],  # type: ignore[return-value]
        result["generations"],  # type: ignore[return-value]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run The Fittest simulation.")
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="随机种子；不提供时每次使用不同的系统随机起始状态。",
    )
    parser.add_argument(
        "--generations",
        type=int,
        default=40,
        help="模拟代数，默认 40。",
    )
    args = parser.parse_args()

    settings = configure_simulation(args.seed, args.generations)
    if settings is None:
        print("Simulation cancelled.")
        return
    seed, encodings, sizes, generations = settings
    if seed is None:
        seed = random.SystemRandom().randrange(0, 2**63)
    simulation = TrustEvolution(
        seed=seed,
        initial_encodings=encodings,
        initial_sizes=sizes,
    )
    simulation.run(generations)
    seed_name = f"seed_{seed}"
    output_figure = OUTPUT_DIR / f"trust_evolution_{seed_name}.png"
    plot_results(simulation, generations, output_figure)
    # The canonical archive is the single source of truth for a run; the legacy
    # results/ JSON is still written so existing tooling keeps working.
    write_report(simulation, OUTPUT_DIR / f"trust_evolution_{seed_name}.json")
    try:
        from evolution_archive import RUNS_DIR, save_run

        archived = save_run(
            simulation,
            seed=seed,
            name=f"cli_{seed_name}",
            note=f"命令行运行，{generations} 代",
            initial_encodings=encodings,
            initial_sizes=sizes,
        )
        print(f"Archived: {archived}")
    except Exception as error:  # noqa: BLE001 - archiving must not lose the run
        print(f"Warning: archive write failed ({error}); see the report above.")
    print(f"Generated: {output_figure}")
    print(f"Generated: {OUTPUT_DIR / f'trust_evolution_{seed_name}.json'}")


if __name__ == "__main__":
    main()
