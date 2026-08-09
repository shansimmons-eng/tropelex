"""
Friction Miner — implicit signal detection from conversation transcripts.

Pure functions that scan transcripts for friction patterns:
rephrasing, retry loops, rapid edits, and escalation markers.
"""

import re
from dataclasses import dataclass, field

from core.agent_identity import normalize_agent_name
from core.result import Err, Ok, Result  # noqa: F401 - re-exported for this module's consumers


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FrictionSignal:
    """A single friction event detected in a transcript."""

    type: str  # rephrase | retry | escalation | rapid_edit
    severity: str  # low | medium | high
    line_number: int
    text_snippet: str
    recommendation: str


@dataclass(frozen=True)
class FrictionZone:
    """A cluster of nearby friction signals forming a zone of interest."""

    start_line: int
    end_line: int
    signals: list[FrictionSignal] = field(default_factory=list)
    zone_severity: str = "low"
    description: str = ""


# ---------------------------------------------------------------------------
# Pattern definitions
# ---------------------------------------------------------------------------

_REPHRASE_PATTERNS: list[re.Pattern] = [
    re.compile(r"\bno,\s+", re.IGNORECASE),
    re.compile(r"\bactually,\s+", re.IGNORECASE),
    re.compile(r"\bwait,\s+", re.IGNORECASE),
    re.compile(r"\bi meant\b", re.IGNORECASE),
    re.compile(r"\bthat'?s wrong\b", re.IGNORECASE),
    re.compile(r"\bnot what i\b", re.IGNORECASE),
]

