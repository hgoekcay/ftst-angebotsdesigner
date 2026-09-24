"""A4 offer presentation based on the supplied FT offer reference."""
import io
import math
from price_notes import item_notes, offer_notes, unit_price_heading
from reference_selection import MAX_REFERENCE_IMAGES
from PIL import Image as PILImage, ImageOps

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate, NextPageTemplate, PageBreak,
    Paragraph, Spacer, Table, TableStyle, Flowable, KeepInFrame,
)

RED = colors.HexColor('#e30613')
INK = colors.HexColor('#15191c')
MUTED = colors.HexColor('#6c7379')
LINE = colors.HexColor('#dfe2e4')
PALE = colors.HexColor('#f6f7f6')
GREEN = colors.HexColor('#0d7d3b')
WHITE = colors.white
WIDTH = 170 * mm


class Photo(Flowable):
    """Honor camera orientation while retaining the complete original framing."""
    def __init__(self, path, height):
        super().__init__()
        self.width, self.height = 82*mm, height
        with PILImage.open(path) as source:
            self.reader = ImageReader(ImageOps.exif_transpose(source).convert('RGB'))

    def draw(self):
        canvas = self.canv
        canvas.setFillColor(PALE)
        canvas.rect(0, 0, self.width, self.height, fill=1, stroke=0)
        iw, ih = self.reader.getSize()
        scale = min(self.width / iw, self.height / ih)
        width, height = iw*scale, ih*scale
        canvas.drawImage(self.reader, (self.width-width)/2, (self.height-height)/2, width, height)


def reference_caption(value, style, escape, max_lines):
    """Use readable fixed-size type and shorten only the reference-card copy."""
    source = ' '.join(str(value or '').split())
    width = 74*mm
    height = style.leading * max_lines

    def paragraph(text):
        result = Paragraph(escape(text), style)
        _, actual_height = result.wrap(width, height)
        return result, actual_height <= height + .01

    # Bound paragraph parsing even when an old library entry has very long copy.
    if len(source) <= 600:
        result, fits = paragraph(source)
        if fits:
            return result
    left, right = 0, min(len(source), 600)
    best, _ = paragraph('...')
    while left <= right:
        middle = (left + right) // 2
        prefix = source[:middle].rstrip()
        if middle < len(source) and ' ' in prefix and not source[middle:middle+1].isspace():
            prefix = prefix.rsplit(' ', 1)[0]
        candidate, fits = paragraph(prefix + '...')
        if fits:
            best = candidate
            left = middle + 1
        else:
            right = middle - 1
    return best


class ReferenceGrid(Flowable):
    """One non-splitting 2-by-2 grid, regardless of caption or library size."""
    def __init__(self, cards):
        super().__init__()
        self.width, self.height = WIDTH, 146*mm
        self.cards = cards[:MAX_REFERENCE_IMAGES]

    def draw(self):
        canvas = self.canv
        for index, (photo, captions) in enumerate(self.cards):
            x = (index % 2) * 88*mm
            y = self.height - 70*mm - (index // 2) * 76*mm
            canvas.saveState()
            canvas.setFillColor(PALE)
            canvas.rect(x, y, 82*mm, 26*mm, fill=1, stroke=0)
            photo.drawOn(canvas, x, y+26*mm)
            cursor = y + 23*mm
            for caption in captions:
                _, height = caption.wrap(74*mm, 23*mm)
                cursor -= height
                caption.drawOn(canvas, x+4*mm, cursor)
            canvas.setStrokeColor(LINE)
            canvas.setLineWidth(.5)
            canvas.rect(x, y, 82*mm, 70*mm, fill=0, stroke=1)
            canvas.restoreState()


class NumberedCanvas(Canvas):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.states = []

    def showPage(self):
        self.states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self.states)
        for state in self.states:
            self.__dict__.update(state)
            self.setFont('Helvetica', 8)
            self.setFillColor(MUTED)
            self.drawRightString(190*mm, 8*mm, f'{self._pageNumber:02d} / {total:02d}')
            super().showPage()
        super().save()


