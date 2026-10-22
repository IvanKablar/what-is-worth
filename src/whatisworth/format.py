"""Numbers, money, time and table cells in the active language."""

from __future__ import annotations

import unicodedata
from datetime import datetime

from .i18n import noun, t


def number(value: float, decimals: int = 0) -> str:
    text = f"{value:,.{decimals}f}"
    return text.replace(",", "\0").replace(".", t("fmt.decimal")).replace("\0", t("fmt.thousands"))


def usd(value: float, decimals: int = 2) -> str:
    return t("fmt.usd", value=number(value, decimals))


def pct(value: float | None) -> str:
    return "–" if value is None else t("fmt.pct", value=f"{value:.0f}")


def factor(value: float) -> str:
    return t("fmt.factor", value=number(value, 1))


def count(value: int) -> str:
    return number(value)


def counted(n: int, key: str) -> str:
    """`n` with the right plural form of `noun.<key>`, e.g. "1 Sitzung", "5 сессий"."""
    word = noun(key, n)
    joiner = "" if word[:1] and width(word[:1]) == 2 else " "
    return f"{count(n)}{joiner}{word}"


def _weekday(moment: datetime) -> str:
    return t("fmt.weekdays").split()[moment.weekday()]


def day_label(epoch_s: float) -> str:
    moment = datetime.fromtimestamp(epoch_s)
    return f"{_weekday(moment)} {moment.strftime(t('fmt.date'))}"


def full_date(epoch_s: float) -> str:
    return datetime.fromtimestamp(epoch_s).strftime(t("fmt.date_full"))


def weekday_time(epoch_s: int) -> str:
    moment = datetime.fromtimestamp(epoch_s)
    return f"{_weekday(moment)} {moment:%H:%M}"


def date_range(start_s: int, end_s: int) -> str:
    a, b = datetime.fromtimestamp(start_s), datetime.fromtimestamp(end_s)
    return f"{day_label(start_s)} {a:%H:%M} – {day_label(end_s)} {b:%H:%M}"


def countdown(seconds: int) -> str:
    seconds = max(seconds, 0)
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    if days:
        return t("fmt.countdown_days", d=days, h=hours)
    return t("fmt.countdown_hours", h=hours, m=rest // 60)


# table cells: pad by display width, so CJK text lines up -----------------------


def width(text: str) -> int:
    """Terminal columns `text` occupies; wide East Asian characters take two."""
    return sum(
        0 if unicodedata.combining(ch) else 2 if unicodedata.east_asian_width(ch) in "WF" else 1
        for ch in text
    )


def clip(text: str, columns: int) -> str:
    out, used = [], 0
    for ch in text:
        w = width(ch)
        if used + w > columns:
            break
        out.append(ch)
        used += w
    return "".join(out)


def left(text: str, columns: int) -> str:
    text = clip(text, columns)
    return text + " " * (columns - width(text))


def right(text: str, columns: int) -> str:
    text = clip(text, columns)
    return " " * (columns - width(text)) + text