_ESCALATION_PATTERNS: list[re.Pattern] = [
    # ── Repetition / correction markers ──
    re.compile(r"\bas i said\b", re.IGNORECASE),
    re.compile(r"\blike i (?:already |previously )said\b", re.IGNORECASE),
    re.compile(r"\bfor the (?:last|third|final|damn) time\b", re.IGNORECASE),
    re.compile(r"\bhow many times\b", re.IGNORECASE),
    re.compile(r"\byou(?:'re| are)? not listening\b", re.IGNORECASE),
    re.compile(r"\bread what i (?:wrote|said|typed|asked)\b", re.IGNORECASE),

    # ── Polite → frustrated escalation ──
    re.compile(r"\bplease\b.{0,20}\b(?:just|stop|already|fix)\b", re.IGNORECASE),
    re.compile(r"\b(?:can|could) you (?:please|just)\b.{0,30}\b(?:again|already)\b", re.IGNORECASE),

    # ── Direct frustration / profanity ──
    re.compile(
        r"\b(?:"
        r"wtf|omg|oh my god|"
        r"goddamn?|god ?dam(?:n|mit)?|"
        r"dam(?:n it|mit|nit)|"
        r"what (?:the (?:hell|fuck)|are you doing|were you thinking|would you do|on earth)\b"
        r")",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:"
        r"fuck(?:ing|ed)?|shit|crap|piss(?:ed)?|cluster\s*?fuck|"
        r"screw(?:ed|ing)?|botch(?:ed|ing)?|"
        r"how the hell|what the hell"
        r")\b",
        re.IGNORECASE,
    ),

    # ── Blame / accusation ──
    re.compile(
        r"\b(?:"
        r"you (?:broke|botched|screwed|fucked|deleted|destroyed|ruined|clobbered|nuked|wiped|overwrote|lost|blew)\s*(?:up)?"
        r"|you (?:just )?assumed"
        r"|you (?:weren'?t|were not) supposed to"
        r"|you (?:did ?n'?t|did not) (?:backup|back ?up|ask|listen|read|check|verify|test|think)"
        r"|you (?:forgot|forget|are forgetting|'re forgetting|keep forgetting)"
        r"|you (?:should|could) have"
        r"|you (?:should|better) know better"
        r"|you (?:did ?n'?t|did not) take the time"
        r"|you messed up"
        r"|you (?:made|make) this worse"
        r"|you (?:piece|idiot|moron)"
        r")\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:"
        r"your(?:'re)? (?:mistake|ridiculous|pathetic|garbage|useless)"
        r"|your (?:forgetting|screwing|botching)"
        r")\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:"
        r"(?:i|I) (?:did ?n'?t|did not|never) (?:ask|tell|want|authorize)"
        r"|(?:i|I) specifically asked"
        r"|what (?:i|I) (?:asked|wanted|said)"
        r"|why (?:did ?n'?t|didn't) (?:you|I)"
        r"|why (?:did|would) you (?:do this|think|assume|delete)"
        r"|why (?:is|the hell is) this taking so long"
        r"|why the delay"
        r"|why (?:am i|do i have to) (?:paying|pay)"
        r")\b",
        re.IGNORECASE,
    ),

    # ── Outcome / quality complaints ──
    re.compile(
        r"\b(?:"
        r"this is (?:garbage|trash|bad|broken|unusable|ridiculous|not (?:ok|going to work|right|working))"
        r"|that(?:'s| is) (?:enough|it)"
        r"|makes no sense"
        r"|all wrong"
        r"|not what (?:i|I) (?:wanted|asked|needed)"
        r"|terrible job"
        r"|absolute (?:fail|failure)"
        r"|you (?:failed|were wrong)"
        r")\b",
        re.IGNORECASE,
    ),

    # ── Hallucination / AI-specific ──
    re.compile(r"\bhallucinat(?:ing|ion|ed|ions)\b", re.IGNORECASE),

    # ── Action demands (revert, restore, etc.) ──
    re.compile(
        r"\b(?:"
        r"(?:go )?back\b.{0,15}\b(?:to (?:before|the (?:old|previous|last)))\b"
        r"|nix (?:that|this) (?:change|commit|edit)"
        r"|it was better before"
        r"|put (?:it|this|that|everything) back"
        r"|revert (?:this|that|it|everything|the (?:last|entire))"
        r"|start over|from scratch"
        r"|trash (?:this|that|it|everything)"
        r"|nuke (?:this|that|it)"
        r")\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:"
        r"do(?:es)? (?:nothing|n'?t work)"
        r"|times? out"
        r"|won'?t (?:load|work|run|start|open)"
        r"|isn'?t (?:loading|working|right)"
        r"|returning error"
        r"|keeps? (?:crashing|erroring|failing)"
        r")\b",
        re.IGNORECASE,
    ),

    # ── Frustrated commands ──
    re.compile(
        r"\b(?:"
        r"fix (?:this|that|it) (?:now|already|please)"
        r"|stop (?:doing|making|breaking|changing)"
        r"|do better"
        r"|don'?t bother"
        r"|last chance"
        r"|enough (?:is enough|already)"
        r"|growing frustrated"
        r")\b",
        re.IGNORECASE,
    ),
]

_RAPID_EDIT_THRESHOLD_LINES = 3  # consecutive short lines count as rapid edits
_SHORT_LINE_MAX_CHARS = 60
_RETRY_MIN_LINES = 2
_ZONE_PROXIMITY = 5  # lines within which signals are grouped


# ---------------------------------------------------------------------------
# Detectors (pure functions)
# ---------------------------------------------------------------------------

def _detect_rephrasing(lines: list[str]) -> list[FrictionSignal]:
    """Find rephrasing markers in transcript lines."""
    signals: list[FrictionSignal] = []
    for i, line in enumerate(lines):
        for pat in _REPHRASE_PATTERNS:
            m = pat.search(line)
            if m:
                signals.append(FrictionSignal(
                    type="rephrase",
                    severity="medium",
                    line_number=i + 1,
                    text_snippet=line.strip()[:80],
                    recommendation="Review for user confusion or miscommunication",
                ))
                break  # one signal per line
    return signals


def _fingerprint(text: str) -> str:
    """Create a word-level fingerprint: lowercase, sorted words joined."""
    words = text.lower().split()
    # Remove common stopwords for fingerprinting
    stopwords = {"the", "a", "an", "is", "are", "was", "were", "be", "been",
                 "have", "has", "had", "do", "does", "did", "will", "would",
                 "could", "should", "may", "might", "shall", "can", "to",
                 "of", "in", "for", "on", "with", "at", "by", "from", "as",
                 "now", "please", "thanks", "thank", "ok", "yes", "no"}
    content = [w for w in words if w not in stopwords]
    return " ".join(sorted(content))


