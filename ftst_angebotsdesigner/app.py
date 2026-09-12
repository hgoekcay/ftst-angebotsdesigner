import io
import os
import html
import logging
from flask import Flask, request, send_file, abort
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from billomat_client import BillomatClient

APP_VERSION = "0.1.12"
log = logging.getLogger("ftst.app")
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "ftst-dev")

RED = colors.HexColor("#D71920")
DARK = colors.HexColor("#111111")
TEXT = colors.HexColor("#202020")
MUTED = colors.HexColor("#6F6F6F")
LIGHT = colors.HexColor("#F4F4F4")
BORDER = colors.HexColor("#DDDDDD")
GREEN = colors.HexColor("#218838")
GREEN_LIGHT = colors.HexColor("#EAF6EE")
WHITE = colors.white

CSS = """
:root{--red:#d71920;--dark:#111;--text:#222;--muted:#707070;--light:#f4f4f4;--green:#218838;--greenlight:#eaf6ee;}
*{box-sizing:border-box}body{margin:0;font-family:Arial,Helvetica,sans-serif;background:#ececec;color:var(--text)}
.top{background:var(--dark);color:#fff;border-bottom:5px solid var(--red)}
.topin{max-width:1180px;margin:auto;padding:22px 26px;display:flex;justify-content:space-between;align-items:center}
.brand{font-size:22px;font-weight:800;letter-spacing:.5px}.sub{font-size:12px;opacity:.72;margin-top:3px}
.wrap{max-width:1180px;margin:28px auto;padding:0 18px}.card{background:#fff;border-radius:16px;padding:28px;margin-bottom:18px;box-shadow:0 6px 24px rgba(0,0,0,.07)}
.hero{padding:36px}.eyebrow{color:var(--red);font-size:12px;font-weight:800;text-transform:uppercase;letter-spacing:1.2px}.hero h1{font-size:34px;line-height:1.05;margin:10px 0}.hero p{font-size:16px;color:var(--muted);max-width:800px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px}.metric{background:var(--light);padding:18px;border-radius:12px}.metric.green{background:var(--greenlight)}.metric .label{font-size:11px;text-transform:uppercase;letter-spacing:.8px;color:var(--muted)}.metric .value{font-size:22px;font-weight:800;margin-top:5px}.metric.green .value{color:var(--green)}
.btn{display:inline-block;background:var(--red);color:#fff;text-decoration:none;padding:12px 18px;border-radius:8px;font-weight:700;border:0;cursor:pointer}.btn.dark{background:var(--dark)}.btn.light{background:#efefef;color:#111}
label{display:block;font-size:12px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.7px;margin-bottom:6px}input,select,textarea{width:100%;padding:12px;border:1px solid #d8d8d8;border-radius:8px;font:inherit;background:#fff}textarea{min-height:115px;resize:vertical}.field{margin-bottom:18px}.hint{font-size:12px;color:var(--muted);margin-top:5px}
table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:13px 10px;border-bottom:1px solid #e8e8e8;vertical-align:top}th{font-size:11px;text-transform:uppercase;color:var(--muted);letter-spacing:.7px}.money{text-align:right;font-weight:800}.muted{color:var(--muted)}.tag{display:inline-block;border-radius:99px;background:var(--greenlight);color:var(--green);padding:6px 10px;font-size:11px;font-weight:700}
.section-title{font-size:22px;margin:0 0 14px}.small{font-size:12px}.footer-note{font-size:12px;color:var(--muted);text-align:center;margin:26px 0 10px}
.checks{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}.check{background:var(--greenlight);color:var(--green);padding:10px;border-radius:8px;font-size:12px;font-weight:700}
"""

