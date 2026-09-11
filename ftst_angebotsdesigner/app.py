import os, io
from flask import Flask, request, send_file, abort
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from billomat_client import BillomatClient

APP_VERSION = "0.1.9"

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "ftst-dev")

CSS = '''body{font-family:Arial,sans-serif;background:#f4f4f4;margin:0;color:#171717}.wrap{max-width:1100px;margin:30px auto;padding:0 20px}.head{background:#111;color:#fff;padding:25px 30px;border-bottom:6px solid #d71920}.logo{font-size:28px;font-weight:800}.muted{color:#777}.card{background:#fff;border-radius:12px;padding:24px;margin:18px 0;box-shadow:0 3px 14px #0001}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px}.stat{background:#f7f7f7;padding:18px;border-radius:10px}.btn{display:inline-block;background:#d71920;color:white;padding:11px 17px;border-radius:7px;text-decoration:none;font-weight:bold}.btn.dark{background:#111}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:10px;border-bottom:1px solid #ddd}th{font-size:12px;text-transform:uppercase;color:#777}.price{text-align:right;font-size:24px;font-weight:800}.tag{display:inline-block;padding:5px 9px;border-radius:20px;background:#eee;font-size:12px}'''


def base(title, body):
    return f'''<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title><style>{CSS}</style></head><body><div class="head"><div class="wrap"><div class="logo">FT SICHERHEITSTECHNIK</div><div>FTST AngebotsDesigner</div></div></div><main class="wrap">{body}</main></body></html>'''


def ingress(path="/"):
    base = request.headers.get("X-Ingress-Path", "").strip().rstrip("/")
    return base + "/" + path.lstrip("/")


def money(v):
    try:
        return f"{float(v):,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "-"


def as_dict(value):
    return value if isinstance(value, dict) else {}


def as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        # Billomat may wrap a single tax/item in a dictionary.
        for key in ("tax", "item", "offer-item", "value"):
            if key in value:
                inner = value[key]
                return inner if isinstance(inner, list) else [inner]
        return [value]
    return []


def client_name(c):
    c = as_dict(c)
    return c.get("name") or c.get("company") or "Kunde"


def normalize_offer(o):
    o = as_dict(o).copy()
    o["client"] = as_dict(o.get("client"))
    o["items"] = as_list(o.get("items"))
    o["taxes"] = as_list(o.get("taxes"))
    o["tax_amount"] = sum(
        float(as_dict(t).get("amount", 0) or 0)
        for t in o["taxes"]
    )
    return o


def detail(o):
    o = normalize_offer(o)
    c = o["client"]
    items = o["items"]
    rows = "".join(
        f'''<tr><td>{i.get("position", "")}</td><td><b>{i.get("title", "")}</b><br><span class="muted">{i.get("description", "") or ""}</span></td><td>{i.get("quantity", "")} {i.get("unit", "")}</td><td>{money(i.get("unit_price"))}</td><td>{money(i.get("total_net"))}</td></tr>'''
        for i in items if isinstance(i, dict)
    )
    body = f'''<div class="card"><a class="btn dark" href="{ingress('offers')}">← Angebote</a> <a class="btn" href="{ingress('offer/'+str(o.get('id'))+'/pdf')}">A4 PDF erzeugen</a></div><div class="card"><h1>Ihr persönliches Angebot</h1><p class="muted">Professionelles FTST-Angebot auf Basis von Billomat</p><div class="grid"><div class="stat"><b>Kunde</b><br>{client_name(c)}<br>{c.get('street','')}<br>{c.get('zip','')} {c.get('city','')}</div><div class="stat"><b>Angebot</b><br>Nr. {o.get('offer_number') or o.get('number','-')}<br>Datum: {o.get('date','-')}<br>Gültig bis: {o.get('validity_date','-')}</div><div class="stat"><b>Status</b><br><span class="tag">{o.get('status','-')}</span></div></div></div><div class="card"><h2>{o.get('title') or 'Projektübersicht'}</h2><p>{o.get('intro') or 'Ihre individuelle Lösung von FT Sicherheitstechnik.'}</p><table><thead><tr><th>Pos.</th><th>Leistung / Artikel</th><th>Menge</th><th>Einzelpreis</th><th>Netto</th></tr></thead><tbody>{rows}</tbody></table></div><div class="card"><div class="grid"><div class="stat"><b>Netto</b><div class="price">{money(o.get('total_net'))}</div></div><div class="stat"><b>MwSt.</b><div class="price">{money(o.get('tax_amount'))}</div></div><div class="stat"><b>Gesamt</b><div class="price">{money(o.get('total_gross'))}</div></div></div></div>'''
    return base("FTST Angebot", body)


