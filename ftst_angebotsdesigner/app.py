import io, os, html, logging
from flask import Flask, request, send_file, abort, session
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from billomat_client import BillomatClient

APP_VERSION = "0.1.14"
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "ftst-dev")
log = logging.getLogger("ftst.app")

RED = colors.HexColor("#D71920")
DARK = colors.HexColor("#111111")
TEXT = colors.HexColor("#202020")
MUTED = colors.HexColor("#6F6F6F")
LIGHT = colors.HexColor("#F4F4F4")
BORDER = colors.HexColor("#DCDCDC")
GREEN = colors.HexColor("#218838")
GREEN_LIGHT = colors.HexColor("#EAF6EE")
WHITE = colors.white

CSS = 'body{margin:0;font-family:Arial,Helvetica,sans-serif;background:#ececec;color:#222}.top{background:#111;color:#fff;border-bottom:5px solid #d71920}.topin{max-width:1180px;margin:auto;padding:22px;display:flex;justify-content:space-between;align-items:center}.brand{font-size:22px;font-weight:800}.sub,.small{font-size:12px;opacity:.75}.wrap{max-width:1180px;margin:28px auto;padding:0 18px}.card{background:#fff;border-radius:14px;padding:26px;margin-bottom:18px;box-shadow:0 5px 20px #00000012}.hero h1{font-size:34px;margin:8px 0}.eyebrow{color:#d71920;font-size:12px;font-weight:800;text-transform:uppercase;letter-spacing:1px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px}.metric{background:#f4f4f4;padding:18px;border-radius:12px}.metric.green{background:#eaf6ee}.metric .label{font-size:11px;color:#707070;text-transform:uppercase}.metric .value{font-size:22px;font-weight:800;margin-top:4px}.metric.green .value{color:#218838}.btn{display:inline-block;background:#d71920;color:#fff;text-decoration:none;padding:11px 17px;border-radius:8px;font-weight:700;margin-right:6px;border:0;cursor:pointer}.btn.dark{background:#111}.btn.light{background:#eee;color:#111}label{display:block;font-size:11px;color:#707070;text-transform:uppercase;font-weight:700;margin:0 0 6px}input,select,textarea{width:100%;box-sizing:border-box;padding:11px;border:1px solid #d5d5d5;border-radius:8px;font:inherit}.field{margin-bottom:16px}textarea{min-height:110px}table{width:100%;border-collapse:collapse}th,td{padding:11px 8px;border-bottom:1px solid #e8e8e8;text-align:left;vertical-align:top}th{font-size:11px;color:#707070;text-transform:uppercase}.money{text-align:right;font-weight:800}.muted{color:#707070}.small{font-size:12px}.checks{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}.check{background:#eaf6ee;color:#218838;padding:10px;border-radius:8px;font-weight:700;font-size:12px}.back{margin-bottom:16px}.back a{color:#111;text-decoration:none;font-weight:700}.back a:hover{color:#d71920}'

TYPES={"Videoüberwachung":("Professionelle Videoüberwachung für Ihr Objekt","Moderne IP-Videoüberwachung mit professioneller Aufzeichnung und Fernzugriff.","Auf Ihr Objekt abgestimmte Videoüberwachung inklusive Montage, Konfiguration, Prüfung und Einweisung.",["Hochauflösende Kameras","Intelligente Erkennung","Professionelle Aufzeichnung","Fernzugriff per App"]),"Alarmanlage":("Professionelle Alarmtechnik für Ihr Objekt","Zuverlässige Alarmtechnik mit moderner Alarmierung.","Objektbezogen geplant, fachgerecht montiert, eingerichtet und getestet.",["Schnelle Alarmierung","App-Steuerung","Sabotageschutz","Erweiterbar"]),"Zutrittskontrolle":("Sichere Zutrittskontrolle für Ihr Objekt","Kontrollieren Sie zuverlässig, wer Ihr Gebäude betreten darf.","Komplett eingerichtete Zutrittslösung mit Rechteverwaltung und Übergabe.",["RFID / Code / App","Zutrittsrechte","Protokollierung","Erweiterbar"]),"Türsprechanlage":("Moderne Video-Türsprechanlage","Sehen und sprechen Sie mit Besuchern vor Ort oder per Smartphone.","Lieferung, Montage, Konfiguration und betriebsbereite Übergabe.",["Video & Audio","Smartphone-Anbindung","Außentauglich","Einfache Bedienung"]),"Brandmeldeanlage":("Professionelle Brandmeldetechnik","Frühzeitige Detektion und strukturierte Alarmierung.","Planung, Installation, Prüfung und Dokumentation abgestimmt auf das Objekt.",["Frühe Detektion","Klare Alarmierung","Dokumentierte Prüfung","Normgerechte Umsetzung"]),"Smart Home":("Smarte Sicherheit und Gebäudeautomation","Sicherheit, Komfort und intelligente Steuerung.","Abgestimmte, einfach bedienbare und erweiterbare Gesamtlösung.",["Zentrale Steuerung","App-Anbindung","Automationen","Erweiterbar"]),"Kombination":("Ihre individuelle Sicherheitslösung","Mehrere Sicherheitssysteme werden zu einer abgestimmten Gesamtlösung.","Koordinierte Planung und vollständig konfigurierte Gesamtlösung.",["Ganzheitliche Planung","Ein Ansprechpartner","Abgestimmte Systeme","Erweiterbar"])}
DEFAULT_STEPS=["Angebot prüfen und bestätigen","Installationstermin abstimmen","Montage, Konfiguration und Inbetriebnahme","Übergabe und Einweisung"]

