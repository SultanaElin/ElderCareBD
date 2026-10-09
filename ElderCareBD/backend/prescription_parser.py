import re
from dataclasses import asdict, dataclass, field
from typing import Literal


Confidence = Literal["high", "medium", "low"]
MAX_MEDICINE_CANDIDATES = 100
MAX_CANDIDATE_SOURCE_CHARACTERS = 2_000
MAX_CANDIDATE_INSTRUCTION_CHARACTERS = 1_000

_FORM_PATTERN = re.compile(
    r"^(?P<form>tab(?:let)?|cap(?:sule)?|syr(?:up)?|inj(?:ection)?|"
    r"cream|ointment|drops?)\.?\s+",
    re.IGNORECASE,
)
_STRENGTH_PATTERN = re.compile(
    r"(?<!\w)(?P<amount>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>mcg|\u00b5g|ug|mg|g|iu|units?|%)"
    r"(?:\s*/\s*(?P<per_amount>\d+(?:\.\d+)?)?\s*"
    r"(?P<per_unit>ml))?(?!\w)",
    re.IGNORECASE,
)
_DOSAGE_PATTERN = re.compile(
    r"\b(?:take\s+)?(?P<dose>\d+(?:\.\d+)?(?:/\d+)?\s*"
    r"(?:tablets?|tabs?|capsules?|caps?|teaspoons?|tsp|ml|drops?))\b",
    re.IGNORECASE,
)
_FREQUENCY_PATTERN = re.compile(
    r"\b(?P<frequency>once\s+daily|twice\s+daily|three\s+times\s+daily|"
    r"four\s+times\s+daily|every\s+\d+\s+hours?|at\s+night|"
    r"in\s+the\s+morning|before\s+bed(?:time)?|as\s+needed)\b",
    re.IGNORECASE,
)
_NUMERIC_FREQUENCY_PATTERN = re.compile(r"(?<!\d)(\d(?:\s*\+\s*\d){1,3})(?!\d)")
_DURATION_PATTERN = re.compile(
    r"(?:\bfor\s+|[x\u00d7]\s*)(?P<amount>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>days?|weeks?|months?)\b",
    re.IGNORECASE,
)
_INSTRUCTION_START_PATTERN = re.compile(
    r"^(?:take|use|apply|instill|administer)\b", re.IGNORECASE
)
_INSTRUCTION_PHRASE_PATTERN = re.compile(
    r"\b(?:after\s+food|before\s+food|with\s+food|with\s+water|"
    r"on\s+an\s+empty\s+stomach)\b",
    re.IGNORECASE,
)
_NON_MEDICINE_HEADING_PATTERN = re.compile(
    r"^(?:rx|prescription|patient|doctor|dr\.?|date|age|diagnosis|signature|"
    r"synthetic)\b",
    re.IGNORECASE,
)


@dataclass
class MedicineCandidate:
    name: str
    strength: str | None = None
    dosage: str | None = None
    frequency: str | None = None
    duration: str | None = None
    instructions: str | None = None
    source_line: str = ""
    confidence: Confidence = "low"
    warnings: list[str] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


