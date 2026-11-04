# Sunrise Dental appointment booking

This is my submission for the Five North Labs developer internship task. It has a small Python API, SQLite storage, and a script that sends the 15 supplied messages through the API.

I kept the focus on avoiding incorrect bookings. If a date or request is unclear, the system asks a question rather than choosing for the patient. The receptionist can check appointments from the terminal.

The message parser uses rules, which the brief allows when no API key is available. **There is no live LLM in this version.** I used AI assistance for the code, tests and documentation.

## Running it

You need Python 3.11 or later with timezone data, which is normally available on macOS and Linux. There are no packages to install for the app or tests.

From this folder, run:

```sh
python3 -m unittest discover -v
python3 -m scripts.evaluate
```

The first command runs the tests. The second starts a temporary API server and database, sends the messages, and prints the results. Messages are sent in order, except m09 and m10, which are sent together to test the slot conflict. Either one can win.

The current results are 52 passing tests, 15/15 expected message outcomes, zero wrong bookings and zero unnecessary questions. These numbers apply to the supplied messages and the interpretation choices below. They don't mean the parser understands every possible message.

Full results, including the replies a patient would receive, are saved in `artifacts/evaluation.json`.

To keep the demo database and view the appointments:

```sh
python3 -m scripts.evaluate --db data/demo.sqlite3
python3 -m booking appointments --date 2026-11-17 --db data/demo.sqlite3
python3 -m booking appointments --date 2026-11-18 --db data/demo.sqlite3
```

The evaluator won't overwrite an existing database. Use a new filename if you run that command again, or leave out `--db` for a fresh temporary database each time.

## Trying the API yourself

Start the server:

```sh
python3 -m booking.server
```

Then, in another terminal:

```sh
# Check free slots
curl 'http://127.0.0.1:8000/availability?date=2026-11-17&doctor=rao'

# Send a patient message
curl -X POST http://127.0.0.1:8000/messages \
  -H 'Content-Type: application/json' \
  -d '{"id":"example-1","from":"+919800000001","text":"tomorrow 11am Dr Rao"}'

# View the day's appointments
curl 'http://127.0.0.1:8000/appointments?date=2026-11-17'

# Cancel using the booking ID returned above (1 on a fresh database)
curl -X POST http://127.0.0.1:8000/bookings/1/cancel \
  -H 'Content-Type: application/json' \
  -d '{"phone":"+919800000001"}'
```

The server uses `data/bookings.sqlite3` by default. This is separate from the evaluator's database. You can use `--db data/demo.sqlite3` to open the retained demo, or `--port 8001` to change the port.

| Endpoint | What it does |
|---|---|
| `GET /health` | Shows the fixed clinic clock and parser mode |
| `GET /availability?date=YYYY-MM-DD&doctor=rao` | Lists free slots; doctor is optional |
| `POST /bookings` | Books an exact slot using `phone`, `date`, `time` and `doctor` |
| `POST /bookings/{id}/cancel` | Cancels a booking belonging to the supplied `phone` |
| `POST /messages` | Processes a message with `id`, `from` and `text` |
| `GET /appointments?date=YYYY-MM-DD` | Lists active appointments for that day |

Dates use `YYYY-MM-DD` and times use 24-hour `HH:MM`. Direct booking returns 201 on success and 409 when the slot cannot be booked. Invalid input returns 400. Cancellation returns 404 for both missing bookings and bookings owned by someone else. The message endpoint returns 200 with a result of `booked`, `cancelled`, `refused` or `asked`.

## A few decisions worth explaining

All appointment decisions use the fixed time in `clinic.json`: November 16, 2026 at 10:00 a.m., Asia/Kolkata. A slot starting exactly at that time is allowed. The system doesn't use today's real date to interpret messages.

The parser extracts the request, but the booking code checks the clinic's hours, closed dates, slot length and whether the time is in the past. Parsed JSON is also checked for wrong types, impossible dates, unknown doctors and unexpected fields. There are at most two attempts. If both fail, nothing is booked and the patient is asked to restate the request. The tests simulate bad provider responses; they don't call a real model.

