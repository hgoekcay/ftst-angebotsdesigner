import io, os, html, logging, re
from flask import Flask, request, send_file, abort, session, redirect
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from billomat_client import BillomatClient
from asset_library import DEFAULT_LOGO
import materials
import projects
import project_intake
import montage
import quote_drafts
import quote_presentation
import inventory_views
import customers
import ai_status
import mail_assistant
import strato_views
import billomat_receipts
import offer_cache
import offer_followup
import offer_delivery
import offer_mail
import offer_chat
import quote_transfer
from price_notes import item_notes, offer_notes, unit_price_heading
from reportlab.platypus import Image
from storage import OfferStore, StorageError, data_directory

APP_VERSION = "0.24.0"
app = Flask(__name__)
app.config['CHAT_ASSET_VERSION'] = APP_VERSION
app.secret_key = os.getenv("FLASK_SECRET", "ftst-dev")
log = logging.getLogger("ftst.app")
app.config['FTST_DATA_DIR'] = str(data_directory())


@app.get('/ui-assets/<version>/<filename>')
def versioned_ui_asset(version, filename):
    if version != APP_VERSION or filename not in {'offer-delivery.js', 'pdf-download.js', 'offer-chat.js'}:
        abort(404)
    response = send_file(os.path.join(app.root_path, 'static', filename),
                         mimetype='application/javascript; charset=utf-8', conditional=False)
    response.headers['Cache-Control'] = 'no-store, max-age=0'
    return response


@app.before_request
def enforce_ingress_peer():
    # Production is reachable only through HA Ingress. Forwarding headers are not authentication.
    if os.getenv('FTST_REQUIRE_INGRESS') == '1' and request.remote_addr != '172.30.32.2':
        abort(403)


def offer_store():
    return OfferStore(app.config['FTST_DATA_DIR'])


@app.errorhandler(StorageError)
def storage_error(error):
    log.error('Persistent storage unavailable: %s', error)
    return base('Speicherung nicht verfügbar', '<div class="card"><h1>Speicherung nicht verfügbar</h1><p>' + clean(error) + '</p><p>Bitte über die Zurück-Funktion des Browsers zu Ihren Eingaben zurückkehren.</p></div>'), 503

@app.errorhandler(409)
@app.errorhandler(400)
def quote_input_error(error):
    if request.endpoint not in ('quote_draft', 'quote_pdf', 'quote_presentation', 'quote_transfer'):
        return error
    key = (request.view_args or {}).get('key', '')
    back = ingress('projects/' + key + '/quote')
    body = ('<div class="card"><div class="eyebrow">Angebotsentwurf</div>'
            '<h1>Bitte Entwurf prüfen</h1><p role="alert">' + clean(error.description) +
            '</p><p>Bei ungespeicherten Eingaben zuerst mit der Browser-Zurück-Funktion zum Formular zurückkehren.</p>'
            '<a class="btn" href="' + back + '">Gespeicherten Entwurf öffnen</a></div>')
    return base('Entwurf prüfen', body), error.code


RED=colors.HexColor("#D71920"); DARK=colors.HexColor("#111111"); TEXT=colors.HexColor("#202020")
MUTED=colors.HexColor("#6F6F6F"); LIGHT=colors.HexColor("#F4F4F4"); BORDER=colors.HexColor("#DCDCDC")
GREEN=colors.HexColor("#218838"); GREEN_LIGHT=colors.HexColor("#EAF6EE"); WHITE=colors.white