def ingress(path="/"):
    base=request.headers.get("X-Ingress-Path","").strip().rstrip("/")
    return base+"/"+path.lstrip("/")

def money(v):
    try:return f"{float(v):,.2f} €".replace(",","X").replace(".",",").replace("X",".")
    except:return "-"

def one_list(v):
    if isinstance(v,list):return v
    if isinstance(v,dict):
        for k in ("tax","item","offer-item","value"):
            if k in v:return v[k] if isinstance(v[k],list) else [v[k]]
        return [v]
    return []

def clean(v):return "" if v is None or isinstance(v,(dict,list)) else html.escape(str(v))
def cname(c):return (c or {}).get("name") or (c or {}).get("company") or "Kunde"

def normalize(o):
    o=dict(o or {});o["client"]=o.get("client") if isinstance(o.get("client"),dict) else {}
    items=[]
    for n,x in enumerate(one_list(o.get("items")),1):
        if isinstance(x,dict):items.append({"position":x.get("position") or n,"title":x.get("title") or "Leistung","description":x.get("description") or "","quantity":x.get("quantity") or 0,"unit":x.get("unit") or "","unit_price":x.get("unit_price") or 0,"total_net":x.get("total_net") or 0})
    o["items"]=items;o["tax_amount"]=sum(float(t.get("amount") or t.get("tax_amount") or 0) for t in one_list(o.get("taxes")) if isinstance(t,dict));return o

def apply_source(raw,src):
    o=normalize(raw);kind=src.get("offer_type") or "Kombination";p=TYPES.get(kind,TYPES["Kombination"]);o["offer_type"]=kind;o["customer_title"]=src.get("customer_title") or p[0];o["customer_intro"]=src.get("customer_intro") or p[1];o["project_summary"]=src.get("project_summary") or p[2];o["benefits"]=[x.strip() for x in str(src.get("benefits","")).splitlines() if x.strip()] or p[3];o["next_steps"]=[x.strip() for x in str(src.get("next_steps","")).splitlines() if x.strip()] or DEFAULT_STEPS;return o

def base(title,body):return f'<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title><style>{CSS}</style></head><body><div class="top"><div class="topin"><div><div class="brand">FT SICHERHEITSTECHNIK</div><div class="sub">FTST AngebotsDesigner</div></div><div class="small">v{APP_VERSION}</div></div></div><main class="wrap">{body}</main></body></html>'

def get_offer(oid):
    bid=os.getenv("BILLOMAT_ID");key=os.getenv("BILLOMAT_API_KEY")
    if not bid or not key:abort(503)
    return apply_source(BillomatClient(bid,key).get_full_offer(oid),session.get("ftst_"+oid,{}))

@app.get("/health")
def health():return {"ok":True,"version":APP_VERSION}

@app.get("/")
def index():return base("FTST",f'<div class="card hero"><div class="eyebrow">FTST AngebotsDesigner</div><h1>Professionelle Angebote aus Billomat</h1><p>Billomat-Angebote auswählen, kundengerecht bearbeiten und als A4-PDF ausgeben.</p><a class="btn" href="{ingress("offers")}">Angebote öffnen</a></div>')

