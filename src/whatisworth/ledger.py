"""The central SQLite ledger.

One writer at a time (guarded by a lock file in `ingest`), any number of
readers thanks to WAL mode. Tokens are stored next to the computed cost, so
`reprice` can recompute every cost when prices change.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable

from .model import AccountObservation, LimitObservation, PromptMarker, UsageEvent
from .pricing import Cost

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS files (
    path TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    size INTEGER NOT NULL,
    inode INTEGER NOT NULL,
    offset INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    source TEXT NOT NULL,
    event_key TEXT NOT NULL,
    ts INTEGER NOT NULL,
    model TEXT NOT NULL,
    session_id TEXT,
    cwd TEXT,
    git_branch TEXT,
    project_key TEXT,
    agent TEXT,
    sidechain INTEGER NOT NULL DEFAULT 0,
    speed TEXT,
    inference_geo TEXT,
    input INTEGER NOT NULL,
    output INTEGER NOT NULL,
    cache_read INTEGER NOT NULL,
    cache_write_5m INTEGER NOT NULL,
    cache_write_1h INTEGER NOT NULL,
    reasoning INTEGER NOT NULL,
    web_search INTEGER NOT NULL,
    total INTEGER NOT NULL,
    cost_usd REAL NOT NULL,
    price_status TEXT NOT NULL,
    price_version TEXT NOT NULL,
    file_path TEXT,
    attrs TEXT,
    PRIMARY KEY (source, event_key)
);
CREATE INDEX IF NOT EXISTS events_ts ON events (ts);
CREATE INDEX IF NOT EXISTS events_session ON events (session_id, ts);

CREATE TABLE IF NOT EXISTS limit_observations (
    source TEXT NOT NULL,
    kind TEXT NOT NULL,
    resets_at INTEGER NOT NULL,
    origin TEXT NOT NULL,
    first_seen INTEGER NOT NULL,
    last_seen INTEGER NOT NULL,
    max_used_pct REAL,
    last_used_pct REAL,
    status TEXT,
    account TEXT,
    first_used_pct REAL,
    PRIMARY KEY (source, kind, resets_at, origin, account)
);

CREATE TABLE IF NOT EXISTS prompts (
    source TEXT NOT NULL,
    prompt_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    ts INTEGER NOT NULL,
    project_key TEXT,
    PRIMARY KEY (source, prompt_id)
);
CREATE INDEX IF NOT EXISTS prompts_session ON prompts (session_id, ts);

-- Session cost as Claude Code itself reports it, kept to cross-check ours.
CREATE TABLE IF NOT EXISTS reported_costs (
    source TEXT NOT NULL,
    session_id TEXT NOT NULL,
    cost_usd REAL NOT NULL,
    observed_at INTEGER NOT NULL,
    PRIMARY KEY (source, session_id)
);

-- Git repository of each working directory, resolved while it existed.
CREATE TABLE IF NOT EXISTS repo_paths (
    cwd TEXT PRIMARY KEY,
    repo TEXT
);

CREATE TABLE IF NOT EXISTS account_observations (
    source TEXT NOT NULL,
    account_id TEXT NOT NULL,
    first_seen INTEGER NOT NULL,
    last_seen INTEGER NOT NULL,
    label TEXT,
    plan TEXT,
    origin TEXT NOT NULL,
    PRIMARY KEY (source, account_id, first_seen)
);
"""

# Keep the most complete copy of a response: the main conversation over a
# sidechain replay, then the copy with the most output (the fully streamed
# one), then the larger total.
_UPSERT_EVENT = """
INSERT INTO events VALUES (
    :source, :event_key, :ts, :model, :session_id, :cwd, :git_branch, :project_key,
    :agent, :sidechain, :speed, :inference_geo, :input, :output, :cache_read,
    :cache_write_5m, :cache_write_1h, :reasoning, :web_search, :total, :cost_usd,
    :price_status, :price_version, :file_path, :attrs
)
ON CONFLICT (source, event_key) DO UPDATE SET
    ts = excluded.ts, model = excluded.model, session_id = excluded.session_id,
    cwd = excluded.cwd, git_branch = excluded.git_branch,
    project_key = excluded.project_key, agent = excluded.agent,
    sidechain = excluded.sidechain, speed = excluded.speed,
    inference_geo = excluded.inference_geo, input = excluded.input,
    output = excluded.output, cache_read = excluded.cache_read,
    cache_write_5m = excluded.cache_write_5m, cache_write_1h = excluded.cache_write_1h,
    reasoning = excluded.reasoning, web_search = excluded.web_search,
    total = excluded.total, cost_usd = excluded.cost_usd,
    price_status = excluded.price_status, price_version = excluded.price_version,
    file_path = excluded.file_path, attrs = excluded.attrs
WHERE (events.sidechain = 1 AND excluded.sidechain = 0)
   OR (events.sidechain = excluded.sidechain AND (
          excluded.output > events.output
          OR (excluded.output = events.output AND excluded.total > events.total)))
"""

_UPSERT_LIMIT = """
INSERT INTO limit_observations (
    source, kind, resets_at, origin, first_seen, last_seen,
    max_used_pct, last_used_pct, first_used_pct, status, account
) VALUES (
    :source, :kind, :resets_at, :origin, :seen, :seen, :pct, :pct, :pct, :status, :account
)
ON CONFLICT (source, kind, resets_at, origin, account) DO UPDATE SET
    first_seen = MIN(first_seen, excluded.first_seen),
    last_seen = MAX(last_seen, excluded.last_seen),
    max_used_pct = CASE WHEN excluded.max_used_pct IS NULL THEN max_used_pct
                        WHEN max_used_pct IS NULL THEN excluded.max_used_pct
                        ELSE MAX(max_used_pct, excluded.max_used_pct) END,
    first_used_pct = CASE WHEN excluded.first_seen < first_seen OR first_used_pct IS NULL
                          THEN COALESCE(excluded.first_used_pct, first_used_pct)
                          ELSE first_used_pct END,
    last_used_pct = CASE WHEN excluded.last_seen >= last_seen
                         THEN COALESCE(excluded.last_used_pct, last_used_pct)
                         ELSE last_used_pct END,
    status = COALESCE(excluded.status, status)
"""


