# Strict review against the assignment

**Verdict:** The required local assessment workflow is implemented and verified in the disclosed rules mode. The original 15-message pass was insufficient evidence of language safety: further review found and fixed wrong-booking and wrong-cancellation cases. This is a bounded prototype, not a production-ready conversational assistant.

## Requirement audit

| Requirement | Finding and evidence |
|---|---|
| Availability, booking and cancellation API | Implemented; endpoint and input-validation tests pass. |
| Clinic rules in code; fixed now everywhere | Schedule generation uses clinic.json, its timezone, closure list and fixed now. Past, off-grid, lunch, end-of-day and weekend checks are tested. |
| Simultaneous requests cannot double book | SQLite partial unique index and transaction; 12 real simultaneous HTTP requests yield one success and 11 conflicts. A direct database test proves the index independently of the service. |
| Cancel only the sender's own booking | Phone-scoped queries, ambiguous cancellation asks, unowned requests refuse without disclosing another booking. Noon and unparsed-constraint regressions now prevent unintended cancellation. |
| LLM extraction or disclosed fallback | Uses the permitted rules fallback. No live LLM calls or live-model benchmark. The provider boundary accepts JSON and is tested with injected malformed responses. |
| Strict validation and bounded retries | Rejects wrong types, unknown doctors, impossible dates, duplicate keys, extra fields and malformed JSON. Maximum two attempts; failure asks without mutation. |
| Stranger text cannot change clinic rules | Text never writes configuration; scheduling and ownership remain in code. Claiming to be the owner cannot book 02:00. This does not prove general semantic resistance to arbitrary language. |
| Decision and patient reply, with real alternatives | Every supplied message gets a response; suggestions come from current free slots, preserve a specified doctor, and are never booked automatically. |
| Persistence and receptionist view | SQLite survives restart; CLI and read-only endpoint list active day appointments. No dashboard is required by the brief. |
| Expected outcome for all 15 | expected.json gives statuses, codes, exact booking tuples, interpretation assumptions and the symmetric race expectation. |
| Self-measurement | Real HTTP replay reports wrong bookings, unnecessary questions and correct outcomes; now also counts unexpected persisted bookings, verifies race sender identity, and detects missing/duplicate message results. |
| README and one-page note | Zero application dependencies; commands verified from an extracted zip. PDF remains one page. |
| Honest account of failures | Original and strict-review artifacts preserve genuine failures. Rules-mode limitations are explicit. |

## Findings fixed during this review

1. **Wrong day:** “day after tomorrow” matched the substring “tomorrow”. It now resolves to November 18. Unsupported expressions such as “next week Wednesday” ask for an exact date instead of booking the upcoming Wednesday.
2. **Wrong cancellation:** “cancel tomorrow at noon” dropped its time constraint and could cancel an 11:00 appointment. Noon now means 12:00. Unsupported cancellation qualifiers ask instead of discarding constraints.
3. **Wrong doctor:** a known doctor's name elsewhere in a message could hide an explicit unknown doctor. Unknown named doctors now force clarification.
4. **Partial date/time matches:** two-digit years, seconds, decimal times and ranges could be truncated or misread. Unsupported representations now ask for clarification. Multiple weekday/relative-date mentions also ask.
5. **Unintended extra booking:** rescheduling language could create a new booking without changing the old one. It now explains the unsupported operation and asks about cancellation first.
6. **Misleading safety metric:** an unexpected stored booking only failed a boolean check while the wrong-booking count stayed zero. The count now includes unexpected/duplicate persisted bookings; identity comparisons use original sender fixtures, not claimed response values.
7. **Redelivery dependency:** a completed message still invoked the parser before checking its saved result. It now returns the persisted result without another provider call, while retaining the in-transaction race check.
8. **Malformed API inputs:** duplicate JSON keys, out-of-range booking IDs and invalid Unicode now produce client errors without mutation.

## Verification

- **52 automated tests pass**, including concurrency, persistence, validation, cancellation, evaluator fault checks and new semantic regressions.
- **15/15 supplied outcomes correct; zero wrong bookings and zero unnecessary questions** under the explicit expected-outcome policy.
- **10 additional review examples** have before/after artifacts. They include valid messages that now book correctly and unsafe inputs that now ask or refuse.
- The evaluator checks structured outcomes and persisted state; it does not fully grade response prose.

## Residual limitations affecting evaluation

- A rules parser can still misunderstand unseen language. This review does not establish zero wrong bookings for all possible messages. A tested LLM adapter plus a larger unseen-language evaluation set is the principal next improvement.
- m02 availability phrasing is treated as booking intent; m15 earliest-slot wording asks for confirmation. These are documented product choices, not uniquely correct interpretations.
- There is no follow-up conversation state. A response such as “yes” cannot confirm a prior proposal; a complete request must be resent.
- Phone identity is supplied by the trusted fixture in this demo. Real callers could spoof that field without a verified WhatsApp transport; authentication was excluded by the assessment.
- Alternatives are snapshots within a bounded search window, not holds. The next booking attempt rechecks availability atomically.