def build(offer, escape, money, date_de, cname):
    o = offer
    is_draft = bool(o.get('is_draft'))
    profile = o.get('company_profile', {})
    customer = o['client']
    number = str(o.get('offer_number') or o.get('number') or o.get('id', ''))
    font = 'Helvetica'
    styles = {
        'body': ParagraphStyle('body', fontName=font, fontSize=10.5, leading=15, textColor=INK, spaceAfter=5),
        'small': ParagraphStyle('small', fontName=font, fontSize=8.5, leading=11, textColor=MUTED),
        'label': ParagraphStyle('label', fontName=font, fontSize=9, leading=13, textColor=RED, spaceAfter=5, keepWithNext=True),
        'title': ParagraphStyle('title', fontName='Helvetica-Bold', fontSize=27, leading=31, textColor=INK, spaceAfter=16, keepWithNext=True),
        'cover': ParagraphStyle('cover', fontName='Helvetica-Bold', fontSize=32, leading=37, textColor=INK, spaceAfter=20),
        'white': ParagraphStyle('white', fontName=font, fontSize=10, leading=14, textColor=WHITE),
        'price': ParagraphStyle('price', fontName='Helvetica-Bold', fontSize=36, leading=44, textColor=WHITE),
        'step': ParagraphStyle('step', fontName='Helvetica-Bold', fontSize=19, leading=25, textColor=RED),
        'footer': ParagraphStyle('footer', fontName=font, fontSize=7.5, leading=10, textColor=MUTED),
        'caption': ParagraphStyle('caption', fontName=font, fontSize=8.5, leading=11, textColor=INK, spaceAfter=3),
        'question': ParagraphStyle('question', fontName='Helvetica-Bold', fontSize=11, leading=14, textColor=INK, spaceAfter=4),
        'answer': ParagraphStyle('answer', fontName=font, fontSize=9, leading=12, textColor=MUTED),
        'service': ParagraphStyle('service', fontName='Helvetica-Bold', fontSize=11, leading=14, textColor=RED, alignment=1),
        'reference_label': ParagraphStyle('reference_label', fontName=font, fontSize=8, leading=10, textColor=RED),
        'reference_title': ParagraphStyle('reference_title', fontName='Helvetica-Bold', fontSize=8.5, leading=11, textColor=INK),
        'reference_detail': ParagraphStyle('reference_detail', fontName=font, fontSize=8.5, leading=11, textColor=MUTED),
    }

    def p(value, style='body'):
        return Paragraph(escape(str(value or '')), styles[style])

    def section(label, title):
        return [p(label, 'label'), p(title, 'title')]

    def box(content, width=WIDTH, background=PALE, accent=False):
        table = Table([[content]], colWidths=[width], splitInRow=1)
        table.hAlign = 'LEFT'
        commands = [('BACKGROUND', (0, 0), (-1, -1), background),
                    ('LEFTPADDING', (0, 0), (-1, -1), 7*mm),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 7*mm),
                    ('TOPPADDING', (0, 0), (-1, -1), 5*mm),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 5*mm)]
        if accent:
            commands.append(('LINEBEFORE', (0, 0), (0, -1), 2.5, RED))
        table.setStyle(TableStyle(commands))
        return table

    def draw_logo(canvas, doc):
        """Clip the original logo asset; never resample or rewrite brand artwork."""
        logo = o.get('logo_path')
        if logo:
            reader = ImageReader(logo)
            iw, ih = reader.getSize()
            left, top, crop_width, crop_height = 0, 0, iw, ih
            crop = o.get('logo_crop')
            if isinstance(crop, (list, tuple)) and len(crop) == 4:
                try:
                    candidate = tuple(float(value) for value in crop)
                    x, y, width, height = candidate
                    if (all(math.isfinite(value) for value in candidate)
                            and x >= 0 and y >= 0 and width > 0 and height > 0
                            and x + width <= iw and y + height <= ih):
                        left, top, crop_width, crop_height = candidate
                except (TypeError, ValueError, OverflowError):
                    pass
            scale = min((75 if doc.page == 1 else 63)*mm/crop_width,
                        (16 if doc.page == 1 else 14)*mm/crop_height)
            x, y = 20*mm, 270*mm
            canvas.saveState()
            clip = canvas.beginPath()
            clip.rect(x, y, crop_width*scale, crop_height*scale)
            canvas.clipPath(clip, stroke=0, fill=0)
            canvas.drawImage(reader, x-left*scale, y-(ih-top-crop_height)*scale,
                             iw*scale, ih*scale, mask='auto')
            canvas.restoreState()
        else:
            canvas.setFont('Helvetica-Bold', 12)
            canvas.setFillColor(INK)
            canvas.drawString(20*mm, 275*mm, 'FT SICHERHEITSTECHNIK')

    def draw_footer(canvas):
        canvas.setStrokeColor(LINE)
        canvas.line(20*mm, 35*mm, 190*mm, 35*mm)
        company_lines = [profile.get('company') or 'FT Sicherheitstechnik']
        if profile.get('owner'):
            company_lines.append('Inhaber: ' + str(profile['owner']))
        company_lines += [profile[key] for key in ('street', 'city') if profile.get(key)]
        contact_lines = [(label + str(profile[key])) for key, label in
                         (('phone', 'Telefon: '), ('email', 'E-Mail: '), ('website', 'Web: '))
                         if profile.get(key)]
        bank_lines = [(label + str(profile[key])) for key, label in
                      (('bank_name', 'Bank: '), ('iban', 'IBAN: '), ('bic', 'BIC: '))
                      if profile.get(key)]
        for x, width, lines in ((20, 55, company_lines), (80, 51, contact_lines), (136, 54, bank_lines)):
            if not lines:
                continue
            text = Paragraph('<br/>'.join(escape(str(line)) for line in lines), styles['footer'])
            footer = KeepInFrame(width*mm, 22*mm, [text], mode='shrink', hAlign='LEFT', vAlign='TOP')
            _, height = footer.wrapOn(canvas, width*mm, 22*mm)
            footer.drawOn(canvas, x*mm, 32*mm-height)

    def heading(canvas, doc):
        canvas.saveState()
        draw_logo(canvas, doc)
        if doc.page == 1:
            canvas.setStrokeColor(RED)
            canvas.roundRect(128*mm, 271*mm, 62*mm, 9*mm, 4.5*mm, fill=0)
            canvas.setFillColor(RED)
            canvas.setFont(font, 8)
            canvas.drawCentredString(159*mm, 274.3*mm, 'ENTWURF / NICHT FREIGEGEBEN' if is_draft else 'IHR LEISTUNGSVORSCHLAG')
            labels = [('DATENSTAND' if is_draft else 'AUSGESTELLT AM', date_de(str(o.get('catalog_at') or '')[:10]) if is_draft else date_de(o.get('date'))),
                      ('STATUS' if is_draft else 'GÜLTIGKEIT', 'Nicht freigegeben' if is_draft else (date_de(o.get('validity_date')) if o.get('validity_date') else (str(o['validity_days'])+' Tage' if o.get('validity_days') else 'Gemäß Vereinbarung'))),
                      ('ENTWURFSPREIS' if is_draft else 'IHR FESTPREIS', money(o.get('total_gross')))]
            for x, (label, value) in zip((20, 78, 136), labels):
                label_p = p(label, 'small')
                label_p.wrapOn(canvas, 53*mm, 12*mm)
                label_p.drawOn(canvas, x*mm, 52*mm)
                value_p = Paragraph(escape(value), ParagraphStyle('meta', parent=styles['body'], fontName='Helvetica-Bold', textColor=GREEN if x==136 else INK))
                _, height = value_p.wrapOn(canvas, 53*mm, 20*mm)
                value_p.drawOn(canvas, x*mm, 49*mm-height)
        else:
            info = p('ENTWURF / NICHT FREIGEGEBEN' if is_draft else f'Leistungsvorschlag {number[:35]} · {cname(customer)[:75]}', 'small')
            info_box = KeepInFrame(88*mm, 17*mm, [info], mode='shrink', hAlign='RIGHT')
            _, info_height = info_box.wrapOn(canvas, 88*mm, 17*mm)
            info_box.drawOn(canvas, 102*mm, 282*mm-info_height)
            canvas.setStrokeColor(LINE)
            canvas.line(20*mm, 265*mm, 190*mm, 265*mm)
        draw_footer(canvas)
        canvas.restoreState()

    buffer = io.BytesIO()
    doc = BaseDocTemplate(buffer, pagesize=(210*mm, 297*mm), title=f'FTST Angebotsentwurf {number}' if is_draft else f'FTST Leistungsvorschlag {number}', author=profile.get('company') or 'FT Sicherheitstechnik')
    doc.addPageTemplates([
        PageTemplate('cover', [Frame(20*mm, 68*mm, WIDTH, 144*mm, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)], onPage=heading),
        PageTemplate('content', [Frame(20*mm, 41*mm, WIDTH, 217*mm, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)], onPage=heading),
    ])
    title = o.get('customer_title') or o.get('title') or 'Ihre individuelle Sicherheitslösung.'
    if len(title) > 120:
        styles['cover'].fontSize = 25
        styles['cover'].leading = 30
    title_html = escape(title)
    for ending in (' für Ihr Objekt.', ' für Ihr Objekt'):
        if title.endswith(ending):
            title_html = escape(title[:-len(ending)]) + '<br/><font color="#6c7379">' + escape(ending.strip()) + '</font>'
            break
    details = [p('ERSTELLT FÜR', 'small'), Paragraph('<b>'+escape(cname(customer))+'</b>', styles['body'])]
    address = ' · '.join(x for x in [customer.get('street'), ' '.join(str(customer.get(k) or '') for k in ('zip','city')).strip()] if x)
    if address:
        details.append(p(address, 'small'))
    story = [NextPageTemplate('content'), p('ANGEBOTSENTWURF' if is_draft else 'LEISTUNGSVORSCHLAG · '+number, 'label'), Paragraph(title_html, styles['cover']),
             p(o.get('customer_intro')), Spacer(1, 12*mm), box(details, width=128*mm, accent=True),
             NextPageTemplate('content'), PageBreak()]

    story += section('01 · IHR PROJEKT AUF EINEN BLICK', 'Das haben wir für Sie zusammengestellt.')
    story += [p(o.get('project_summary')), Spacer(1, 10*mm)]
    cards = [box([p('KUNDE / OBJEKT', 'small'), p(cname(customer)), p(address, 'small')], width=82*mm),
             box([p('IHRE SICHERHEITSLÖSUNG', 'small'), p(o.get('offer_type')), p(f'{len(o["items"])} Leistungspositionen', 'small')], width=82*mm)]
    grid = Table([[cards[0], '', cards[1]]], colWidths=[82*mm,6*mm,82*mm])
    grid.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),0)]))
    story += [grid, Spacer(1, 12*mm)]
    if o.get('benefits'):
        story.append(p('IHRE VORTEILE', 'label'))
    for benefit in o.get('benefits', []):
        story += [Paragraph('<font color="#0d7d3b">+</font>  '+escape(benefit), styles['body']), Spacer(1,3*mm)]
    story += [PageBreak()]

    story += section('02 · KALKULATION ZUR PRÜFUNG' if is_draft else '02 · IHRE FESTPREIS-LEISTUNG', 'Ihre Leistung. Klar kalkuliert.')
    story += [Spacer(1,4*mm), box([p('ENTWURFSPREIS · NICHT FREIGEGEBEN' if is_draft else 'IHR GESAMTPREIS', 'white'), p(money(o.get('total_gross')), 'price'),
                       p('Netto '+money(o.get('total_net'))+' · MwSt. '+money(o.get('tax_amount')), 'white')], background=GREEN), Spacer(1,8*mm)]
    for note in offer_notes(o):
        story += [p(note, 'small'), Spacer(1, 2*mm)]
    rows = [[p(t, 'small') for t in ('POS.', 'LEISTUNG / ARTIKEL', 'MENGE', unit_price_heading(o), 'NETTO')]]
    for item in o['items']:
        description = [Paragraph('<b>'+escape(item['title'])+'</b>', styles['small'])]
        for note in item_notes(item, o.get('currency_code') or 'EUR'):
            description.append(p(note, 'small'))
        if item.get('description'):
            description.append(p(item['description'], 'small'))
        rows.append([p(item['position'], 'small'), description,
                     p(f'{item["quantity"]} {item["unit"]}', 'small'), p(money(item['unit_price']), 'small'), p(money(item['total_net']), 'small')])
    table = Table(rows, colWidths=[12*mm,77*mm,21*mm,29*mm,31*mm], repeatRows=1, splitInRow=1)
    table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),PALE),('LINEBELOW',(0,0),(-1,-1),0.4,LINE),
                              ('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),2*mm),
                              ('RIGHTPADDING',(0,0),(-1,-1),2*mm),('TOPPADDING',(0,0),(-1,-1),4*mm),('BOTTOMPADDING',(0,0),(-1,-1),4*mm)]))
    story += [table, Spacer(1,6*mm), p('Interner Kalkulationsentwurf. Keine Angebotsfreigabe, kein Kundenversand.' if is_draft else 'Maßgeblich sind die im Leistungsvorschlag aufgeführten Leistungen und Konditionen.', 'small')]

    # Protect legacy selections as well as current UI/API input at the last mile.
    images = list(o.get('reference_images') or [])[:MAX_REFERENCE_IMAGES]
    section_number = 3
    if images:
        story += [PageBreak()] + section(f'{section_number:02d} · EINBLICKE IN UNSERE ARBEIT', 'Sicherheitstechnik in der Praxis.')
        story += [p('Ausgewählte Bilder zu Ihrer Sicherheitslösung.', 'small'), Spacer(1, 5*mm)]
        cards = []
        for item in images:
            category = str(item.get('category') or 'Projektfoto')
            kind = str(item.get('kind') or '')
            # Keep the provenance visible even when a category name is long.
            label = kind + ' · ' + category if kind and kind != category else category
            details = ' · '.join(str(item[key]) for key in ('place', 'object_type', 'description') if item.get(key))
            captions = [reference_caption(label, styles['reference_label'], escape, 1),
                        reference_caption(item.get('title'), styles['reference_title'], escape, 2),
                        reference_caption(details, styles['reference_detail'], escape, 2)]
            cards.append((Photo(item['path'], 44*mm), captions))
        story += [ReferenceGrid(cards), Spacer(1, 5*mm)]
        services = Table([[p(value, 'service') for value in ('Beratung', 'Planung', 'Montage', 'Einweisung')]],
                         colWidths=[WIDTH/4]*4)
        services.setStyle(TableStyle([('LINEABOVE', (0, 0), (-1, 0), .5, LINE),
                                     ('LINEBELOW', (0, 0), (-1, 0), .5, LINE),
                                     ('TOPPADDING', (0, 0), (-1, -1), 5*mm),
                                     ('BOTTOMPADDING', (0, 0), (-1, -1), 5*mm)]))
        story.append(services)
        section_number += 1

    story += [PageBreak()] + section(f'{section_number:02d} · SO GEHT ES WEITER', 'Von der Planung zur sicheren Übergabe.')
    story += [p('Prüfung und Freigabe stehen noch aus.' if is_draft else 'Wir begleiten Sie von der Abstimmung bis zur Übergabe.'), Spacer(1,8*mm)]
    default_details = {
        'Angebot prüfen und bestätigen': 'Sie prüfen die angebotenen Geräte und Leistungen. Offene Fragen klären wir vor der Beauftragung.',
        'Installationstermin abstimmen': 'Montageorte, Leitungswege und den Termin stimmen wir passend zu Ihrem Objekt ab.',
        'Montage, Konfiguration und Inbetriebnahme': 'Die vereinbarten Komponenten werden installiert, eingerichtet und auf ihre Funktion geprüft.',
        'Übergabe und Einweisung': 'Sie erhalten eine Einweisung in die Bedienung und die für Ihr System vereinbarten Funktionen.',
    }
    steps = list(o.get('next_steps', []))
    if not is_draft and steps == list(default_details):
        steps.append('Abrechnung nach Vereinbarung')
        default_details[steps[-1]] = 'Für Abrechnung und Zahlung gelten die im Leistungsvorschlag oder in der Auftragsbestätigung vereinbarten Konditionen.'
    for n, step in enumerate(steps, 1):
        contents = [p('Leistungsvorschlag prüfen und bestätigen' if not is_draft and step == 'Angebot prüfen und bestätigen' else step, 'question')]
        if step in default_details:
            contents.append(p(default_details[step], 'answer'))
        row = Table([[p(f'{n:02d}', 'step'), contents]], colWidths=[16*mm,154*mm], splitInRow=1)
        row.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LINEBELOW',(0,0),(-1,-1),0.4,LINE),
                                ('LEFTPADDING',(0,0),(-1,-1),0), ('RIGHTPADDING',(0,0),(-1,-1),2*mm),
                                ('TOPPADDING',(0,0),(-1,-1),5*mm),('BOTTOMPADDING',(0,0),(-1,-1),5*mm)]))
        story.append(row)
    story += [Spacer(1, 8*mm), box([
        Paragraph('<b>Auf Ihr Objekt abgestimmt.</b>', styles['white']),
        p('Der konkrete Leistungsumfang, die Geräteauswahl und die Konditionen ergeben sich aus diesem Leistungsvorschlag. Änderungen stimmen wir gemeinsam ab.', 'white')], background=INK, accent=True)]

    section_number += 1
    story += [PageBreak()] + section(f'{section_number:02d} · HÄUFIGE FRAGEN', 'Was Sie noch wissen möchten.')
    questions = [
        ('Wie bediene ich meine Sicherheitstechnik?',
         'Bei der Übergabe erklären wir die vereinbarte Bedienung. App, Bedienteil und Zugriffsrechte richten sich nach den ausgewählten Geräten.'),
        ('Kann ich mein System später erweitern?',
         'Wir prüfen passende Ergänzungen anhand der vorhandenen Zentrale, Geräte und Systemgrenzen. Die Kompatibilität wird vor einer Erweiterung geklärt.'),
        ('Was passiert bei Strom- oder Internetausfall?',
         'Das hängt von den Geräten, ihrer Stromversorgung und den gewählten Übertragungswegen ab. Wir stimmen die benötigte Absicherung mit Ihnen ab.'),
        ('Wie wird die Montage vorbereitet?',
         'Montageorte, Leitungswege und den Zugang zum Objekt stimmen wir vorab mit Ihnen ab. Besondere Anforderungen werden in der Planung berücksichtigt.'),
        ('Wie läuft die Bezahlung ab?',
         'Es gelten die Zahlungsbedingungen im Leistungsvorschlag oder in der Auftragsbestätigung. Die Bankverbindung finden Sie in der Fußzeile, sofern sie hinterlegt ist.'),
    ]
    for question, answer in questions:
        row = Table([[p('?', 'label'), [p(question, 'question'), p(answer, 'answer')]]],
                    colWidths=[6*mm, 164*mm], splitInRow=1)
        row.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'),
                                ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                                ('TOPPADDING', (0, 0), (-1, -1), 3*mm), ('BOTTOMPADDING', (0, 0), (-1, -1), 3*mm),
                                ('LINEBELOW', (0, 0), (-1, -1), .4, LINE)]))
        story.append(row)
    story += [Spacer(1, 6*mm)]
    contact = [p('IHR PERSÖNLICHER KONTAKT', 'label')]
    for key in ('company', 'contact', 'phone', 'email', 'website'):
        if profile.get(key):
            contact.append(p(profile[key], 'caption'))
    if len(contact)==1:
        contact.append(p('FT Sicherheitstechnik'))
    story += [box(contact, accent=True), Spacer(1, 5*mm)]
    closing_title = ('Gemeinsam prüfen. Danach freigeben.' if is_draft else
                     'Ihr nächster Schritt: Leistungsvorschlag gemeinsam abstimmen.')
    closing_text = ('Dieser Entwurf ist noch nicht freigegeben. Bitte prüfen Sie die Angaben und den Leistungsumfang.' if is_draft else
                    ('Ihr Leistungsvorschlag ist bis '+date_de(o['validity_date'])+' gültig.' if o.get('validity_date') else
                     'Gültigkeit und Konditionen entnehmen Sie diesem Leistungsvorschlag.'))
    story += [box([Paragraph('<b>'+escape(closing_title)+'</b>', styles['white']), p(closing_text, 'white')], background=INK)]
    doc.build(story, canvasmaker=NumberedCanvas)
    buffer.seek(0)
    return buffer