@app.get("/health")
def health():
    return {"ok": True, "version": APP_VERSION}


@app.get("/")
def index():
    body = f'''<div class="card"><h1>FTST AngebotsDesigner</h1><p>Billomat-Angebote importieren, prüfen und als professionelles FTST-A4-Angebot ausgeben.</p><div class="grid"><a class="btn" href="{ingress('offers')}">Angebote öffnen</a><a class="btn dark" href="{ingress('demo')}">Demo ansehen</a></div></div>'''
    return base("FTST AngebotsDesigner", body)


@app.get("/offers")
def offers():
    bid = os.getenv("BILLOMAT_ID")
    key = os.getenv("BILLOMAT_API_KEY")
    if not bid or not key:
        return base("Billomat", '<div class="card"><h1>Billomat nicht konfiguriert</h1><p>Bitte Billomat-ID und API-Key in der Home-Assistant-App konfigurieren.</p></div>')
    try:
        data = BillomatClient(bid, key).list_offers(request.args.get("search", ""))
    except Exception as e:
        return base("Billomat Fehler", f'<div class="card"><h1>Billomat-Fehler</h1><p>{e}</p></div>'), 502
    rows = "".join(
        f'<tr><td>{o.get("offer_number") or o.get("number","")}</td><td>{o.get("date","")}</td><td>{o.get("title","")}</td><td>{money(o.get("total_gross"))}</td><td><a class="btn" href="{ingress("offer/"+str(o.get("id")))}">Öffnen</a></td></tr>'
        for o in data if isinstance(o, dict)
    )
    return base("Angebote", f'<div class="card"><h1>Billomat-Angebote</h1><p class="muted">Neueste Angebote zuerst · {len(data)} geladen</p><table><thead><tr><th>Nr.</th><th>Datum</th><th>Titel</th><th>Brutto</th><th></th></tr></thead><tbody>{rows}</tbody></table></div>')


@app.get("/offer/<offer_id>")
def offer(offer_id):
    bid = os.getenv("BILLOMAT_ID")
    key = os.getenv("BILLOMAT_API_KEY")
    if not bid or not key:
        abort(503)
    try:
        o = BillomatClient(bid, key).get_full_offer(offer_id)
    except Exception as e:
        return base("Fehler", f'<div class="card"><h1>Fehler</h1><p>{e}</p></div>'), 502
    return detail(o)


@app.get("/demo")
def demo():
    o = {"id":"demo","offer_number":"26-79","date":"12.06.2026","validity_date":"26.06.2026","status":"draft","title":"Videoüberwachung – Pasa Firin","intro":"Professionelle IP-Videoüberwachung mit KI-Personen-/Fahrzeugerkennung.","total_net":6452.40,"total_gross":7678.36,"taxes":[{"amount":1225.96}],"client":{"name":"Pasa Firin","street":"G2 9","zip":"68159","city":"Mannheim"},"items":[{"position":1,"title":"8MP Domekamera","description":"2.8mm · Tag/Nacht · KI Person/Fahrzeug","quantity":16,"unit":"Stk.","unit_price":298,"total_net":4768},{"position":2,"title":"16-Kanal NVR","description":"AI-Aufzeichnung","quantity":1,"unit":"Stk.","unit_price":900,"total_net":900},{"position":3,"title":"24-Port PoE Switch","quantity":1,"unit":"Stk.","unit_price":222,"total_net":222},{"position":4,"title":"Techniker","quantity":4,"unit":"Std.","unit_price":85,"total_net":340},{"position":5,"title":"Helfer","quantity":4,"unit":"Std.","unit_price":35,"total_net":140}]}
    return detail(o)