For double bookings, SQLite has a unique index on doctor, date and time for active bookings. Each write uses `BEGIN IMMEDIATE`. This means the database protects the slot even if two requests arrive together. The test sends 12 HTTP requests for the same slot and checks that one succeeds and the other 11 get a conflict.

Message IDs are stored with the result in the same transaction as the booking or cancellation. Sending the same message again returns its saved response. Reusing its ID with different content is rejected. The direct booking endpoint doesn't have this replay behaviour, although it still prevents slot conflicts.

Cancellation searches only the sender's upcoming bookings. If more than one matches, it asks which one to cancel. Cancelled bookings stay in the database, but their slots become available again.

When a requested slot can't be booked, the reply offers up to three free alternatives. These keep the requested doctor and are sorted by how close they are to the requested time, preferring a later time on a tie. The search covers a 15-day window starting up to seven days before the requested date, never before the fixed current time. Suggestions aren't held or booked automatically.

## How I interpreted the messages

`expected.json` records the expected outcome for every message. A few have more than one reasonable interpretation:

- **m02:** I treated “kal shaam 6 baje Dr Rao milenge?” as a request to book tomorrow at 6 p.m. Asking for confirmation first would also be a reasonable product choice.
- **m03:** “Next Friday” could mean November 20 or 27. The reply asks which one and mentions that the 20th is closed.
- **m04:** At 3 p.m. on Thursday, only Dr. Iyer works, so the system chooses Iyer. If both doctors work at the requested time, it asks. It doesn't choose a different doctor just because one is already booked.
- **m05 and m06:** The system refuses an unavailable doctor or a time outside the slot grid. It doesn't change the doctor or round the time without asking.
- **m09 and m10:** Exactly one gets the slot. There is no preferred winner.
- **m13:** `21/11` is unambiguous, so it uses November 21 in the fixed clock's year. Bare `10:30` and `12:00` are treated as daytime.
- **m14:** `11/12` needs a question: November 12 or December 11?
- **m15:** The reply offers the earliest available slot and asks for confirmation rather than booking an immediate appointment automatically.

## What failed, and what's still limited

The original 15-message run passed, but that wasn't enough. Further checks found that “day after tomorrow” could become tomorrow, and “cancel tomorrow at noon” could cancel an 11 a.m. booking because the time was missed. Those cases are fixed and covered by tests. There were also fixes for unknown doctors, partially parsed dates and times, and rescheduling requests that could create an extra booking.

The evaluator had a bug too: an unexpected database booking failed a separate check but didn't increase the wrong-booking count. It now counts those bookings and checks the original sender numbers, message coverage and final database state. It still doesn't judge every sentence of a reply.

The main limitation is the rules parser. It handles selected English, Hindi and Hinglish expressions, but unfamiliar wording can still be misunderstood. It also has no conversation history: replying “yes” won't confirm a suggestion. The patient needs to send the full date, time and doctor again. Rescheduling isn't implemented.

The phone number is trusted input in this local demo. A caller who supplies someone else's number could impersonate them. For actual WhatsApp use, the sender would need to come from a verified webhook. The API is local only; I haven't added login, deployment or a WhatsApp connection, as these weren't required.

With more time, I'd add a real LLM adapter, test it on messages outside the supplied set, and add a confirmation step that remembers the suggested slot for each sender.

## Files to look at

- `SUBMISSION_NOTE.pdf`: the one-page note requested in the brief; a Markdown copy is included.
- `artifacts/evaluation.json`: current results and patient replies.
- `artifacts/tests.txt`: current test output.
- `artifacts/strict-review-before.json` and `strict-review-after.json`: examples of the failures and corrected behaviour.
- `artifacts/first-run.json` and `first-tests.txt`: earlier runs, kept for reference.
- `REVIEW.md`: the detailed check against the assignment.

The PDF is already included. Only regenerating it with `scripts/build_note.py` needs the optional `reportlab` package; running the application doesn't.
