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
    # "script": from a prepared transcript. "model": guessed by the local LLM from
    # the words, for uploaded audio. Agents treat a guessed label with care.
    speaker_source: str = "script"


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
    # "transcript": evidence is segment ids. "measure": the sentence is filled
    # in from questionnaire scores, so there is no transcript line to cite.
    source: str = "transcript"
    # A weak sentence that is about risk, or that the local model rejected:
    # signing waits until the therapist confirms it.
    must_confirm: bool = False
    # The local model was asked and said the cited lines do not support the sentence.
    model_rejected: bool = False
    # The therapist read a flagged sentence against the transcript and kept it as written.
    confirmed_by_therapist: bool = False


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
    # True when the line's speaker was guessed by the model, not confirmed.
    speaker_unconfirmed: bool = False


@dataclass
class RiskReport:
    level: str
    flags: list[RiskFlag] = field(default_factory=list)
    protective: list[RiskFlag] = field(default_factory=list)
    screening_asked: list[int] = field(default_factory=list)
    safety_actions: list[int] = field(default_factory=list)
    # Filled only when suicide or self-harm cues are present.
    checklist: list[dict] = field(default_factory=list)


def to_dict(obj) -> dict:
    return asdict(obj)