def _detect_retries(lines: list[str]) -> list[FrictionSignal]:
    """Find retry patterns: same instruction appearing 2+ times with variation."""
    signals: list[FrictionSignal] = []
    seen: dict[str, list[int]] = {}
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or len(stripped.split()) < 3:
            continue
        fingerprint = _fingerprint(stripped)
        if fingerprint not in seen:
            seen[fingerprint] = []
        seen[fingerprint].append(i)

    for fingerprint, indices in seen.items():
        if len(indices) >= _RETRY_MIN_LINES:
            signals.append(FrictionSignal(
                type="retry",
                severity="high",
                line_number=indices[0] + 1,
                text_snippet=lines[indices[0]].strip()[:80],
                recommendation="User repeated themselves — consider clarifying earlier",
            ))
    return signals


def _detect_rapid_edits(lines: list[str]) -> list[FrictionSignal]:
    """Find clusters of short messages in quick succession."""
    signals: list[FrictionSignal] = []
    short_run = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped and len(stripped) <= _SHORT_LINE_MAX_CHARS:
            short_run += 1
        else:
            short_run = 0
        if short_run >= _RAPID_EDIT_THRESHOLD_LINES:
            if short_run == _RAPID_EDIT_THRESHOLD_LINES:
                signals.append(FrictionSignal(
                    type="rapid_edit",
                    severity="medium",
                    line_number=i + 1,
                    text_snippet=stripped[:80],
                    recommendation="Rapid short messages — user may be frustrated or iterating fast",
                ))
    return signals


def _detect_escalation(lines: list[str]) -> list[FrictionSignal]:
    """Find escalation markers indicating growing frustration."""
    signals: list[FrictionSignal] = []
    for i, line in enumerate(lines):
        for pat in _ESCALATION_PATTERNS:
            m = pat.search(line)
            if m:
                signals.append(FrictionSignal(
                    type="escalation",
                    severity="high",
                    line_number=i + 1,
                    text_snippet=line.strip()[:80],
                    recommendation="User showing frustration — consider de-escalation or re-prompting",
                ))
                break
    return signals


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_friction_signals(transcript: str) -> Result:
    """Scan a transcript for friction patterns.

    Args:
        transcript: Raw conversation transcript text.

    Returns:
        Ok(list[FrictionSignal]) on success (empty list for short/empty input).
        Err on truly unexpected input (non-string).
    """
    if not isinstance(transcript, str):
        return Err(error="transcript must be a string", code="TYPE_ERROR")

    lines = transcript.splitlines()

    # Graceful on empty or very short transcripts
    word_count = len(transcript.split())
    if word_count < 10:
        return Ok(value=[])

    signals: list[FrictionSignal] = []
    signals.extend(_detect_rephrasing(lines))
    signals.extend(_detect_retries(lines))
    signals.extend(_detect_rapid_edits(lines))
    signals.extend(_detect_escalation(lines))

    return Ok(value=signals)


def compute_friction_score(signals: list[FrictionSignal]) -> float:
    """Compute a weighted friction score 0.0-1.0.

    Factors: signal count, severity distribution, and density.
    """
    if not signals:
        return 0.0

    severity_weights = {"low": 0.3, "medium": 0.6, "high": 1.0}
    total_weight = sum(severity_weights.get(s.severity, 0.5) for s in signals)

    # Normalise by a reference maximum (10 high-severity signals = 1.0)
    raw = total_weight / 10.0

    # Density bonus: if many signals in few lines, score is higher
    line_numbers = [s.line_number for s in signals]
    span = max(line_numbers) - min(line_numbers) + 1 if len(line_numbers) > 1 else 1
    density = len(signals) / span
    density_bonus = min(density * 0.2, 0.2)  # cap at +0.2

    return round(min(raw + density_bonus, 1.0), 3)


