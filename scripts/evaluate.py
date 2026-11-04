"""Send the supplied messages through the API and compare with expected.json."""
import argparse
import json
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from booking.config import Clinic, ROOT
from booking.server import Server
from booking.service import BookingService
from booking.store import Store


def call(base, path, payload=None):
    req = Request(base + path, data=json.dumps(payload).encode() if payload is not None else None,
                  headers={'Content-Type': 'application/json'})
    try:
        with urlopen(req, timeout=15) as response:
            return response.status, json.load(response)
    except HTTPError as exc:
        return exc.code, json.load(exc)


def measure(results, expected, appointments):
    """Check both the API replies and what was actually saved in the database."""
    from collections import Counter
    senders = {m['id']: m['from'] for m in json.loads((ROOT / 'messages.json').read_text())}
    wrong_ids, seen_slots = set(), set()
    unnecessary, correct = 0, 0
    counts = Counter(r.get('message_id') for r in results)
    coverage_ok = set(counts) == set(expected) and all(n == 1 for n in counts.values())
    race = [r for r in results if r.get('message_id') in ('m09', 'm10')]
    race_ok = (len(race) == 2 and {r.get('message_id') for r in race} == {'m09', 'm10'}
               and sum(r.get('status') == 'booked' for r in race) == 1
               and sum(r.get('status') == 'refused' and r.get('code') == 'slot_taken' for r in race) == 1)
    per_message = []
    for index, result in enumerate(results):
        mid = result.get('message_id')
        exp = expected.get(mid, {})
        booking = result.get('booking') or {}
        slot = [booking.get(k) for k in ('date', 'time', 'doctor')]
        is_booked = result.get('status') == 'booked'
        bad_booking = is_booked and ('booked' not in exp.get('status', [])
            or slot != exp.get('slot') or booking.get('phone') != senders.get(mid)
            or tuple(slot) in seen_slots or type(booking.get('id')) is not int)
        if is_booked:
            seen_slots.add(tuple(slot))
        if bad_booking:
            wrong_ids.add(('id', booking['id']) if type(booking.get('id')) is int else ('response', index))
        unnecessary += int(result.get('status') == 'asked' and exp.get('clear_to_book', False))
        ok = (counts[mid] == 1 and result.get('status') in exp.get('status', [])
              and result.get('code') in exp.get('codes', []) and not bad_booking)
        if result.get('status') == 'cancelled':
            ok = ok and slot == exp.get('slot') and booking.get('phone') == senders.get(mid)
        if exp.get('race_group'):
            ok = ok and race_ok
        correct += int(ok)
        per_message.append({'id': mid, 'correct': ok, 'status': result.get('status'), 'reason': exp.get('reason', 'Unexpected message')})
    # Work out which bookings should remain using the original inputs.
    survivor_ids = ['m02', 'm04', 'm13']
    winner = next((r for r in race if r.get('status') == 'booked'), None)
    if winner:
        survivor_ids.append(winner['message_id'])
    wanted = Counter((senders[mid], *expected[mid]['slot']) for mid in survivor_ids)
    actual = Counter()
    occupied = set()
    for index, row in enumerate(appointments):
        key = tuple(row.get(k) for k in ('phone', 'date', 'time', 'doctor'))
        slot = key[1:]
        actual[key] += 1
        if actual[key] > wanted[key] or slot in occupied:
            wrong_ids.add(('id', row['id']) if type(row.get('id')) is int else ('row', index))
        occupied.add(slot)
    return {'wrong_bookings': len(wrong_ids), 'unnecessary_questions': unnecessary,
            'messages_handled_correctly': correct, 'total_messages': len(results),
            'race_passed': race_ok, 'message_coverage_correct': coverage_ok,
            'persisted_state_correct': actual == wanted,
            'per_message': per_message}


def replay(base):
    messages = json.loads((ROOT / 'messages.json').read_text())
    results = []
    index = 0
    while index < len(messages):
        msg = messages[index]
        if msg['id'] == 'm09':
            barrier = threading.Barrier(2)
            def send(message):
                barrier.wait(timeout=5)
                status, result = call(base, '/messages', message)
                if status != 200:
                    raise RuntimeError(result)
                return result
            with ThreadPoolExecutor(max_workers=2) as pool:
                results.extend(pool.map(send, messages[index:index + 2]))
            index += 2
        else:
            status, result = call(base, '/messages', msg)
            if status != 200:
                raise RuntimeError(result)
            results.append(result)
            index += 1
    return results


def run(db_path):
    service = BookingService(Clinic(), Store(db_path))
    server = Server(('127.0.0.1', 0), service)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        results = replay(f'http://127.0.0.1:{server.server_port}')
        with service.store.connect() as db:
            appointments = [service.public(r) for r in db.execute('SELECT * FROM bookings WHERE cancelled_at IS NULL')]
        metrics = measure(results, json.loads((ROOT / 'expected.json').read_text()), appointments)
        return {'mode': 'rules (no LLM calls)', 'fixed_now': service.clinic.now.isoformat(),
                'metrics': metrics, 'results': results, 'active_appointments': appointments}
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='artifacts/evaluation.json')
    parser.add_argument('--db', help='Retain demo database at this NEW path; existing files are never overwritten')
    args = parser.parse_args()
    if args.db:
        if Path(args.db).exists():
            parser.error('--db must be a new path; refusing to overwrite existing bookings')
        report = run(args.db)
    else:
        with tempfile.TemporaryDirectory() as directory:
            report = run(Path(directory) / 'demo.sqlite3')
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    for item in report['metrics']['per_message']:
        print(f"{item['id']}  {item['status']:<10} {'PASS' if item['correct'] else 'FAIL'}")
    print(json.dumps({k:v for k,v in report['metrics'].items() if k != 'per_message'}, indent=2))
    print(f'Full patient replies and extraction trace: {path}')
    metrics = report['metrics']
    return 0 if (metrics['wrong_bookings'] == 0 and metrics['unnecessary_questions'] == 0
                 and metrics['messages_handled_correctly'] == 15 and metrics['race_passed']
                 and metrics['persisted_state_correct'] and metrics['message_coverage_correct']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
