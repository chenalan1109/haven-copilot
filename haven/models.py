"""Shared data structures passed between Haven agents."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Segment:
    id: int
    start: float
    end: float
    speaker: str  # "therapist" | "client" | "unknown"
    text: str


@dataclass
class Transcript:
    session_id: str
    client_id: str
    session_no: int
    date: str
    segments: list[Segment]
    simulated: bool = True

    def by_id(self) -> dict[int, Segment]:
        return {s.id: s for s in self.segments}


@dataclass
class NoteSentence:
    text: str
    evidence: list[int]
    # Filled in by the verifier agent.
    status: str = "unchecked"  # supported | weak | unsupported
    support: float = 0.0
    reason: str = ""


@dataclass
class Note:
    template: str
    sections: dict[str, list[NoteSentence]]
    engine: str

    def sentences(self) -> list[NoteSentence]:
        return [s for items in self.sections.values() for s in items]


@dataclass
class RiskFlag:
    category: str
    level: str  # critical | high | review | info
    segment_id: int
    quote: str
    cue: str
    negated: bool = False


@dataclass
class RiskReport:
    level: str
    flags: list[RiskFlag] = field(default_factory=list)
    protective: list[RiskFlag] = field(default_factory=list)
    screening_asked: list[int] = field(default_factory=list)
    safety_actions: list[int] = field(default_factory=list)


def to_dict(obj) -> dict:
    return asdict(obj)
