import os
import re
import shutil
import subprocess
import tempfile
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


DEFAULT_OCR_TIMEOUT_SECONDS = 20.0
MAX_OCR_TIMEOUT_SECONDS = 120.0
MAX_OCR_CONCURRENCY = 4
MAX_OCR_TEXT_CHARACTERS = 200_000
MAX_OCR_OUTPUT_BYTES = MAX_OCR_TEXT_CHARACTERS * 4
_LANGUAGE_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")


class PrescriptionOcrError(Exception):
    """A safe OCR failure whose message may be shown to a caregiver."""

    user_message = "OCR processing failed. You can enter medicines manually."


class PrescriptionOcrUnavailableError(PrescriptionOcrError):
    user_message = "OCR is not available. You can enter medicines manually."


class PrescriptionOcrTimeoutError(PrescriptionOcrError):
    user_message = "OCR processing timed out. You can enter medicines manually."


class PrescriptionOcrBusyError(PrescriptionOcrError):
    user_message = "OCR is busy. Please try again or enter medicines manually."


class PrescriptionOcrOutputError(PrescriptionOcrError):
    user_message = "OCR returned too much text. You can enter medicines manually."


@dataclass(frozen=True)
class PrescriptionOcrResult:
    text: str
    engine: str
    languages: tuple[str, ...]


class PrescriptionOcrEngine(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def languages(self) -> tuple[str, ...]:
        raise NotImplementedError

    @abstractmethod
    def extract_text(self, image_path: Path) -> PrescriptionOcrResult:
        raise NotImplementedError


def _bounded_float(value, default, minimum, maximum):
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return min(max(parsed, minimum), maximum)


def _bounded_int(value, default, minimum, maximum):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return min(max(parsed, minimum), maximum)


def _configured_languages(value):
    requested = (value or "eng").replace(",", "+").split("+")
    languages = tuple(
        language.strip()
        for language in requested
        if language.strip()
    )
    if not languages or any(
        _LANGUAGE_PATTERN.fullmatch(language) is None for language in languages
    ):
        raise ValueError(
            "ELDERCARE_TESSERACT_LANGUAGES must contain safe Tesseract "
            "language identifiers separated by '+'."
        )
    return languages


class TesseractPrescriptionOcrEngine(PrescriptionOcrEngine):
    """Bounded, shell-free adapter for the local Tesseract executable."""

    def __init__(
        self,
        executable=None,
        languages=None,
        timeout_seconds=None,
        max_concurrency=None,
    ):
        configured_executable = executable or os.getenv("ELDERCARE_TESSERACT_CMD")
        self._executable = configured_executable or shutil.which("tesseract")
        self._languages = _configured_languages(
            languages
            if languages is not None
            else os.getenv("ELDERCARE_TESSERACT_LANGUAGES", "eng")
        )
        self._timeout_seconds = _bounded_float(
            timeout_seconds
            if timeout_seconds is not None
            else os.getenv("ELDERCARE_TESSERACT_TIMEOUT_SECONDS"),
            DEFAULT_OCR_TIMEOUT_SECONDS,
            1.0,
            MAX_OCR_TIMEOUT_SECONDS,
        )
        concurrency = _bounded_int(
            max_concurrency
            if max_concurrency is not None
            else os.getenv("ELDERCARE_OCR_MAX_CONCURRENCY"),
            2,
            1,
            MAX_OCR_CONCURRENCY,
        )
        self._semaphore = threading.BoundedSemaphore(concurrency)

    @property
    def name(self):
        return "tesseract"

    @property
    def languages(self):
        return self._languages

    def extract_text(self, image_path):
        if not self._executable:
            raise PrescriptionOcrUnavailableError()

        acquired = self._semaphore.acquire(blocking=False)
        if not acquired:
            raise PrescriptionOcrBusyError()

        command = [
            self._executable,
            str(Path(image_path)),
            "stdout",
            "-l",
            "+".join(self._languages),
            "--psm",
            "6",
        ]
        subprocess_options = {
            "args": command,
            "stdin": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "timeout": self._timeout_seconds,
            "check": False,
            "shell": False,
        }
        if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
            subprocess_options["creationflags"] = subprocess.CREATE_NO_WINDOW

        try:
            with tempfile.TemporaryFile(mode="w+b") as output_file:
                subprocess_options["stdout"] = output_file
                try:
                    completed = subprocess.run(**subprocess_options)
                except subprocess.TimeoutExpired as exc:
                    raise PrescriptionOcrTimeoutError() from exc
                except (FileNotFoundError, PermissionError, OSError) as exc:
                    raise PrescriptionOcrUnavailableError() from exc

                if completed.returncode != 0:
                    # Tesseract stderr can contain local paths and is discarded,
                    # never logged or included in the public exception.
                    raise PrescriptionOcrError()
                output_size = output_file.seek(0, os.SEEK_END)
                if output_size > MAX_OCR_OUTPUT_BYTES:
                    raise PrescriptionOcrOutputError()
                output_file.seek(0)
                output_text = output_file.read().decode("utf-8", errors="replace")
                if len(output_text) > MAX_OCR_TEXT_CHARACTERS:
                    raise PrescriptionOcrOutputError()
        finally:
            self._semaphore.release()

        return PrescriptionOcrResult(
            text=output_text,
            engine=self.name,
            languages=self.languages,
        )


@lru_cache(maxsize=1)
def get_prescription_ocr_engine():
    return TesseractPrescriptionOcrEngine()