@app.get("/offers")
def offers():
    try:
        bid=os.getenv("BILLOMAT_ID");key=os.getenv("BILLOMAT_API_KEY")
        if not bid or not key:return base("Billomat",'<div class="card"><h1>Billomat nicht konfiguriert</h1></div>')
        data=BillomatClient(bid,key).list_offers(request.args.get("search",""));data=sorted(data,key=lambda x:str(x.get("date","") if isinstance(x,dict) else ""),reverse=True)
        rows="".join(f'<tr><td><b>{clean(o.get("offer_number") or o.get("number") or "-")}</b></td><td>{clean(o.get("date"))}</td><td>{clean(o.get("title") or "-")}</td><td class="money">{money(o.get("total_gross"))}</td><td><a class="btn" href="{ingress("offer/"+str(o.get("id")))}">Öffnen</a></td></tr>' for o in data if isinstance(o,dict))
        return base("Angebote",f'<div class="card"><div class="eyebrow">Billomat</div><h1>Ihre Angebote</h1><p class="muted">{len(data)} Angebote · neueste zuerst</p><table><thead><tr><th>Nr.</th><th>Datum</th><th>Titel</th><th>Brutto</th><th></th></tr></thead><tbody>{rows}</tbody></table></div>')
    except Exception as e:
        log.exception("Offer list failed");return base("Fehler",f'<div class="card"><h1>Fehler</h1><p>{clean(e)}</p></div>'),502

@app.get("/offer/<oid>")
def offer(oid):return detail(get_offer(oid))

@app.route("/offer/<oid>/edit",methods=["GET","POST"])
def edit(oid):
    o=get_offer(oid)
    if request.method=="POST":
        src={k:request.form.get(k,"") for k in ("offer_type","customer_title","customer_intro","project_summary","benefits","next_steps")};session["ftst_"+oid]=src;session.modified=True;o=apply_source(o,src)
    options="".join(f'<option {"selected" if o.get("offer_type")==k else ""}>{k}</option>' for k in TYPES);benefits="\n".join(o.get("benefits",[]));steps="\n".join(o.get("next_steps",[]))
    body=f'''<div class="back"><a href="{ingress('offer/'+oid)}">← Zurück zum Angebot</a></div><div class="card"><div class="eyebrow">Angebot bearbeiten</div><h1>Kundendarstellung</h1><p class="muted">Billomat-Preise und Positionen bleiben unverändert. Hier bearbeiten Sie nur die Präsentation.</p><form method="post"><div class="field"><label>Angebotstyp</label><select name="offer_type">{options}</select></div><div class="field"><label>Kundentitel</label><input name="customer_title" value="{clean(o.get('customer_title'))}"></div><div class="field"><label>Einleitung</label><textarea name="customer_intro">{clean(o.get('customer_intro'))}</textarea></div><div class="field"><label>Projekt auf einen Blick</label><textarea name="project_summary">{clean(o.get('project_summary'))}</textarea></div><div class="field"><label>Ihre Vorteile · ein Vorteil pro Zeile</label><textarea name="benefits">{clean(benefits)}</textarea></div><div class="field"><label>Nächste Schritte · ein Schritt pro Zeile</label><textarea name="next_steps">{clean(steps)}</textarea></div><button class="btn" type="submit">Speichern</button><a class="btn light" href="{ingress('offer/'+oid)}">Abbrechen</a></form></div>'''
    return base("Angebot bearbeiten",body)

