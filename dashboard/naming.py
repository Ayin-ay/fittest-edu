"""Chinese naming for strategy encodings.

Naming rules (reconciled version):
- Trigger slots map to adjectives (A then B, joined by 「且 / 但」).
- The modifier slot (C) is an adjective.
- The default slot (D) is the final noun.
- If the default slot is missing but triggers exist, an implicit ``S0`` (善者)
  is used. If only modifiers exist, the modifier becomes the noun.
- Four modules: ``A且B的CD``; three A+B: ``A且B的D``; three A+C: ``A的C的D``;
  two A+D: ``A的D``; two C+D: ``C的D``.

Every valid module token has a Chinese name. The dictionaries below act as
*curated overrides*; anything not listed is generated from the module's
semantics so the output is always pure Chinese (never a raw code).
"""

from __future__ import annotations

# --- Curated overrides (user-provided table wins where present) ----------
ADJECTIVES = {
    "P1-1": "反击", "P1-2": "双倍反击", "P1-3": "三倍反击",
    "P2-1": "宽容", "P1-M": "绝情", "PM-1": "至善",
    "H1-1": "投机", "H1-M": "贪婪",
    "R1-1": "报复", "R1-2": "双倍报复", "R1-M": "血仇",
    "B1-2": "求和", "B1-3": "求和", "B1-M": "永和",
    "M1": "失忆", "M2": "失忆", "M3": "失忆",
    "C1": "神经质", "C2": "神经质", "C3": "神经质", "C4": "神经质",
    "C4-C": "心软", "C4-D": "心狠",
    "RPT1-1": "悔改", "RPT3-1": "悔改", "RPT1-M": "圣徒",
}

NOUNS = {
    "S0": "老好人", "S1": "警惕者", "S2": "警惕者", "S3": "警惕者",
    "SM": "恶棍",
    "F1": "钟摆", "F2": "双善钟摆", "F3": "双恶钟摆",
    "T2": "探子", "T3": "探子", "T4": "探子",
    "D0": "跟风者", "D1": "跟风者",
    "AD0": "反骨仔", "AD1": "反骨仔",
    "W": "变色龙",
    "BS1": "背刺者", "BS2": "背刺者", "BS3": "背刺者",
    "S0_IMPLICIT": "善者",
}

ADJ_TO_NOUN = {
    "反击": "反击者", "双倍反击": "双倍反击者", "三倍反击": "三倍反击者",
    "宽容": "宽容者", "绝情": "绝情者", "至善": "至善者",
    "投机": "投机者", "贪婪": "贪婪者",
    "报复": "报复者", "双倍报复": "双倍报复者", "血仇": "血仇者",
    "求和": "求和者", "永和": "永和者",
    "失忆": "失忆者", "神经质": "神经质者", "心软": "心软者",
    "心狠": "心狠者", "悔改": "悔改者", "圣徒": "圣徒",
}


def _classify(part: str) -> str | None:
    if part.startswith("AD") or part.startswith("BS"):
        return "default"
    if part.startswith("RPT"):
        return "modifier"
    if part.startswith("RC"):
        return "trigger"
    first = part[0]
    if first in "SFTD" or first == "W":
        return "default"
    if first in "PHRBK":
        return "trigger"
    if first in "MC":
        return "modifier"
    return None


def _split(part: str) -> tuple[str, str]:
    body = part[1:]
    if "-" in body:
        a_part, b = body.split("-", 1)
        return a_part, b
    return body, "1"


