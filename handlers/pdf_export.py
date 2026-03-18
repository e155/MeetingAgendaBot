from config import PDF_TITLE
import os
import tempfile
from datetime import datetime

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    from reportlab.lib.enums import TA_CENTER
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    REPORTLAB_OK = True
except ImportError:
    REPORTLAB_OK = False

# ── Register DejaVu fonts (cyrillic support) ───────────────
FONT_REGULAR = "DejaVuSans"
FONT_BOLD    = "DejaVuSans-Bold"

# Font search paths — system locations + project fonts/ dir
_FONT_SEARCH = [
    "/usr/share/fonts/truetype/dejavu",
    "/usr/share/fonts/dejavu",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "fonts"),
]
_FONT_URLS = {
    "DejaVuSans.ttf":      "https://github.com/dejavu-fonts/dejavu-fonts/raw/master/ttf/DejaVuSans.ttf",
    "DejaVuSans-Bold.ttf": "https://github.com/dejavu-fonts/dejavu-fonts/raw/master/ttf/DejaVuSans-Bold.ttf",
}


def _find_font(filename: str):
    """Search for font file in known locations."""
    for d in _FONT_SEARCH:
        path = os.path.join(d, filename)
        if os.path.isfile(path):
            return path
    return None


def _download_fonts():
    """Download DejaVu fonts to project fonts/ dir if not found on system."""
    try:
        import requests
        fonts_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fonts")
        os.makedirs(fonts_dir, exist_ok=True)
        for filename, url in _FONT_URLS.items():
            dest = os.path.join(fonts_dir, filename)
            if not os.path.isfile(dest):
                r = requests.get(url, timeout=15)
                r.raise_for_status()
                with open(dest, "wb") as f:
                    f.write(r.content)
        return True
    except Exception:
        return False


def _register_fonts():
    """Register DejaVu fonts. Downloads them if not found locally."""
    reg_path = _find_font("DejaVuSans.ttf")
    bold_path = _find_font("DejaVuSans-Bold.ttf")

    if not reg_path or not bold_path:
        _download_fonts()
        reg_path  = _find_font("DejaVuSans.ttf")
        bold_path = _find_font("DejaVuSans-Bold.ttf")

    if not reg_path or not bold_path:
        return False

    try:
        pdfmetrics.registerFont(TTFont(FONT_REGULAR, reg_path))
        pdfmetrics.registerFont(TTFont(FONT_BOLD,    bold_path))
        return True
    except Exception:
        return False


