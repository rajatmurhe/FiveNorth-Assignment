import argparse
from .config import Clinic
from .service import BookingService
from .store import Store

parser = argparse.ArgumentParser(description='Receptionist appointment list (clinic timezone)')
parser.add_argument('command', choices=['appointments'])
parser.add_argument('--date', required=True)
parser.add_argument('--db', default='data/bookings.sqlite3')
args = parser.parse_args()
service = BookingService(Clinic(), Store(args.db))
rows = service.appointments(args.date)
print(f"Sunrise Dental | {args.date} | Asia/Kolkata")
print(f"{'ID':<6}{'TIME':<8}{'DOCTOR':<14}PHONE")
for row in rows:
    print(f"{row['id']:<6}{row['time']:<8}{service.clinic.doctors[row['doctor']]['name']:<14}{row['phone']}")
if not rows:
    print('No active appointments.')