OFFER_TYPES = {
    "Videoüberwachung": {
        "headline": "Professionelle Videoüberwachung für Ihr Objekt",
        "intro": "Moderne IP-Videoüberwachung mit professioneller Aufzeichnung und zuverlässiger Fernzugriffsmöglichkeit.",
        "summary": "Wir planen und realisieren eine auf Ihr Objekt abgestimmte Videoüberwachung – inklusive Montage, Konfiguration, Funktionsprüfung und Einweisung.",
        "benefits": ["Hochauflösende Kameras", "Intelligente Erkennung", "Professionelle Aufzeichnung", "Fernzugriff per App"],
    },
    "Alarmanlage": {
        "headline": "Professionelle Alarmtechnik für Ihr Objekt",
        "intro": "Zuverlässige Gefahrenmeldung mit moderner Alarmtechnik und klaren Alarmierungswegen.",
        "summary": "Die Anlage wird objektbezogen geplant, fachgerecht montiert, eingerichtet und vollständig getestet übergeben.",
        "benefits": ["Schnelle Alarmierung", "App-Steuerung", "Sabotageschutz", "Erweiterbar"],
    },
    "Zutrittskontrolle": {
        "headline": "Sichere Zutrittskontrolle für Ihr Objekt",
        "intro": "Kontrollieren Sie zuverlässig, wer Ihr Gebäude oder einzelne Bereiche betreten darf.",
        "summary": "Von der Türkomponente bis zur Administration wird die Lösung vollständig eingerichtet und betriebsbereit übergeben.",
        "benefits": ["RFID / Code / App", "Zutrittsrechte", "Protokollierung", "Flexible Erweiterung"],
    },
    "Türsprechanlage": {
        "headline": "Moderne Video-Türsprechanlage",
        "intro": "Sehen und sprechen Sie mit Besuchern – vor Ort oder komfortabel über Ihr Smartphone.",
        "summary": "Wir liefern, montieren, konfigurieren und übergeben die Türkommunikation vollständig betriebsbereit.",
        "benefits": ["Video & Audio", "Smartphone-Anbindung", "Außentaugliche Komponenten", "Einfache Bedienung"],
    },
    "Brandmeldeanlage": {
        "headline": "Professionelle Brandmeldetechnik",
        "intro": "Frühzeitige Detektion und strukturierte Alarmierung mit professioneller Brandmeldetechnik.",
        "summary": "Planung, Installation, Konfiguration und Dokumentation werden auf die Anforderungen des Objekts abgestimmt.",
        "benefits": ["Frühe Detektion", "Klare Alarmierung", "Dokumentierte Prüfung", "Normgerechte Umsetzung"],
    },
    "Smart Home": {
        "headline": "Smarte Sicherheit und Gebäudeautomation",
        "intro": "Sicherheit, Komfort und intelligente Steuerung in einer abgestimmten Lösung.",
        "summary": "Wir verbinden die gewünschten Funktionen zu einer einfach bedienbaren und erweiterbaren Gesamtlösung.",
        "benefits": ["Zentrale Steuerung", "App-Anbindung", "Automationen", "Erweiterbar"],
    },
    "Kombination": {
        "headline": "Ihre individuelle Sicherheitslösung",
        "intro": "Mehrere Sicherheitssysteme werden zu einer abgestimmten Gesamtlösung kombiniert.",
        "summary": "Wir koordinieren die verschiedenen Gewerke und übergeben eine vollständig konfigurierte Gesamtlösung.",
        "benefits": ["Ganzheitliche Planung", "Ein Ansprechpartner", "Abgestimmte Systeme", "Erweiterbar"],
    },
}


def ingress(path="/"):
    base = request.headers.get("X-Ingress-Path", "").strip().rstrip("/")
    return base + "/" + path.lstrip("/")


def money(v):
    try:
        return f"{float(v):,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "-"


def one_or_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in ("tax", "item", "offer-item", "value"):
            if key in value:
                inner = value[key]
                return inner if isinstance(inner, list) else [inner]
        return [value]
    return []


def client_name(c):
    c = c if isinstance(c, dict) else {}
    return c.get("name") or c.get("company") or "Kunde"


def safe_text(value):
    if value is None or isinstance(value, (dict, list)):
        return ""
    return html.escape(str(value))