CSS='body{margin:0;font-family:Arial,Helvetica,sans-serif;background:#ececec;color:#222}.top{background:#111;color:#fff;border-bottom:5px solid #d71920}.topin{max-width:1180px;margin:auto;padding:22px;display:flex;justify-content:space-between;align-items:center}.brand{font-size:22px;font-weight:800}.sub,.small{font-size:12px;opacity:.75}.wrap{max-width:1180px;margin:28px auto;padding:0 18px}.card{background:#fff;border-radius:14px;padding:26px;margin-bottom:18px;box-shadow:0 5px 20px #00000012}.hero h1{font-size:34px;margin:8px 0}.eyebrow{color:#d71920;font-size:12px;font-weight:800;text-transform:uppercase;letter-spacing:1px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px}.metric{background:#f4f4f4;padding:18px;border-radius:12px}.metric.green{background:#eaf6ee}.metric .label{font-size:11px;color:#707070;text-transform:uppercase}.metric .value{font-size:22px;font-weight:800;margin-top:4px}.metric.green .value{color:#218838}.btn{display:inline-block;background:#d71920;color:#fff;text-decoration:none;padding:11px 17px;border-radius:8px;font-weight:700;margin-right:6px;border:0;cursor:pointer}.btn.dark{background:#111}.btn.light{background:#eee;color:#111}label{display:block;font-size:11px;color:#707070;text-transform:uppercase;font-weight:700;margin:0 0 6px}input,select,textarea{width:100%;box-sizing:border-box;padding:11px;border:1px solid #d5d5d5;border-radius:8px;font:inherit}.field{margin-bottom:16px}textarea{min-height:110px}table{width:100%;border-collapse:collapse}th,td{padding:11px 8px;border-bottom:1px solid #e8e8e8;text-align:left;vertical-align:top}th{font-size:11px;color:#707070;text-transform:uppercase}.money{text-align:right;font-weight:800}.muted{color:#707070}.small{font-size:12px}.checks{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}.check{background:#eaf6ee;color:#218838;padding:10px;border-radius:8px;font-weight:700;font-size:12px}.back{margin-bottom:16px}.back a{color:#111;text-decoration:none;font-weight:700}.back a:hover{color:#d71920}.success{background:#eaf6ee;color:#218838;border:1px solid #b9dfc5;padding:13px 16px;border-radius:10px;font-weight:700;margin-bottom:18px}.success span{color:#17682b;font-weight:800}.auto{display:inline-block;background:#eef3f7;color:#425466;border-radius:999px;padding:5px 9px;font-size:11px;font-weight:700;margin-left:8px}'

CSS += """
body{background:#f5f6f7;color:#15191c;font-family:Segoe UI,Arial,sans-serif;font-size:15px;line-height:1.55}
.top{background:#fff;color:#15191c;border-bottom:1px solid #e1e4e6;padding:20px 0}
.topin{max-width:1180px;margin:auto;padding:0 32px;gap:20px;display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between}
.app-brand{width:300px;max-width:100%;flex:0 1 300px}.app-logo{display:block;width:300px;max-width:100%;height:auto;background:white}
.sub{color:#72797f;font-size:10px;letter-spacing:2px;text-transform:uppercase;margin:7px 0 0}
.appnav{display:flex;flex-wrap:wrap;align-items:center;gap:24px}.appnav a{color:#525a61;text-decoration:none;font-size:13px;font-weight:600}.appnav a:hover{color:#e30613}.appnav span{color:#879096}
.wrap{max-width:1180px;padding:36px 32px 70px;margin:auto}
.card{background:#fff;border:1px solid #e2e5e7;border-radius:12px;padding:30px;box-shadow:none;margin-bottom:22px}
.hero{padding:44px;background:white;border-top:3px solid #e30613}
.hero h1{max-width:780px;font-size:36px;line-height:1.16;letter-spacing:-1.1px;font-weight:650;margin:14px 0 20px}
.hero p{max-width:760px;color:#626a70;font-size:16px;line-height:1.7;margin-bottom:26px}
h1{font-size:30px;letter-spacing:-.7px;line-height:1.2}h2{font-size:22px;letter-spacing:-.35px;margin:0 0 18px}
.eyebrow{color:#e30613;font-size:11px;letter-spacing:1.5px;text-transform:uppercase;font-weight:650}
.btn{border-radius:6px;padding:11px 18px;background:#e30613;color:white;font-size:13px;box-shadow:none;margin:6px 8px 0 0;display:inline-block;text-decoration:none}.btn.light{background:#fff;color:#343c43;border:1px solid #dbe0e3}.btn.dark{background:#15191c}
.grid{gap:22px}.metric{background:#fff;border:1px solid #e1e4e6;border-radius:10px;padding:24px}.metric.green{background:#eff8f2;border-color:#d5e9dc;color:#0d7d3b}.metric .label{font-size:10px;letter-spacing:1px;color:#72797f}.metric .value{font-size:30px;letter-spacing:-.5px;margin:7px 0}
th{background:#f6f7f8;color:#697178;font-size:10px;letter-spacing:.65px}td,th{padding:15px 12px;border-bottom:1px solid #e6e9eb}tbody tr:hover{background:#fafbfb}
input,textarea,select{border:1px solid #d9dee1;border-radius:6px;background:#fff;padding:12px;color:#15191c}input:focus,textarea:focus,select:focus{outline:2px solid #f3bbc0;outline-offset:1px}
.check{background:#f0f8f3;border:1px solid #e0eee5;border-radius:6px;padding:16px}.back{font-size:13px;margin-bottom:22px}.muted{color:#72797f}
*,*::before,*::after{box-sizing:border-box}
.topin>*,.grid>*,.card,form{min-width:0}
img,video,audio{max-width:100%}input,select,textarea{min-width:0;max-width:100%}
.card{overflow-wrap:anywhere}input[type=checkbox],input[type=radio]{width:22px!important;height:22px;vertical-align:middle;margin:0 8px 0 0;flex-shrink:0}
@media screen and (max-width:700px){
 .topin{padding:0 16px;flex-wrap:wrap;gap:14px}.appnav{width:100%;gap:4px 16px;flex-wrap:wrap}.appnav a{min-height:44px;display:flex;align-items:center;font-size:14px}
 .wrap{padding:18px 12px 36px}.hero,.card{padding:18px}.hero h1{font-size:28px}h1{font-size:26px}h2{font-size:22px}.grid,.checks{grid-template-columns:minmax(0,1fr)}
 .btn{display:block;width:100%;min-height:46px;margin:10px 0 0;text-align:center;white-space:normal;overflow-wrap:anywhere;font-size:16px;line-height:1.4}
 input,select,textarea{font-size:16px;min-height:46px}input[type=checkbox],input[type=radio]{min-height:22px}label{font-size:12px;line-height:1.6}label:has(input[type=checkbox]),label:has(input[type=radio]){padding:10px 0;min-height:44px}
 table,thead,tbody,tfoot,tr,td,th{display:block;width:100%;min-width:0;max-width:100%}
 thead,tr:has(>th):not(:has(>td)){position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%)}
 tr{border:1px solid #dfe4e7;border-radius:8px;margin:14px 0;padding:8px 12px}td,th{padding:9px 0;border:0;text-align:left;white-space:normal}
 td+td{border-top:1px solid #eef0f2}td[data-label]::before{content:attr(data-label);display:block;color:#697178;font-size:12px;font-weight:700;letter-spacing:.3px;margin-bottom:4px}
 td.money{text-align:left}td label{margin-bottom:6px}.card ul,.card ol{padding-left:22px}.metric{padding:18px}
 .material-grid{grid-template-columns:minmax(0,1fr)!important}.material-actions{position:static!important}
}
"""

