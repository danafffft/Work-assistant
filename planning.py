"""Deterministic draft planning; never writes appointments to Outlook."""
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo


def build_plan(tasks, meetings, now=None, timezone='Europe/Kyiv', start_hour=9, end_hour=18, days=7):
    zone = ZoneInfo(timezone)
    now = (now or datetime.now(zone)).astimezone(zone)
    events = []
    for event in meetings:
        start = datetime.fromisoformat(event['start']).astimezone(zone)
        end = datetime.fromisoformat(event['end']).astimezone(zone)
        if end > start:
            events.append((start, end, event))
    slots = []
    for offset in range(days):
        day = now.date() + timedelta(days=offset)
        if day.weekday() >= 5: continue
        begin = datetime.combine(day, time(start_hour), zone)
        finish = datetime.combine(day, time(end_hour), zone)
        cursor = max(begin, now.replace(second=0, microsecond=0) + timedelta(minutes=1))
        # Explicit lunch break.
        blocked = [(datetime.combine(day, time(13), zone), datetime.combine(day, time(14), zone))]
        blocked += [(s, e) for s, e, m in events if m.get('busy', True) and s < finish and e > begin]
        for start, end in sorted(blocked):
            if start > cursor: slots.append([cursor, min(start, finish)])
            cursor = max(cursor, end)
            if cursor >= finish: break
        if cursor < finish: slots.append([cursor, finish])
    slots = [s for s in slots if s[1] > s[0]]
    blocks, backlog, seen = [], [], set()
    ordered = sorted(tasks, key=lambda t: (t.get('due') or '9999-12-31', t.get('rank', 3), t['id']))
    for task in ordered:
        if task['id'] in seen: continue
        seen.add(task['id'])
        remaining = max(15, min(int(task.get('minutes') or 60), 2400))
        for slot in slots:
            capacity = int((slot[1] - slot[0]).total_seconds() // 60)
            if capacity < 15 or not remaining: continue
            duration = min(60, capacity, remaining)
            end = slot[0] + timedelta(minutes=duration)
            blocks.append({**task, 'start': slot[0].isoformat(), 'end': end.isoformat(), 'overdue': bool(task.get('due') and end.date().isoformat() > task['due'])})
            slot[0] = end
            remaining -= duration
            # Next task block can continue in the same slot on another pass.
            while remaining and int((slot[1]-slot[0]).total_seconds()//60) >= 15:
                duration = min(60, remaining, int((slot[1]-slot[0]).total_seconds()//60))
                end = slot[0]+timedelta(minutes=duration)
                blocks.append({**task, 'start':slot[0].isoformat(), 'end':end.isoformat(), 'overdue':bool(task.get('due') and end.date().isoformat()>task['due'])})
                slot[0]=end; remaining-=duration
        if remaining: backlog.append({**task, 'remainingMinutes': remaining})
    return {'blocks': blocks, 'meetings': meetings, 'backlog': backlog, 'timezone': timezone, 'draft': True}
