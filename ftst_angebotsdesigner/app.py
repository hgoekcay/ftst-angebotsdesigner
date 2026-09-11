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
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether
from billomat_client import BillomatClient

APP_VERSION = "0.1.11"
log = logging.getLogger("ftst.app")
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "ftst-dev")

# FTST brand: red stays the corporate accent; green communicates positive price/status.
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
.btn{display:inline-block;background:var(--red);color:#fff;text-decoration:none;padding:12px 18px;border-radius:8px;font-weight:700}.btn.dark{background:var(--dark)}.btn.light{background:#efefef;color:#111}
table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:13px 10px;border-bottom:1px solid #e8e8e8;vertical-align:top}th{font-size:11px;text-transform:uppercase;color:var(--muted);letter-spacing:.7px}.money{text-align:right;font-weight:800}.muted{color:var(--muted)}.tag{display:inline-block;border-radius:99px;background:var(--greenlight);color:var(--green);padding:6px 10px;font-size:11px;font-weight:700}
.section-title{font-size:22px;margin:0 0 14px}.small{font-size:12px}.footer-note{font-size:12px;color:var(--muted);text-align:center;margin:26px 0 10px}
"""


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
    return (c or {}).get("name") or (c or {}).get("company") or "Kunde"


def safe_text(value):
    if value is None or isinstance(value, (dict, list)):
        return ""
    return html.escape(str(value))


def normalize_item(item, pos):
    if not isinstance(item, dict):
        return {"position":pos,"title":str(item),"description":"","quantity":1,"unit":"","unit_price":0,"total_net":0}
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
    o["items"] = [normalize_item(x, i+1) for i, x in enumerate(one_or_list(o.get("items")))]
    taxes = one_or_list(o.get("taxes"))
    total_tax = 0.0
    for tax in taxes:
        if isinstance(tax, dict):
            try: total_tax += float(tax.get("amount") or tax.get("tax_amount") or 0)
            except Exception: pass
    o["tax_amount"] = total_tax
    return o


def base(title, body):
    return f'''<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title><style>{CSS}</style></head><body><div class="top"><div class="topin"><div><div class="brand">FT SICHERHEITSTECHNIK</div><div class="sub">FTST AngebotsDesigner</div></div><div class="small">Version {APP_VERSION}</div></div></div><main class="wrap">{body}</main></body></html>'''


def detail(o):
    o = normalize_offer(o); c = o["client"]
    rows = "".join(f'''<tr><td>{safe_text(i['position'])}</td><td><b>{safe_text(i['title'])}</b><br><span class="muted small">{safe_text(i['description'])}</span></td><td>{safe_text(i['quantity'])} {safe_text(i['unit'])}</td><td class="money">{money(i['unit_price'])}</td><td class="money">{money(i['total_net'])}</td></tr>''' for i in o["items"])
    body = f'''<div class="card hero"><div class="eyebrow">Ihr persönliches Angebot</div><h1>{safe_text(o.get('title') or 'Individuelle Sicherheitslösung')}</h1><p>{safe_text(o.get('intro') or 'Ihre individuelle Lösung von FT Sicherheitstechnik – professionell geplant, sauber umgesetzt und auf Ihre Anforderungen abgestimmt.')}</p><div style="margin-top:22px"><a class="btn" href="{ingress('offer/'+str(o.get('id'))+'/pdf')}">A4-Angebot als PDF</a> <a class="btn light" href="{ingress('offers')}">← Zur Übersicht</a></div></div><div class="grid"><div class="metric"><div class="label">Kunde</div><div class="value" style="font-size:18px">{safe_text(client_name(c))}</div><div class="muted small">{safe_text(c.get('street',''))}<br>{safe_text(c.get('zip',''))} {safe_text(c.get('city',''))}</div></div><div class="metric"><div class="label">Angebot</div><div class="value" style="font-size:18px">Nr. {safe_text(o.get('offer_number') or o.get('number') or '-')}</div><div class="muted small">Datum: {safe_text(o.get('date','-'))}<br>Gültig: {safe_text(o.get('validity_date') or o.get('validity_days') or '-')}</div></div><div class="metric green"><div class="label">Ihr Festpreis</div><div class="value">{money(o.get('total_gross'))}</div><div class="muted small">Netto {money(o.get('total_net'))}</div></div></div><div class="card"><h2 class="section-title">Projekt auf einen Blick</h2><p class="muted">Die nachfolgende Übersicht zeigt die in Billomat erfassten Leistungen und Artikel. Die Positionen werden direkt aus Ihrem Angebot übernommen.</p></div><div class="card"><h2 class="section-title">Leistungsumfang</h2><table><thead><tr><th>Pos.</th><th>Leistung / Artikel</th><th>Menge</th><th>Einzelpreis</th><th>Netto</th></tr></thead><tbody>{rows}</tbody></table></div><div class="card"><h2 class="section-title">Kostenübersicht</h2><div class="grid"><div class="metric"><div class="label">Netto</div><div class="value">{money(o.get('total_net'))}</div></div><div class="metric"><div class="label">MwSt.</div><div class="value">{money(o.get('tax_amount'))}</div></div><div class="metric green"><div class="label">Gesamt</div><div class="value">{money(o.get('total_gross'))}</div></div></div></div><div class="footer-note">FT Sicherheitstechnik · Professionelle Sicherheitstechnik</div>'''
    return base("FTST Angebot", body)


@app.get("/health")
def health(): return {"ok": True, "version": APP_VERSION}


@app.get("/")
def index():
    body = f'''<div class="card hero"><div class="eyebrow">FTST AngebotsDesigner</div><h1>Professionelle Angebote aus Billomat</h1><p>Billomat-Daten importieren, prüfen und als hochwertiges FTST-A4-Angebot ausgeben.</p><a class="btn" href="{ingress('offers')}">Angebote öffnen</a> <a class="btn dark" href="{ingress('demo')}">Design-Demo</a></div>'''
    return base("FTST AngebotsDesigner", body)


@app.get("/offers")
def offers():
    bid=os.getenv("BILLOMAT_ID"); key=os.getenv("BILLOMAT_API_KEY")
    if not bid or not key: return base("Billomat", '<div class="card"><h1>Billomat nicht konfiguriert</h1><p>Bitte Billomat-ID und API-Key in der Home-Assistant-App konfigurieren.</p></div>')
    try:
        data=BillomatClient(bid,key).list_offers(request.args.get("search",""))
        data=sorted(data,key=lambda x:str(x.get("date","") if isinstance(x,dict) else ""),reverse=True)
    except Exception as e:
        log.exception("Offer list failed"); return base("Billomat Fehler",f'<div class="card"><h1>Billomat-Fehler</h1><p>{safe_text(e)}</p></div>'),502
    rows="".join(f'''<tr><td><b>{safe_text(o.get("offer_number") or o.get("number") or "-")}</b></td><td>{safe_text(o.get("date"))}</td><td>{safe_text(o.get("title") or "-")}</td><td class="money">{money(o.get("total_gross"))}</td><td><a class="btn" href="{ingress('offer/'+str(o.get('id')))}">Öffnen</a></td></tr>''' for o in data if isinstance(o,dict))
    return base("Angebote", f'''<div class="card"><div class="eyebrow">Billomat</div><h1>Ihre Angebote</h1><p class="muted">{len(data)} Angebote · neueste zuerst</p><table><thead><tr><th>Nr.</th><th>Datum</th><th>Titel</th><th>Brutto</th><th></th></tr></thead><tbody>{rows}</tbody></table></div>''')


@app.get("/offer/<offer_id>")
def offer(offer_id):
    bid=os.getenv("BILLOMAT_ID"); key=os.getenv("BILLOMAT_API_KEY")
    if not bid or not key: abort(503)
    try: o=BillomatClient(bid,key).get_full_offer(offer_id)
    except Exception as e:
        log.exception("Offer detail failed"); return base("Fehler",f'<div class="card"><h1>Angebot konnte nicht geladen werden</h1><p>{safe_text(e)}</p></div>'),502
    return detail(o)


@app.get("/demo")
def demo():
    o={"id":"demo","offer_number":"26-79","date":"12.06.2026","validity_date":"26.06.2026","status":"draft","title":"Videoüberwachung – Pasa Firin","intro":"Professionelle IP-Videoüberwachung mit KI-Personen-/Fahrzeugerkennung.","total_net":6452.40,"total_gross":7678.36,"taxes":[{"amount":1225.96}],"client":{"name":"Pasa Firin","street":"G2 9","zip":"68159","city":"Mannheim"},"items":[{"position":1,"title":"8MP Domekamera","description":"2.8mm · Tag/Nacht · KI Person/Fahrzeug","quantity":16,"unit":"Stk.","unit_price":298,"total_net":4768},{"position":2,"title":"16-Kanal NVR","description":"AI-Aufzeichnung","quantity":1,"unit":"Stk.","unit_price":900,"total_net":900},{"position":3,"title":"24-Port PoE Switch","description":"Managed PoE","quantity":1,"unit":"Stk.","unit_price":222,"total_net":222},{"position":4,"title":"Techniker","description":"Montage und Inbetriebnahme","quantity":4,"unit":"Std.","unit_price":85,"total_net":340},{"position":5,"title":"Helfer","description":"Unterstützende Montagearbeiten","quantity":4,"unit":"Std.","unit_price":35,"total_net":140}]}
    return detail(o)


def footer(canvas, doc):
    canvas.saveState()
    width, height = A4
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(18*mm, 9*mm, "FT Sicherheitstechnik · Professionelle Sicherheitstechnik")
    canvas.drawRightString(width-18*mm, 9*mm, f"Seite {doc.page}")
    canvas.setStrokeColor(BORDER)
    canvas.line(18*mm, 13*mm, width-18*mm, 13*mm)
    canvas.restoreState()


def make_pdf(o):
    o=normalize_offer(o); c=o["client"]; buffer=io.BytesIO()
    doc=SimpleDocTemplate(buffer,pagesize=A4,leftMargin=18*mm,rightMargin=18*mm,topMargin=18*mm,bottomMargin=19*mm)
    styles=getSampleStyleSheet()
    title=ParagraphStyle("FTTitle",parent=styles["Title"],fontName="Helvetica-Bold",fontSize=26,leading=30,textColor=DARK,spaceAfter=8)
    cover=ParagraphStyle("FTCover",parent=title,fontSize=29,leading=33,spaceAfter=12)
    h2=ParagraphStyle("FTH2",parent=styles["Heading2"],fontName="Helvetica-Bold",fontSize=17,leading=20,textColor=DARK,spaceBefore=4,spaceAfter=8)
    body=ParagraphStyle("FTBody",parent=styles["BodyText"],fontName="Helvetica",fontSize=9.7,leading=14,textColor=TEXT)
    small=ParagraphStyle("FTSmall",parent=body,fontSize=7.8,leading=10,textColor=MUTED)
    redsmall=ParagraphStyle("FTRedSmall",parent=small,textColor=RED,fontName="Helvetica-Bold",spaceAfter=3)
    greensmall=ParagraphStyle("FTGreenSmall",parent=small,textColor=GREEN,fontName="Helvetica-Bold",spaceAfter=3)
    greenbig=ParagraphStyle("FTGreenBig",parent=body,fontName="Helvetica-Bold",fontSize=24,leading=28,textColor=GREEN)
    right=ParagraphStyle("FTRight",parent=body,alignment=TA_RIGHT)
    whitebig=ParagraphStyle("FTWhiteBig",parent=body,fontName="Helvetica-Bold",fontSize=15,leading=18,textColor=WHITE)

    number = safe_text(o.get("offer_number") or o.get("number") or "-")
    customer = safe_text(client_name(c))
    street = safe_text(c.get("street",""))
    city = safe_text(f"{c.get('zip','')} {c.get('city','')}")
    title_text = safe_text(o.get("title") or "Individuelle Sicherheitslösung")
    intro_text = safe_text(o.get("intro") or "Professionelle Sicherheitstechnik – geplant und umgesetzt von FT Sicherheitstechnik.")

    story=[]

    # 1 — Cover
    cover_header=Table([[Paragraph("FT SICHERHEITSTECHNIK",whitebig), ""]],colWidths=[125*mm,45*mm])
    cover_header.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),DARK),("LINEBELOW",(0,0),(-1,0),3*mm,RED),("VALIGN",(0,0),(-1,-1),"MIDDLE"),("TOPPADDING",(0,0),(-1,-1),7*mm),("BOTTOMPADDING",(0,0),(-1,-1),7*mm)]))
    story += [cover_header,Spacer(1,18*mm),Paragraph("IHR PERSÖNLICHES ANGEBOT",redsmall),Paragraph(title_text,cover),Paragraph("Ihre neue Sicherheitslösung – professionell geplant, sauber umgesetzt und bereit für den täglichen Einsatz.",body),Spacer(1,15*mm)]
    info=Table([[Paragraph("ERSTELLT FÜR",redsmall),Paragraph("AUSGESTELLT AM",redsmall),Paragraph("GÜLTIG BIS",redsmall)],[Paragraph(f"<b>{customer}</b><br/>{street}<br/>{city}",body),Paragraph(safe_text(o.get("date","-")),body),Paragraph(safe_text(o.get("validity_date") or o.get("validity_days") or "-"),body)]],colWidths=[75*mm,47*mm,48*mm])
    info.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),LIGHT),("BOX",(0,0),(-1,-1),0.5,BORDER),("INNERGRID",(0,0),(-1,-1),0.4,BORDER),("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),4*mm),("RIGHTPADDING",(0,0),(-1,-1),4*mm),("TOPPADDING",(0,0),(-1,-1),3.5*mm),("BOTTOMPADDING",(0,0),(-1,-1),3.5*mm)]))
    story += [info,Spacer(1,12*mm)]
    pricebox=Table([[Paragraph("IHR FESTPREIS",greensmall),Paragraph("ANGEBOT",redsmall)],[Paragraph(money(o.get("total_gross")),greenbig),Paragraph(f"<b>{number}</b><br/>Netto {money(o.get('total_net'))}",body)]],colWidths=[95*mm,75*mm])
    pricebox.setStyle(TableStyle([("BACKGROUND",(0,0),(0,-1),GREEN_LIGHT),("BACKGROUND",(1,0),(1,-1),LIGHT),("BOX",(0,0),(-1,-1),0.6,BORDER),("VALIGN",(0,0),(-1,-1),"MIDDLE"),("LEFTPADDING",(0,0),(-1,-1),5*mm),("TOPPADDING",(0,0),(-1,-1),5*mm),("BOTTOMPADDING",(0,0),(-1,-1),5*mm)]))
    story += [pricebox,Spacer(1,10*mm),Paragraph("FT Sicherheitstechnik · info@ftst.eu · +49 621 15 96 47 34",small),PageBreak()]

    # 2 — Project overview
    story += [Paragraph("01 · IHR PROJEKT AUF EINEN BLICK",redsmall),Paragraph("Das haben wir für Sie zusammengestellt.",title),Paragraph(intro_text,body),Spacer(1,6*mm)]
    count=len(o["items"])
    overview=Table([[Paragraph("LEISTUNGEN",redsmall),Paragraph("ANZAHL",redsmall),Paragraph("INVESTITION",redsmall)],[Paragraph("Produkte & Dienstleistungen aus Ihrem Billomat-Angebot",body),Paragraph(f"{count} Positionen",body),Paragraph(money(o.get("total_gross")),ParagraphStyle("ovprice",parent=body,fontName="Helvetica-Bold",textColor=GREEN,fontSize=14))]],colWidths=[82*mm,36*mm,52*mm])
    overview.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),LIGHT),("BOX",(0,0),(-1,-1),0.5,BORDER),("INNERGRID",(0,0),(-1,-1),0.4,BORDER),("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),4*mm),("TOPPADDING",(0,0),(-1,-1),4*mm),("BOTTOMPADDING",(0,0),(-1,-1),4*mm)]))
    story += [overview,Spacer(1,9*mm)]
    cards=[]
    for i in o["items"][:6]:
        cards.append(Paragraph(f"<b>✓ {safe_text(i['title'])}</b><br/><font color='#707070'>{safe_text(i['description'])}</font>",body))
    while len(cards)<6: cards.append(Paragraph("",body))
    card_table=Table([[cards[0],cards[1]],[cards[2],cards[3]],[cards[4],cards[5]]],colWidths=[85*mm,85*mm])
    card_table.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),LIGHT),("BOX",(0,0),(-1,-1),0.5,BORDER),("INNERGRID",(0,0),(-1,-1),0.4,BORDER),("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),4*mm),("RIGHTPADDING",(0,0),(-1,-1),4*mm),("TOPPADDING",(0,0),(-1,-1),4*mm),("BOTTOMPADDING",(0,0),(-1,-1),4*mm)]))
    story += [card_table,Spacer(1,9*mm),Paragraph("Alles aus einer Hand",h2),Paragraph("Planung, Lieferung, fachgerechte Montage, Konfiguration und Übergabe können – soweit im Billomat-Angebot enthalten – als zusammenhängende Leistung dargestellt werden.",body),PageBreak()]

    # 3 — Scope / price
    story += [Paragraph("02 · IHRE FESTPREIS-LEISTUNG",redsmall),Paragraph("Ein Preis. Die komplette Lösung.",title),Paragraph("Die folgenden Positionen werden aus dem bestehenden Billomat-Angebot übernommen.",body),Spacer(1,6*mm)]
    rows=[[Paragraph("POS.",small),Paragraph("LEISTUNG / ARTIKEL",small),Paragraph("MENGE",small),Paragraph("EINZELPREIS",small),Paragraph("NETTO",small)]]
    for i in o["items"]:
        rows.append([Paragraph(str(i["position"]),body),Paragraph(f"<b>{safe_text(i['title'])}</b><br/><font color='#707070'>{safe_text(i['description'])}</font>",body),Paragraph(f"{safe_text(i['quantity'])} {safe_text(i['unit'])}",body),Paragraph(money(i["unit_price"]),right),Paragraph(money(i["total_net"]),right)])
    tbl=Table(rows,colWidths=[12*mm,84*mm,22*mm,27*mm,30*mm],repeatRows=1)
    tbl.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),DARK),("TEXTCOLOR",(0,0),(-1,0),WHITE),("GRID",(0,0),(-1,-1),0.3,BORDER),("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),2.5*mm),("RIGHTPADDING",(0,0),(-1,-1),2.5*mm),("TOPPADDING",(0,0),(-1,-1),3*mm),("BOTTOMPADDING",(0,0),(-1,-1),3*mm)]))
    story += [tbl,Spacer(1,8*mm)]
    totals=Table([[Paragraph("NETTO",small),Paragraph("MWST.",small),Paragraph("GESAMT",greensmall)],[Paragraph(money(o.get("total_net")),body),Paragraph(money(o.get("tax_amount")),body),Paragraph(money(o.get("total_gross")),greenbig)]],colWidths=[56*mm,56*mm,58*mm])
    totals.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),LIGHT),("BACKGROUND",(2,0),(2,-1),GREEN_LIGHT),("BOX",(0,0),(-1,-1),0.5,BORDER),("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),4*mm),("TOPPADDING",(0,0),(-1,-1),4*mm),("BOTTOMPADDING",(0,0),(-1,-1),5*mm)]))
    story += [totals,Spacer(1,10*mm),Paragraph("✓ Transparente Kalkulation",greensmall),Paragraph("Die Preise und Mengen werden direkt aus Ihrem Billomat-Angebot übernommen. Die Gestaltung ändert die Darstellung, nicht die Kalkulation.",body),PageBreak()]

    # 4 — Benefits / trust
    story += [Paragraph("03 · IHRE VORTEILE",redsmall),Paragraph("Was Sie von FT Sicherheitstechnik erwarten können.",title)]
    benefits=[("PROFESSIONELLE PLANUNG","Die angebotenen Positionen werden übersichtlich als zusammenhängende Sicherheitslösung dargestellt."),("SAUBERE UMSETZUNG","Montage, Konfiguration und Übergabe können transparent und nachvollziehbar beschrieben werden."),("ERWEITERBAR","Die Darstellung ist so aufgebaut, dass spätere zusätzliche Leistungen und Systeme ergänzt werden können."),("PERSÖNLICHER SERVICE","Klarer Ansprechpartner und direkte Kommunikation von der Planung bis zur Übergabe.")]
    for head,text in benefits:
        box=Table([[Paragraph("✓",ParagraphStyle("check",parent=body,fontName="Helvetica-Bold",fontSize=18,textColor=GREEN)),Paragraph(head,redsmall)],["",Paragraph(text,body)]],colWidths=[12*mm,158*mm])
        box.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),LIGHT),("BOX",(0,0),(-1,-1),0.5,BORDER),("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),4*mm),("TOPPADDING",(0,0),(-1,-1),3.5*mm),("BOTTOMPADDING",(0,0),(-1,-1),3.5*mm)]))
        story += [box,Spacer(1,4*mm)]
    story += [Spacer(1,6*mm),Paragraph("Hinweis",h2),Paragraph("Konkrete Hersteller-, Zertifizierungs-, Garantie- oder Referenzaussagen sollten im finalen Angebot nur verwendet werden, wenn sie für das jeweilige Projekt tatsächlich zutreffen.",small),PageBreak()]

    # 5 — Next steps
    story += [Paragraph("04 · NÄCHSTE SCHRITTE",redsmall),Paragraph("So geht es weiter.",title),Paragraph("Wir halten den Ablauf für Sie einfach und transparent.",body),Spacer(1,8*mm)]
    steps=[("1","Angebot prüfen","Sie prüfen Umfang, Preise und enthaltene Leistungen."),("2","Auftrag bestätigen","Bestätigung per E-Mail oder nach Vereinbarung."),("3","Termin abstimmen","Wir koordinieren Material und Installationstermin."),("4","Installation & Übergabe","Fachgerechte Umsetzung, Konfiguration und Einweisung – entsprechend dem vereinbarten Leistungsumfang.")]
    for n,head,text in steps:
        step=Table([[Paragraph(n,whitebig),Paragraph(f"<b>{head}</b><br/>{text}",body)]],colWidths=[18*mm,152*mm])
        step.setStyle(TableStyle([("BACKGROUND",(0,0),(0,0),RED),("BACKGROUND",(1,0),(1,0),LIGHT),("BOX",(0,0),(-1,-1),0.5,BORDER),("VALIGN",(0,0),(-1,-1),"MIDDLE"),("LEFTPADDING",(0,0),(-1,-1),4*mm),("TOPPADDING",(0,0),(-1,-1),4*mm),("BOTTOMPADDING",(0,0),(-1,-1),4*mm)]))
        story += [step,Spacer(1,4*mm)]
    story += [Spacer(1,10*mm),Table([[Paragraph("IHR FESTPREIS",greensmall),Paragraph("DANKE FÜR IHR VERTRAUEN",redsmall)],[Paragraph(money(o.get("total_gross")),greenbig),Paragraph("Wir freuen uns auf die Umsetzung Ihres Projekts.",body)]],colWidths=[75*mm,95*mm],style=TableStyle([("BACKGROUND",(0,0),(0,-1),GREEN_LIGHT),("BACKGROUND",(1,0),(1,-1),LIGHT),("BOX",(0,0),(-1,-1),0.5,BORDER),("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),5*mm),("TOPPADDING",(0,0),(-1,-1),5*mm),("BOTTOMPADDING",(0,0),(-1,-1),5*mm)]))]

    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    buffer.seek(0)
    return buffer


@app.get("/offer/<offer_id>/pdf")
def offer_pdf(offer_id):
    if offer_id=='demo':
        o={"offer_number":"26-79","date":"12.06.2026","validity_date":"26.06.2026","title":"Videoüberwachung – Pasa Firin","intro":"Professionelle IP-Videoüberwachung mit KI-Personen-/Fahrzeugerkennung.","total_net":6452.40,"total_gross":7678.36,"taxes":[{"amount":1225.96}],"client":{"name":"Pasa Firin","street":"G2 9","zip":"68159","city":"Mannheim"},"items":[]}
    else:
        bid=os.getenv('BILLOMAT_ID'); key=os.getenv('BILLOMAT_API_KEY')
        if not bid or not key: abort(503)
        try: o=BillomatClient(bid,key).get_full_offer(offer_id)
        except Exception as e: return base("Fehler",f'<div class="card"><h1>PDF konnte nicht erstellt werden</h1><p>{safe_text(e)}</p></div>'),500
    number=str(o.get('offer_number') or o.get('number') or offer_id)
    return send_file(make_pdf(o),mimetype='application/pdf',as_attachment=False,download_name=f"FTST-Angebot-{number}.pdf")


if __name__=='__main__':
    app.run(host='0.0.0.0',port=int(os.getenv('PORT','8099')))
