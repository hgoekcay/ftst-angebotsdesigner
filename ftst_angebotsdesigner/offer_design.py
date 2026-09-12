"""A4 offer presentation based on the supplied FT offer reference."""
import io
from collections import OrderedDict
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
            self.drawRightString(190*mm, 14*mm, f'{self._pageNumber:02d} / {total:02d}')
            super().showPage()
        super().save()


def build(offer, escape, money, date_de, cname):
    o = offer
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

    def heading(canvas, doc):
        canvas.saveState()
        logo = o.get('logo_path')
        if logo:
            reader = ImageReader(logo)
            iw, ih = reader.getSize()
            scale = min((52 if doc.page == 1 else 38)*mm/iw, 13*mm/ih)
            canvas.drawImage(reader, 20*mm, 270*mm, iw*scale, ih*scale, mask='auto')
        else:
            canvas.setFont('Helvetica-Bold', 10)
            canvas.setFillColor(INK)
            canvas.drawString(20*mm, 275*mm, 'FT SICHERHEITSTECHNIK')
        if doc.page == 1:
            canvas.setStrokeColor(RED)
            canvas.roundRect(128*mm, 271*mm, 62*mm, 9*mm, 4.5*mm, fill=0)
            canvas.setFillColor(RED)
            canvas.setFont(font, 8)
            canvas.drawCentredString(159*mm, 274.3*mm, 'IHR PERSÖNLICHES ANGEBOT')
            labels = [('AUSGESTELLT AM', date_de(o.get('date'))),
                      ('GÜLTIGKEIT', date_de(o.get('validity_date')) if o.get('validity_date') else (str(o['validity_days'])+' Tage' if o.get('validity_days') else 'Gemäß Angebot')),
                      ('IHR FESTPREIS', money(o.get('total_gross')))]
            for x, (label, value) in zip((20, 78, 136), labels):
                p(label, 'small').wrapOn(canvas, 53*mm, 12*mm)
                label_p = p(label, 'small')
                label_p.wrapOn(canvas, 53*mm, 12*mm)
                label_p.drawOn(canvas, x*mm, 40*mm)
                value_p = Paragraph(escape(value), ParagraphStyle('meta', parent=styles['body'], fontName='Helvetica-Bold', textColor=GREEN if x==136 else INK))
                _, height = value_p.wrapOn(canvas, 53*mm, 20*mm)
                value_p.drawOn(canvas, x*mm, 37*mm-height)
        else:
            info = p(f'Angebot {number[:35]} · {cname(customer)[:75]}', 'small')
            info.wrapOn(canvas, 92*mm, 20*mm)
            info.drawOn(canvas, 98*mm, 274*mm)
            canvas.setStrokeColor(LINE)
            canvas.line(20*mm, 265*mm, 190*mm, 265*mm)
        canvas.setStrokeColor(LINE)
        canvas.line(20*mm, 20*mm, 190*mm, 20*mm)
        foot = profile.get('company') or 'FT Sicherheitstechnik'
        if profile.get('email'):
            foot += ' · ' + profile['email']
        # Keep even unusually long company/contact names inside the footer band.
        footer = KeepInFrame(145*mm, 12*mm, [p(foot, 'small')], mode='shrink')
        _, footer_height = footer.wrapOn(canvas, 145*mm, 12*mm)
        footer.drawOn(canvas, 20*mm, 18*mm-footer_height)
        canvas.restoreState()

    buffer = io.BytesIO()
    doc = BaseDocTemplate(buffer, pagesize=(210*mm, 297*mm), title=f'FTST Angebot {number}', author=profile.get('company') or 'FT Sicherheitstechnik')
    doc.addPageTemplates([
        PageTemplate('cover', [Frame(20*mm, 58*mm, WIDTH, 144*mm, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)], onPage=heading),
        PageTemplate('content', [Frame(20*mm, 26*mm, WIDTH, 232*mm, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)], onPage=heading),
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
    story = [NextPageTemplate('content'), p('ANGEBOT · '+number, 'label'), Paragraph(title_html, styles['cover']),
             p(o.get('customer_intro')), Spacer(1, 12*mm), box(details, width=128*mm, accent=True),
             NextPageTemplate('content'), PageBreak()]

    story += section('01 · IHR PROJEKT AUF EINEN BLICK', 'Das haben wir für Sie zusammengestellt.')
    story += [p(o.get('project_summary')), Spacer(1, 10*mm)]
    cards = [box([p('KUNDE / OBJEKT', 'small'), p(cname(customer)), p(address, 'small')], width=82*mm),
             box([p('IHRE SICHERHEITSLÖSUNG', 'small'), p(o.get('offer_type')), p(f'{len(o["items"])} Angebotspositionen', 'small')], width=82*mm)]
    grid = Table([[cards[0], '', cards[1]]], colWidths=[82*mm,6*mm,82*mm])
    grid.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),0)]))
    story += [grid, Spacer(1, 12*mm), p('IHRE VORTEILE', 'label')]
    for benefit in o.get('benefits', []):
        story += [Paragraph('<font color="#0d7d3b">+</font>  '+escape(benefit), styles['body']), Spacer(1,3*mm)]
    story += [PageBreak()]

    story += section('02 · IHRE FESTPREIS-LEISTUNG', 'Ihre Leistung. Klar kalkuliert.')
    story += [Spacer(1,4*mm), box([p('IHR ANGEBOTSPREIS', 'white'), p(money(o.get('total_gross')), 'price'),
                       p('Netto '+money(o.get('total_net'))+' · MwSt. '+money(o.get('tax_amount')), 'white')], background=GREEN), Spacer(1,8*mm)]
    rows = [[p(t, 'small') for t in ('POS.', 'LEISTUNG / ARTIKEL', 'MENGE', 'PREIS', 'NETTO')]]
    for item in o['items']:
        description = [Paragraph('<b>'+escape(item['title'])+'</b>', styles['small'])]
        if item.get('description'):
            description.append(p(item['description'], 'small'))
        rows.append([p(item['position'], 'small'), description,
                     p(f'{item["quantity"]} {item["unit"]}', 'small'), p(money(item['unit_price']), 'small'), p(money(item['total_net']), 'small')])
    table = Table(rows, colWidths=[12*mm,77*mm,21*mm,29*mm,31*mm], repeatRows=1, splitInRow=1)
    table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),PALE),('LINEBELOW',(0,0),(-1,-1),0.4,LINE),
                              ('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),2*mm),
                              ('RIGHTPADDING',(0,0),(-1,-1),2*mm),('TOPPADDING',(0,0),(-1,-1),4*mm),('BOTTOMPADDING',(0,0),(-1,-1),4*mm)]))
    story += [table, Spacer(1,6*mm), p('Maßgeblich sind die im Angebot aufgeführten Leistungen und Konditionen.', 'small')]

    groups = OrderedDict()
    for item in o.get('reference_images', []):
        groups.setdefault(item.get('category') or 'Projektbilder', []).append(item)
    section_number = 3
    for category, images in groups.items():
        for start in range(0, len(images), 4):
            story += [PageBreak()] + section(f'{section_number:02d} · EINBLICKE', category + ' in der Praxis.')
            story += [p('Ausgewählte Bilder zu Ihrer Sicherheitslösung.'), Spacer(1,7*mm)]
            batch = images[start:start+4]
            for offset in range(0, len(batch), 2):
                cells = []
                for item in batch[offset:offset+2]:
                    image = Photo(item['path'], (100 if len(batch)<=2 else 58)*mm)
                    kind = item.get('kind') or 'Projektfoto'
                    cells.append([image, Spacer(1,3*mm), p(kind, 'label'),
                                  Paragraph('<b>'+escape(item.get('title') or '')+'</b>', styles['body']),
                                  p(' · '.join(item[k] for k in ('place','object_type') if item.get(k)), 'small'),
                                  p(item.get('description'), 'small')])
                if len(cells)==1:
                    cells.append('')
                row = Table([[cells[0], '', cells[1]]], colWidths=[82*mm,6*mm,82*mm], splitInRow=1)
                row.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),0)]))
                story += [row, Spacer(1,10*mm)]
            section_number += 1

    story += [PageBreak()] + section(f'{section_number:02d} · NÄCHSTE SCHRITTE', 'So geht es weiter.')
    story += [p('Wir begleiten Sie von der Abstimmung bis zur Übergabe.'), Spacer(1,8*mm)]
    for n, step in enumerate(o.get('next_steps', []),1):
        row = Table([[p(n,'step'), p(step)]], colWidths=[16*mm,154*mm], splitInRow=1)
        row.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LINEBELOW',(0,0),(-1,-1),0.4,LINE),('TOPPADDING',(0,0),(-1,-1),5*mm),('BOTTOMPADDING',(0,0),(-1,-1),5*mm)]))
        story.append(row)
    story += [Spacer(1,10*mm)]
    contact = [p('IHR KONTAKT', 'label')]
    for key in ('company','contact','street','city','phone','email','website'):
        if profile.get(key):
            contact.append(p(profile[key]))
    if len(contact)==1:
        contact.append(p('FT Sicherheitstechnik'))
    story += [box(contact, accent=True), Spacer(1,8*mm), p('Vielen Dank für Ihr Vertrauen.')]
    doc.build(story, canvasmaker=NumberedCanvas)
    buffer.seek(0)
    return buffer