def make_pdf(o):
    o = normalize_offer(o)
    out = io.BytesIO()
    p = canvas.Canvas(out, pagesize=A4)
    w, h = A4
    p.setFillColorRGB(.08, .08, .08)
    p.rect(0, h-35*mm, w, 35*mm, fill=1, stroke=0)
    p.setFillColorRGB(1, 1, 1)
    p.setFont("Helvetica-Bold", 19)
    p.drawString(20*mm, h-18*mm, "FT SICHERHEITSTECHNIK")
    p.setFillColorRGB(.84, .05, .08)
    p.rect(0, h-38*mm, w, 3*mm, fill=1, stroke=0)
    p.setFillColorRGB(.1, .1, .1)
    p.setFont("Helvetica-Bold", 24)
    p.drawString(20*mm, h-58*mm, "Ihr persönliches Angebot")
    y = h-72*mm
    p.setFont("Helvetica", 10)
    p.setFillColorRGB(.2, .2, .2)
    c = o["client"]
    p.drawString(20*mm, y, client_name(c))
    p.drawString(20*mm, y-5*mm, f"{c.get('street','')} · {c.get('zip','')} {c.get('city','')}")
    p.drawRightString(w-20*mm, y, f"Angebot {o.get('offer_number') or o.get('number','-')}")
    p.drawRightString(w-20*mm, y-5*mm, f"Datum {o.get('date','-')}")
    y -= 18*mm
    p.setFont("Helvetica-Bold", 14)
    p.drawString(20*mm, y, o.get('title') or 'Projektübersicht')
    y -= 8*mm
    p.setFont("Helvetica", 10)
    intro = (o.get('intro') or '').replace('\n', ' ')
    if intro:
        p.drawString(20*mm, y, intro[:115])
    y -= 12*mm
    p.setFont("Helvetica-Bold", 9)
    p.drawString(20*mm, y, "Pos.")
    p.drawString(35*mm, y, "Leistung / Artikel")
    p.drawString(125*mm, y, "Menge")
    p.drawString(150*mm, y, "Einzelpreis")
    p.drawRightString(w-20*mm, y, "Netto")
    y -= 5*mm
    p.line(20*mm, y, w-20*mm, y)
    y -= 7*mm
    p.setFont("Helvetica", 9)
    for i in o["items"]:
        if not isinstance(i, dict):
            continue
        title = str(i.get('title',''))
        desc = str(i.get('description','') or '')
        p.drawString(20*mm, y, str(i.get('position','')))
        p.drawString(35*mm, y, title[:50])
        p.drawString(125*mm, y, f"{i.get('quantity','')} {i.get('unit','')}")
        p.drawString(150*mm, y, money(i.get('unit_price')))
        p.drawRightString(w-20*mm, y, money(i.get('total_net')))
        y -= 8*mm
        if desc:
            p.setFont('Helvetica', 7)
            p.drawString(35*mm, y, desc[:75])
            p.setFont('Helvetica', 9)
            y -= 6*mm
        if y < 35*mm:
            p.showPage()
            y = h-25*mm
    y -= 4*mm
    p.line(120*mm, y, w-20*mm, y)
    y -= 8*mm
    p.setFont("Helvetica-Bold", 11)
    p.drawString(120*mm, y, "Netto")
    p.drawRightString(w-20*mm, y, money(o.get('total_net')))
    y -= 7*mm
    p.drawString(120*mm, y, "MwSt.")
    p.drawRightString(w-20*mm, y, money(o.get('tax_amount')))
    y -= 7*mm
    p.drawString(120*mm, y, "Gesamt")
    p.drawRightString(w-20*mm, y, money(o.get('total_gross')))
    p.setFont('Helvetica', 7)
    p.drawString(20*mm, 12*mm, "FT Sicherheitstechnik · Professionelle Sicherheitstechnik")
    p.save()
    out.seek(0)
    return out


@app.get("/offer/<offer_id>/pdf")
def offer_pdf(offer_id):
    if offer_id == 'demo':
        o = {"offer_number":"26-79","date":"12.06.2026","title":"Videoüberwachung – Pasa Firin","total_net":6452.40,"total_gross":7678.36,"taxes":[{"amount":1225.96}],"client":{"name":"Pasa Firin","street":"G2 9","zip":"68159","city":"Mannheim"},"items":[]}
    else:
        bid = os.getenv('BILLOMAT_ID')
        key = os.getenv('BILLOMAT_API_KEY')
        if not bid or not key:
            abort(503)
        try:
            o = BillomatClient(bid, key).get_full_offer(offer_id)
        except Exception as e:
            return base("Fehler", f'<div class="card"><h1>PDF konnte nicht erstellt werden</h1><p>{e}</p></div>'), 502
    return send_file(make_pdf(o), mimetype='application/pdf', as_attachment=False, download_name=f"FTST-Angebot-{o.get('offer_number') or o.get('number','')}.pdf")


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT','8099')))