def detail(o):
    rows="".join(f'<tr><td>{clean(i["position"])}</td><td><b>{clean(i["title"])}</b><br><span class="muted small">{clean(i["description"])}</span></td><td>{clean(i["quantity"])} {clean(i["unit"])}</td><td class="money">{money(i["unit_price"])}</td><td class="money">{money(i["total_net"])}</td></tr>' for i in o["items"]);checks="".join(f'<span class="check">✓ {clean(x)}</span>' for x in o.get("benefits",[]));steps="".join(f'<li>{clean(x)}</li>' for x in o.get("next_steps",[]));c=o["client"]
    body=f'''<div class="back"><a href="{ingress('offers')}">← Zurück zur Angebotsübersicht</a></div><div class="card hero"><div class="eyebrow">{clean(o.get("offer_type"))} · Ihr persönliches Angebot</div><h1>{clean(o.get("customer_title") or o.get("title"))}</h1><p>{clean(o.get("customer_intro"))}</p><a class="btn" href="{ingress('offer/'+str(o['id'])+'/edit')}">Angebot bearbeiten</a><a class="btn dark" href="{ingress('offer/'+str(o['id'])+'/pdf')}">A4-PDF erzeugen</a></div><div class="grid"><div class="metric"><div class="label">Kunde</div><div class="value" style="font-size:18px">{clean(cname(c))}</div><div class="muted small">{clean(c.get('street',''))}<br>{clean(c.get('zip',''))} {clean(c.get('city',''))}</div></div><div class="metric"><div class="label">Angebot</div><div class="value" style="font-size:18px">Nr. {clean(o.get('offer_number') or o.get('number'))}</div><div class="muted small">Datum: {clean(o.get('date'))}<br>Gültig: {clean(o.get('validity_date') or o.get('validity_days'))}</div></div><div class="metric green"><div class="label">Ihr Festpreis</div><div class="value">{money(o.get('total_gross'))}</div><div class="muted small">Netto {money(o.get('total_net'))}</div></div></div><div class="card"><h2>Projekt auf einen Blick</h2><p>{clean(o.get('project_summary'))}</p></div><div class="card"><h2>Leistungsumfang</h2><table><thead><tr><th>Pos.</th><th>Leistung / Artikel</th><th>Menge</th><th>Einzelpreis</th><th>Netto</th></tr></thead><tbody>{rows}</tbody></table></div><div class="card"><h2>Ihre Vorteile</h2><div class="checks">{checks}</div></div><div class="card"><h2>Nächste Schritte</h2><ol>{steps}</ol></div><div class="card"><h2>Kostenübersicht</h2><div class="grid"><div class="metric"><div class="label">Netto</div><div class="value">{money(o.get('total_net'))}</div></div><div class="metric"><div class="label">MwSt.</div><div class="value">{money(o.get('tax_amount'))}</div></div><div class="metric green"><div class="label">Gesamt</div><div class="value">{money(o.get('total_gross'))}</div></div></div></div>'''
    return base("FTST Angebot",body)

def footer(canvas,doc):
    canvas.saveState();w,_=A4;canvas.setFont("Helvetica",7.5);canvas.setFillColor(MUTED);canvas.drawString(18*mm,9*mm,"FT Sicherheitstechnik · Professionelle Sicherheitstechnik");canvas.drawRightString(w-18*mm,9*mm,f"Seite {doc.page}");canvas.setStrokeColor(BORDER);canvas.line(18*mm,13*mm,w-18*mm,13*mm);canvas.restoreState()

