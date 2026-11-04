"""Regression cases found by reviewing the brief beyond the supplied examples."""
import copy
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from tests import test_booking as fixtures
from booking.config import ROOT
from booking.server import Server
from booking.service import InputError
from scripts.evaluate import measure, run, call


class ParserReviewTests(fixtures.Base):
    def test_day_after_tomorrow_is_not_tomorrow(self):
        result = self.message('Book day after tomorrow at 11am with Rao')
        self.assertEqual(result['status'], 'booked')
        self.assertEqual(result['booking']['date'], '2026-11-18')

    def test_unsupported_date_qualifiers_do_not_book(self):
        for i, text in enumerate(['Book next week Wednesday 11am Rao', 'Book 21/11/27 at 10:30 Rao', 'Book in two weeks Wednesday 11am Rao']):
            with self.subTest(text=text):
                self.assertEqual(self.message(text, mid=f'date{i}')['status'], 'asked')
        self.assertEqual(self.service.appointments('2026-11-18'), [])

    def test_unknown_doctor_cannot_be_hidden_by_known_name(self):
        result = self.message('Book tomorrow 11am Dr Smith; Rao is unavailable')
        self.assertEqual(result['status'], 'asked')
        self.assertIsNone(result['booking'])

    def test_time_precision_and_ranges_never_truncated(self):
        for i, text in enumerate(['Book tomorrow 11:30:45 Rao', 'Book tomorrow 11.00am Rao', 'Book tomorrow 11-12pm Rao']):
            with self.subTest(text=text):
                self.assertEqual(self.message(text, mid=f'time{i}')['status'], 'asked')

    def test_cancel_noon_does_not_cancel_eleven(self):
        self.book()
        result = self.message('Cancel tomorrow at noon')
        self.assertEqual(result['status'], 'refused')
        self.assertEqual(self.service.appointments('2026-11-17')[0]['time'], '11:00')

    def test_noon_book_and_cancel(self):
        result = self.message('Book tomorrow at noon with Rao')
        self.assertEqual(result['booking']['time'], '12:00')
        self.assertEqual(self.message('cancel tomorrow at noon', mid='cancel')['status'], 'cancelled')

    def test_unsupported_cancel_constraints_never_discarded(self):
        self.book()
        for i, text in enumerate(['cancel my appointment in the evening', 'cancel appointment #2', 'cancel my appointment next week', 'cancel my November appointment']):
            with self.subTest(text=text):
                self.assertEqual(self.message(text, mid=f'cancel{i}')['status'], 'asked')
        self.assertEqual(len(self.service.appointments('2026-11-17')), 1)

    def test_reschedule_does_not_create_second_booking(self):
        self.book()
        result = self.message('Please reschedule my appointment to tomorrow 12 noon Rao')
        self.assertEqual(result['status'], 'asked')
        self.assertEqual(len(self.service.appointments('2026-11-17')), 1)

    def test_multiple_weekdays_or_relative_dates(self):
        for i, text in enumerate(['Book Tuesday Wednesday 11am Rao', 'Book today tomorrow 11am Rao']):
            self.assertEqual(self.message(text, mid=f'multi{i}')['status'], 'asked')

    def test_redelivery_does_not_call_provider(self):
        first = self.message('tomorrow 11am Rao')
        def unavailable(_):
            raise AssertionError('Completed message must not invoke provider again')
        self.service.provider = unavailable
        self.assertEqual(self.message('tomorrow 11am Rao'), first)

    def test_invalid_unicode_is_client_error(self):
        with self.assertRaises(InputError):
            self.message('tomorrow 11am Rao\ud800')


class MetricReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as directory:
            cls.report = run(Path(directory) / 'eval.sqlite3')
        cls.expected = json.loads((ROOT / 'expected.json').read_text())

    def score(self, mutate):
        report = copy.deepcopy(self.report)
        mutate(report)
        return measure(report['results'], self.expected, report['active_appointments'])

    def test_extra_database_booking_increments_wrong_metric(self):
        def mutate(r):
            r['active_appointments'].append(dict(id=999, phone='+919800000088', date='2026-11-18', time='18:00', doctor='rao'))
        metrics = self.score(mutate)
        self.assertEqual(metrics['wrong_bookings'], 1)
        self.assertFalse(metrics['persisted_state_correct'])

    def test_database_duplicate_increments_wrong_metric(self):
        def mutate(r):
            duplicate = dict(r['active_appointments'][0], id=999)
            r['active_appointments'].append(duplicate)
        self.assertEqual(self.score(mutate)['wrong_bookings'], 1)

    def test_wrong_phone_in_race_not_trusted(self):
        def mutate(r):
            winner = next(x for x in r['results'] if x['message_id'] in ('m09','m10') and x['status'] == 'booked')
            winner['booking']['phone'] = '+919800000099'
            for row in r['active_appointments']:
                if row['id'] == winner['booking']['id']:
                    row['phone'] = '+919800000099'
        metrics = self.score(mutate)
        self.assertEqual(metrics['wrong_bookings'], 1)
        self.assertFalse(metrics['persisted_state_correct'])

    def test_missing_and_duplicate_message_results(self):
        def mutate(r):
            r['results'][-1] = copy.deepcopy(r['results'][0])
        metrics = self.score(mutate)
        self.assertFalse(metrics['message_coverage_correct'])
        self.assertLess(metrics['messages_handled_correctly'], 15)

    def test_missing_booking_payload_is_counted_not_crash(self):
        def mutate(r):
            r['results'][0]['booking'] = None
        self.assertEqual(self.score(mutate)['wrong_bookings'], 1)

    def test_cancelled_message_must_not_book(self):
        def mutate(r):
            r['results'][10]['status'] = 'booked'
            r['results'][10]['code'] = 'booked'
        self.assertGreaterEqual(self.score(mutate)['wrong_bookings'], 1)


class HTTPReviewTests(fixtures.Base):
    def test_duplicate_keys_and_oversized_booking_ids(self):
        server = Server(('127.0.0.1', 0), self.service)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            request = Request(base + '/bookings', data=b'{"phone":"+919800000001","phone":"+919800000002","date":"2026-11-17","time":"11:00","doctor":"rao"}', headers={'Content-Type':'application/json'})
            with self.assertRaises(HTTPError) as context:
                urlopen(request, timeout=5)
            self.assertEqual(context.exception.code, 400)
            context.exception.close()
            for booking_id in ['0', '9'*30, str(2**63)]:
                self.assertEqual(call(base, f'/bookings/{booking_id}/cancel', {'phone': '+919800000001'})[0], 400)
            self.assertEqual(self.service.appointments('2026-11-17'), [])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