TYPES={
 "Videoüberwachung":("Professionelle Videoüberwachung für Ihr Objekt","Moderne IP-Videoüberwachung mit professioneller Aufzeichnung und Fernzugriff.","Auf Ihr Objekt abgestimmte Videoüberwachung inklusive Montage, Konfiguration, Prüfung und Einweisung.",["Hochauflösende Kameras","Intelligente Erkennung","Professionelle Aufzeichnung","Fernzugriff per App"]),
 "Alarmanlage":("Professionelle Alarmtechnik für Ihr Objekt","Zuverlässige Einbruchmeldetechnik mit moderner Alarmierung.","Objektbezogen geplant, fachgerecht montiert, eingerichtet und getestet.",["Schnelle Alarmierung","App-Steuerung","Sabotageschutz","Erweiterbar"]),
 "Rauchmeldeanlage":("Professionelle Rauchmeldeanlage für Ihr Objekt","Frühzeitige Erkennung von Rauch, Hitze und – je nach Melder – Kohlenmonoxid.","Auf Ihr Objekt abgestimmte Rauchmelderlösung inklusive Montage, Einrichtung, Prüfung und Einweisung.",["Frühzeitige Warnung","Vernetzte Melder","Lokale Alarmierung","Erweiterbar"]),
 "Brandwarnanlage":("Professionelle Brandwarnanlage für Ihr Objekt","Strukturierte Brandwarnung für ausgewählte Gebäude und Nutzungskonzepte.","Objektbezogen geplante Brandwarnlösung mit abgestimmter Detektion, Alarmierung, Prüfung und Einweisung.",["Frühe Detektion","Strukturierte Alarmierung","Dokumentierte Prüfung","Erweiterbar"]),
 "Zutrittskontrolle":("Sichere Zutrittskontrolle für Ihr Objekt","Kontrollieren Sie zuverlässig, wer Ihr Gebäude betreten darf.","Komplett eingerichtete Zutrittslösung mit Rechteverwaltung und Übergabe.",["RFID / Code / App","Zutrittsrechte","Protokollierung","Erweiterbar"]),
 "Türsprechanlage":("Moderne Video-Türsprechanlage","Sehen und sprechen Sie mit Besuchern vor Ort oder per Smartphone.","Lieferung, Montage, Konfiguration und betriebsbereite Übergabe.",["Video & Audio","Smartphone-Anbindung","Außentauglich","Einfache Bedienung"]),
 "Smart Home":("Smarte Sicherheit und Gebäudeautomation","Sicherheit, Komfort und intelligente Steuerung.","Abgestimmte, einfach bedienbare und erweiterbare Gesamtlösung.",["Zentrale Steuerung","App-Anbindung","Automationen","Erweiterbar"]),
 "Kombination":("Ihre individuelle Sicherheitslösung","Mehrere Sicherheitssysteme werden zu einer abgestimmten Gesamtlösung.","Koordinierte Planung und vollständig konfigurierte Gesamtlösung.",["Ganzheitliche Planung","Ein Ansprechpartner","Abgestimmte Systeme","Erweiterbar"])
}
DEFAULT_STEPS=["Angebot prüfen und bestätigen","Installationstermin abstimmen","Montage, Konfiguration und Inbetriebnahme","Übergabe und Einweisung"]

