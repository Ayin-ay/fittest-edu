"""Per-module Chinese explanations for a strategy encoding.

Text is fully parameter-substituted (no "A=..., B=..." placeholders):
e.g. ``P3-2`` -> "累计被单方面背叛（我合作、对手背叛）达 3 次后触发；触发后连续背叛 2 轮，之后重新计数。"
"""


def _default_text(token: str) -> tuple[str, str] | None:
    head = token[0]
    if token == "W":
        return "变色龙", "对手上一轮合作就跟着合作，否则翻转自己上一轮的动作（赢留输变）。"
    if head == "S":
        n = token[1:]
        if n == "0":
            return "老好人", "始终合作。"
        if n == "M":
            return "恶棍", "始终背叛。"
        return "警惕者", f"前 {n} 轮背叛，之后一直合作。"
    if head == "D":
        n = token[1:]
        tail = "平局时默认合作。" if n == "0" else "平局时默认背叛。"
        return "跟风者", "跟随对手历史多数出牌；" + tail
    if token.startswith("AD"):
        n = token[2:]
        tail = "平局时默认合作。" if n == "0" else "平局时默认背叛。"
        return "反骨仔", "反着对手历史多数出牌；" + tail
    if token.startswith("BS"):
        n = token[2:]
        return "背刺者", f"前面一直合作，到最后 {n} 轮连续背叛。"
    if head == "F" and "-" in token[1:]:
        n, m = token[1:].split("-", 1)
        return "钟摆", f"先连续合作 {n} 轮，再连续背叛 {m} 轮，如此循环。"
    if head == "T" and "-" in token[1:]:
        n, m = token[1:].split("-", 1)
        return "探子", f"先连续背叛 {n} 轮，再连续合作 {m} 轮，如此循环。"
    return None


def _trigger_text(token: str) -> tuple[str, str] | None:
    kind = "RC" if token.startswith("RC") else token[0]
    body = token[2:] if kind == "RC" else token[1:]
    if "-" not in body:
        return None
    a, b = body.split("-", 1)
    sustain = "持续到本局结束" if b == "M" else f"持续 {b} 轮"
    if kind == "P":
        return "反击", f"累计被单方面背叛（我合作、对手背叛）达 {a} 次后触发；触发后连续背叛，{sustain}，之后重新计数。"
    if kind == "H":
        return "投机", f"累计占到便宜（我背叛、对手没报复）达 {a} 次后触发；触发后连续背叛，{sustain}，之后重新计数。"
    if kind == "R":
        return "报复", f"对手最近连续 {a} 轮都在背叛时触发；触发后连续背叛，{sustain}。"
    if kind == "B":
        return "求和", f"双方最近 {a} 轮都在互相背叛时求和；求和后连续合作，{sustain}。"
    if kind == "K":
        return "示好", f"对手最近连续 {a} 轮都在合作时触发；触发后连续合作，{sustain}。"
    if kind == "RC":
        return "宽宥", f"对手最近 {a} 轮内出现由背叛转为合作的迹象时触发；触发后连续合作，{sustain}。"
    return None


def _modifier_text(token: str) -> tuple[str, str] | None:
    if token.startswith("M"):
        n = token[1:]
        if n.isdigit():
            return "失忆", f"只看最近 {n} 轮的历史来做判断。"
    if token.startswith("C"):
        body = token[1:]
        if "-" in body:
            n, direction = body.split("-", 1)
            if n.isdigit():
                pct = int(n) * 10
                if direction == "C":
                    return "心软", f"每轮有 {pct}% 的概率把合作翻成背叛。"
                return "心狠", f"每轮有 {pct}% 的概率把背叛翻成合作。"
        elif body.isdigit():
            return "神经质", f"每轮有 {int(body) * 10}% 的概率随机翻转出牌。"
    if token.startswith("RPT"):
        body = token[3:]
        if "-" in body:
            a, b = body.split("-", 1)
            sustain = "持续到本局结束" if b == "M" else f"持续 {b} 轮"
            window = "本局任意时刻" if a == "M" else f"最近 {a} 轮"
            return "悔改", f"自己{window}内出过背叛时，强制自己连续合作，{sustain}。"
    return None


def _is_trigger(token: str) -> bool:
    if token.startswith("RPT"):
        return False
    if token.startswith("RC"):
        return True
    return token[0] in {"P", "H", "B", "K", "R"}


def describe_token(token: str, trigger_index: int | None) -> tuple[str, str, str] | None:
    """Return (slot_label, module_name, text) for one token, or None."""
    if _is_trigger(token):
        info = _trigger_text(token)
        slot = f"触发槽{trigger_index + 1}" if trigger_index is not None else "触发槽"
    elif token.startswith(("C", "M", "RPT")):
        info = _modifier_text(token)
        slot = "修正槽"
    else:
        info = _default_text(token)
        slot = "默认槽"
    if info is None:
        return None
    module_name, text = info
    return slot, f"{token} {module_name}", text


def parse_strategy_detail(encoding: str) -> list[tuple[str, str, str]]:
    """Return ordered list of (slot_label, module_name, text) per module."""
    details: list[tuple[str, str, str]] = []
    trigger_index = 0
    for token in encoding.split("+"):
        info = describe_token(token, trigger_index if _is_trigger(token) else None)
        if info is None:
            continue
        details.append(info)
        if _is_trigger(token):
            trigger_index += 1
    return details
