import json
import re
import sqlite3
from datetime import date, timedelta

from .understanding import RulesProvider, extract


class InputError(ValueError):
    pass


def phone_number(phone):
    if type(phone) is not str or not re.fullmatch(r'\+[1-9]\d{7,14}', phone):
        raise InputError('phone must be an international number, e.g. +919800000001')
    return phone


def day_value(value):
    if type(value) is not str or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise InputError('date must be YYYY-MM-DD')
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise InputError('date must exist in the calendar') from exc
    return value


class BookingService:
    def __init__(self, clinic, store, provider=None):
        self.clinic, self.store = clinic, store
        self.provider = provider or RulesProvider(clinic)

    def free(self, db, day, doctor=None):
        day_value(day)
        if doctor is not None and doctor not in self.clinic.doctors:
            raise InputError('Unknown doctor')
        occupied = {(r['doctor'], r['time']) for r in db.execute(
            'SELECT doctor,time FROM bookings WHERE day=? AND cancelled_at IS NULL', (day,))}
        return [s for s in self.clinic.slots(day, doctor) if (s['doctor'], s['time']) not in occupied]

    def availability(self, day, doctor=None):
        with self.store.connect() as db:
            return self.free(db, day, doctor)

    def alternatives(self, db, day=None, clock=None, doctor=None):
        """Find nearby free slots within a 15-day window; prefer later slots on ties."""
        target = max(self.clinic.at(day, clock or '12:00'), self.clinic.now) if day else self.clinic.now
        look_back = min(7, (target.date() - self.clinic.now.date()).days)
        first = target.date() - timedelta(days=look_back)
        slots = []
        for offset in range(15):
            if offset > (date.max - first).days:
                break
            candidate = first + timedelta(days=offset)
            slots.extend(self.free(db, candidate.isoformat(), doctor))
        slots.sort(key=lambda slot: (abs((self.clinic.at(slot['date'], slot['time']) - target).total_seconds()),
                                     self.clinic.at(slot['date'], slot['time']) < target,
                                     slot['date'], slot['time'], slot['doctor']))
        return slots[:3]

    def describe(self, slot):
        return f"{date.fromisoformat(slot['date']):%a %d %b} at {slot['time']} with {self.clinic.doctors[slot['doctor']]['name']}"

    def response(self, status, code, reply, alternatives=None, booking=None):
        slots = alternatives or []
        if slots:
            reply += ' Available options (IST): ' + '; '.join(self.describe(s) for s in slots) + '. Please confirm one before we book.'
        return dict(status=status, code=code, reply=reply, booking=booking, alternatives=slots)

    @staticmethod
    def public(row):
        return {'id': row['id'], 'phone': row['phone'], 'doctor': row['doctor'], 'date': row['day'], 'time': row['time']}

    def book(self, db, phone, day, clock, doctor):
        slot = {'date': day, 'time': clock, 'doctor': doctor}
        if slot not in self.clinic.slots(day, doctor):
            return self.response('refused', 'invalid_slot', 'That time is outside the clinic schedule, in the past, or not a 30-minute slot.', self.alternatives(db, day, clock, doctor))
        try:
            cursor = db.execute('INSERT INTO bookings(phone,doctor,day,time,created_at) VALUES(?,?,?,?,?)',
                                (phone, doctor, day, clock, self.clinic.now.isoformat()))
        except sqlite3.IntegrityError:
            return self.response('refused', 'slot_taken', 'That slot has just been booked.', self.alternatives(db, day, clock, doctor))
        row = db.execute('SELECT * FROM bookings WHERE id=?', (cursor.lastrowid,)).fetchone()
        return self.response('booked', 'booked', f"Confirmed: {self.describe(slot)} IST. Booking #{row['id']}.", booking=self.public(row))

    def book_direct(self, payload):
        if set(payload) != {'phone', 'date', 'time', 'doctor'}:
            raise InputError('Required fields: phone, date, time, doctor')
        phone = phone_number(payload['phone'])
        day = day_value(payload['date'])
        clock, doctor = payload['time'], payload['doctor']
        if type(clock) is not str or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', clock):
            raise InputError('time must be HH:MM in 24-hour format')
        if type(doctor) is not str or doctor not in self.clinic.doctors:
            raise InputError('Unknown doctor')
        with self.store.connect(write=True) as db:
            return self.book(db, phone, day, clock, doctor)

    def cancel(self, db, phone, request, booking_id=None):
        rows = db.execute('SELECT * FROM bookings WHERE phone=? AND cancelled_at IS NULL ORDER BY day,time,id', (phone,)).fetchall()
        matches = [r for r in rows if self.clinic.at(r['day'], r['time']) >= self.clinic.now
                   and (booking_id is None or r['id'] == booking_id)
                   and all(request[k] is None or request[k] == r[column] for k, column in [('date','day'),('time','time'),('doctor','doctor')])]
        if not matches:
            return self.response('refused', 'no_owned_booking', 'I could not find a matching upcoming booking under your phone number.')
        if len(matches) > 1:
            return self.response('asked', 'ambiguous_cancellation', 'You have more than one upcoming booking; which date and time should I cancel?')
        row = matches[0]
        db.execute('UPDATE bookings SET cancelled_at=? WHERE id=? AND phone=? AND cancelled_at IS NULL',
                   (self.clinic.now.isoformat(), row['id'], phone))
        booking = self.public(row)
        return self.response('cancelled', 'cancelled', f"Cancelled your booking #{row['id']}: {self.describe(booking)} IST.", booking=booking)

    def cancel_direct(self, booking_id, phone):
        phone_number(phone)
        with self.store.connect(write=True) as db:
            return self.cancel(db, phone, dict(date=None, time=None, doctor=None), booking_id)

    def decide(self, db, phone, request):
        if request is None:
            return self.response('asked', 'invalid_extraction', 'I could not reliably understand that; could you send the date, time and doctor again?')
        day, clock, doctor = (request[k] for k in ('date', 'time', 'doctor'))
        if request['clarification']:
            options = self.alternatives(db, day, clock, doctor) if request['intent'] == 'book' else []
            context = f"The clinic is closed on {date.fromisoformat(day):%d %B}. " if day in self.clinic.closed else ''
            return self.response('asked', 'clarification', context + request['clarification'], options)
        if request['intent'] == 'cancel':
            return self.cancel(db, phone, request)
        if request['intent'] == 'other':
            return self.response('asked', 'unsupported', 'I can help book or cancel an appointment; what date and time would you like?')
        if not day or not clock:
            question = 'What date would you like?' if not day else 'What time would you like?'
            return self.response('asked', 'missing_details', question, self.alternatives(db, day, clock, doctor))
        scheduled = [s for s in self.clinic.slots(day, doctor) if s['time'] == clock]
        if not scheduled:
            return self.response('refused', 'invalid_slot', 'That request does not fit an available working time or is in the past.', self.alternatives(db, day, clock, doctor))
        if doctor is None:
            # Choose a doctor only when the schedule leaves one option. A booked
            # slot should not silently send the patient to another doctor.
            if len(scheduled) != 1:
                return self.response('asked', 'doctor_required', 'Would you like Dr. Rao or Dr. Iyer?', self.alternatives(db, day, clock))
            doctor = scheduled[0]['doctor']
        return self.book(db, phone, day, clock, doctor)

    def message(self, payload):
        if set(payload) - {'id', 'from', 'text', 'sent_at_same_time_as'} or not {'id', 'from', 'text'} <= set(payload):
            raise InputError('Required message fields: id, from, text')
        mid, phone, text = payload['id'], phone_number(payload['from']), payload['text']
        if type(mid) is not str or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', mid):
            raise InputError('Invalid message id')
        if type(text) is not str or not 1 <= len(text.strip()) <= 2000:
            raise InputError('text must contain 1..2000 characters')
        try:
            text.encode('utf-8')
        except UnicodeEncodeError as exc:
            raise InputError('text must be valid Unicode') from exc
        # Return saved replies without calling the parser again. We check again
        # inside the transaction in case two copies arrive at the same time.
        with self.store.connect() as db:
            existing = db.execute('SELECT * FROM messages WHERE id=?', (mid,)).fetchone()
            if existing:
                if existing['phone'] != phone or existing['text'] != text:
                    raise InputError('Message id reused with different content')
                return json.loads(existing['response'])
        # Parse before taking the write lock so a slow provider does not block bookings.
        request, attempts = extract(text, self.clinic, self.provider)
        with self.store.connect(write=True) as db:
            existing = db.execute('SELECT * FROM messages WHERE id=?', (mid,)).fetchone()
            if existing:
                if existing['phone'] != phone or existing['text'] != text:
                    raise InputError('Message id reused with different content')
                return json.loads(existing['response'])
            result = self.decide(db, phone, request)
            result.update(message_id=mid, extraction=request, attempts=attempts, provider='rules' if isinstance(self.provider, RulesProvider) else 'injected')
            db.execute('INSERT INTO messages(id,phone,text,response) VALUES(?,?,?,?)', (mid, phone, text, json.dumps(result)))
            return result

    def appointments(self, day):
        day_value(day)
        with self.store.connect() as db:
            return [self.public(r) for r in db.execute('SELECT * FROM bookings WHERE day=? AND cancelled_at IS NULL ORDER BY time,doctor', (day,))]