class Ledger:
    def __init__(self, path: Path, timeout: float = 30) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, timeout=timeout)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(_SCHEMA)
        self._migrate()
        self.conn.execute(
            "INSERT OR IGNORE INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),)
        )
        self.conn.commit()

    def _migrate(self) -> None:
        columns = {r[1] for r in self.conn.execute("PRAGMA table_info(limit_observations)")}
        if "first_used_pct" not in columns:
            self.conn.execute("ALTER TABLE limit_observations ADD COLUMN first_used_pct REAL")

    def close(self) -> None:
        self.conn.close()

    # files ---------------------------------------------------------------

    def file_state(self, path: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM files WHERE path = ?", (path,)).fetchone()

    def set_file_state(self, path: str, source: str, size: int, inode: int, offset: int) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO files VALUES (?, ?, ?, ?, ?)",
            (path, source, size, inode, offset),
        )

    # events --------------------------------------------------------------

    def forget_events_from(self, paths: list[str]) -> None:
        """Drop events read from `paths` so they can be read again."""
        self.conn.executemany("DELETE FROM events WHERE file_path = ?", ((p,) for p in paths))

    def upsert_events(self, rows: Iterable[tuple[UsageEvent, Cost]], price_version: str) -> None:
        self.conn.executemany(
            _UPSERT_EVENT, (_event_params(e, c, price_version) for e, c in rows)
        )

    def upsert_limits(self, observations: Iterable[LimitObservation]) -> None:
        self.conn.executemany(
            _UPSERT_LIMIT,
            (
                {
                    "source": o.source,
                    "kind": o.kind,
                    "resets_at": o.resets_at,
                    "origin": o.origin,
                    "seen": o.observed_at_ms,
                    "pct": o.used_pct,
                    "status": o.status,
                    "account": o.account or "",
                }
                for o in observations
            ),
        )

    def upsert_prompts(self, prompts: Iterable[PromptMarker]) -> None:
        self.conn.executemany(
            "INSERT INTO prompts VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT (source, prompt_id) DO UPDATE SET ts = MIN(ts, excluded.ts)",
            ((p.source, p.prompt_id, p.session_id, p.timestamp_ms, p.project_key) for p in prompts),
        )

    def record_reported_cost(self, source: str, session_id: str, cost: float, at_ms: int) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO reported_costs VALUES (?, ?, ?, ?)",
            (source, session_id, cost, at_ms),
        )

    def unresolved_cwds(self) -> list[str]:
        return [r[0] for r in self.conn.execute(
            "SELECT DISTINCT cwd FROM events WHERE cwd IS NOT NULL "
            "AND cwd NOT IN (SELECT cwd FROM repo_paths)"
        )]

    def set_repo(self, cwd: str, repo: str | None) -> None:
        self.conn.execute("INSERT OR REPLACE INTO repo_paths VALUES (?, ?)", (cwd, repo))

    def repo_map(self) -> dict[str, str | None]:
        return dict(self.conn.execute("SELECT cwd, repo FROM repo_paths"))

    def get_meta(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, value))

    def record_account(self, obs: AccountObservation) -> None:
        """Extend the current account stretch, or start a new one on a switch."""
        last = self.conn.execute(
            "SELECT account_id, first_seen FROM account_observations "
            "WHERE source = ? ORDER BY last_seen DESC LIMIT 1",
            (obs.source,),
        ).fetchone()
        if last and last["account_id"] == obs.account_id:
            self.conn.execute(
                "UPDATE account_observations SET last_seen = MAX(last_seen, ?), "
                "label = COALESCE(?, label), plan = COALESCE(?, plan) "
                "WHERE source = ? AND account_id = ? AND first_seen = ?",
                (obs.observed_at_ms, obs.label, obs.plan, obs.source, obs.account_id, last["first_seen"]),
            )
        else:
            self.conn.execute(
                "INSERT OR IGNORE INTO account_observations VALUES (?, ?, ?, ?, ?, ?, ?)",
                (obs.source, obs.account_id, obs.observed_at_ms, obs.observed_at_ms,
                 obs.label, obs.plan, obs.origin),
            )

    def commit(self) -> None:
        self.conn.commit()


def _event_params(event: UsageEvent, cost: Cost, price_version: str) -> dict:
    t = event.tokens
    attrs = dict(event.attrs)
    sidechain = 1 if attrs.pop("sidechain", False) else 0
    return {
        "source": event.source,
        "event_key": event.event_key,
        "ts": event.timestamp_ms,
        "model": event.model,
        "session_id": event.session_id,
        "cwd": event.cwd,
        "git_branch": event.git_branch,
        "project_key": event.project_key,
        "agent": event.agent,
        "sidechain": sidechain,
        "speed": event.speed,
        "inference_geo": event.inference_geo,
        "input": t.input,
        "output": t.output,
        "cache_read": t.cache_read,
        "cache_write_5m": t.cache_write_5m,
        "cache_write_1h": t.cache_write_1h,
        "reasoning": t.reasoning,
        "web_search": t.web_search_requests,
        "total": t.total,
        "cost_usd": cost.usd,
        "price_status": cost.status,
        "price_version": price_version,
        "file_path": event.file_path,
        "attrs": json.dumps(attrs, separators=(",", ":")) if attrs else None,
    }