def normalize_item(item, pos):
    if not isinstance(item, dict):
        return {"position": pos, "title": str(item), "description": "", "quantity": 1, "unit": "", "unit_price": 0, "total_net": 0}
    return {
        "position": item.get("position") or pos,
        "title": item.get("title") or "Leistung",
        "description": item.get("description") or "",
        "quantity": item.get("quantity") or 0,
        "unit": item.get("unit") or "",
        "unit_price": item.get("unit_price") or 0,
        "total_net": item.get("total_net") or 0,
    }


def normalize_offer(o):
    o = dict(o or {})
    o["client"] = o.get("client") if isinstance(o.get("client"), dict) else {}
    o["items"] = [normalize_item(x, i + 1) for i, x in enumerate(one_or_list(o.get("items")))]
    total_tax = 0.0
    for tax in one_or_list(o.get("taxes")):
        if isinstance(tax, dict):
            try:
                total_tax += float(tax.get("amount") or tax.get("tax_amount") or 0)
            except Exception:
                pass
    o["tax_amount"] = total_tax
    return o


def offer_data_from_form(raw, form):
    o = normalize_offer(raw)
    kind = form.get("offer_type") or "Kombination"
    preset = OFFER_TYPES.get(kind, OFFER_TYPES["Kombination"])
    o["offer_type"] = kind
    o["customer_title"] = form.get("customer_title") or preset["headline"]
    o["customer_intro"] = form.get("customer_intro") or preset["intro"]
    o["project_summary"] = form.get("project_summary") or preset["summary"]
    benefits = form.get("benefits", "").strip()
    o["benefits"] = [x.strip() for x in benefits.split("\n") if x.strip()] or preset["benefits"]
    steps = form.get("next_steps", "").strip()
    o["next_steps"] = [x.strip() for x in steps.split("\n") if x.strip()] or ["Angebot prüfen und bestätigen", "Installationstermin abstimmen", "Montage, Konfiguration und Inbetriebnahme", "Übergabe und Einweisung"]
    return o


def base(title, body):
    return f'''<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title><style>{CSS}</style></head><body><div class="top"><div class="topin"><div><div class="brand">FT SICHERHEITSTECHNIK</div><div class="sub">FTST AngebotsDesigner</div></div><div class="small">Version {APP_VERSION}</div></div></div><main class="wrap">{body}</main></body></html>'''


def load_offer(offer_id):
    bid = os.getenv("BILLOMAT_ID")
    key = os.getenv("BILLOMAT_API_KEY")
    if not bid or not key:
        abort(503)
    return normalize_offer(BillomatClient(bid, key).get_full_offer(offer_id))