class PrescriptionMedicineParser:
    """Conservative deterministic parser for common printed prescriptions."""

    review_warning = (
        "OCR-derived candidates require caregiver review before confirmation."
    )

    def parse(self, raw_text):
        lines = [line.strip() for line in (raw_text or "").splitlines() if line.strip()]
        candidates = []
        current = None

        for source_line in lines:
            candidate = None
            if self._has_explicit_medicine_signal(source_line):
                candidate = self._parse_medicine_line(source_line)

            if candidate is None and self._is_instruction_line(source_line):
                if current is not None:
                    self._apply_instruction(current, source_line)
                continue

            if candidate is None:
                candidate = self._parse_medicine_line(source_line)
            if candidate is None:
                continue
            if current is not None:
                candidates.append(self._finalize_candidate(current))
                if len(candidates) >= MAX_MEDICINE_CANDIDATES:
                    current = None
                    break
            current = candidate

        if current is not None and len(candidates) < MAX_MEDICINE_CANDIDATES:
            candidates.append(self._finalize_candidate(current))

        return [candidate.to_dict() for candidate in candidates]

    @staticmethod
    def _finalize_candidate(candidate):
        if (
            candidate.frequency is None
            and "Frequency was not recognized." not in candidate.warnings
        ):
            candidate.warnings.append("Frequency was not recognized.")
        return candidate

    def _parse_medicine_line(self, source_line):
        normalized = " ".join(source_line.split())
        if _NON_MEDICINE_HEADING_PATTERN.match(normalized):
            return None

        form_match = _FORM_PATTERN.match(normalized)
        strength_match = _STRENGTH_PATTERN.search(normalized)
        if len(re.findall(r"[A-Za-z]", normalized)) < 2:
            return None

        name_start = form_match.end() if form_match else 0
        instruction_start = self._instruction_start(normalized, name_start)
        if strength_match:
            name_end = strength_match.start()
        elif form_match and instruction_start is not None:
            name_end = instruction_start
        else:
            name_end = len(normalized)
        name = normalized[name_start:name_end]
        name = re.sub(r"^\s*\d+[.)]\s*", "", name)
        name = name.strip(" \t:;,-")
        if not name or len(name) > 200 or not re.search(r"[A-Za-z]", name):
            return None

        # Without a dosage-form prefix or strength, retain only a short line as
        # an explicitly low-confidence review candidate. Longer prose remains
        # available in raw OCR text and is not guessed into medicine fields.
        if not form_match and not strength_match and len(name.split()) > 5:
            return None

        strength = None
        if strength_match:
            strength = (
                f"{strength_match.group('amount')} "
                f"{strength_match.group('unit')}"
            )
            if strength_match.group("per_unit"):
                per_amount = strength_match.group("per_amount")
                strength += "/"
                if per_amount:
                    strength += f"{per_amount} "
                strength += strength_match.group("per_unit")

        warnings = ["Confidence is heuristic and not clinically validated."]
        if form_match and strength_match:
            confidence = "high"
        elif form_match or strength_match:
            confidence = "medium"
        else:
            confidence = "low"
            warnings.append("Medicine name is uncertain.")
        if strength is None:
            warnings.append("Strength was not recognized.")

        candidate_source = source_line.strip()
        if len(candidate_source) > MAX_CANDIDATE_SOURCE_CHARACTERS:
            candidate_source = candidate_source[:MAX_CANDIDATE_SOURCE_CHARACTERS]
            warnings.append(
                "Source line was shortened; review the complete raw OCR text."
            )

        candidate = MedicineCandidate(
            name=name,
            strength=strength,
            source_line=candidate_source,
            confidence=confidence,
            warnings=warnings,
        )

        trailing_start = None
        if strength_match:
            trailing_start = strength_match.end()
        elif form_match and instruction_start is not None:
            trailing_start = instruction_start
        if trailing_start is not None:
            trailing_instruction = normalized[trailing_start:].strip(" -,:;")
            if trailing_instruction:
                self._apply_instruction(
                    candidate,
                    trailing_instruction,
                    append_source=False,
                )
        return candidate

    @staticmethod
    def _instruction_start(normalized, minimum_index=0):
        starts = []
        for pattern in (
            _DOSAGE_PATTERN,
            _FREQUENCY_PATTERN,
            _NUMERIC_FREQUENCY_PATTERN,
            _DURATION_PATTERN,
        ):
            match = pattern.search(normalized, minimum_index)
            if match is not None:
                starts.append(match.start())
        return min(starts) if starts else None

    @staticmethod
    def _has_explicit_medicine_signal(source_line):
        normalized = " ".join(source_line.split())
        if _FORM_PATTERN.match(normalized):
            return True
        if _INSTRUCTION_START_PATTERN.match(normalized):
            return False
        strength_match = _STRENGTH_PATTERN.search(normalized)
        if strength_match is None:
            return False
        return re.search(r"[A-Za-z]{2}", normalized[: strength_match.start()]) is not None

    def _is_instruction_line(self, source_line):
        normalized = " ".join(source_line.split())
        return any(
            pattern.search(normalized) is not None
            for pattern in (
                _DOSAGE_PATTERN,
                _FREQUENCY_PATTERN,
                _NUMERIC_FREQUENCY_PATTERN,
                _DURATION_PATTERN,
                _INSTRUCTION_START_PATTERN,
                _INSTRUCTION_PHRASE_PATTERN,
            )
        )

    def _apply_instruction(self, candidate, source_line, append_source=True):
        normalized = " ".join(source_line.split())
        if append_source:
            combined_source = f"{candidate.source_line}\n{source_line.strip()}"
            if len(combined_source) > MAX_CANDIDATE_SOURCE_CHARACTERS:
                candidate.source_line = combined_source[
                    :MAX_CANDIDATE_SOURCE_CHARACTERS
                ]
                warning = (
                    "Source line was shortened; review the complete raw OCR text."
                )
                if warning not in candidate.warnings:
                    candidate.warnings.append(warning)
            else:
                candidate.source_line = combined_source
        remainder = normalized

        dosage_match = _DOSAGE_PATTERN.search(normalized)
        if dosage_match:
            candidate.dosage = " ".join(dosage_match.group("dose").split())
            remainder = remainder.replace(dosage_match.group(0), " ", 1)

        frequency_match = _FREQUENCY_PATTERN.search(normalized)
        if frequency_match:
            candidate.frequency = " ".join(
                frequency_match.group("frequency").split()
            )
            remainder = remainder.replace(frequency_match.group(0), " ", 1)
        else:
            numeric_frequency_match = _NUMERIC_FREQUENCY_PATTERN.search(normalized)
            if numeric_frequency_match:
                candidate.frequency = re.sub(
                    r"\s+", "", numeric_frequency_match.group(1)
                )
                remainder = remainder.replace(
                    numeric_frequency_match.group(0), " ", 1
                )

        if candidate.frequency is not None:
            candidate.warnings = [
                warning
                for warning in candidate.warnings
                if warning != "Frequency was not recognized."
            ]

        duration_match = _DURATION_PATTERN.search(normalized)
        if duration_match:
            candidate.duration = (
                f"{duration_match.group('amount')} "
                f"{duration_match.group('unit').lower()}"
            )
            remainder = remainder.replace(duration_match.group(0), " ", 1)

        remainder = _INSTRUCTION_START_PATTERN.sub("", remainder, count=1)
        remainder = re.sub(r"\s+", " ", remainder).strip(" \t,;:-.")
        if remainder:
            if len(remainder) <= MAX_CANDIDATE_INSTRUCTION_CHARACTERS:
                candidate.instructions = remainder
            else:
                candidate.warnings.append(
                    "Instructions were too long to extract safely; review the "
                    "raw OCR text."
                )

        if (
            candidate.frequency is None
            and "Frequency was not recognized." not in candidate.warnings
        ):
            candidate.warnings.append("Frequency was not recognized.")
