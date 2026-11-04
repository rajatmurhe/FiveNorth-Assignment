import argparse
import json
import logging
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .config import Clinic
from .service import BookingService, InputError
from .store import Store


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64
    def __init__(self, address, service):
        self.service = service
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass  # Do not log patient text/phone numbers.

    def send_json(self, status, payload):
        data = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def body(self):
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            raise InputError('Content-Type must be application/json')
        try:
            size = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            raise InputError('Invalid Content-Length')
        if not 1 <= size <= 16384:
            raise InputError('JSON body must be 1..16384 bytes')
        try:
            def unique_fields(pairs):
                obj = {}
                for key, value in pairs:
                    if key in obj:
                        raise ValueError('Duplicate JSON key')
                    obj[key] = value
                return obj
            body = json.loads(self.rfile.read(size), object_pairs_hook=unique_fields)
        except (ValueError, UnicodeDecodeError, RecursionError):
            raise InputError('Invalid JSON body')
        if type(body) is not dict:
            raise InputError('JSON body must be an object')
        return body

    def dispatch(self):
        service = self.server.service
        url = urlparse(self.path)
        query = parse_qs(url.query)
        if self.command == 'GET' and url.path == '/health':
            return 200, {'ok': True, 'clinic': service.clinic.raw['clinic'], 'now': service.clinic.now.isoformat(), 'provider': 'rules'}
        if self.command == 'GET' and url.path in {'/availability', '/appointments'}:
            if 'date' not in query:
                raise InputError('date query parameter is required')
            day = query['date'][0]
            if url.path == '/availability':
                return 200, {'slots': service.availability(day, query.get('doctor', [None])[0])}
            return 200, {'appointments': service.appointments(day)}
        if self.command == 'POST' and url.path == '/messages':
            return 200, service.message(self.body())
        if self.command == 'POST' and url.path == '/bookings':
            result = service.book_direct(self.body())
            return (201 if result['status'] == 'booked' else 409), result
        if self.command == 'POST' and url.path.startswith('/bookings/') and url.path.endswith('/cancel'):
            parts = url.path.strip('/').split('/')
            if len(parts) != 3 or not parts[1].isascii() or not parts[1].isdigit() or len(parts[1]) > 19:
                raise InputError('Invalid booking id')
            if not 1 <= int(parts[1]) <= 2**63 - 1:
                raise InputError('Invalid booking id')
            body = self.body()
            if set(body) != {'phone'}:
                raise InputError('Required field: phone')
            result = service.cancel_direct(int(parts[1]), body['phone'])
            return (200 if result['status'] == 'cancelled' else 404), result
        return 404, {'error': 'Route not found'}

    def handle_request(self):
        self.connection.settimeout(5)
        try:
            status, payload = self.dispatch()
        except InputError as exc:
            status, payload = 400, {'error': str(exc)}
        except sqlite3.OperationalError:
            status, payload = 503, {'error': 'Storage temporarily unavailable; please retry'}
        except TimeoutError:
            status, payload = 408, {'error': 'Request timed out'}
        except Exception:
            logging.exception('Unexpected server error')
            status, payload = 500, {'error': 'Internal server error'}
        self.send_json(status, payload)

    do_GET = handle_request
    do_POST = handle_request


def main():
    parser = argparse.ArgumentParser(description='Local-only appointment booking API')
    parser.add_argument('--db', default='data/bookings.sqlite3')
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    server = Server(('127.0.0.1', args.port), BookingService(Clinic(), Store(args.db)))
    print(f'Sunrise Dental • http://127.0.0.1:{server.server_port} • rules provider', flush=True)
    print('Fixed clock: ' + server.service.clinic.now.isoformat(), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