def detail(o):
    o = normalize_offer(o)
    c = o["client"]
    rows = "".join(
        f'''<tr><td>{safe_text(i['position'])}</td><td><b>{safe_text(i['title'])}</b><br><span class="muted small">{safe_text(i['description'])}</span></td><td>{safe_text(i['quantity'])} {safe_text(i['unit'])}</td><td class="money">{money(i['unit_price'])}</td><td class="money">{money(i['total_net'])}</td></tr>'''
        for i in o["items"]
    )
    benefits = "".join(f'<span class="check">✓ {safe_text(x)}</span>' for x in o.get("benefits", []))
    body = f'''<div class="card hero"><div class="eyebrow">Ihr persönliches Angebot</div><h1>{safe_text(o.get('customer_title') or o.get('title') or 'Individuelle Sicherheitslösung')}</h1><p>{safe_text(o.get('customer_intro') or o.get('intro') or '')}</p><div style="margin-top:22px"><a class="btn" href="{ingress('offer/'+str(o.get('id'))+'/edit')}">Angebot bearbeiten</a> <a class="btn dark" href="{ingress('offer/'+str(o.get('id'))+'/pdf')}">A4-PDF erzeugen</a> <a class="btn light" href="{ingress('offers')}">← Übersicht</a></div></div><div class="grid"><div class="metric"><div class="label">Kunde</div><div class="value" style="font-size:18px">{safe_text(client_name(c))}</div><div class="muted small">{safe_text(c.get('street',''))}<br>{safe_text(c.get('zip',''))} {safe_text(c.get('city',''))}</div></div><div class="metric"><div class="label">Angebot</div><div class="value" style="font-size:18px">Nr. {safe_text(o.get('offer_number') or o.get('number') or '-')}</div><div class="muted small">Datum: {safe_text(o.get('date','-'))}<br>Gültig: {safe_text(o.get('validity_date') or o.get('validity_days') or '-')}</div></div><div class="metric green"><div class="label">Ihr Festpreis</div><div class="value">{money(o.get('total_gross'))}</div><div class="muted small">Netto {money(o.get('total_net'))}</div></div></div><div class="card"><h2 class="section-title">Projekt auf einen Blick</h2><p>{safe_text(o.get('project_summary') or 'Die nachfolgende Übersicht beschreibt die geplante Lösung auf Basis Ihres Angebots.')}</p></div><div class="card"><h2 class="section-title">Leistungsumfang</h2><table><thead><tr><th>Pos.</th><th>Leistung / Artikel</th><th>Menge</th><th>Einzelpreis</th><th>Netto</th></tr></thead><tbody>{rows}</tbody></table></div><div class="card"><h2 class="section-title">Ihre Vorteile</h2><div class="checks">{benefits}</div></div><div class="card"><h2 class="section-title">Kostenübersicht</h2><div class="grid"><div class="metric"><div class="label">Netto</div><div class="value">{money(o.get('total_net'))}</div></div><div class="metric"><div class="label">MwSt.</div><div class="value">{money(o.get('tax_amount'))}</div></div><div class="metric green"><div class="label">Gesamt</div><div class="value">{money(o.get('total_gross'))}</div></div></div></div><div class="footer-note">FT Sicherheitstechnik · Professionelle Sicherheitstechnik</div>'''
    return base("FTST Angebot", body)


@app.get("/health")
def health():
    return {"ok": True, "version": APP_VERSION}


@app.get("/")
def index():
    body = f'''<div class="card hero"><div class="eyebrow">FTST AngebotsDesigner</div><h1>Professionelle Angebote aus Billomat</h1><p>Billomat-Daten importieren, prüfen und als hochwertiges FTST-A4-Angebot ausgeben.</p><a class="btn" href="{ingress('offers')}">Angebote öffnen</a> <a class="btn dark" href="{ingress('demo')}">Design-Demo</a></div>'''
    return base("FTST AngebotsDesigner", body)


@app.get("/offers")
def offers():
    bid = os.getenv("BILLOMAT_ID")
    key = os.getenv("BILLOMAT_API_KEY")
    if not bid or not key:
        return base("Billomat", '<div class="card"><h1>Billomat nicht konfiguriert</h1><p>Bitte Billomat-ID und API-Key in der Home-Assistant-App konfigurieren.</p></div>')
    try:
        data = BillomatClient(bid, key).list_offers(request.args.get("search", ""))
        data = sorted(data, key=lambda x: str(x.get("date", "") if isinstance(x, dict) else ""), reverse=True)
    except Exception as e:
        log.exception("Offer list failed")
        return base("Billomat Fehler", f'<div class="card"><h1>Billomat-Fehler</h1><p>{safe_text(e)}</p></div>'), 502
    rows = "".join(f'''<tr><td><b>{safe_text(o.get("offer_number") or o.get("number") or "-")}</b></td><td>{safe_text(o.get("date"))}</td><td>{safe_text(o.get("title") or "-")}</td><td class="money">{money(o.get("total_gross"))}</td><td><a class="btn" href="{ingress('offer/'+str(o.get('id')))}">Öffnen</a></td></tr>''' for o in data if isinstance(o, dict))
    return base("Angebote", f'''<div class="card"><div class="eyebrow">Billomat</div><h1>Ihre Angebote</h1><p class="muted">{len(data)} Angebote · neueste zuerst</p><table><thead><tr><th>Nr.</th><th>Datum</th><th>Titel</th><th>Brutto</th><th></th></tr></thead><tbody>{rows}</tbody></table></div>''')