def compute_friction_by_agent(history: list[dict], agent: str) -> dict:
    """Filter a project's friction_history down to one agent and aggregate.

    Mirrors core/market/calibration.py's filter-then-aggregate pattern:
    history is a flat list of scan records (each already tagged with
    agent_name), never restructured — just filtered per call.
    """
    agent = normalize_agent_name(agent)
    entries = [h for h in history if h.get("agent_name", "unspecified") == agent]
    if not entries:
        return {"agent_name": agent, "total_scans": 0, "avg_friction_score": 0.0, "severity_totals": {}}

    avg = round(sum(h.get("friction_score", 0.0) for h in entries) / len(entries), 3)
    severity_totals: dict[str, int] = {}
    for h in entries:
        for sev, n in h.get("severity_distribution", {}).items():
            severity_totals[sev] = severity_totals.get(sev, 0) + n

    return {
        "agent_name": agent,
        "total_scans": len(entries),
        "avg_friction_score": avg,
        "severity_totals": severity_totals,
    }


def compute_friction_penalty(history: list[dict]) -> float:
    """Average recent friction_score into a capped safety-score penalty.

    Extracted from core/tropebook/web/server.py's _friction_penalty
    (behavior-preserving — server.py's version is now a thin wrapper
    around this) so core/goals/router.py's alignment aggregator can reuse
    the same scoring without importing from the app module. Averages the
    last 10 recorded scans; 0.0 if none. Capped at 0.15 — friction nudges
    a score, it doesn't dominate it.
    """
    if not history:
        return 0.0
    recent = history[-10:]
    avg = sum(h.get("friction_score", 0.0) for h in recent) / len(recent)
    return round(min(avg * 0.15, 0.15), 3)


def group_signals_by_zone(signals: list[FrictionSignal]) -> list[FrictionZone]:
    """Group nearby signals (within 5 lines) into friction zones."""
    if not signals:
        return []

    sorted_signals = sorted(signals, key=lambda s: s.line_number)
    zones: list[FrictionZone] = []
    current: list[FrictionSignal] = [sorted_signals[0]]

    for sig in sorted_signals[1:]:
        if sig.line_number - current[-1].line_number <= _ZONE_PROXIMITY:
            current.append(sig)
        else:
            zones.append(_build_zone(current))
            current = [sig]

    if current:
        zones.append(_build_zone(current))

    return zones


def _build_zone(signals: list[FrictionSignal]) -> FrictionZone:
    """Build a FrictionZone from a list of nearby signals."""
    severity_weights = {"low": 0.3, "medium": 0.6, "high": 1.0}
    max_sev = max(severity_weights.get(s.severity, 0) for s in signals)

    if max_sev >= 1.0:
        zone_sev = "high"
    elif max_sev >= 0.6:
        zone_sev = "medium"
    else:
        zone_sev = "low"

    types = [s.type for s in signals]
    desc = f"Friction zone: {', '.join(sorted(set(types)))}"

    return FrictionZone(
        start_line=signals[0].line_number,
        end_line=signals[-1].line_number,
        signals=signals,
        zone_severity=zone_sev,
        description=desc,
    )


def suggest_decision_from_zone(zone: FrictionZone) -> dict[str, str] | None:
    """Suggest a decision candidate from a high-severity friction zone (#56).

    Same "suggest, don't save" shape as PatternLearner.detect_decisions and
    detect_goals — this doesn't persist anything, it just proposes text a
    caller can review and turn into a real decision. Only "high" severity
    zones are promotion-worthy; a single low/medium zone (one rephrase, one
    retry) is normal conversational noise, not a signal something needs a
    tracked decision. Returns None for anything below that.

    friction_history (the persisted, cross-session record) only stores
    numeric aggregates — no signal text — so this operates on a zone from
    the *current* scan, not historical friction. Promoting based on
    accumulated history across scans would need history to carry text it
    currently doesn't; noted as a real gap, not silently worked around.
    """
    if zone.zone_severity != "high":
        return None
    content = "; ".join(s.text_snippet for s in zone.signals[:3])
    return {
        "type": "friction_promotion",
        "content": content[:500],
        "confidence": "medium",
        "zone_description": zone.description,
    }
