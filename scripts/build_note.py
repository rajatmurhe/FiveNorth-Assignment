"""Regenerate the submission note. This script needs reportlab.
The booking app, evaluator and tests have zero third-party dependencies.
"""
from pathlib import Path
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

ROOT = Path(__file__).resolve().parent.parent
sections = [
('Where I drew the line between parsing and booking',
 'I used the rules fallback allowed in the brief because no LLM API key was configured. There are no live model calls in this version. The parser extracts intent, date, time and doctor into JSON. The booking code then checks working hours, closures, slot length, the fixed clock and who owns the booking. I kept these checks separate because a correctly formatted request can still ask for something the clinic cannot do. Invalid output gets at most two attempts before the system asks the patient to restate it.'),
('Preventing double bookings',
 'I used SQLite with a unique index on doctor, date and time for active bookings. Each write runs in a transaction, so checking availability is not the only protection. The concurrency test sends 12 HTTP requests for one slot: one succeeds and eleven get a conflict. The replay also sends m09 and m10 together. Either can win, but both cannot book. Message IDs and responses are saved with the booking, so retrying the same message does not repeat the action.'),
('When I chose to ask',
 'For m14, "11/12 at 5pm", the reply asks whether the patient means November 12 or December 11. I would rather ask that question than assume a date format. For m04, no doctor is given, but only Dr. Iyer works Thursday at 3 p.m., so that request can be booked. For m15, the system offers the earliest free slot and asks for confirmation. It does not automatically book someone into an appointment starting immediately.'),
('What went wrong',
 'The first run of the 15 messages passed the expected outcomes, but the m03 reply missed an important detail: November 20 is closed. That reply is now clearer. Testing other messages found more serious issues. "Day after tomorrow" could be read as tomorrow, and "cancel tomorrow at noon" could cancel an 11 a.m. booking because noon was not parsed. Both are fixed and have regression tests. The evaluator also failed to include unexpected database bookings in its wrong-booking count; that is fixed too. The before-and-after files are included in artifacts. The current run has 15/15 expected outcomes, zero wrong bookings and zero unnecessary questions. All 52 tests pass.'),
('What I would do with another day',
 'I would add a real LLM adapter and test it on a wider set of messages, then add conversation state so a patient can confirm a suggested slot. The rules parser still has limited language coverage, and passing the supplied examples does not mean it will understand every request. Rescheduling and follow-up replies are not supported. Phone numbers are trusted in this demo; real WhatsApp use would need verified sender identity. I left out a UI, login and deployment since the brief did not require them. I used AI assistance for implementation, tests and documentation.')
]

def main():
    title = ParagraphStyle('title', fontName='Helvetica-Bold', fontSize=22, leading=25, textColor=colors.HexColor('#153d36'))
    sub = ParagraphStyle('sub', fontName='Helvetica', fontSize=9, leading=13, textColor=colors.HexColor('#62716d'))
    head = ParagraphStyle('head', fontName='Helvetica-Bold', fontSize=10, leading=13, textColor=colors.HexColor('#153d36'), spaceAfter=3)
    body = ParagraphStyle('body', fontName='Helvetica', fontSize=9.3, leading=13, alignment=TA_LEFT, textColor=colors.HexColor('#26332f'))
    story = [Paragraph('Notes on the implementation', title), Spacer(1, 7), Paragraph('Rajat Murhe | Five North Labs internship task', sub), Spacer(1, 18)]
    for heading, text in sections:
        story.extend([Paragraph(heading, head), Paragraph(text, body), Spacer(1, 12)])
    def footer(canvas, doc):
        canvas.setStrokeColor(colors.HexColor('#d7e1dc'))
        canvas.line(43, 38, A4[0]-43, 38)
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(colors.HexColor('#62716d'))
        canvas.drawString(43, 24, 'Five North Labs | Developer internship assessment | November 2026')
        canvas.drawRightString(A4[0]-43, 24, str(doc.page))
    SimpleDocTemplate(str(ROOT/'SUBMISSION_NOTE.pdf'), pagesize=A4, rightMargin=43, leftMargin=43, topMargin=38, bottomMargin=48,
                      title='Sunrise Dental - Engineering note', author='Rajat Murhe').build(story, onFirstPage=footer, onLaterPages=footer)
    (ROOT/'SUBMISSION_NOTE.md').write_text('# Notes on the implementation\n\n' + '\n\n'.join('## '+h+'\n\n'+t for h,t in sections)+'\n')

if __name__ == '__main__':
    main()