@app.get("/offer/<offer_id>")
def offer(offer_id):
    try:
        return detail(load_offer(offer_id))
    except Exception as e:
        log.exception("Offer detail failed")
        return base("Fehler", f'<div class="card"><h1>Angebot konnte nicht geladen werden</h1><p>{safe_text(e)}</p></div>'), 502


@app.route("/offer/<offer_id>/edit", methods=["GET", "POST"])
def edit_offer(offer_id):
    raw = load_offer(offer_id)
    if request.method == "POST":
        o = offer_data_from_form(raw, request.form)
        return detail(o)
    kind = "Kombination"
    title = raw.get("title") or OFFER_TYPES[kind]["headline"]
    body = f'''<div class="card"><div class="eyebrow">FTST Angebotseditor</div><h1>{safe_text(title)}</h1><p class="muted">Hier passt du die kundenseitige Darstellung an. Preise und Billomat-Positionen bleiben unverändert.</p></div><form method="post" action="{ingress('offer/'+str(offer_id)+'/edit')}"><div class="card"><h2 class="section-title">1. Angebotsart</h2><div class="field"><label>Angebotstyp</label><select name="offer_type" id="offer_type">{''.join(f'<option>{safe_text(x)}</option>' for x in OFFER_TYPES)}</select><div class="hint">Die Auswahl stellt passende Textbausteine bereit, die du anschließend ändern kannst.</div></div><div class="field"><label>Kundentitel</label><input name="customer_title" value="{safe_text(title)}"></div><div class="field"><label>Einleitung</label><textarea name="customer_intro">{safe_text(raw.get('intro') or OFFER_TYPES[kind]['intro'])}</textarea></div></div><div class="card"><h2 class="section-title">2. Projekt auf einen Blick</h2><div class="field"><label>Projektbeschreibung</label><textarea name="project_summary">{safe_text(OFFER_TYPES[kind]['summary'])}</textarea></div></div><div class="card"><h2 class="section-title">3. Ihre Vorteile</h2><div class="field"><label>Vorteile – ein Punkt pro Zeile</label><textarea name="benefits">{safe_text(chr(10).join(OFFER_TYPES[kind]['benefits']))}</textarea></div></div><div class="card"><h2 class="section-title">4. Nächste Schritte</h2><div class="field"><label>Schritte – ein Punkt pro Zeile</label><textarea name="next_steps">Angebot prüfen und bestätigen\nInstallationstermin abstimmen\nMontage, Konfiguration und Inbetriebnahme\nÜbergabe und Einweisung</textarea></div></div><div class="card"><button class="btn" type="submit">Vorschau erstellen</button> <a class="btn light" href="{ingress('offer/'+str(offer_id))}">Abbrechen</a></div></form>'''
    return base("Angebot bearbeiten", body)


@app.get("/demo")
def demo():
    o = {"id":"demo","offer_number":"26-79","date":"12.06.2026","validity_date":"26.06.2026","status":"draft","title":"Videoüberwachung – Pasa Firin","intro":"Professionelle IP-Videoüberwachung mit KI-Personen-/Fahrzeugerkennung.","total_net":6452.40,"total_gross":7678.36,"taxes":[{"amount":1225.96}],"client":{"name":"Pasa Firin","street":"G2 9","zip":"68159","city":"Mannheim"},"items":[{"position":1,"title":"8MP Domekamera","description":"2.8mm · Tag/Nacht · KI Person/Fahrzeug","quantity":16,"unit":"Stk.","unit_price":298,"total_net":4768},{"position":2,"title":"16-Kanal NVR","description":"AI-Aufzeichnung","quantity":1,"unit":"Stk.","unit_price":900,"total_net":900},{"position":3,"title":"24-Port PoE Switch","description":"Managed PoE","quantity":1,"unit":"Stk.","unit_price":222,"total_net":222},{"position":4,"title":"Techniker","description":"Montage und Inbetriebnahme","quantity":4,"unit":"Std.","unit_price":85,"total_net":340},{"position":5,"title":"Helfer","description":"Unterstützende Montagearbeiten","quantity":4,"unit":"Std.","unit_price":35,"total_net":140}]}
    o = offer_data_from_form(o, {"offer_type":"Videoüberwachung"})
    return detail(o)


