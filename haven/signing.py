"""The signing gate, decided on the server from the server's own data.

The browser sends the note the therapist wants to sign: the sentence texts, the
segments each one cites, which flagged sentences the therapist confirmed, and
which risk cues the therapist chose to leave out (with a reason). Everything
else is worked out here: a ``status``, ``support``, ``source`` or
``must_confirm`` sent by the browser is ignored.
"""

from __future__ import annotations

import hashlib
import json

from . import config, store
from .agents.verifier import VERIFIER_VERSION, Verifier
from .agents.writer import TEMPLATES
from .models import Note, NoteSentence, Transcript, to_dict

SECTION_KEYS = {name: tuple(sections) for name, sections in TEMPLATES.items()}
GATED_LEVELS = ("high", "critical")
MAX_TEXT = 2000
MAX_REASON = 500
MIN_REASON = 2


class BadNote(ValueError):
    """The payload is not a note (wrong types); answered with 400."""


def transcript_sha256(session_id: str) -> str:
    return hashlib.sha256((config.SESSIONS_DIR / f"{session_id}.json").read_bytes()).hexdigest()


def note_sha256(note: dict) -> str:
    return hashlib.sha256(json.dumps(note, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _key(text: str, evidence: list[int]) -> tuple[str, str]:
    return text, json.dumps(evidence)


def remember(session_id: str, note: Note, llm_failed: bool = False, by_model: bool = False) -> None:
    """Stores the server's verdict on each transcript sentence of ``note``.
    ``by_model``: a local model was there to rule on the sentences the rules
    could not settle. A verdict made without one is not reused by a check that
    has a model, so turning the model on later does change the result."""
    verdicts = {}
    for s in note.sentences():
        if s.source == "measure" or s.status == "unchecked":
            continue
        if llm_failed and s.status != "supported":
            continue  # the model did not answer: ask again next time
        verdicts[_key(s.text, s.evidence)] = {"status": s.status, "support": s.support, "reason": s.reason,
                                              "model_rejected": s.model_rejected, "by_model": by_model and not llm_failed}
    if verdicts:
        store.save_verdicts(session_id, transcript_sha256(session_id), VERIFIER_VERSION, verdicts)


def note_from_payload(session_id: str, payload, template: str, engine: str, measures: list[str], with_model: bool = False) -> tuple[Note, list[str]]:
    """Builds the note to check from what the browser sent. Returns the note and the
    texts sent as score lines that are not the server's score lines. With
    ``with_model``, a cached verdict the rules alone reached (other than
    "supported") is set aside so the model gets its turn."""
    if not isinstance(payload, dict) or not isinstance(payload.get("sections"), dict):
        raise BadNote("note.sections must be an object")
    if payload.get("template") in SECTION_KEYS:
        template = payload["template"]
    known = store.get_verdicts(session_id, transcript_sha256(session_id), VERIFIER_VERSION)
    sections: dict[str, list[NoteSentence]] = {k: [] for k in SECTION_KEYS[template]}
    forged: list[str] = []
    for key, items in payload["sections"].items():
        if key not in sections:
            raise BadNote(f"section {key!r} is not part of a {template} note")
        if not isinstance(items, list):
            raise BadNote(f"section {key} must be a list")
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("text", ""), str):
                raise BadNote("each sentence must be an object with a text")
            text = item.get("text", "").strip()
            if not text:
                continue
            if len(text) > MAX_TEXT:
                raise BadNote("sentence too long")
            evidence = item.get("evidence", [])
            if not isinstance(evidence, list) or not all(isinstance(e, int) and not isinstance(e, bool) for e in evidence):
                raise BadNote("evidence must be a list of segment numbers")
            confirmed = item.get("confirmed_by_therapist") is True
            keep_reason = item.get("keep_reason", "")
            if not isinstance(keep_reason, str) or len(keep_reason) > MAX_REASON:
                raise BadNote("keep_reason must be a short text")
            if text in measures and not evidence:
                sections[key].append(NoteSentence(text, [], source="measure"))
                continue
            if item.get("source") == "measure":
                forged.append(text)
            s = NoteSentence(text, evidence, confirmed_by_therapist=confirmed,
                             keep_reason=keep_reason.strip() if confirmed and not evidence else "")
            seen = known.get(_key(text, evidence))
            if seen and with_model and not seen.get("by_model") and seen["status"] != "supported":
                seen = None
            if item.get("source") == "measure":
                s.source = "measure"  # the verifier turns it into an unsupported claim
            elif seen:
                s.status, s.support, s.reason, s.model_rejected = seen["status"], seen["support"], seen["reason"], bool(seen.get("model_rejected"))
            sections[key].append(s)
    return Note(template, sections, engine), forged


def uncovered_risk(risk: dict, note: Note | dict, dismissals: list[dict] = ()) -> list[dict]:
    """High-level risk cues that no note sentence cites and the therapist has not
    left out with a reason. A note that leaves a disclosure out can read as if
    the therapist never heard it, so these block signing."""
    if isinstance(note, Note):
        cited = {e for s in note.sentences() for e in s.evidence}
    else:
        cited = {e for items in note.get("sections", {}).values() for s in items for e in s.get("evidence", [])}
    left_out = {d["segment_id"] for d in dismissals}
    out, seen = [], set()
    for f in risk.get("flags", []):
        seg = f["segment_id"]
        if f["level"] in GATED_LEVELS and seg not in cited and seg not in left_out and seg not in seen:
            seen.add(seg)
            out.append({"segment_id": seg, "category": f["category"], "level": f["level"], "quote": f["quote"]})
    return out


def parse_dismissals(raw) -> list[dict]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise BadNote("risk_dismissals must be a list")
    out = []
    for d in raw:
        if not isinstance(d, dict) or not isinstance(d.get("segment_id"), int) or isinstance(d.get("segment_id"), bool):
            raise BadNote("each risk dismissal needs a segment_id")
        reason = d.get("reason")
        if not isinstance(reason, str) or len(reason.strip()) < 2 or len(reason) > 500:
            raise BadNote("each risk dismissal needs a written reason")
        out.append({"segment_id": d["segment_id"], "reason": reason.strip()})
    return out


def needs_reason(s: NoteSentence) -> bool:
    """A sentence that cites no transcript line is kept only with the therapist's
    written basis: one click would let a made-up sentence through as easily as
    the therapist's own observation."""
    return s.source != "measure" and not s.evidence and len(s.keep_reason) < MIN_REASON


def blocking_sentences(note: Note) -> list[NoteSentence]:
    """Sentences that stop signing: unchecked, unsupported, or held for
    confirmation, unless the therapist confirmed that exact sentence (and, for a
    sentence with no citation, wrote what it is based on)."""
    return [s for s in note.sentences()
            if s.status not in ("supported", "weak", "unsupported")
            or ((s.status == "unsupported" or s.must_confirm) and not s.confirmed_by_therapist)
            or (s.status == "unsupported" and needs_reason(s))]


def summarize(note: dict) -> dict:
    """Verification summary of a stored (signed) note."""
    claims = [s for items in note["sections"].values() for s in items if s.get("source") != "measure"]
    counts = {k: sum(1 for s in claims if s.get("status") == k) for k in ("supported", "weak", "unsupported")}
    n = len(claims)
    return {"total": n, **counts, "supported_ratio": round(counts["supported"] / n, 3) if n else 0.0,
            "verifier_version": VERIFIER_VERSION}


def check(session_id: str, transcript: Transcript, payload, template: str, engine: str, measures: list[str], verifier: Verifier) -> tuple[Note, dict, list[str]]:
    """Re-verifies what the browser sent. Sentences the server has already judged
    (same text, same citations, same transcript, same rules) keep that verdict;
    the rest go through ``verifier``."""
    note, forged = note_from_payload(session_id, payload, template, engine, measures, with_model=verifier.llm is not None)
    verification = verifier.run(note, transcript, measures)
    return note, verification, forged


def signed_form(note: Note, dismissals: list[dict]) -> dict:
    out = to_dict(note)
    out["risk_dismissals"] = dismissals
    return out
