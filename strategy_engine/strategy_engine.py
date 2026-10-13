"""Strategy-code generator, parser, explainer, and executor.

The engine only observes completed-round actions (C/D), never an opponent's
strategy code or internal state.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from typing import Optional

Action = str
VALID_ACTIONS = {"C", "D"}


def _require_action(action: Action) -> None:
    if action not in VALID_ACTIONS:
        raise ValueError("action must be 'C' or 'D'")


@dataclass(frozen=True)
class Module:
    code: str
    kind: str
    first: Optional[str] = None
    second: Optional[str] = None


DEFAULT_RE = re.compile(r"^(S[0-3M]|F[1-3]-[1-3]|T[1-3]-[1-3]|(?:AD|D)[01]|BS[1-3]|W)$")
TRIGGER_RE = re.compile(r"^(P|H|R|B|K|RC)([1-3])-(1|2|3|M)$")
RPT_RE = re.compile(r"^RPT(1|2|3|M)-(1|2|3|M)$")
M_RE = re.compile(r"^M[1-3]$")
C_RE = re.compile(r"^C[1-4](?:-[CD])?$")


@dataclass
class StrategyDefinition:
    code: str
    default: Module
    triggers: list[Module] = field(default_factory=list)
    modifier: Optional[Module] = None

    def explain(self) -> str:
        parts = [_explain_module(self.default)]
        parts.extend(_explain_module(module) for module in self.triggers)
        if self.modifier is not None:
            parts.append(_explain_module(self.modifier))
        return "\n".join(f"- {part}" for part in parts)


def _parse_module(token: str, slot: str) -> Module:
    if slot == "default":
        if not DEFAULT_RE.fullmatch(token):
            raise ValueError(f"invalid default module: {token}")
        if token.startswith("S"):
            return Module(token, "S", token[1:])
        if token.startswith("F"):
            n, m = token[1:].split("-")
            return Module(token, "F", n, m)
        if token.startswith("T"):
            n, m = token[1:].split("-")
            return Module(token, "T", n, m)
        if token.startswith("AD"):
            return Module(token, "AD", token[2:])
        if token.startswith("BS"):
            return Module(token, "BS", token[2:])
        if token.startswith("D"):
            return Module(token, "D", token[1:])
        return Module(token, "W")

    if slot == "trigger":
        match = TRIGGER_RE.fullmatch(token)
        if not match:
            raise ValueError(f"invalid trigger module: {token}")
        return Module(token, match.group(1), match.group(2), match.group(3))

    if slot == "modifier":
        if M_RE.fullmatch(token):
            return Module(token, "M", token[1:])
        if C_RE.fullmatch(token):
            body = token[1:].split("-")
            return Module(token, "C", body[0], body[1] if len(body) == 2 else None)
        match = RPT_RE.fullmatch(token)
        if match:
            return Module(token, "RPT", match.group(1), match.group(2))
        raise ValueError(f"invalid modifier module: {token}")

    raise ValueError(f"unknown slot: {slot}")


def parse_strategy(code: str) -> StrategyDefinition:
    tokens = [token.strip() for token in code.split("+")]
    if not tokens or any(not token for token in tokens) or len(tokens) > 4:
        raise ValueError("strategy must contain one to four non-empty modules")

    default: Optional[Module] = None
    triggers: list[Module] = []
    modifier: Optional[Module] = None
    for token in tokens:
        if DEFAULT_RE.fullmatch(token):
            if default is not None:
                raise ValueError("a strategy may contain at most one default module")
            default = _parse_module(token, "default")
        elif M_RE.fullmatch(token) or C_RE.fullmatch(token) or RPT_RE.fullmatch(token):
            if modifier is not None:
                raise ValueError("a strategy may contain at most one modifier")
            modifier = _parse_module(token, "modifier")
        elif token.startswith(("P", "H", "R", "B", "K", "RC")):
            if modifier is not None:
                raise ValueError("a trigger cannot follow a modifier")
            if len(triggers) >= 2:
                raise ValueError("a strategy may contain at most two trigger modules")
            triggers.append(_parse_module(token, "trigger"))
        else:
            raise ValueError(f"unknown module: {token}")

    if default is None:
        default = _parse_module("S0", "default")
    if modifier is not None and modifier.kind == "RPT":
        # M and RPT are mutually exclusive by occupying the same slot.
        pass
    return StrategyDefinition(code, default, triggers, modifier)


def _explain_module(module: Module) -> str:
    if module.kind == "S":
        return f"{module.code}: 前{module.first}轮背叛，之后合作" if module.first != "M" else "SM: 永久背叛"
    if module.kind == "F":
        return f"{module.code}: 合作{module.first}轮、背叛{module.second}轮循环"
    if module.kind == "T":
        return f"{module.code}: 背叛{module.first}轮、合作{module.second}轮循环"
    if module.kind == "D":
        return f"{module.code}: 跟随对手历史多数，默认{module.first}"
    if module.kind == "AD":
        return f"{module.code}: 反跟随对手历史多数，默认{module.first}"
    if module.kind == "W":
        return "W: 上一回合C/C留在原动作，其他结果改变自身上一动作"
    if module.kind == "BS":
        return f"{module.code}: 前段合作，最后{module.first}轮背叛（需要外部总回合数）"
    if module.kind in {"P", "H", "R", "B", "K", "RC"}:
        return f"{module.code}: 触发后输出{'D' if module.kind in {'P', 'H', 'R'} else 'C'}，持续{module.second}轮"
    if module.kind == "M":
        return f"{module.code}: 前方历史统计只看最近{module.first}个已完成回合"
    if module.kind == "C":
        target = "任意输出" if module.second is None else f"仅{module.second}输出"
        return f"{module.code}: {target}按{int(module.first) * 10}%概率翻转"
    if module.kind == "RPT":
        return f"{module.code}: 自身最近{module.first}轮有D时强制合作{module.second}轮"
    raise ValueError(f"unknown module kind: {module.kind}")


def random_strategy(rng: Optional[random.Random] = None) -> StrategyDefinition:
    rng = rng or random.Random()
    defaults = [
        "S1", "S2", "F1-1", "F2-3", "T1-2", "D0", "D1", "AD0", "AD1", "W", "BS1", "BS2", "BS3"
    ]
    trigger_kinds = ["P", "H", "R", "B", "K", "RC"]
    triggers = []
    for _ in range(rng.randint(1, 2)):
        kind = rng.choice(trigger_kinds)
        response = rng.choice(["1", "2", "3", "M"])
        if kind == "B":
            response = rng.choice(["2", "3", "M"])
        triggers.append(f"{kind}{rng.randint(1, 3)}-{response}")
    modifier = rng.choice(["", "M1", "M2", "M3", "C2", "C3", "C4-C", "C2-D", "RPT1-1"])
    if modifier == "RPT1-1" and any(trigger for trigger in triggers):
        # RPT is valid with triggers; M is the only incompatible modifier.
        pass
    return parse_strategy("+".join([rng.choice(defaults), *triggers, modifier] if modifier else [rng.choice(defaults), *triggers]))


@dataclass
class StrategyState:
    definition: StrategyDefinition
    total_turns: int
    own_history: list[Action] = field(default_factory=list)
    opponent_history: list[Action] = field(default_factory=list)
    active_remaining: dict[str, int] = field(default_factory=dict)
    trigger_reset_at: dict[str, int] = field(default_factory=lambda: {"P": 0, "H": 0})
    b_converted: bool = False
    rpt_failed: bool = False
    # Optional random source for probabilistic modifiers. When omitted the
    # process-wide ``random`` module is used, preserving standalone behavior.
    rng: random.Random | None = None

    def decide(self, opponent_action_history: list[Action]) -> Action:
        if len(opponent_action_history) != len(self.own_history):
            raise ValueError("both histories must contain exactly the completed rounds")
        if any(action not in VALID_ACTIONS for action in opponent_action_history):
            raise ValueError("opponent history contains an invalid action")
        self.opponent_history = list(opponent_action_history)

        if self.b_converted:
            action = self.opponent_history[-1] if self.opponent_history else "C"
            self._record(action)
            return action

        if self._rpt_is_active():
            if self.own_history and self.own_history[-1] == "C" and self.opponent_history[-1:] == ["D"]:
                self.rpt_failed = True
                self.active_remaining.pop("RPT", None)
            else:
                action = "C"
                self._record(action)
                return action

        output = self._default_output()
        for module in self.definition.triggers:
            triggered, action = self._trigger_output(module)
            if triggered:
                output = action

        modifier = self.definition.modifier
        if modifier is not None and modifier.kind == "RPT" and not self.rpt_failed:
            if self._rpt_condition(modifier):
                self.active_remaining["RPT"] = _remaining(modifier.second, self.total_turns, len(self.own_history)) - 1
                output = "C"
                self._record(output)
                return output
        output = self._apply_modifier(output)
        self._record(output)
        return output

    def _record(self, action: Action) -> None:
        self.own_history.append(action)

    def _window(self) -> tuple[list[Action], list[Action]]:
        modifier = self.definition.modifier
        size = int(modifier.first) if modifier and modifier.kind == "M" else None
        if size is None:
            return self.own_history, self.opponent_history
        return self.own_history[-size:], self.opponent_history[-size:]

    def _default_output(self) -> Action:
        module = self.definition.default
        turn = len(self.own_history) + 1
        if module.kind == "S":
            return "D" if module.first == "M" or turn <= int(module.first) else "C"
        if module.kind == "F":
            cycle = int(module.first) + int(module.second)
            return "C" if (turn - 1) % cycle < int(module.first) else "D"
        if module.kind == "T":
            cycle = int(module.first) + int(module.second)
            return "D" if (turn - 1) % cycle < int(module.first) else "C"
        if module.kind in {"D", "AD"}:
            counts = {"C": self.opponent_history.count("C"), "D": self.opponent_history.count("D")}
            default = "D" if module.first == "1" else "C"
            majority = default if counts["C"] == counts["D"] else ("C" if counts["C"] > counts["D"] else "D")
            return majority if module.kind == "D" else ("D" if majority == "C" else "C")
        if module.kind == "W":
            if not self.own_history:
                return "C"
            if self.opponent_history[-1:] == ["C"] and self.own_history[-1] == "C":
                return "C"
            return "D" if self.own_history[-1] == "C" else "C"
        if module.kind == "BS":
            return "D" if turn > self.total_turns - int(module.first) else "C"
        raise ValueError(f"unsupported default module: {module.kind}")

    def _trigger_output(self, module: Module) -> tuple[bool, Action]:
        kind = module.kind
        if kind in self.active_remaining:
            remaining = self.active_remaining[kind]
            if remaining > 0:
                self.active_remaining[kind] = remaining - 1
                if kind == "B" and self.opponent_history[-1:] == ["C"]:
                    self.b_converted = True
                return True, "D" if kind in {"P", "H", "R"} else "C"
            self.active_remaining.pop(kind, None)

        own, opponent = self._window()
        triggered = False
        if kind in {"P", "H"}:
            window_size = (
                int(self.definition.modifier.first)
                if self.definition.modifier and self.definition.modifier.kind == "M"
                else len(self.opponent_history)
            )
            start = max(0, len(self.opponent_history) - window_size)
            start = max(start, self.trigger_reset_at[kind])
            events = zip(self.own_history[start:], self.opponent_history[start:])
            if kind == "P":
                current = sum(a == "C" and b == "D" for a, b in events)
            else:
                current = sum(a == "D" and b == "C" for a, b in events)
            if current >= int(module.first):
                triggered = True
                self.trigger_reset_at[kind] = len(self.opponent_history)
        elif kind == "R":
            triggered = len(opponent) >= int(module.first) and all(
                action == "D" for action in opponent[-int(module.first):]
            )
        elif kind in {"B", "K"}:
            if len(opponent) >= int(module.first):
                recent_opponent = opponent[-int(module.first):]
                if kind == "B":
                    recent_own = own[-int(module.first):]
                    triggered = all(a == "D" and b == "D" for a, b in zip(recent_own, recent_opponent))
                else:
                    triggered = all(action == "C" for action in recent_opponent)
        elif kind == "RC":
            a = int(module.first)
            for offset in range(a):
                newer = len(opponent) - 1 - offset
                older = newer - 1
                if older >= 0 and opponent[older] == "D" and opponent[newer] == "C":
                    triggered = True
                    break

        if triggered:
            self.active_remaining[kind] = _remaining(module.second, self.total_turns, len(self.own_history)) - 1
            return True, "D" if kind in {"P", "H", "R"} else "C"
        return False, "C"

    def _rpt_condition(self, module: Module) -> bool:
        if module.first == "M":
            return "D" in self.own_history
        size = int(module.first)
        return len(self.own_history) >= size and "D" in self.own_history[-size:]

    def _rpt_is_active(self) -> bool:
        return self.active_remaining.get("RPT", 0) > 0

    def _apply_modifier(self, output: Action) -> Action:
        modifier = self.definition.modifier
        if modifier is None or modifier.kind == "M":
            return output
        if modifier.kind == "C":
            probability = int(modifier.first) / 10
            if modifier.second is None or (modifier.second == "D" and output == "C") or (
                modifier.second == "C" and output == "D"
            ):
                if (self.rng or random).random() < probability:
                    return "D" if output == "C" else "C"
        return output


def _remaining(value: str, total_turns: int, completed_turns: int) -> int:
    if value == "M":
        return max(total_turns - completed_turns, 1)
    return int(value)