def ingress(path="/"):
    base=request.headers.get("X-Ingress-Path","").strip().rstrip("/")
    return base+"/"+path.lstrip("/")

def money(v):
    try:return f"{float(v):,.2f} €".replace(",","X").replace(".",",").replace("X",".")
    except:return "-"

def date_de(v):
    s=str(v or "")
    if re.match(r"^\d{4}-\d{2}-\d{2}$",s):
        y,m,d=s.split("-"); return f"{d}.{m}.{y}"
    return s

def one_list(v):
    if isinstance(v,list): return v
    if isinstance(v,dict):
        for k in ("tax","item","offer-item","value"):
            if k in v:return v[k] if isinstance(v[k],list) else [v[k]]
        return [v]
    return []

def clean(v): return "" if v is None or isinstance(v,(dict,list)) else html.escape(str(v))

def compact(v,limit=190):
    s=re.sub(r"\s+"," ",str(v or "")).strip()
    return s if len(s)<=limit else s[:limit].rsplit(" ",1)[0].rstrip(".,;:-")+" …"

def cname(c):
    c=c or {}
    for key in ("company","company_name","name"):
        val=str(c.get(key) or "").strip()
        if val and val.lower()!="kunde": return val
    full=(str(c.get("first_name") or c.get("firstname") or "")+" "+str(c.get("last_name") or c.get("lastname") or "")).strip()
    return full or "Kunde"

def normalize(o):
    o=dict(o or {}); o["client"]=o.get("client") if isinstance(o.get("client"),dict) else {}
    o['is_draft'] = bool(o.get('is_draft')) or o.get('status') == 'DRAFT'
    items=[]
    for n,x in enumerate(one_list(o.get("items")),1):
        if isinstance(x,dict):
            items.append({"position":x.get("position") or n,"title":x.get("title") or "Leistung","description":x.get("description") or "","quantity":x.get("quantity") or 0,"unit":x.get("unit") or "","unit_price":x.get("unit_price") or 0,"total_net":x.get("total_net") or 0,"optional":x.get("optional", 0),"reduction":x.get("reduction", "")})
    o["items"]=items
    o["tax_amount"]=sum(float(t.get("amount") or t.get("tax_amount") or 0) for t in one_list(o.get("taxes")) if isinstance(t,dict))
    return o

def _contains_any(text,words): return any(w in text for w in words)