def make_pdf(o):
    styles=getSampleStyleSheet();body=ParagraphStyle("body",parent=styles["BodyText"],fontSize=9.5,leading=14,textColor=TEXT);small=ParagraphStyle("small",parent=body,fontSize=7.8,leading=10,textColor=MUTED);h1=ParagraphStyle("h1",parent=styles["Title"],fontName="Helvetica-Bold",fontSize=25,leading=29,textColor=DARK);h2=ParagraphStyle("h2",parent=styles["Heading2"],fontSize=16,leading=19,textColor=DARK);red=ParagraphStyle("red",parent=small,fontName="Helvetica-Bold",textColor=RED);right=ParagraphStyle("right",parent=body,alignment=TA_RIGHT);brand=ParagraphStyle("brand",parent=body,fontName="Helvetica-Bold",fontSize=15,textColor=WHITE);green=ParagraphStyle("green",parent=body,fontName="Helvetica-Bold",fontSize=16,textColor=GREEN)
    o=normalize(o);c=o["client"];buf=io.BytesIO();doc=SimpleDocTemplate(buf,pagesize=A4,leftMargin=18*mm,rightMargin=18*mm,topMargin=18*mm,bottomMargin=19*mm);story=[]
    header=Table([[Paragraph("FT SICHERHEITSTECHNIK",brand),""]],colWidths=[120*mm,50*mm]);header.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),DARK),("BOTTOMPADDING",(0,0),(-1,-1),7*mm),("TOPPADDING",(0,0),(-1,-1),7*mm),("LINEBELOW",(0,0),(-1,0),3*mm,RED)]));story += [header,Spacer(1,10*mm),Paragraph("IHR PERSÖNLICHES ANGEBOT",red),Paragraph(clean(o.get("customer_title") or o.get("title") or "Individuelle Sicherheitslösung"),h1),Paragraph(clean(o.get("customer_intro") or "Professionelle Sicherheitstechnik."),body),Spacer(1,7*mm)]
    customer_data=[[Paragraph("KUNDE",red),Paragraph("ANGEBOT",red)],[Paragraph(f"<b>{clean(cname(c))}</b><br>{clean(c.get('street',''))}<br>{clean(c.get('zip',''))} {clean(c.get('city',''))}",body),Paragraph(f"<b>Nr. {clean(o.get('offer_number') or o.get('number'))}</b><br>Datum: {clean(o.get('date'))}<br>Gültig: {clean(o.get('validity_date') or o.get('validity_days'))}",body)]]
    customer=Table(customer_data,colWidths=[82*mm,88*mm]);customer.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),LIGHT),("BOX",(0,0),(-1,-1),0.5,BORDER),("INNERGRID",(0,0),(-1,-1),0.5,BORDER),("LEFTPADDING",(0,0),(-1,-1),4*mm),("RIGHTPADDING",(0,0),(-1,-1),4*mm),("TOPPADDING",(0,0),(-1,-1),4*mm),("BOTTOMPADDING",(0,0),(-1,-1),4*mm)]));story += [customer,Spacer(1,7*mm)]
    stats=Table([[Paragraph("NETTO",red),Paragraph("MWST.",red),Paragraph("IHR FESTPREIS",red)],[Paragraph(money(o.get("total_net")),body),Paragraph(money(o.get("tax_amount")),body),Paragraph(money(o.get("total_gross")),green)]],colWidths=[56*mm,56*mm,58*mm]);stats.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),LIGHT),("BACKGROUND",(2,0),(2,1),GREEN_LIGHT),("BOX",(0,0),(-1,-1),0.5,BORDER),("LEFTPADDING",(0,0),(-1,-1),4*mm),("TOPPADDING",(0,0),(-1,-1),4*mm),("BOTTOMPADDING",(0,0),(-1,-1),5*mm)]));story += [stats,Spacer(1,8*mm),Paragraph("01 · IHR PROJEKT AUF EINEN BLICK",red),Paragraph("Das haben wir für Sie zusammengestellt.",h2),Paragraph(clean(o.get("project_summary")),body),PageBreak(),Paragraph("02 · IHRE FESTPREIS-LEISTUNG",red),Paragraph("Ein Preis. Alles drin.",h1)]
    rows=[[Paragraph("POS.",small),Paragraph("LEISTUNG / ARTIKEL",small),Paragraph("MENGE",small),Paragraph("PREIS",small),Paragraph("NETTO",small)]]
    for i in o["items"]:rows.append([Paragraph(str(i["position"]),body),Paragraph(f"<b>{clean(i['title'])}</b><br><font color='#6F6F6F'>{clean(i['description'])}</font>",body),Paragraph(f"{clean(i['quantity'])} {clean(i['unit'])}",body),Paragraph(money(i["unit_price"]),right),Paragraph(money(i["total_net"]),right)])
    tbl=Table(rows,colWidths=[12*mm,84*mm,22*mm,27*mm,30*mm],repeatRows=1);tbl.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),DARK),("TEXTCOLOR",(0,0),(-1,0),WHITE),("GRID",(0,0),(-1,-1),0.3,BORDER),("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),2.5*mm),("RIGHTPADDING",(0,0),(-1,-1),2.5*mm),("TOPPADDING",(0,0),(-1,-1),3*mm),("BOTTOMPADDING",(0,0),(-1,-1),3*mm)]));story += [tbl,Spacer(1,8*mm),Paragraph("Ihre Vorteile",h2),Paragraph(" · ".join(str(x) for x in o.get("benefits",[])),body),PageBreak(),Paragraph("03 · NÄCHSTE SCHRITTE",red),Paragraph("So geht es weiter.",h1),Paragraph("<br>".join(f"{n}. {clean(x)}" for n,x in enumerate(o.get("next_steps",[]),1)),body),Spacer(1,10*mm),Paragraph("Vielen Dank für Ihr Vertrauen in FT Sicherheitstechnik.",h2)];doc.build(story,onFirstPage=footer,onLaterPages=footer);buf.seek(0);return buf

@app.get("/offer/<oid>/pdf")
def offer_pdf(oid):
    try:return send_file(make_pdf(get_offer(oid)),mimetype="application/pdf",as_attachment=False,download_name=f"FTST-Angebot-{oid}.pdf")
    except Exception as e:
        log.exception("PDF generation failed");return base("PDF Fehler",f'<div class="back"><a href="{ingress("offer/"+oid)}">← Zurück zum Angebot</a></div><div class="card"><h1>PDF konnte nicht erstellt werden</h1><p>{clean(e)}</p></div>'),500

if __name__=="__main__":app.run(host="0.0.0.0",port=int(os.getenv("PORT","8099")))
