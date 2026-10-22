"""Incremental import of source files into the ledger."""

from __future__ import annotations

import fcntl
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .i18n import t
from .ledger import Ledger
from .projects import resolve_repo
from .pricing import PriceBook
from .sources import Source


class SyncBusy(RuntimeError):
    """Another process holds the sync lock."""


@dataclass
class SyncStats:
    files_seen: int = 0
    files_read: int = 0
    events: int = 0
    limits: int = 0
    prompts: int = 0
    bad_lines: int = 0


@contextmanager
def sync_lock(lock_path: Path, wait: bool = True) -> Iterator[None]:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w") as handle:
        flags = fcntl.LOCK_EX if wait else fcntl.LOCK_EX | fcntl.LOCK_NB
        try:
            fcntl.flock(handle, flags)
        except BlockingIOError:
            raise SyncBusy(t("sync.busy")) from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def sync(
    ledger: Ledger,
    sources: list[Source],
    prices: PriceBook,
    only: list[Path] | None = None,
    full: bool = False,
    rebuild: bool = False,
) -> SyncStats:
    """Read new data from every source file into the ledger.

    Each file is committed together with its new offset, so an interrupted
    run never loses or double-counts data. `full` re-reads everything; the
    upsert makes that idempotent. `rebuild` also drops what was read from the
    existing files first, so changed parsing rules take full effect; events
    from transcripts that no longer exist are kept.
    """
    stats = SyncStats()
    for source in sources:
        paths = only if only is not None else source.discover()
        if rebuild:
            ledger.forget_events_from([str(p) for p in paths])
            full = True
        for path in paths:
            stats.files_seen += 1
            try:
                st = path.stat()
            except FileNotFoundError:
                continue
            key = str(path)
            state = None if full else ledger.file_state(key)
            offset = 0
            if state is not None:
                same_file = state["inode"] == st.st_ino and st.st_size >= state["offset"]
                if same_file and st.st_size == state["size"]:
                    continue  # unchanged
                offset = state["offset"] if same_file else 0
            result = source.parse(path, offset)
            ledger.upsert_events(
                ((event, prices.cost(event)) for event in result.events), prices.version
            )
            ledger.upsert_limits(result.limits)
            ledger.upsert_prompts(result.prompts)
            ledger.set_file_state(key, source.name, st.st_size, st.st_ino, result.end_offset)
            ledger.commit()
            stats.files_read += 1
            stats.events += len(result.events)
            stats.limits += len(result.limits)
            stats.prompts += len(result.prompts)
            stats.bad_lines += result.skipped_lines
    resolve_projects(ledger)
    return stats


def resolve_projects(ledger: Ledger) -> None:
    """Store the repository of every new working directory that still exists.

    Directories that are gone stay unresolved; reports then fall back to the
    directory name.
    """
    for cwd in ledger.unresolved_cwds():
        repo = resolve_repo(cwd)
        if repo is not None or Path(cwd).is_dir():
            ledger.set_repo(cwd, repo)
    ledger.commit()


def reprice(ledger: Ledger, prices: PriceBook) -> int:
    """Recompute every stored cost with the current price book."""
    from .model import TokenCounts, UsageEvent

    rows = ledger.conn.execute(
        "SELECT source, event_key, ts, model, speed, inference_geo, input, output, "
        "cache_read, cache_write_5m, cache_write_1h, reasoning, web_search FROM events"
    ).fetchall()
    updates = []
    for r in rows:
        event = UsageEvent(
            source=r["source"], event_key=r["event_key"], timestamp_ms=r["ts"], model=r["model"],
            speed=r["speed"], inference_geo=r["inference_geo"],
            tokens=TokenCounts(
                input=r["input"], output=r["output"], cache_read=r["cache_read"],
                cache_write_5m=r["cache_write_5m"], cache_write_1h=r["cache_write_1h"],
                reasoning=r["reasoning"], web_search_requests=r["web_search"],
            ),
        )
        cost = prices.cost(event)
        updates.append((cost.usd, cost.status, prices.version, r["source"], r["event_key"]))
    ledger.conn.executemany(
        "UPDATE events SET cost_usd = ?, price_status = ?, price_version = ? "
        "WHERE source = ? AND event_key = ?",
        updates,
    )
    ledger.commit()
    return len(updates)