def detect_offer_type(o):
    title_text=" ".join(str(o.get(k) or "") for k in ("title","label","intro")).lower()
    item_texts=[(str(i.get("title") or "")+" "+str(i.get("description") or "")).lower() for i in o.get("items",[])]
    all_text=" ".join([title_text]+item_texts)

    if _contains_any(all_text,["brandwarnanlage","brandwarnsystem"]) or re.search(r"\bbwa\b", all_text): return "Brandwarnanlage"
    kinds = set()

    for kind,words in {
      "Videoüberwachung":["videoüberwachung","überwachungskamera","ip-kamera","ip kamera","domekamera","bulletkamera","netzwerkkamera","nvr","videorekorder","guard live","guard station","uniview"],
      "Zutrittskontrolle":["zutrittskontrolle","zutrittsleser","kartenleser","rfid-leser","rfid leser","türcontroller","access control","transponderleser"],
      "Türsprechanlage":["türsprechanlage","video-türsprechanlage","videosprechanlage","intercom","türstation","innenstation"],
      "Smart Home":["smart home","smarthome","knx","gebäudeautomation","hausautomation"],
    }.items():
        if _contains_any(all_text,words): kinds.add(kind)

    intrusion=["motionprotect","doorprotect","glassprotect","homesiren","streetsiren","spacecontrol","keypad","bewegungsmelder","öffnungsmelder","glasbruch","einbruch","außensirene","innensirene"]
    fire=["fireprotect","rauchmelder","rauchwarnmelder","rauchwarn","hitzemelder","wärmemelder","co-sensor","kohlenmonoxid","co melder","co-melder","heat detector","smoke detector"]
    hubs=["hub/alarmzentrale","ajax hub","hub 2","hub plus","alarmzentrale","hub/zentrale","hub"]

    intrusion_hits=sum(1 for t in item_texts if _contains_any(t,intrusion))
    fire_hits=sum(1 for t in item_texts if _contains_any(t,fire))
    hub_hits=sum(1 for t in item_texts if _contains_any(t,hubs))

    if intrusion_hits>0: kinds.add("Alarmanlage")
    elif fire_hits>0 or _contains_any(all_text,["rauchmeldeanlage","rauchwarnanlage","rauchwarnsystem"]): kinds.add("Rauchmeldeanlage")
    if len(kinds)>1: return "Kombination"
    if kinds: return next(iter(kinds))
    if hub_hits>0: return "Kombination"

    scores={
      "Alarmanlage":sum(all_text.count(w) for w in ["alarm","einbruch","sirene","bewegungsmelder","öffnungsmelder"]),
      "Rauchmeldeanlage":sum(all_text.count(w) for w in fire),
      "Brandwarnanlage":sum(all_text.count(w) for w in ["brandwarn","bwa"]),
      "Videoüberwachung":sum(all_text.count(w) for w in ["kamera","video","rekorder","aufzeichnung"]),
      "Zutrittskontrolle":sum(all_text.count(w) for w in ["zutritt","rfid","transponder"]),
      "Türsprechanlage":sum(all_text.count(w) for w in ["sprech","klingel","intercom"]),
      "Smart Home":sum(all_text.count(w) for w in ["smart","automation","knx"]),
    }
    ranked=sorted(scores.items(),key=lambda x:x[1],reverse=True)
    return ranked[0][0] if ranked and ranked[0][1]>=2 else "Kombination"

def apply_source(raw,src):
    o=normalize(raw); manual_kind=str(src.get("offer_type") or "").strip()
    if manual_kind not in TYPES: manual_kind=""
    kind=manual_kind or detect_offer_type(o) or "Kombination"; p=TYPES.get(kind,TYPES["Kombination"])
    o["offer_type"]=kind; o["offer_type_auto"]=not bool(manual_kind)
    o["customer_title"]=src.get("customer_title") or p[0]
    o["customer_intro"]=src.get("customer_intro") or p[1]
    o["project_summary"]=src.get("project_summary") or p[2]
    o["benefits"]=[x.strip() for x in str(src.get("benefits","")).splitlines() if x.strip()] or p[3]
    o["next_steps"]=[x.strip() for x in str(src.get("next_steps","")).splitlines() if x.strip()] or DEFAULT_STEPS
    return o

def base(title,body):
    return f'<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title><style>{CSS}</style></head><body><div class="top"><div class="topin"><div class="app-brand"><a href="{ingress()}"><img class="app-logo" src="{ingress("materials/"+DEFAULT_LOGO)}" alt="FT Sicherheitstechnik ®"></a><div class="sub">FTST AngebotsDesigner</div></div><nav class="appnav"><a href="{ingress("chat")}">KI-Chat</a><a href="{ingress("offers")}">Angebote</a><a href="{ingress("projects")}">Projekte</a><a href="{ingress("inventory")}">Lager</a><a href="{ingress("customers")}">Kunden</a><a href="{ingress("materials")}">Bilder</a><a href="{ingress("company")}">Firma</a><span class="small">v{APP_VERSION}</span></nav></div></div><main class="wrap">{body}</main><script defer src="{ingress("ui-assets/"+APP_VERSION+"/pdf-download.js")}"></script></body></html>'