def build_pdf(meeting, agenda, decisions, pending, open_tasks, output_path):
    fonts_ok = _register_fonts()
    fn  = FONT_REGULAR if fonts_ok else "Helvetica"
    fnb = FONT_BOLD    if fonts_ok else "Helvetica-Bold"

    doc = SimpleDocTemplate(
        output_path, pagesize=A4,
        rightMargin=2*cm, leftMargin=2*cm,
        topMargin=2*cm, bottomMargin=2*cm
    )

    def style(name, base, **kw):
        return ParagraphStyle(name, parent=base, fontName=fn, **kw)

    base = getSampleStyleSheet()
    S = {
        'title':  ParagraphStyle('T',  fontName=fnb, fontSize=16, spaceAfter=4,
                                 alignment=TA_CENTER, textColor=colors.HexColor('#1a1a2e')),
        'h2':     ParagraphStyle('H2', fontName=fnb, fontSize=11, spaceBefore=10,
                                 spaceAfter=4, textColor=colors.HexColor('#3b8ad1')),
        'normal': ParagraphStyle('N',  fontName=fn,  fontSize=9,  leading=13, spaceAfter=3),
        'small':  ParagraphStyle('SM', fontName=fn,  fontSize=7,  textColor=colors.grey,
                                 alignment=TA_CENTER),
        'grey':   ParagraphStyle('GR', fontName=fn,  fontSize=8,  textColor=colors.grey,
                                 leftIndent=10),
        'bold':   ParagraphStyle('B',  fontName=fnb, fontSize=9,  leading=13),
    }

    def hr(bold=False):
        return HRFlowable(width="100%",
                          thickness=2 if bold else 0.5,
                          color=colors.HexColor('#3b8ad1') if bold else colors.lightgrey,
                          spaceAfter=6)

    def tbl_header_style(t):
        t.setStyle(TableStyle([
            ('BACKGROUND',   (0,0), (-1,0), colors.HexColor('#3b8ad1')),
            ('TEXTCOLOR',    (0,0), (-1,0), colors.white),
            ('FONTNAME',     (0,0), (-1,0), fnb),
            ('FONTSIZE',     (0,0), (-1,0), 9),
            ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white, colors.HexColor('#f5f5f5')]),
            ('GRID',         (0,0), (-1,-1), 0.4, colors.lightgrey),
            ('VALIGN',       (0,0), (-1,-1), 'TOP'),
            ('TOPPADDING',   (0,0), (-1,-1), 5),
            ('BOTTOMPADDING',(0,0), (-1,-1), 5),
            ('LEFTPADDING',  (0,0), (-1,-1), 6),
        ]))

    STATUS_LABEL = {
        'done':         'Closed',
        'pending_next': 'Deferred',
        'discussing':   'Discussed',
        'pending':      'Not reviewed',
    }

    story = []

    # ── Заголовок ────────────────────────────────────────────
    story.append(Paragraph(PDF_TITLE, S['title']))
    story.append(Spacer(1, 4))
    story.append(hr(bold=True))

    started = (meeting.get('started_at') or '')[:16].replace('T', ' ')
    ended   = (meeting.get('ended_at')   or datetime.now().strftime('%Y-%m-%d %H:%M'))[:16]
    story.append(Paragraph(f"Topic: {meeting['title']}", S['bold']))
    story.append(Paragraph(f"Start: {started}    End: {ended}", S['normal']))
    story.append(Spacer(1, 8))

    # ── 1. Повестка ──────────────────────────────────────────
    story.append(hr())
    story.append(Paragraph("1. AGENDA", S['h2']))
    if agenda:
        header_row = [
            Paragraph('#', S['bold']),
            Paragraph('Agenda Item', S['bold']),
            Paragraph('Details', S['bold']),
            Paragraph('Status', S['bold']),
        ]
        rows = [header_row]
        for i, item in enumerate(agenda, 1):
            status = STATUS_LABEL.get(item['status'], item['status'])
            rows.append([
                Paragraph(str(i), S['normal']),
                Paragraph(item['title'], S['normal']),
                Paragraph(item.get('details') or '—', S['normal']),
                Paragraph(status, S['normal']),
            ])
        t = Table(rows, colWidths=[1*cm, 7*cm, 5.5*cm, 3*cm], repeatRows=1)
        tbl_header_style(t)
        story.append(t)
    else:
        story.append(Paragraph("No agenda items.", S['grey']))

    # ── 2. Решения ───────────────────────────────────────────
    story.append(Spacer(1, 8))
    story.append(hr())
    story.append(Paragraph("2. DECISIONS", S['h2']))
    if decisions:
        for i, d in enumerate(decisions, 1):
            kind = "Done" if d['decision_type'] == 'done' else "ToDo (task)"
            resp = f"  |  Assignee: {d['responsible']}" if d.get('responsible') else ""
            ref  = f"  |  Agenda item: {d.get('agenda_title') or '—'}"
            story.append(Paragraph(f"{i}. {d['text']}", S['bold']))
            story.append(Paragraph(f"{kind}{resp}{ref}", S['grey']))
            story.append(Spacer(1, 3))
    else:
        story.append(Paragraph("No decisions were made.", S['grey']))

    # ── 3. Отложено ──────────────────────────────────────────
    if pending:
        story.append(Spacer(1, 8))
        story.append(hr())
        story.append(Paragraph("3. DEFERRED TO NEXT MEETING", S['h2']))
        for p in pending:
            resp = f"  |  Responsible: {p['responsible']}" if p.get('responsible') else ""
            note = f": {p['note']}" if p.get('note') else ""
            story.append(Paragraph(f"• {p.get('agenda_title') or '—'}{note}", S['bold']))
            if resp:
                story.append(Paragraph(resp.strip(" |").strip(), S['grey']))
            story.append(Spacer(1, 3))

    # ── 4. Задачи ────────────────────────────────────────────
    story.append(Spacer(1, 8))
    story.append(hr())
    story.append(Paragraph("4. OPEN TASKS", S['h2']))
    if open_tasks:
        header_row = [
            Paragraph('#', S['bold']),
            Paragraph('Task', S['bold']),
            Paragraph('Assignee', S['bold']),
            Paragraph('Deadline', S['bold']),
            Paragraph('Author/Editor', S['bold']),
        ]
        rows = [header_row]
        for i, t in enumerate(open_tasks, 1):
            meta = []
            if t.get('created_by_name'):
                meta.append(f"created by: {t['created_by_name']}")
            if t.get('updated_by_name'):
                meta.append(f"edited by: {t['updated_by_name']}")
            meta_str = ', '.join(meta) if meta else '—'
            # Format full details history for PDF
            details_raw = t.get('details') or ''
            if '\n--- ' in details_raw:
                # Has history — format each entry
                parts = details_raw.split('\n--- ')
                details_lines = [parts[0]]
                for part in parts[1:]:
                    if '---\n' in part:
                        sep, text = part.split('---\n', 1)
                        details_lines.append(f'<font color="grey" size="7">— {sep} —</font>')
                        details_lines.append(text.strip())
                    else:
                        details_lines.append(part)
                details_pdf = '<br/>'.join(details_lines)
            else:
                details_pdf = details_raw

            rows.append([
                Paragraph(str(i), S['normal']),
                Paragraph(f"{t['title']}<br/><font size='8' color='grey'>{details_pdf}</font>" if details_pdf else t['title'], S['normal']),
                Paragraph(t['assignee'] or '—', S['normal']),
                Paragraph(t['deadline'] or '—', S['normal']),
                Paragraph(meta_str, S['normal']),
            ])
        tbl = Table(rows, colWidths=[1*cm, 6*cm, 3.5*cm, 2.5*cm, 3.5*cm], repeatRows=1)
        tbl_header_style(tbl)
        story.append(tbl)
    else:
        story.append(Paragraph("No open tasks.", S['grey']))

    # ── Подвал ───────────────────────────────────────────────
    story.append(Spacer(1, 16))
    story.append(hr(bold=True))
    story.append(Paragraph(
        f"Auto-generated  {datetime.now().strftime('%d.%m.%Y %H:%M')}",
        S['small']
    ))

    doc.build(story)


async def send_pdf(context, chat_id, meeting, agenda, decisions, pending, open_tasks):
    if not REPORTLAB_OK:
        await context.bot.send_message(chat_id, "reportlab не установлен: pip install reportlab")
        return

    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
        tmp_path = tmp.name

    try:
        build_pdf(meeting, agenda, decisions, pending, open_tasks, tmp_path)
        safe = "".join(c for c in meeting['title'] if c.isalnum() or c in ' _-')[:30].strip()
        filename = f"protocol_{safe}.pdf"
        with open(tmp_path, 'rb') as f:
            await context.bot.send_document(
                chat_id, document=f, filename=filename,
                caption=f"{PDF_TITLE}: {meeting['title']}"
            )
    except Exception as e:
        await context.bot.send_message(chat_id, f"Ошибка генерации PDF: {e}")
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
