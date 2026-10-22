"""Interface that every usage source implements."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from ..model import LimitObservation, PromptMarker, UsageEvent


@dataclass
class ParseResult:
    """What one incremental read of a file produced."""

    events: list[UsageEvent] = field(default_factory=list)
    limits: list[LimitObservation] = field(default_factory=list)
    prompts: list[PromptMarker] = field(default_factory=list)
    # Byte offset after the last complete record, where the next read starts.
    end_offset: int = 0
    skipped_lines: int = 0


class Source(ABC):
    """A tool whose local files record token usage.

    Sources read append-only files incrementally: the ingest step stores the
    returned offset per file and passes it back on the next run.
    """

    name: str

    @abstractmethod
    def discover(self) -> list[Path]:
        """Return every file this source would read."""

    @abstractmethod
    def parse(self, path: Path, start_offset: int = 0) -> ParseResult:
        """Read `path` from `start_offset` and return the new records."""
