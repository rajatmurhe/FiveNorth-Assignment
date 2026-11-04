"""Rules-based message parser. Its output goes through the same checks as model JSON.

This is explicitly NOT an LLM. No credentials or network are required. Recognized
ambiguities ask a question; arbitrary language is not guaranteed to be understood.
A provider is a callable(text)->str.
"""
import json
import re
from datetime import date, timedelta

FIELDS = {'intent', 'date', 'time', 'doctor', 'clarification'}


class InvalidExtraction(ValueError):
    pass


def validate(raw, clinic):
    if type(raw) is not str or len(raw) > 8192:
        raise InvalidExtraction('Expected a bounded JSON string')
    try:
        def pairs(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise InvalidExtraction('Duplicate JSON key')
                result[key] = value
            return result
        obj = json.loads(raw, object_pairs_hook=pairs)
        if type(obj) is not dict or set(obj) != FIELDS:
            raise InvalidExtraction('Unexpected fields')
        if type(obj['intent']) is not str or obj['intent'] not in {'book', 'cancel', 'other'}:
            raise InvalidExtraction('Invalid intent')
        for key in FIELDS - {'intent'}:
            if obj[key] is not None and type(obj[key]) is not str:
                raise InvalidExtraction(f'Invalid type for {key}')
        if obj['date'] is not None:
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', obj['date']):
                raise InvalidExtraction('Invalid date format')
            date.fromisoformat(obj['date'])
        if obj['time'] is not None and not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', obj['time']):
            raise InvalidExtraction('Invalid time')
        if obj['doctor'] is not None and obj['doctor'] not in clinic.doctors:
            raise InvalidExtraction('Unknown doctor')
        if obj['clarification'] is not None and len(obj['clarification']) > 300:
            raise InvalidExtraction('Clarification too long')
        return obj
    except (ValueError, TypeError, RecursionError) as exc:
        raise InvalidExtraction(str(exc)) from exc


def extract(text, clinic, provider, max_attempts=2):
    """Retry once if the output is invalid or the provider is temporarily unavailable."""
    if not 1 <= max_attempts <= 3:
        raise ValueError('max_attempts must be 1..3')
    for attempt in range(1, max_attempts + 1):
        try:
            return validate(provider(text), clinic), attempt
        except (InvalidExtraction, TimeoutError, ConnectionError):
            pass
    return None, max_attempts


class RulesProvider:
    def __init__(self, clinic):
        self.clinic = clinic

    def __call__(self, text):
        s = text.lower().strip()
        # Handle a few common Hindi words used in appointment requests.
        for old, new in {'कल': 'kal', 'आज': 'today', 'शाम': 'shaam', 'सुबह': 'subah',
                         'बजे': 'baje', 'राव': 'rao', 'अय्यर': 'iyer',
                         'कल सुबह': 'kal subah'}.items():
            s = s.replace(old, new)
        s = s.translate(str.maketrans('०१२३४५६७८९', '0123456789'))
        result = dict(intent='book', date=None, time=None, doctor=None, clarification=None)
        if re.search(r'\bcancel\b|रद्द', s):
            result['intent'] = 'cancel'
        doctors = [key for key in self.clinic.doctors if re.search(r'\b' + re.escape(key) + r'\b', s)]
        if len(doctors) == 1:
            result['doctor'] = doctors[0]
        elif len(doctors) > 1:
            result['clarification'] = 'Which doctor would you like?'
        elif re.search(r'\bdr\.?\s+\w+|\bdoctor\s+[a-z]+|\bwith\s+[a-z]+', s) and not re.search(r'\b(any|bhi) doctor\b', s):
            result['clarification'] = 'Would you like Dr. Rao or Dr. Iyer?'
        today = self.clinic.now.date()
        if re.search(r'\bday after tomorrow\b', s):
            result['date'] = (today + timedelta(days=2)).isoformat()
        elif re.search(r'\btomorrow\b|\bkal\b', s):
            result['date'] = (today + timedelta(days=1)).isoformat()
        elif re.search(r'\btoday\b|\btonight\b', s):
            result['date'] = today.isoformat()
        numeric = re.search(r'\b(\d{1,2})/(\d{1,2})(?:/(\d{4}))?\b', s)
        named = re.search(r'\b(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*(?:\s+(\d{4}))?\b', s)
        iso = re.search(r'\b\d{4}-\d{2}-\d{2}\b', s)
        try:
            explicit = None
            if iso:
                explicit = date.fromisoformat(iso[0]).isoformat()
            elif numeric:
                d, m = int(numeric[1]), int(numeric[2])
                if d <= 12 and m <= 12 and d != m:
                    result['clarification'] = f'Do you mean {d} {date(2000, m, 1):%B} or {m} {date(2000, d, 1):%B}?'
                explicit = date(int(numeric[3] or today.year), m, d).isoformat()
            elif named:
                month = ['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec'].index(named[2]) + 1
                explicit = date(int(named[3] or today.year), month, int(named[1])).isoformat()
            if explicit:
                if result['date'] and explicit != result['date']:
                    result['clarification'] = 'Which exact date would you like?'
                result['date'] = explicit
        except ValueError:
            result['clarification'] = 'What valid calendar date would you like?'
            result['date'] = None
        weekday_names = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
        weekday = re.search(r'\b(mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|thu(?:rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)\b', s)
        if weekday:
            idx = weekday_names.index(weekday[1][:3])
            if result['date']:
                if date.fromisoformat(result['date']).weekday() != idx:
                    result['clarification'] = 'The weekday and date disagree; which exact date do you mean?'
            else:
                delta = (idx - today.weekday()) % 7 or 7
                day = today + timedelta(days=delta)
                result['date'] = day.isoformat()
                if re.search(r'\bnext\s+' + weekday[1], s):
                    result['clarification'] = f'Do you mean {day:%d %B} or {day + timedelta(days=7):%d %B}?'
        clock = re.search(r'\b(\d{1,2})(?::(\d{2}))?\s*(am|pm|noon|baje)\b', s)
        if not clock:
            clock = re.search(r'\b(\d{1,2}):(\d{2})\b', s)
        if not clock:
            clock = re.search(r'\bat\s+(\d{1,2})(?![\d/])\b', s)
        if clock:
            hour, minute = int(clock[1]), int(clock[2] or 0) if clock.lastindex >= 2 else 0
            suffix = clock[3] if clock.lastindex >= 3 else None
            if suffix in ('am', 'pm', 'noon') and not 1 <= hour <= 12:
                result['clarification'] = 'What valid appointment time would you like?'
            else:
                if suffix == 'am':
                    hour %= 12
                elif suffix in ('pm', 'noon') or 'shaam' in s or 'evening' in s:
                    hour = hour % 12 + 12
                elif 'subah' in s or 'morning' in s:
                    hour %= 12
                elif hour < 8:
                    result['clarification'] = 'Do you mean AM or PM?'
                if 0 <= hour <= 23 and 0 <= minute <= 59:
                    result['time'] = f'{hour:02}:{minute:02}'
                else:
                    result['clarification'] = 'What valid appointment time would you like?'
        elif re.search(r'\bnoon\b', s):
            result['time'] = '12:00'
        elif re.search(r'\bmidnight\b', s):
            result['time'] = '00:00'
        if result['intent'] != 'cancel' and not any(result[k] for k in ('date', 'time', 'doctor')):
            if re.search(r'jaldi|earliest|soon|pain|dard', s):
                result['clarification'] = 'Would you like the earliest available appointment?'
            elif re.search(r'book|appointment', s):
                result['clarification'] = 'What date and time would you like?'
            else:
                result['intent'] = 'other'
        # If the message gives several options, ask instead of picking the first.
        time_mentions = re.findall(r'\b\d{1,2}(?::\d{2})?\s*(?:am|pm|noon|baje)\b|\b\d{1,2}:\d{2}\b', s)
        date_mentions = re.findall(r'\b\d{1,2}/\d{1,2}(?:/\d{4})?\b|\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b', s)
        mixed_intent = result['intent'] == 'cancel' and re.search(r'\b(book|reschedule)\b', s)
        if mixed_intent:
            result['clarification'] = 'Would you like to cancel your existing appointment first?'
        elif len(time_mentions) > 1 or len(date_mentions) > 1 or re.search(r"\b(not|instead|either|or|don't)\b", s):
            result['clarification'] = 'Which single date, time and doctor would you like?'
        # Catch partial matches, such as reading 21/11/27 as just 21/11.
        weekday_mentions = re.findall(r'\b(?:mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|thu(?:rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)\b', s)
        relative_mentions = re.findall(r'\b(?:tomorrow|today|tonight|kal)\b', s)
        explicit_doctors = re.findall(r'\b(?:dr\.?|doctor)\s+([a-z]+)', s)
        with_doctors = re.findall(r'\bwith\s+(?!dr\b|doctor\b)([a-z]+)', s)
        unknown_doctor = any(name not in self.clinic.doctors and name not in {'on', 'at', 'tomorrow', 'today', 'any', 'anyone'}
                             for name in explicit_doctors + with_doctors)
        if unknown_doctor:
            result['doctor'] = None
            result['clarification'] = 'Would you like Dr. Rao or Dr. Iyer?'
        if len(weekday_mentions) > 1 or len(relative_mentions) > 1:
            result['clarification'] = 'Which single calendar date do you mean?'
        if re.search(r'\b\d{1,2}/\d{1,2}/\d{1,3}\b|\b(?:next|last|this)\s+(?:week|month|year)\b|\bin\s+.+?\b(?:days?|weeks?|months?|years?)\b', s):
            result['clarification'] = 'What exact date do you mean, including the four-digit year?'
        if re.search(r'\b\d{1,2}:\d{2}:\d+\b|\b\d{1,2}\.\d+\s*(?:am|pm)?\b|\b\d{1,2}[-–]\d{1,2}\s*(?:am|pm)\b', s):
            result['clarification'] = 'What single appointment time do you mean, in HH:MM AM/PM format?'
        if re.search(r'\b(reschedule|move|change)\b', s):
            result['clarification'] = 'Rescheduling is not supported yet; would you like to cancel your existing appointment first?'
        if result['intent'] == 'cancel':
            # Do not cancel a different appointment just because a detail was missed.
            unparsed_time = result['time'] is None and re.search(r'\b(at|morning|evening|afternoon|night|noon|shaam|subah|before|after)\b|\d', s)
            unparsed_date = result['date'] is None and re.search(r'\b(next|last|week|month|year|jan\w*|feb\w*|mar\w*|apr\w*|may|jun\w*|jul\w*|aug\w*|sep\w*|oct\w*|nov\w*|dec\w*)\b|\d[/\-]\d', s)
            if unparsed_time or unparsed_date or re.search(r'#\s*\d|\bid\s*\d', s):
                result['clarification'] = 'Which exact date and time should I cancel?'
        return json.dumps(result, ensure_ascii=False)