def get_offer(oid):
    bid=os.getenv("BILLOMAT_ID"); key=os.getenv("BILLOMAT_API_KEY")
    if not bid or not key: abort(503)
    raw = BillomatClient(bid,key).get_full_offer(oid)
    legacy_key = 'ftst_' + oid
    source = offer_store().load(bid.strip().lower(), oid, session.get(legacy_key))
    session.pop(legacy_key, None)
    return materials.enrich(apply_source(raw, source), offer_store())

@app.get("/health")
def health():
    try:
        offer_store().check()
        return {"ok":True,"version":APP_VERSION,"storage":"ok"}
    except StorageError:
        return {"ok":False,"version":APP_VERSION,"storage":"unavailable"}, 503

@app.get("/")
def index():
    return base("FTST",f'<div class="card hero"><div class="eyebrow">FTST AngebotsDesigner</div><h1>Professionelle Angebote aus Billomat</h1><a class="btn" style="background:#16803c" href="{ingress("chat")}">Mit dem KI-Chat erstellen</a><p>Billomat-Angebote auswählen, kundengerecht bearbeiten und als A4-PDF ausgeben.</p><a class="btn" href="{ingress("offers")}">Angebote öffnen</a><a class="btn light" href="{ingress("company")}">Firmendaten</a><a class="btn light" href="{ingress("materials")}">Fotos & Referenzen</a><a class="btn light" href="{ingress("projects")}">Projekte & Assistent</a><a class="btn light" href="{ingress("customers")}">Kunden finden & anlegen</a><a class="btn light" href="{ingress("billomat")}">Billomat-Daten laden</a><a class="btn light" href="{ingress("ai")}">Lokale KI prüfen</a><a class="btn light" href="{ingress("mail")}">Antwortassistent</a></div>')

@app.get("/offers")
def offers():
    bid=os.getenv("BILLOMAT_ID", "").strip(); key=os.getenv("BILLOMAT_API_KEY", "")
    if not bid or not key:
        return base("Billomat", '<div class="card"><h1>Billomat nicht konfiguriert</h1></div>')
    response = app.make_response(offer_cache.page(request, offer_store(), bid.lower(), BillomatClient(bid,key),
                                                 base, ingress, clean, money, date_de))
    response.headers['Cache-Control'] = 'no-store'
    return response

@app.get("/offer/<oid>")
def offer(oid): return detail(get_offer(oid))

@app.route("/offer/<oid>/edit",methods=["GET","POST"])
def edit(oid):
    o=get_offer(oid)
    if request.method=="POST":
        src={k:request.form.get(k,"") for k in ("offer_type","customer_title","customer_intro","project_summary","benefits","next_steps")}
        if src['offer_type'] and src['offer_type'] not in TYPES:
            abort(400, 'Unbekannter Angebotstyp')
        offer_store().save(os.environ['BILLOMAT_ID'].strip().lower(), oid, src)
        session.pop('ftst_' + oid, None)
        return redirect(ingress("offer/"+oid)+"?saved=1")
    options='<option value="" ' + ('selected' if o.get('offer_type_auto') else '') + '>Automatisch erkennen</option>'
    options+="".join(f'<option {"selected" if not o.get("offer_type_auto") and o.get("offer_type")==k else ""}>{k}</option>' for k in TYPES)
    benefits="\n".join(o.get("benefits",[])); steps="\n".join(o.get("next_steps",[]))
    auto_hint='<span class="auto">Automatisch erkannt</span>' if o.get("offer_type_auto") else ""
    body=f'''<div class="back"><a href="{ingress('offer/'+oid)}">← Zurück zum Angebot</a></div><div class="card"><div class="eyebrow">Angebot bearbeiten {auto_hint}</div><h1>Kundendarstellung</h1><p class="muted">Billomat-Preise und Positionen bleiben unverändert. Der Angebotstyp wird aus der Zusammensetzung der Positionen erkannt. Ihre manuelle Auswahl hat immer Vorrang.</p><form method="post"><div class="field"><label>Angebotstyp</label><select name="offer_type">{options}</select></div><div class="field"><label>Kundentitel</label><input name="customer_title" value="{clean(o.get('customer_title'))}"></div><div class="field"><label>Einleitung</label><textarea name="customer_intro">{clean(o.get('customer_intro'))}</textarea></div><div class="field"><label>Projekt auf einen Blick</label><textarea name="project_summary">{clean(o.get('project_summary'))}</textarea></div><div class="field"><label>Ihre Vorteile · ein Vorteil pro Zeile</label><textarea name="benefits">{clean(benefits)}</textarea></div><div class="field"><label>Nächste Schritte · ein Schritt pro Zeile</label><textarea name="next_steps">{clean(steps)}</textarea></div><button class="btn" type="submit">Speichern</button><a class="btn light" href="{ingress('offer/'+oid)}">Abbrechen</a></form></div>'''
    return base("Angebot bearbeiten",body)

