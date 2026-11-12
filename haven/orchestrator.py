"""Orchestrator agent: runs the specialist agents for one session and assembles the result."""

from __future__ import annotations

import json
import time

from . import config, signing, store
from .agents.memory import CaseMemory
from .agents.outcome import OutcomeAgent
from .agents.risk import RiskAgent
from .agents.speakers import SpeakerAgent
from .agents.verifier import VERIFIER_VERSION, Verifier
from .agents.writer import NoteWriter
from .llm import get_llm
from .models import Note, NoteSentence, to_dict
from .transcript import load_transcript


def load_clients() -> list[dict]:
    return json.loads(config.CLIENTS_FILE.read_text(encoding="utf-8"))


def get_client(client_id: str) -> dict:
    for c in load_clients():
        if c["id"] == client_id:
            return c
    raise KeyError(client_id)


class Orchestrator:
    def __init__(self, llm=None, use_llm: bool = True):
        self.llm = llm if llm is not None else (get_llm() if use_llm else None)
        self.writer = NoteWriter(self.llm)
        self.verifier = Verifier(self.llm)
        self.risk = RiskAgent()
        self.outcome = OutcomeAgent()
        self.memory = CaseMemory(self.llm)
        self.speakers = SpeakerAgent(self.llm)

    @property
    def engine(self) -> str:
        return self.llm.label if self.llm else "rule-based demo"

    def measure_sentences(self, client: dict, session_no: int) -> list[str]:
        """The score lines for one session, built from the questionnaire data. These
        are the only sentences accepted as source="measure"."""
        return [s["text"] for s in self.outcome.note_sentences(client, session_no)]

    def process_session(self, session_id: str, template: str = "SOAP") -> dict:
        # A signed note is the record. Nothing that could replace what the
        # therapist sees for that session runs after signing.
        if store.get_signature(session_id):
            raise store.AlreadySignedError(session_id)
        timings: dict[str, float] = {}

        def timed(name, fn, *args):
            t0 = time.perf_counter()
            out = fn(*args)
            timings[name] = round((time.perf_counter() - t0) * 1000, 1)
            return out

        transcript = timed("asr", load_transcript, session_id)
        client = get_client(transcript.client_id)
        transcript.client_age = client.get("age")
        note = timed("writer", self.writer.run, transcript, template)
        # Scores go into the objective section from the questionnaire data itself,
        # so the model never restates (and never misstates) a number.
        measures = self.measure_sentences(client, transcript.session_no)
        scores = [NoteSentence(text, [], source="measure") for text in measures]
        objective = "O" if template == "SOAP" else "D"
        note.sections[objective] = scores + note.sections.get(objective, [])
        verification = timed("verifier", self.verifier.run, note, transcript, measures)
        risk = timed("risk", self.risk.run, transcript)
        outcome = timed("outcome", self.outcome.run, client)

        result = {
            "session_id": session_id,
            "client_id": client["id"],
            "session_no": transcript.session_no,
            "date": transcript.date,
            "simulated": transcript.simulated,
            # What actually wrote this draft: the model's name, or the rule engine when the model did not answer.
            "engine": note.engine,
            "warnings": note.warnings + verification.get("warnings", []),
            "transcript": [to_dict(s) for s in transcript.segments],
            "note": to_dict(note),
            "verification": verification,
            "risk": to_dict(risk),
            # High-level risk cues no note sentence cites yet; signing waits for them.
            "risk_uncovered": signing.uncovered_risk(to_dict(risk), note),
            "outcome": outcome,
            "timings_ms": timings,
        }
        store.save_result(session_id, result)
        signing.remember(session_id, note, verification.get("llm_failed", False))
        store.audit("process_session", f"{session_id} engine={note.engine}" + (f" configured={self.engine}" if note.engine != self.engine else "")
                    + ("; verifier: local model did not answer" if verification.get("llm_failed") else ""))
        return result

    def refresh(self, result: dict) -> dict:
        """Re-checks a stored draft written under older verifier rules: the note
        text is kept, every sentence is verified again and the risk cues are
        scanned again."""
        session_id = result["session_id"]
        transcript = load_transcript(session_id)
        client = get_client(transcript.client_id)
        transcript.client_age = client.get("age")
        measures = self.measure_sentences(client, transcript.session_no)
        stored = result["note"]
        note = Note(stored["template"], {
            k: [NoteSentence(s["text"], list(s.get("evidence", [])), source="measure" if s["text"] in measures and not s.get("evidence") else "transcript")
                for s in items]
            for k, items in stored["sections"].items()
        }, stored.get("engine", ""), stored.get("warnings", []))
        result["verification"] = self.verifier.run(note, transcript, measures)
        result["note"] = to_dict(note)
        result["risk"] = to_dict(self.risk.run(transcript))
        result["risk_uncovered"] = signing.uncovered_risk(result["risk"], note)
        result["warnings"] = stored.get("warnings", []) + result["verification"].get("warnings", [])
        store.save_result(session_id, result)
        signing.remember(session_id, note, result["verification"].get("llm_failed", False))
        store.audit("reverify_stored_draft", f"{session_id} verifier={VERIFIER_VERSION}")
        return result

    def brief(self, client_id: str) -> dict:
        """Pre-session brief: last plan, last risk picture, outcome alerts."""
        client = get_client(client_id)
        # Uses stored results only, so opening a client never waits on the model.
        sessions = client.get("sessions", [])
        last = store.get_result(sessions[-1]) if sessions else None
        plan = []
        if last:
            # Prefer the signed note; otherwise show only sentences the verifier backed.
            signed = store.get_signed_note(last["session_id"])
            sections = (signed or last["note"])["sections"]
            plan = [s["text"] for s in sections.get("P", []) if signed or s.get("status") == "supported"]
        return {
            "client": client,
            "last_session": last and {
                "session_id": last["session_id"],
                "session_no": last["session_no"],
                "date": last["date"],
                "risk_level": last["risk"]["level"],
            },
            "plan": plan,
            "outcome": self.outcome.run(client),
        }
