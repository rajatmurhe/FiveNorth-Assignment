import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent


class Clinic:
    def __init__(self, path=ROOT / 'clinic.json'):
        self.raw = json.loads(Path(path).read_text())
        self.zone = ZoneInfo(self.raw['timezone'])
        self.now = datetime.fromisoformat(self.raw['now']).astimezone(self.zone)
        self.minutes = self.raw['slot_minutes']
        self.doctors = {d['id']: d for d in self.raw['doctors']}
        self.closed = set(self.raw['closed_dates'])

    def at(self, day, clock):
        return datetime.combine(date.fromisoformat(day), time.fromisoformat(clock), self.zone)

    def slots(self, day, doctor=None):
        date.fromisoformat(day)
        if day in self.closed:
            return []
        weekday = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')[date.fromisoformat(day).weekday()]
        result = []
        for doc_id, doc in self.doctors.items():
            if doctor is not None and doc_id != doctor:
                continue
            for hours in doc['hours'][weekday]:
                start, end = hours.split('-')
                cursor, finish = self.at(day, start), self.at(day, end)
                while cursor + timedelta(minutes=self.minutes) <= finish:
                    if cursor >= self.now:
                        result.append({'date': day, 'time': cursor.strftime('%H:%M'), 'doctor': doc_id})
                    cursor += timedelta(minutes=self.minutes)
        return sorted(result, key=lambda s: (s['date'], s['time'], s['doctor']))