def footer(canvas, doc):
    canvas.saveState()
    width, _ = A4
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(18*mm, 9*mm, "FT Sicherheitstechnik · Professionelle Sicherheitstechnik")
    canvas.drawRightString(width-18*mm, 9*mm, f"Seite {doc.page}")
    canvas.setStrokeColor(BORDER)
    canvas.line(18*mm, 13*mm, width-18*mm, 13*mm)
    canvas.restoreState()


def make_pdf(o):
    o = normalize_offer(o)
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=18*mm, rightMargin=18*mm, topMargin=18*mm, bottomMargin=19*mm)
    styles = getSampleStyleSheet()
    title = ParagraphStyle("FTTitle", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=25, leading=29, textColor=DARK, spaceAfter=8)
    h2 = ParagraphStyle("FTH2", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=16, leading=19, textColor=DARK, spaceBefore=8, spaceAfter=8)
    body = ParagraphStyle("FTBody", parent=styles["BodyText"], fontName="Helvetica", fontSize=9.4, leading=13.5, textColor=TEXT)
    small = ParagraphStyle("FTSmall", parent=body, fontSize=7.8, leading=10, textColor=MUTED)
    redsmall = ParagraphStyle("FTRedSmall", parent=small, textColor=RED, fontName="Helvetica-Bold")
    greensmall = ParagraphStyle("FTGreenSmall", parent=small, textColor=GREEN, fontName="Helvetica-Bold")
    right = ParagraphStyle("FTRight", parent=body, alignment=TA_RIGHT)
    story = []

    header = Table([[Paragraph("FT SICHERHEITSTECHNIK", ParagraphStyle("brand", parent=body, fontName="Helvetica-Bold", fontSize=15, textColor=WHITE)), ""]], colWidths=[120*mm, 50*mm])
    header.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,-1), DARK), ("TEXTCOLOR", (0,0), (-1,-1), WHITE), ("VALIGN", (0,0), (-1,-1), "MIDDLE"), ("BOTTOMPADDING", (0,0), (-1,-1), 7*mm), ("TOPPADDING", (0,0), (-1,-1), 7*mm), ("LINEBELOW", (0,0), (-1,0), 2*mm, RED)]))
    story += [header, Spacer(1, 11*mm), Paragraph("IHR PERSÖNLICHES ANGEBOT", redsmall), Paragraph(str(o.get("customer_title") or o.get("title") or "Individuelle Sicherheitslösung"), title), Paragraph(str(o.get("customer_intro") or o.get("intro") or "Professionelle Sicherheitstechnik – geplant und umgesetzt von FT Sicherheitstechnik."), body), Spacer(1, 7*mm)]

    customer = Table([[Paragraph("KUNDE", redsmall), Paragraph("ANGEBOT", redsmall)], [Paragraph(f"<b>{safe_text(client_name(o['client']))}</b><br/>{safe_text(o['client'].get('street',''))}<br/>{safe_text(o['client'].get('zip',''))} {safe_text(o['client'].get('city',''))}", body), Paragraph(f"<b>Nr. {safe_text(o.get('offer_number') or o.get('number') or '-')}</b><br/>Datum: {safe_text(o.get('date','-'))}<br/>Gültig: {safe_text(o.get('validity_date') or o.get('validity_days') or '-')}", body)]], colWidths=[82*mm, 88*mm])
    customer.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),LIGHT),("BOX",(0,0),(-1,-1),0.5,BORDER),("INNERGRID",(0,0),(-1,-1),0.5,colors.HexColor('#E5E5E5')),("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),5*mm),("RIGHTPADDING",(0,0),(-1,-1),5*mm),("TOPPADDING",(0,0),(-1,-1),4*mm),("BOTTOMPADDING",(0,0),(-1,-1),4*mm)]))
    story += [customer, Spacer(1, 8*mm)]

    stat1 = Paragraph(money(o.get("total_net")), ParagraphStyle("st1", parent=body, fontSize=15, fontName="Helvetica-Bold"))
    stat2 = Paragraph(money(o.get("tax_amount")), ParagraphStyle("st2", parent=body, fontSize=15, fontName="Helvetica-Bold"))
    stat3 = Paragraph(money(o.get("total_gross")), ParagraphStyle("st3", parent=body, fontSize=16, fontName="Helvetica-Bold", textColor=GREEN))
    stats = Table([[Paragraph("GESAMT NETTO", redsmall), Paragraph("MWST.", redsmall), Paragraph("IHR FESTPREIS", greensmall)], [stat1, stat2, stat3]], colWidths=[56*mm,56*mm,58*mm])
    stats.setStyle(TableStyle([("BACKGROUND",(0,0),(1,-1),LIGHT),("BACKGROUND",(2,0),(2,-1),GREEN_LIGHT),("BOX",(0,0),(-1,-1),0.5,BORDER),("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),4*mm),("TOPPADDING",(0,0),(-1,-1),4*mm),("BOTTOMPADDING",(0,0),(-1,-1),5*mm)]))
    story += [stats, Spacer(1, 10*mm), Paragraph("01 · IHR PROJEKT AUF EINEN BLICK", redsmall), Paragraph("Das haben wir für Sie zusammengestellt.", title), Paragraph(str(o.get("project_summary") or "Ihr Projekt wurde anhand der aufgeführten Leistungen und Artikel vorbereitet."), body), Spacer(1, 7*mm)]

    benefits = o.get("benefits") or []
    benefit_cells = [Paragraph(f"✓ {safe_text(x)}", ParagraphStyle(f"benefit{i}", parent=body, textColor=GREEN, fontName="Helvetica-Bold")) for i, x in enumerate(benefits)]
    if benefit_cells:
        cols = min(2, len(benefit_cells))
        data = []
        for i in range(0, len(benefit_cells), cols):
            row = benefit_cells[i:i+cols]
            while len(row) < cols: row.append("")
            data.append(row)
        btable = Table(data, colWidths=[85*mm]*cols)
        btable.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),GREEN_LIGHT),("BOX",(0,0),(-1,-1),0.4,colors.HexColor('#CDE8D5'))),("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),4*mm),("RIGHTPADDING",(0,0),(-1,-1),4*mm),("TOPPADDING",(0,0),(-1,-1),3*mm),("BOTTOMPADDING",(0,0),(-1,-1),3*mm)]))
        story += [btable, Spacer(1, 7*mm)]

    story += [PageBreak(), Paragraph("02 · IHRE FESTPREIS-LEISTUNG", redsmall), Paragraph("Ein Preis. Alles drin.", title)]
    rows = [[Paragraph("POS.", small), Paragraph("LEISTUNG / ARTIKEL", small), Paragraph("MENGE", small), Paragraph("PREIS", small), Paragraph("NETTO", small)]]
    for i in o["items"]:
        rows.append([Paragraph(str(i["position"]), body), Paragraph(f"<b>{safe_text(i['title'])}</b><br/><font color='#6F6F6F'>{safe_text(i['description'])}</font>", body), Paragraph(f"{safe_text(i['quantity'])} {safe_text(i['unit'])}", body), Paragraph(money(i["unit_price"]), right), Paragraph(money(i["total_net"]), right)])
    tbl = Table(rows, colWidths=[12*mm,84*mm,22*mm,27*mm,30*mm], repeatRows=1)
    tbl.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),DARK),("TEXTCOLOR",(0,0),(-1,0),WHITE),("GRID",(0,0),(-1,-1),0.3,BORDER),("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),2.5*mm),("RIGHTPADDING",(0,0),(-1,-1),2.5*mm),("TOPPADDING",(0,0),(-1,-1),3*mm),("BOTTOMPADDING",(0,0),(-1,-1),3*mm)]))
    story += [tbl, Spacer(1, 7*mm), stats, Spacer(1, 10*mm), Paragraph("Im Preis enthalten", h2)]
    include = ["Fachgerechte Montage", "Konfiguration und Inbetriebnahme", "Funktionsprüfung", "Einweisung und Übergabe"]
    story.append(Table([[Paragraph(f"✓ {x}", ParagraphStyle(f"inc{x}", parent=body, textColor=GREEN, fontName="Helvetica-Bold")) for x in include]], colWidths=[42.5*mm]*4, style=[("BACKGROUND",(0,0),(-1,-1),GREEN_LIGHT),("BOX",(0,0),(-1,-1),0.4,colors.HexColor('#CDE8D5'))),("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),3*mm),("RIGHTPADDING",(0,0),(-1,-1),3*mm),("TOPPADDING",(0,0),(-1,-1),4*mm),("BOTTOMPADDING",(0,0),(-1,-1),4*mm)]))

    story += [PageBreak(), Paragraph("03 · NÄCHSTE SCHRITTE", redsmall), Paragraph("So geht es weiter.", title)]
    steps = o.get("next_steps") or []
    step_rows = []
    for idx, step in enumerate(steps[:6], 1):
        step_rows.append([Paragraph(str(idx), ParagraphStyle(f"step{idx}", parent=body, fontName="Helvetica-Bold", fontSize=13, textColor=WHITE, alignment=TA_RIGHT)), Paragraph(safe_text(step), body)])
    if step_rows:
        st = Table(step_rows, colWidths=[16*mm,154*mm])
        st.setStyle(TableStyle([("BACKGROUND",(0,0),(0,-1),RED),("VALIGN",(0,0),(-1,-1),"MIDDLE"),("BOX",(0,0),(-1,-1),0.4,BORDER),("INNERGRID",(0,0),(-1,-1),0.4,colors.HexColor('#EEEEEE'))),("LEFTPADDING",(0,0),(-1,-1),4*mm),("RIGHTPADDING",(0,0),(-1,-1),4*mm),("TOPPADDING",(0,0),(-1,-1),5*mm),("BOTTOMPADDING",(0,0),(-1,-1),5*mm)]))
        story.append(st)
    story += [Spacer(1, 12*mm), Paragraph("Vielen Dank für Ihr Vertrauen in FT Sicherheitstechnik.", h2), Paragraph("Die Preise und Positionen stammen aus dem zugrunde liegenden Billomat-Angebot. Diese Darstellung ergänzt die kundenseitige Präsentation, ohne die Kalkulation zu verändern.", small)]

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    buffer.seek(0)
    return buffer


@app.route("/offer/<offer_id>/pdf", methods=["GET", "POST"])
def offer_pdf(offer_id):
    if offer_id == "demo":
        o = {"offer_number":"26-79","date":"12.06.2026","validity_date":"26.06.2026","title":"Videoüberwachung – Pasa Firin","intro":"Professionelle IP-Videoüberwachung mit KI-Personen-/Fahrzeugerkennung.","total_net":6452.40,"total_gross":7678.36,"taxes":[{"amount":1225.96}],"client":{"name":"Pasa Firin","street":"G2 9","zip":"68159","city":"Mannheim"},"items":[]}
    else:
        o = load_offer(offer_id)
    if request.method == "POST":
        o = offer_data_from_form(o, request.form)
    number = str(o.get("offer_number") or o.get("number") or offer_id)
    return send_file(make_pdf(o), mimetype="application/pdf", as_attachment=False, download_name=f"FTST-Angebot-{number}.pdf")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8099")))
