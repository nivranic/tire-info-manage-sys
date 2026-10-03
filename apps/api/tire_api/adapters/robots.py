"""Small robots policy with wildcard/end-anchor and longest-rule semantics.

Unlike urllib.robotparser, this understands the wildcard rules used by the
manufacturer sites. Network failures never construct an allow-all policy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import quote, urlsplit


def _normalize_path(value: str) -> str:
    def normalize_escape(match: re.Match) -> str:
        number = int(match.group(0)[1:], 16)
        char = chr(number)
        return char if char.isascii() and (char.isalnum() or char in "-._~") else f"%{number:02X}"
    escaped = re.sub(r"%[0-9a-fA-F]{2}", normalize_escape, value)
    return quote(escaped, safe="/?=&:;%+~!$'()*,-._")


@dataclass(frozen=True)
class Rule:
    allow: bool
    pattern: str

    @property
    def specificity(self) -> int:
        return len(self.pattern.rstrip("$").replace("*", "").encode("utf-8"))

    def matches(self, path: str) -> bool:
        anchored = self.pattern.endswith("$")
        pattern = self.pattern[:-1] if anchored else self.pattern
        regex = "^" + ".*".join(re.escape(part) for part in pattern.split("*"))
        return re.search(regex + ("$" if anchored else ""), path) is not None


@dataclass
class Group:
    agents: list[str] = field(default_factory=list)
    rules: list[Rule] = field(default_factory=list)
    interval: float = 0


class RobotsPolicy:
    def __init__(self, body: str, user_agent: str):
        groups: list[Group] = []
        current: Group | None = None
        has_records = False
        for original in body.splitlines():
            line = original.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            name, value = (part.strip() for part in line.split(":", 1))
            name = name.casefold()
            if name == "user-agent":
                if current is None or has_records:
                    current = Group()
                    groups.append(current)
                    has_records = False
                current.agents.append(value.casefold())
            elif current is not None:
                has_records = True
                if name in ("allow", "disallow") and value:
                    current.rules.append(Rule(name == "allow", _normalize_path(value)))
                elif name == "crawl-delay":
                    try:
                        number = float(value)
                        if 0 <= number <= 604800:
                            current.interval = max(current.interval, number)
                    except ValueError:
                        pass
                elif name == "request-rate":
                    match = re.fullmatch(r"(\d+)\s*/\s*(\d+)", value)
                    if match and int(match[1]) > 0:
                        current.interval = max(current.interval, int(match[2]) / int(match[1]))
        agent = user_agent.casefold().split("/", 1)[0]
        matched: list[tuple[int, Group]] = []
        for group in groups:
            specificity = max((len(value) for value in group.agents if value != "*" and value and value in agent), default=-1)
            if specificity >= 0:
                matched.append((specificity, group))
            elif "*" in group.agents:
                matched.append((0, group))
        maximum = max((score for score, _ in matched), default=-1)
        active = [group for score, group in matched if score == maximum]
        self.rules = [rule for group in active for rule in group.rules]
        self.minimum_interval = max((group.interval for group in active), default=0)

    def can_fetch(self, url: str) -> bool:
        parsed = urlsplit(url)
        path = _normalize_path((parsed.path or "/") + ("?" + parsed.query if parsed.query else ""))
        matching = [rule for rule in self.rules if rule.matches(path)]
        if not matching:
            return True
        rule = max(matching, key=lambda entry: (entry.specificity, entry.allow))
        return rule.allow

