"""Claude Code transcripts under ~/.claude/projects/.

Layout, as of Claude Code 2.1.3xx:

    projects/<project-dir>/<session>.jsonl
    projects/<project-dir>/<session>/subagents/agent-<id>.jsonl
    projects/<project-dir>/<session>/subagents/workflows/<wf>/agent-<id>.jsonl

Every API response appears as one or more `assistant` lines, one per content
block. The copies share `message.id`, but their usage can differ while a
response streams, so the ledger keeps the most complete copy.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from ..model import LimitObservation, PromptMarker, TokenCounts, UsageEvent
from .base import ParseResult, Source

# Models Claude Code writes for locally generated messages, never billed.
_UNBILLED_MODELS = {"<synthetic>", ""}

# Values of usage.inference_geo that mean "no data residency surcharge".
GLOBAL_GEOS = {None, "", "global", "not_available"}


def default_roots() -> list[Path]:
    """Claude config directories to scan, without duplicates."""
    roots: list[Path] = []
    extra = os.environ.get("WIW_CLAUDE_DIRS")
    if extra:
        roots.extend(Path(p).expanduser() for p in extra.split(os.pathsep) if p)
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    if config_dir:
        roots.append(Path(config_dir).expanduser())
    roots.append(Path.home() / ".claude")
    unique: list[Path] = []
    for root in roots:
        resolved = root.resolve()
        if resolved not in unique and (resolved / "projects").is_dir():
            unique.append(resolved)
    return unique


def _parse_timestamp_ms(value: Any) -> int | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None


def _int(value: Any) -> int:
    return value if isinstance(value, int) and value > 0 else 0


def token_counts(usage: dict[str, Any]) -> TokenCounts:
    """Split Claude usage into billing categories.

    `cache_creation_input_tokens` is the sum of both cache lifetimes and is
    authoritative. The `cache_creation` object only splits it: a remainder it
    does not explain is billed at the 5-minute rate (the API default), and a
    split larger than the total, seen on streamed and fallback responses, is
    scaled down to the total.
    """
    write_total = _int(usage.get("cache_creation_input_tokens"))
    split = usage.get("cache_creation") or {}
    write_1h = _int(split.get("ephemeral_1h_input_tokens"))
    write_5m = _int(split.get("ephemeral_5m_input_tokens"))
    if write_1h + write_5m > write_total:
        write_1h = round(write_total * write_1h / (write_1h + write_5m))
        write_5m = write_total - write_1h
    else:
        write_5m += write_total - write_1h - write_5m
    server_tools = usage.get("server_tool_use") or {}
    return TokenCounts(
        input=_int(usage.get("input_tokens")),
        output=_int(usage.get("output_tokens")),
        cache_read=_int(usage.get("cache_read_input_tokens")),
        cache_write_5m=write_5m,
        cache_write_1h=write_1h,
        web_search_requests=_int(server_tools.get("web_search_requests")),
    )


def event_key(record: dict[str, Any], message: dict[str, Any]) -> str | None:
    """Deduplication key of one API response.

    Anthropic message ids (`msg_...`) are unique per response, so they alone
    identify it, including replays under a new request id. Other ids, for
    example from gateways, are combined with the request id or the session.
    """
    message_id = message.get("id")
    request_id = record.get("requestId")
    if isinstance(message_id, str) and message_id:
        if message_id.startswith("msg_"):
            return message_id
        if request_id:
            return f"{message_id}|{request_id}"
        return f"{message_id}|{record.get('sessionId')}|{record.get('timestamp')}"
    if request_id:
        return f"req|{request_id}"
    uuid = record.get("uuid")
    return f"uuid|{uuid}" if uuid else None


class ClaudeCodeSource(Source):
    name = "claude-code"

    def __init__(self, roots: list[Path] | None = None) -> None:
        self.roots = roots if roots is not None else default_roots()

    def discover(self) -> list[Path]:
        files: list[Path] = []
        for root in self.roots:
            files.extend((root / "projects").rglob("*.jsonl"))
        return sorted(files)

    def _project_key(self, path: Path) -> str | None:
        for root in self.roots:
            try:
                return path.relative_to(root / "projects").parts[0]
            except (ValueError, IndexError):
                continue
        return None

    def parse(self, path: Path, start_offset: int = 0) -> ParseResult:
        result = ParseResult(end_offset=start_offset)
        project_key = self._project_key(path)
        file_path = str(path)
        with path.open("rb") as handle:
            handle.seek(start_offset)
            for line in handle:
                # A line still being written has no newline yet; read it next time.
                if not line.endswith(b"\n"):
                    break
                result.end_offset += len(line)
                self._read_line(line, result, project_key, file_path)
        return result

    def _read_line(
        self, line: bytes, result: ParseResult, project_key: str | None, file_path: str
    ) -> None:
        # Cheap pre-filter: only usage, quota and human prompt lines matter.
        if (
            b'"usage"' not in line
            and b'"quotaLimits"' not in line
            and b'"kind":"human"' not in line
        ):
            return
        try:
            record = json.loads(line)
        except ValueError:
            result.skipped_lines += 1
            return
        if not isinstance(record, dict):
            return
        self._read_limits(record, result)
        self._read_prompt(record, result, project_key)
        event = self._read_event(record, project_key, file_path)
        if event is not None:
            result.events.append(event)

    def _read_event(
        self, record: dict[str, Any], project_key: str | None, file_path: str
    ) -> UsageEvent | None:
        if record.get("type") != "assistant":
            return None
        message = record.get("message")
        if not isinstance(message, dict):
            return None
        usage = message.get("usage")
        model = message.get("model") or ""
        if not isinstance(usage, dict) or model in _UNBILLED_MODELS:
            return None
        timestamp_ms = _parse_timestamp_ms(record.get("timestamp"))
        key = event_key(record, message)
        if timestamp_ms is None or key is None:
            return None
        tokens = token_counts(usage)
        if tokens.total == 0 and tokens.web_search_requests == 0:
            return None
        attrs = {
            name: record[field]
            for name, field in (
                ("request_id", "requestId"),
                ("entrypoint", "entrypoint"),
                ("version", "version"),
                ("skill", "attributionSkill"),
                ("mcp_server", "attributionMcpServer"),
                ("attributed_agent", "attributionAgent"),
                ("effort", "effort"),
            )
            if record.get(field) not in (None, "")
        }
        if record.get("isSidechain"):
            attrs["sidechain"] = True
        return UsageEvent(
            source=self.name,
            event_key=key,
            timestamp_ms=timestamp_ms,
            model=model,
            tokens=tokens,
            session_id=record.get("sessionId"),
            cwd=record.get("cwd"),
            git_branch=record.get("gitBranch") or None,
            project_key=project_key,
            agent=record.get("agentId") or None,
            speed=usage.get("speed"),
            inference_geo=usage.get("inference_geo"),
            service_tier=usage.get("service_tier"),
            file_path=file_path,
            attrs=attrs,
        )

    def _read_prompt(
        self, record: dict[str, Any], result: ParseResult, project_key: str | None
    ) -> None:
        origin = record.get("origin")
        if record.get("type") != "user" or not isinstance(origin, dict):
            return
        if origin.get("kind") != "human" or record.get("isMeta"):
            return
        prompt_id, session_id = record.get("promptId"), record.get("sessionId")
        timestamp_ms = _parse_timestamp_ms(record.get("timestamp"))
        if prompt_id and session_id and timestamp_ms is not None:
            result.prompts.append(
                PromptMarker(self.name, prompt_id, session_id, timestamp_ms, project_key)
            )

    def _read_limits(self, record: dict[str, Any], result: ParseResult) -> None:
        quota = record.get("quotaLimits")
        if not isinstance(quota, dict):
            return
        resets_at = quota.get("resetsAt")
        kind = quota.get("rateLimitType")
        observed = _parse_timestamp_ms(record.get("timestamp"))
        if not isinstance(resets_at, int) or not kind or observed is None:
            return
        result.limits.append(
            LimitObservation(
                source=self.name,
                observed_at_ms=observed,
                kind=kind,
                resets_at=resets_at,
                origin="transcript",
                status=quota.get("status"),
            )
        )


def signed_in_account(config_file: Path | None = None) -> dict[str, str] | None:
    """The account Claude Code is currently signed in with, from ~/.claude.json."""
    path = config_file or Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home())) / ".claude.json"
    if not path.exists():
        path = Path.home() / ".claude.json"
    try:
        account = json.loads(path.read_text()).get("oauthAccount") or {}
    except (OSError, ValueError):
        return None
    account_id = account.get("accountUuid")
    if not account_id:
        return None
    from ..plans import plan_id

    return {
        "id": account_id,
        "label": account.get("emailAddress") or account.get("displayName") or account_id[:8],
        "plan": plan_id(account.get("organizationType"), account.get("organizationRateLimitTier"))
        or account.get("billingType") or "",
    }