def _trigger_cn(part: str) -> str:
    """Collapse every trigger variant into the established vocabulary.

    No stacked compound adjectives like "忍双倍反击" — variants reuse the
    existing words of the same family (by the sustaining parameter B), and
    families without a curated entry fall back to one simple word.
    """
    if part in ADJECTIVES:
        return ADJECTIVES[part]
    if part.startswith("RC"):
        return "宽宥"
    kind = part[0]
    a_part, b = _split(part)
    if kind == "P":
        if a_part == "M":
            return "至善"
        if b == "M":
            return "绝情"
        if a_part != "1" and b == "1":
            return "宽容"
        return {"2": "双倍反击", "3": "三倍反击"}.get(b, "反击")
    if kind == "H":
        return "贪婪" if b == "M" else "投机"
    if kind == "R":
        if b == "M":
            return "血仇"
        return "双倍报复" if b == "2" else "报复"
    if kind == "B":
        return "永和" if b == "M" else "求和"
    return "示好" if kind == "K" else "反击"


def _modifier_cn(part: str) -> str:
    if part in ADJECTIVES:
        return ADJECTIVES[part]
    if part.startswith("RPT"):
        _a_part, b = part[3:].split("-", 1)
        return "圣徒" if b == "M" else "悔改"
    if part.startswith("C"):
        rest = part[1:]
        if "-" in rest:
            _n, direction = rest.split("-", 1)
            return "心软" if direction == "C" else "心狠"
        return "神经质"
    if part.startswith("M"):
        return "失忆"
    return "未知"


def _default_cn(part: str) -> str:
    if part in NOUNS:
        return NOUNS[part]
    if part == "S0_IMPLICIT":
        return "善者"
    if part.startswith("S"):
        return "警惕者" if part != "SM" else "恶棍"
    if part.startswith("BS"):
        return "背刺者"
    if part.startswith("AD"):
        return "反骨仔"
    if part in ("D0", "D1"):
        return "跟风者"
    if part == "W":
        return "变色龙"
    if part.startswith("F"):
        return {"1": "钟摆", "2": "双善钟摆", "3": "双恶钟摆"}.get(part[1], "钟摆")
    if part.startswith("T"):
        return "探子"
    return "无名氏"


def _nounify(adj: str) -> str:
    if adj in ADJ_TO_NOUN:
        return ADJ_TO_NOUN[adj]
    if adj.endswith(("者", "仔", "员", "摆", "子")):
        return adj
    return adj + "者"


def generate_name(encoding: str, connector: str = "且") -> str:
    """Return the Chinese name for a strategy encoding."""
    triggers: list[str] = []
    modifier: str | None = None
    default: str | None = None
    for part in encoding.split("+"):
        slot = _classify(part)
        if slot == "trigger":
            triggers.append(part)
        elif slot == "modifier":
            modifier = part
        elif slot == "default":
            default = part

    trigger_adj = [_trigger_cn(part) for part in triggers]
    modifier_adj = _modifier_cn(modifier) if modifier else None

    if default is None:
        if triggers:
            default = "S0_IMPLICIT"  # implicit cooperative baseline -> 善者
        elif modifier is not None:
            return _nounify(modifier_adj)
        else:
            return "无名氏"
    noun = _default_cn(default)

    if not trigger_adj:
        if modifier_adj:
            return f"{modifier_adj}的{noun}"
        return noun
    if len(trigger_adj) == 1:
        if modifier_adj:
            return f"{trigger_adj[0]}的{modifier_adj}的{noun}"
        return f"{trigger_adj[0]}的{noun}"
    if modifier_adj:
        return f"{trigger_adj[0]}{connector}{trigger_adj[1]}的{modifier_adj}{noun}"
    # Two adjectives + one noun: A的BD（如「双倍反击的宽宥智者」）
    return f"{trigger_adj[0]}的{trigger_adj[1]}{noun}"


def build_name_map(encodings: list[str], connector: str = "且") -> dict[str, str]:
    """Map encodings to unique Chinese names (deduplicate with a trailing number)."""
    seen: dict[str, int] = {}
    result: dict[str, str] = {}
    for encoding in dict.fromkeys(encodings):
        base = generate_name(encoding, connector)
        seen[base] = seen.get(base, 0) + 1
        result[encoding] = base if seen[base] == 1 else f"{base} {seen[base]}"
    return result