def detail(o):
    def pricing_note(item):
        return '<br>'.join(clean(note) for note in item_notes(item, o.get('currency_code') or 'EUR'))
    price_summary = ''.join('<p>' + clean(note) + '</p>' for note in offer_notes(o))
    rows="".join(f'<tr><td data-label="Pos.">{clean(i["position"])}</td><td data-label="Leistung / Artikel"><b>{clean(i["title"])}</b><br>{pricing_note(i)}<br><span class="muted small">{clean(i["description"])}</span></td><td data-label="Menge">{clean(i["quantity"])} {clean(i["unit"])}</td><td data-label="{clean(unit_price_heading(o))}" class="money">{money(i["unit_price"])}</td><td data-label="Netto" class="money">{money(i["total_net"])}</td></tr>' for i in o["items"])
    checks="".join(f'<span class="check">✓ {clean(x)}</span>' for x in o.get("benefits",[]))
    steps="".join(f'<li>{clean(x)}</li>' for x in o.get("next_steps",[])); c=o["client"]
    saved_notice='<div class="success">✓ <span>Änderungen gespeichert.</span> Ihre Angebotsdarstellung wurde erfolgreich gespeichert.</div>' if request.args.get("saved")=="1" else ""
    if o.get('is_draft'):
        saved_notice += '<div class="card" role="status"><strong>Billomat-Entwurf – noch nicht freigegeben.</strong><p>Die PDF ist als Entwurf gekennzeichnet. Freigabe und Versand erfolgen in Billomat.</p></div>'
    auto_hint='<span class="auto">Automatisch erkannt</span>' if o.get("offer_type_auto") else ""
    body=f'''<div class="back"><a href="{ingress('offers')}">← Zurück zur Angebotsübersicht</a></div>{saved_notice}<div class="card hero"><div class="eyebrow">{clean(o.get('offer_type'))} · Ihr persönliches Angebot {auto_hint}</div><h1>{clean(o.get('customer_title') or o.get('title'))}</h1><p>{clean(o.get('customer_intro'))}</p><a class="btn" href="{ingress('offer/'+str(o['id'])+'/edit')}">Angebot bearbeiten</a><a class="btn dark" data-pdf="FTST-Angebot-{clean(o['id'])}.pdf" title="PDF innerhalb der angemeldeten App vorbereiten" href="{ingress('offer/'+str(o['id'])+'/pdf')}">A4-PDF erzeugen</a><a class="btn light" href="{ingress("offer/"+str(o["id"])+"/references")}">Fotos auswählen ({len(o.get("reference_images", []))})</a><p class="muted">{ "Automatische Referenzbilder" if o.get("reference_selection_auto") else "Gespeicherte Bildauswahl" }: {len(o.get("reference_images", []))} Bilder für die PDF. Über Fotos auswählen können Sie diese ändern.</p></div><div class="grid"><div class="metric"><div class="label">Kunde</div><div class="value" style="font-size:18px">{clean(cname(c))}</div><div class="muted small">{clean(c.get('street',''))}<br>{clean(c.get('zip',''))} {clean(c.get('city',''))}</div></div><div class="metric"><div class="label">Angebot</div><div class="value" style="font-size:18px">Nr. {clean(o.get('offer_number') or o.get('number'))}</div><div class="muted small">Datum: {date_de(o.get('date'))}<br>Gültig: {date_de(o.get('validity_date') or o.get('validity_days'))}</div></div><div class="metric green"><div class="label">Ihr Festpreis</div><div class="value">{money(o.get('total_gross'))}</div><div class="muted small">Netto {money(o.get('total_net'))}</div></div></div><div class="card"><h2>Projekt auf einen Blick</h2><p>{clean(o.get('project_summary'))}</p></div><div class="card"><h2>Leistungsumfang</h2>{price_summary}<table><thead><tr><th>Pos.</th><th>Leistung / Artikel</th><th>Menge</th><th>{clean(unit_price_heading(o))}</th><th>Netto</th></tr></thead><tbody>{rows}</tbody></table></div><div class="card"><h2>Ihre Vorteile</h2><div class="checks">{checks}</div></div><div class="card"><h2>Nächste Schritte</h2><ol>{steps}</ol></div><div class="card"><h2>Kostenübersicht</h2>{price_summary}<div class="grid"><div class="metric"><div class="label">Netto</div><div class="value">{money(o.get('total_net'))}</div></div><div class="metric"><div class="label">MwSt.</div><div class="value">{money(o.get('tax_amount'))}</div></div><div class="metric green"><div class="label">Gesamt</div><div class="value">{money(o.get('total_gross'))}</div></div></div></div>'''
    if o.get('is_draft'):
        body = body.replace('Ihr persönliches Angebot', 'Ihr Angebotsentwurf').replace('Ihr Festpreis', 'Entwurfsbetrag')
    else:
        body = body.replace('Ihr persönliches Angebot', 'Ihr persönlicher Leistungsvorschlag').replace('data-pdf="FTST-Angebot-', 'data-pdf="FTST-Leistungsvorschlag-')
    body = body.replace('<div class="grid">', offer_delivery.panel(o, ingress) + '<div class="grid">', 1)
    body += '<script defer src="' + ingress('ui-assets/'+APP_VERSION+'/offer-delivery.js') + '"></script>'
    return base("FTST Angebotsentwurf" if o.get('is_draft') else "FTST Leistungsvorschlag",body)

