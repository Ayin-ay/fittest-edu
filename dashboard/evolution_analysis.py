"""Turn a finished evolution into something a model can actually read.

The game mode hands the model a step-by-step record of one player's moves. The
creation mode has no player: what happened is an *evolution* -- which strategies
rose, which were driven out, what shifted the fitness average, and when. This
module reduces that to a compact text digest so the same streaming pipeline can
report on it.

Deliberately lossy. A full run can hold hundreds of generations and dozens of
species; sending all of it would be both expensive and unreadable. The digest
keeps the shape of the run -- start, turning points, end -- plus the per-turn
detail of whichever generations the caller asks to expand.
"""

from __future__ import annotations

from dashboard import theme  # noqa: F401  (kept for colour constants elsewhere)


def _fitness(value: float) -> str:
    return "{:.2f}".format(value)


def summarise(simulation, names: dict, max_turning_points: int = 6) -> str:
    """The narrative of a run: how it opened, when it turned, how it ended."""
    records = simulation.generation_records
    if not records:
        return "这次演化还没有任何数据。"

    first = records[0]
    last = records[-1]
    total = len(records) - 1

    lines = [
        "本次演化共 {} 代（不含初始代）。".format(total),
        "开局：{} 个物种，平均适应度 {}。".format(
            len(first.species_data), _fitness(first.average_fitness)),
        "终局：{} 个物种，平均适应度 {}。".format(
            len(last.species_data), _fitness(last.average_fitness)),
    ]

    # Turning points: the generations where the fitness average moved most.
    # That finds the moments worth reading about, instead of reporting every
    # generation and letting them blur together.
    moves = []
    for index in range(1, len(records)):
        delta = records[index].average_fitness - records[index - 1].average_fitness
        moves.append((abs(delta), index, delta))
    moves.sort(reverse=True)

    chosen = sorted(index for _, index, _ in moves[:max_turning_points])
    if chosen:
        lines.append("")
        lines.append("变化最大的几代：")
        for index in chosen:
            delta = records[index].average_fitness - records[index - 1].average_fitness
            direction = "上升" if delta > 0 else ("下降" if delta < 0 else "持平")
            lines.append(
                "  第 {} 代：平均适应度 {}（较上一代{} {}），存活 {} 个物种。".format(
                    index, _fitness(records[index].average_fitness),
                    direction, _fitness(abs(delta)),
                    len(records[index].species_data),
                )
            )

    return "\n".join(lines)


def generation_detail(simulation, names: dict, generation: int) -> str:
    """One generation in full: who held how many seats, and what happened."""
    records = simulation.generation_records
    if not 0 <= generation < len(records):
        return ""
    record = records[generation]

    lines = [
        "第 {} 代：平均适应度 {}，物种数 {}。".format(
            generation, _fitness(record.average_fitness),
            len(record.species_data)),
        "份额前几名：",
    ]
    ordered = sorted(
        record.species_data.items(),
        key=lambda item: -(item[1].get("population_size", 0)
                          + (item[1]["subspecies"]["size"]
                             if item[1].get("subspecies") else 0)),
    )[:8]
    for code, data in ordered:
        size = data.get("population_size", 0)
        sub = data.get("subspecies")
        if sub:
            size += sub["size"]
        label = names.get(code, code) if names else code
        lines.append("  {}　{}　席位 {}".format(code, label, size))

    events = [e for e in simulation.events if e.generation == generation]
    if events:
        lines.append("本代事件：")
        for event in events:
            lines.append("  {}".format(
                event.message if hasattr(event, "message") else event))
    return "\n".join(lines)


def build_digest(simulation, names: dict, generations: list[int] | None = None,
                 max_turning_points: int = 6) -> str:
    """The text handed to the model.

    ``generations`` names generations to expand in full; without it only the
    run's shape is sent, which keeps a long run affordable.
    """
    parts = [
        "以下是一场信任演化模拟的结果摘要。",
        "",
        summarise(simulation, names, max_turning_points=max_turning_points),
    ]
    for generation in (generations or []):
        detail = generation_detail(simulation, names, generation)
        if detail:
            parts.extend(["", detail])
    return "\n".join(parts)


EVOLUTION_SYSTEM_PROMPT = """\
你是一位分析「演化模拟」的研究者，面向的对象是运行这场模拟的人。

这场模拟里没有玩家操作：每一种策略是一个物种，它们在重复的囚徒困境中相互
交锋，占据有限的席位（座位），适应度低的被淘汰、适应度高的扩张。亚种会
变异出新的组合，某些组合会被推平。

请回答：

1. 这场演化里**谁赢了、为什么**。指出具体是哪几个策略（或它们的编码），
   以及它们的行为特征说明了什么。
2. **变化发生在什么时候**。哪些代是转折点，那一代发生了什么。
3. **被淘汰的那些**有什么共同点。把它们和存活下来的对比来看。
4. 这场演化对「策略演化」本身说明什么——哪些结论只是这一次运行的偶然，
   哪些更可能是普遍的。

写作要求：

* 用简体中文，平实、具体，**不要写成空泛的感想**。
* 每个判断都要挂靠在上面给出的数据上（具体哪一代、哪个策略、多少份额）。
  数据支撑不了的，明确说「这一份摘要看不出」。
* 不要使用人格类型或性格标签（MBTI、大五人格、「你是一个……的人」这类），
  这里分析的是策略不是人。
* 不要复述摘要的全部内容，只挑真正值得说的。
"""