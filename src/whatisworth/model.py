"""Source-independent records that every adapter produces.

Adapters translate their tool's raw files into these records. Everything
downstream (ledger, pricing, reports) only knows these types, so a new
agent such as Gemini only needs a new adapter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TokenCounts:
    """Token counts of one API response, split by billing category."""

    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write_5m: int = 0
    cache_write_1h: int = 0
    # Reasoning tokens that a source reports separately from output.
    # Claude Code already includes thinking in `output`, so it stays 0 there.
    reasoning: int = 0
    web_search_requests: int = 0

    @property
    def prompt_tokens(self) -> int:
        """All tokens sent to the model, used for long-context price tiers."""
        return self.input + self.cache_read + self.cache_write_5m + self.cache_write_1h

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.output + self.reasoning


@dataclass(frozen=True)
class UsageEvent:
    """One billed API response."""

    source: str  # adapter name, e.g. "claude-code"
    event_key: str  # unique within the source, used for deduplication
    timestamp_ms: int  # UTC epoch milliseconds
    model: str
    tokens: TokenCounts
    session_id: str | None = None
    cwd: str | None = None
    git_branch: str | None = None
    project_key: str | None = None  # raw project identifier of the source
    agent: str | None = None  # None for the main conversation, else subagent id
    speed: str | None = None  # e.g. "standard", "fast"
    inference_geo: str | None = None
    service_tier: str | None = None
    file_path: str | None = None
    # Source-specific details kept for later features, stored as JSON.
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PromptMarker:
    """Start of one user query. Its cost is every response of the session
    until the next marker, including subagents."""

    source: str
    prompt_id: str
    session_id: str
    timestamp_ms: int
    project_key: str | None = None


@dataclass(frozen=True)
class LimitObservation:
    """A rate-limit window state seen at a point in time.

    Claude Code reports these in the status line input and, when a request is
    rejected, inside the transcript. `account` is None when the origin does
    not say which account was signed in.
    """

    source: str
    observed_at_ms: int
    kind: str  # "seven_day", "five_hour", ...
    resets_at: int  # UTC epoch seconds
    origin: str  # "statusline" or "transcript"
    used_pct: float | None = None
    status: str | None = None
    account: str | None = None


@dataclass(frozen=True)
class AccountObservation:
    """Which account was signed in at a point in time."""

    source: str
    observed_at_ms: int
    account_id: str
    label: str | None = None
    plan: str | None = None
    origin: str = "statusline"