def footer(canvas,doc):
    canvas.saveState(); w,_=A4
    canvas.setFont("Helvetica",7.5); canvas.setFillColor(MUTED)
    canvas.drawString(18*mm,9*mm,"FT Sicherheitstechnik · Professionelle Sicherheitstechnik")
    canvas.drawRightString(w-18*mm,9*mm,f"Seite {doc.page}")
    canvas.setStrokeColor(BORDER); canvas.line(18*mm,13*mm,w-18*mm,13*mm); canvas.restoreState()

def make_pdf(o):
    from offer_design import build
    return build(normalize(o), clean, money, date_de, cname)

@app.get("/offer/<oid>/pdf")
def offer_pdf(oid):
    try:
        o = get_offer(oid)
        name = 'Angebotsentwurf' if o.get('is_draft') else 'Leistungsvorschlag'
        return send_file(make_pdf(o),mimetype="application/pdf",as_attachment=False,download_name=f"FTST-{name}-{oid}.pdf")
    except StorageError:
        raise
    except Exception as e:
        log.exception("PDF generation failed")
        return base("PDF Fehler",f'<div class="back"><a href="{ingress("offer/"+oid)}">← Zurück zum Angebot</a></div><div class="card"><h1>PDF konnte nicht erstellt werden</h1><p>{clean(e)}</p></div>'),500

materials.register(app, base, ingress, clean, offer_store, TYPES, get_offer)
projects.register(app, base, ingress, clean, offer_store)
project_intake.register(app, base, ingress, clean, offer_store)
montage.register(app, base, ingress, clean, offer_store)
quote_drafts.register(app, base, ingress, clean, offer_store)
quote_presentation.register(app, base, ingress, clean, offer_store)
quote_transfer.register(app, base, ingress, clean, offer_store, detect_offer_type)
offer_followup.register(app, offer_store, base, ingress, clean, date_de)
offer_mail.register(app, base, ingress, clean, offer_store, get_offer, make_pdf)
offer_chat.register(app, base, ingress, clean, offer_store, get_offer, make_pdf, detect_offer_type)
inventory_views.register(app, base, ingress, clean, offer_store)
customers.register(app, base, ingress, clean, offer_store)
ai_status.register(app, base, ingress, clean)
mail_assistant.register(app, base, ingress, clean, offer_store)
strato_views.register(app, base, ingress, clean, offer_store)
billomat_receipts.register(app, base, ingress, clean)

if __name__=="__main__":
    bid=os.getenv("BILLOMAT_ID", "").strip(); key=os.getenv("BILLOMAT_API_KEY", "")
    if bid and key:
        offer_cache.worker(offer_store(), bid.lower(), BillomatClient(bid,key)).start()
    from mail_automation import MailAutomation
    automation = MailAutomation(offer_store, materials.account())
    automation.start(app.config['FTST_DATA_DIR'])
    try:
        app.run(host="0.0.0.0",port=int(os.getenv("PORT","8099")))
    finally:
        automation.stop()
