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

APP_VERSION = "0.1.10"
log = logging.getLogger("ftst.app")
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "ftst-dev")

RED = colors.HexColor("#D71920")
DARK = colors.HexColor("#111111")
TEXT = colors.HexColor("#202020")
MUTED = colors.HexColor("#707070")
LIGHT = colors.HexColor("#F4F4F4")
WHITE = colors.white

CSS = """
:root{--red:#d71920;--dark:#111;--text:#222;--muted:#707070;--light:#f4f4f4;}
*{box-sizing:border-box}body{margin:0;font-family:Arial,Helvetica,sans-serif;background:#ececec;color:var(--text)}
.top{background:var(--dark);color:#fff;border-bottom:5px solid var(--red)}
.topin{max-width:1180px;margin:auto;padding:22px 26px;display:flex;justify-content:space-between;align-items:center}
.brand{font-size:22px;font-weight:800;letter-spacing:.5px}.sub{font-size:12px;opacity:.72;margin-top:3px}
.wrap{max-width:1180px;margin:28px auto;padding:0 18px}.card{background:#fff;border-radius:16px;padding:28px;margin-bottom:18px;box-shadow:0 6px 24px rgba(0,0,0,.07)}
.hero{padding:36px}.eyebrow{color:var(--red);font-size:12px;font-weight:800;text-transform:uppercase;letter-spacing:1.2px}.hero h1{font-size:34px;line-height:1.05;margin:10px 0}.hero p{font-size:16px;color:var(--muted);max-width:800px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px}.metric{background:var(--light);padding:18px;border-radius:12px}.metric .label{font-size:11px;text-transform:uppercase;letter-spacing:.8px;color:var(--muted)}.metric .value{font-size:22px;font-weight:800;margin-top:5px}
.btn{display:inline-block;background:var(--red);color:#fff;text-decoration:none;padding:12px 18px;border-radius:8px;font-weight:700}.btn.dark{background:var(--dark)}.btn.light{background:#efefef;color:#111}
table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:13px 10px;border-bottom:1px solid #e8e8e8;vertical-align:top}th{font-size:11px;text-transform:uppercase;color:var(--muted);letter-spacing:.7px}.money{text-align:right;font-weight:800}.muted{color:var(--muted)}.tag{display:inline-block;border-radius:99px;background:#eee;padding:6px 10px;font-size:11px;font-weight:700}
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
    body = f'''<div class="card hero"><div class="eyebrow">Ihr persönliches Angebot</div><h1>{safe_text(o.get('title') or 'Individuelle Sicherheitslösung')}</h1><p>{safe_text(o.get('intro') or 'Ihre individuelle Lösung von FT Sicherheitstechnik – professionell geplant, zuverlässig umgesetzt.')}</p><div style="margin-top:22px"><a class="btn" href="{ingress('offer/'+str(o.get('id'))+'/pdf')}">A4-Angebot als PDF</a> <a class="btn light" href="{ingress('offers')}">← Zur Übersicht</a></div></div><div class="grid"><div class="metric"><div class="label">Kunde</div><div class="value" style="font-size:18px">{safe_text(client_name(c))}</div><div class="muted small">{safe_text(c.get('street',''))}<br>{safe_text(c.get('zip',''))} {safe_text(c.get('city',''))}</div></div><div class="metric"><div class="label">Angebot</div><div class="value" style="font-size:18px">Nr. {safe_text(o.get('offer_number') or o.get('number') or '-')}</div><div class="muted small">Datum: {safe_text(o.get('date','-'))}<br>Gültig: {safe_text(o.get('validity_date') or o.get('validity_days') or '-')}</div></div><div class="metric"><div class="label">Gesamt</div><div class="value">{money(o.get('total_gross'))}</div><div class="muted small">Netto {money(o.get('total_net'))}</div></div></div><div class="card"><h2 class="section-title">Leistungsübersicht</h2><table><thead><tr><th>Pos.</th><th>Leistung / Artikel</th><th>Menge</th><th>Einzelpreis</th><th>Netto</th></tr></thead><tbody>{rows}</tbody></table></div><div class="card"><h2 class="section-title">Kostenübersicht</h2><div class="grid"><div class="metric"><div class="label">Netto</div><div class="value">{money(o.get('total_net'))}</div></div><div class="metric"><div class="label">MwSt.</div><div class="value">{money(o.get('tax_amount'))}</div></div><div class="metric"><div class="label">Gesamt</div><div class="value">{money(o.get('total_gross'))}</div></div></div></div><div class="footer-note">FT Sicherheitstechnik · Professionelle Sicherheitstechnik · Ihr Angebot wird als A4-PDF ausgegeben.</div>'''
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

def make_pdf(o):
    o=normalize_offer(o); c=o["client"]; buffer=io.BytesIO()
    doc=SimpleDocTemplate(buffer,pagesize=A4,leftMargin=18*mm,rightMargin=18*mm,topMargin=18*mm,bottomMargin=18*mm)
    styles=getSampleStyleSheet()
    title=ParagraphStyle("FTTitle",parent=styles["Title"],fontName="Helvetica-Bold",fontSize=25,leading=29,textColor=DARK,spaceAfter=8)
    h2=ParagraphStyle("FTH2",parent=styles["Heading2"],fontName="Helvetica-Bold",fontSize=16,leading=19,textColor=DARK,spaceBefore=8,spaceAfter=8)
    body=ParagraphStyle("FTBody",parent=styles["BodyText"],fontName="Helvetica",fontSize=9.5,leading=14,textColor=TEXT)
    small=ParagraphStyle("FTSmall",parent=body,fontSize=7.8,leading=10,textColor=MUTED)
    redsmall=ParagraphStyle("FTRedSmall",parent=small,textColor=RED,fontName="Helvetica-Bold")
    right=ParagraphStyle("FTRight",parent=body,alignment=TA_RIGHT)
    story=[]
    header=Table([[Paragraph("FT SICHERHEITSTECHNIK",ParagraphStyle("brand",parent=body,fontName="Helvetica-Bold",fontSize=15,textColor=WHITE)),""]],colWidths=[120*mm,50*mm])
    header.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),DARK),("TEXTCOLOR",(0,0),(-1,-1),WHITE),("VALIGN",(0,0),(-1,-1),"MIDDLE"),("BOTTOMPADDING",(0,0),(-1,-1),8*mm),("TOPPADDING",(0,0),(-1,-1),8*mm),("LINEBELOW",(0,0),(-1,0),3*mm,RED)]))
    story += [header,Spacer(1,14*mm),Paragraph("IHR PERSÖNLICHES ANGEBOT",redsmall),Paragraph(str(o.get("title") or "Individuelle Sicherheitslösung"),title),Paragraph(str(o.get("intro") or "Professionelle Sicherheitstechnik – geplant und umgesetzt von FT Sicherheitstechnik."),body),Spacer(1,8*mm)]
    customer=Table([[Paragraph("KUNDE",redsmall),Paragraph("ANGEBOT",redsmall)],[Paragraph(f"<b>{safe_text(client_name(c))}</b><br/>{safe_text(c.get('street',''))}<br/>{safe_text(c.get('zip',''))} {safe_text(c.get('city',''))}",body),Paragraph(f"<b>Nr. {safe_text(o.get('offer_number') or o.get('number') or '-')}</b><br/>Datum: {safe_text(o.get('date','-'))}<br/>Gültig: {safe_text(o.get('validity_date') or o.get('validity_days') or '-')}",body)]],colWidths=[82*mm,88*mm])
    customer.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),LIGHT),("BOX",(0,0),(-1,-1),0.5,colors.HexColor('#dddddd')),("INNERGRID",(0,0),(-1,-1),0.5,colors.HexColor('#e5e5e5')),("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),5*mm),("RIGHTPADDING",(0,0),(-1,-1),5*mm),("TOPPADDING",(0,0),(-1,-1),4*mm),("BOTTOMPADDING",(0,0),(-1,-1),4*mm)]))
    story += [customer,Spacer(1,10*mm)]
    stat1=Paragraph(money(o.get("total_net")),ParagraphStyle("st1",parent=body,fontSize=15,fontName="Helvetica-Bold"));stat2=Paragraph(money(o.get("tax_amount")),ParagraphStyle("st2",parent=body,fontSize=15,fontName="Helvetica-Bold"));stat3=Paragraph(money(o.get("total_gross")),ParagraphStyle("st3",parent=body,fontSize=15,fontName="Helvetica-Bold",textColor=RED))
    stats=Table([[Paragraph("GESAMT NETTO",redsmall),Paragraph("MWST.",redsmall),Paragraph("GESAMT",redsmall)],[stat1,stat2,stat3]],colWidths=[56*mm,56*mm,58*mm])
    stats.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),LIGHT),("BOX",(0,0),(-1,-1),0.5,colors.HexColor('#dddddd')),("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),4*mm),("TOPPADDING",(0,0),(-1,-1),4*mm),("BOTTOMPADDING",(0,0),(-1,-1),5*mm)]))
    story += [stats,Spacer(1,11*mm),Paragraph("Projekt auf einen Blick",h2),Paragraph("Dieses Angebot enthält die aufgeführten Produkte und Leistungen. Die Darstellung ist für den direkten Versand an Ihren Kunden optimiert.",body),PageBreak(),Paragraph("Leistungsumfang",redsmall),Paragraph("Was wir für Sie umsetzen",title)]
    rows=[[Paragraph("POS.",small),Paragraph("LEISTUNG / ARTIKEL",small),Paragraph("MENGE",small),Paragraph("PREIS",small),Paragraph("NETTO",small)]]
    for i in o["items"]:
        rows.append([Paragraph(str(i["position"]),body),Paragraph(f"<b>{safe_text(i['title'])}</b><br/><font color='#707070'>{safe_text(i['description'])}</font>",body),Paragraph(f"{safe_text(i['quantity'])} {safe_text(i['unit'])}",body),Paragraph(money(i["unit_price"]),right),Paragraph(money(i["total_net"]),right)])
    tbl=Table(rows,colWidths=[12*mm,84*mm,22*mm,27*mm,30*mm],repeatRows=1)
    tbl.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),DARK),("TEXTCOLOR",(0,0),(-1,0),WHITE),("GRID",(0,0),(-1,-1),0.3,colors.HexColor('#dddddd')),("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),2.5*mm),("RIGHTPADDING",(0,0),(-1,-1),2.5*mm),("TOPPADDING",(0,0),(-1,-1),3*mm),("BOTTOMPADDING",(0,0),(-1,-1),3*mm)]))
    story += [Spacer(1,4*mm),tbl,Spacer(1,9*mm),Paragraph("Ihre Vorteile",h2)]
    advantages=Table([[Paragraph("PROFESSIONELL",redsmall),Paragraph("ZUVERLÄSSIG",redsmall),Paragraph("ZUKUNFTSFÄHIG",redsmall)],[Paragraph("Fachgerechte Planung, Montage und Inbetriebnahme durch FT Sicherheitstechnik.",body),Paragraph("Saubere Umsetzung und dokumentierte Inbetriebnahme für einen stabilen Betrieb.",body),Paragraph("Moderne Sicherheitstechnik mit der Möglichkeit zur späteren Erweiterung.",body)]],colWidths=[56*mm,56*mm,58*mm])
    advantages.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),LIGHT),("BOX",(0,0),(-1,-1),0.4,colors.HexColor('#dddddd')),("INNERGRID",(0,0),(-1,-1),0.4,colors.HexColor('#e5e5e5')),("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),3.5*mm),("RIGHTPADDING",(0,0),(-1,-1),3.5*mm),("TOPPADDING",(0,0),(-1,-1),3*mm),("BOTTOMPADDING",(0,0),(-1,-1),4*mm)]))
    story += [advantages,PageBreak(),Paragraph("Investition & nächster Schritt",redsmall),Paragraph("Ein Preis. Ihre komplette Lösung.",title),Spacer(1,5*mm),stats,Spacer(1,9*mm),Paragraph("So geht es weiter",h2)]
    steps=Table([[Paragraph("1",ParagraphStyle("step",parent=body,fontName="Helvetica-Bold",fontSize=13,textColor=WHITE)),Paragraph("Auftrag bestätigen",body)],[Paragraph("2",ParagraphStyle("step2",parent=body,fontName="Helvetica-Bold",fontSize=13,textColor=WHITE)),Paragraph("Termin gemeinsam abstimmen",body)],[Paragraph("3",ParagraphStyle("step3",parent=body,fontName="Helvetica-Bold",fontSize=13,textColor=WHITE)),Paragraph("Montage / Umsetzung und Inbetriebnahme",body)],[Paragraph("4",ParagraphStyle("step4",parent=body,fontName="Helvetica-Bold",fontSize=13,textColor=WHITE)),Paragraph("Übergabe der fertigen Anlage",body)]],colWidths=[14*mm,156*mm])
    steps.setStyle(TableStyle([("BACKGROUND",(0,0),(0,-1),RED),("VALIGN",(0,0),(-1,-1),"MIDDLE"),("BOX",(0,0),(-1,-1),0.4,colors.HexColor('#dddddd')),("INNERGRID",(0,0),(-1,-1),0.4,colors.HexColor('#eeeeee')),("LEFTPADDING",(0,0),(-1,-1),4*mm),("RIGHTPADDING",(0,0),(-1,-1),4*mm),("TOPPADDING",(0,0),(-1,-1),4*mm),("BOTTOMPADDING",(0,0),(-1,-1),4*mm)]))
    story += [steps,Spacer(1,12*mm),Paragraph("Vielen Dank für Ihr Vertrauen in FT Sicherheitstechnik.",h2),Paragraph("Dieses Angebot wurde aus den in Billomat hinterlegten Daten erstellt und als druckfertiges A4-Dokument gestaltet.",small)]
    doc.build(story); buffer.seek(0); return buffer

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

if __name__=='__main__': app.run(host='0.0.0.0',port=int(os.getenv('PORT','8099')))
