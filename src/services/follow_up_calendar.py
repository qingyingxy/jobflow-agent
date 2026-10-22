"""Portable calendar exports with stable event identities and local-day semantics."""
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo


def escape(value):
    return str(value or "").replace("\\", "\\\\").replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n").replace(";", "\\;").replace(",", "\\,")


def stamp(value):
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def fold(line):
    parts, current = [], ""
    for char in line:
        if len((current + char).encode("utf-8")) > 75:
            parts.append(current)
            current = " "
        current += char
    return "\r\n".join([*parts, current])


def export_calendar(view, *, now=None):
    task = view.task
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//JobFlow//Follow Up//ZH",
             "CALSCALE:GREGORIAN", "BEGIN:VEVENT", f"UID:{task.id}@jobflow.local",
             f"DTSTAMP:{stamp(now or datetime.now(UTC))}",
             f"LAST-MODIFIED:{stamp(task.updated_at)}", f"SUMMARY:{escape(task.title)}",
             f"DESCRIPTION:{escape(task.next_action + (chr(10) + task.notes if task.notes else ''))}"]
    if task.all_day:
        day = view.local_scheduled_at.date()
        lines += [f"DTSTART;VALUE=DATE:{day:%Y%m%d}", f"DTEND;VALUE=DATE:{day + timedelta(days=1):%Y%m%d}"]
        remind = datetime.combine(day, time(9), tzinfo=ZoneInfo(task.timezone))
        trigger = f"TRIGGER;VALUE=DATE-TIME:{stamp(remind)}"
    else:
        start = view.local_scheduled_at
        lines += [f"DTSTART:{stamp(start)}", f"DTEND:{stamp(start + timedelta(minutes=task.duration_minutes or 30))}"]
        trigger = "TRIGGER:-PT30M"
    if task.channel:
        lines.append(f"LOCATION:{escape(task.channel)}")
    lines.append("STATUS:CANCELLED" if task.status == "CANCELLED" else "STATUS:CONFIRMED")
    if task.status == "PENDING":
        lines += ["BEGIN:VALARM", trigger, "ACTION:DISPLAY", f"DESCRIPTION:{escape(task.title)}", "END:VALARM"]
    lines += ["END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(map(fold, lines)) + "\r\n"
