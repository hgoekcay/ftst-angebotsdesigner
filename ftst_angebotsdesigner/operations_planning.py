"""Internal scheduling proposals from manually verified free intervals only."""
from datetime import datetime, timedelta, timezone
from itertools import combinations, product
from zoneinfo import ZoneInfo
from inventory import InventoryError, procurement


def local_time(value):
    try:
        value = datetime.fromisoformat(str(value).strip())
        zone = ZoneInfo('Europe/Berlin')
        if value.tzinfo:
            return value.astimezone(timezone.utc)
        # Refuse ambiguous/nonexistent local clock times around DST transitions.
        first = value.replace(tzinfo=zone, fold=0)
        second = value.replace(tzinfo=zone, fold=1)
        if first.utcoffset() != second.utcoffset() or first.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) != value:
            raise ValueError
        return first.astimezone(timezone.utc)
    except (ValueError, TypeError):
        raise InventoryError('Datum/Uhrzeit prüfen. Bei Zeitumstellung bitte UTC-Offset angeben, z. B. +02:00.') from None


def parse_availability(text):
    """Name; skills separated by comma; start; end. No implicit work schedules."""
    people = {}
    rows = [r for r in text.splitlines() if r.strip()]
    if not 1 <= len(rows) <= 30:
        raise InventoryError('Bitte 1 bis 30 geprüfte freie Zeitfenster eingeben.')
    for row in rows:
        fields = [f.strip() for f in row.split(';')]
        if len(fields) != 4 or not fields[0] or not fields[1]:
            raise InventoryError('Zeitfenster: Name; Fähigkeiten; Beginn; Ende.')
        name, skills, start, end = fields
        skills = {s.strip().casefold() for s in skills.split(',') if s.strip()}
        start, end = local_time(start), local_time(end)
        if end <= start or end - start > timedelta(hours=24):
            raise InventoryError('Ein freies Zeitfenster muss innerhalb von 24 Stunden enden.')
        person = people.setdefault(name.casefold(), {'name': name, 'skills': skills, 'windows': []})
        if person['skills'] != skills:
            raise InventoryError('Fähigkeiten derselben Person müssen in allen Zeilen übereinstimmen.')
        person['windows'].append((start, end))
    if len(people) > 3:
        raise InventoryError('Die erste Stufe unterstützt das dreiköpfige FTST-Team.')
    return list(people.values())


def suggestions(state, order_id, availability, minutes, crew, skills, buffer_minutes, checked_at, now=None):
    now = now or datetime.now(timezone.utc)
    try:
        minutes, crew, buffer_minutes = int(minutes), int(crew), int(buffer_minutes)
        if not 1 <= minutes <= 720 or not 1 <= crew <= 3 or not 0 <= buffer_minutes <= 240:
            raise ValueError
    except (ValueError, TypeError):
        raise InventoryError('Dauer 1–720 Minuten, Teamgröße 1–3 und Fahrt-/Rüstpuffer 0–240 Minuten angeben.') from None
    order = state['orders'][order_id]
    if not order['active']:
        raise InventoryError('Auftrag ist storniert.')
    checked = local_time(checked_at)
    if checked > now or now - checked > timedelta(hours=24):
        raise InventoryError('Freie Zeiten müssen innerhalb der letzten 24 Stunden geprüft worden sein.')
    needed = {s.strip().casefold() for s in skills.split(',') if s.strip()}
    if not needed:
        raise InventoryError('Erforderliche Fähigkeiten ausdrücklich angeben.')
    people = parse_availability(availability)
    missing = procurement(state, order_id)
    if missing:
        return {'slots': [], 'reason': 'Materialfreigabe fehlt: Bestände zählen, Fehlmengen beschaffen und Material reservieren.'}
    duration = timedelta(minutes=minutes + buffer_minutes)
    found = set()
    eligible = [p for p in people if needed <= p['skills']]
    for team in combinations(eligible, crew):
        for windows in product(*(p['windows'] for p in team)):
            start = max(now, *(w[0] for w in windows))
            end = min(w[1] for w in windows)
            if start + duration <= end:
                found.add((start, start + duration, tuple(p['name'] for p in team)))
    slots = [dict(start=s.astimezone(ZoneInfo('Europe/Berlin')).isoformat(),
                  end=e.astimezone(ZoneInfo('Europe/Berlin')).isoformat(), team=list(team))
             for s, e, team in sorted(found)[:3]]
    return {'slots': slots, 'reason': 'Vorläufige interne Vorschläge aus manuell geprüften freien Zeiten. Kein Kalenderabgleich, kein Kundentermin gebucht.' if slots else 'Kein gemeinsames Zeitfenster mit passender Teamgröße, Fähigkeiten und Puffer gefunden.'}
