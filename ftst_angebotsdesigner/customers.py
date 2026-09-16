"""Reviewable company onboarding with durable, at-most-once Billomat submission."""
import hashlib
import os
import re
import secrets
import uuid
from datetime import datetime, timezone
from urllib.parse import quote
from flask import abort, redirect, request, session
from billomat_client import BillomatClient, CustomerWriteUncertain
from company_search import FIELDS, SearchError, research, safe_url
from materials import account
from quote_drafts import catalog_snapshot
from storage import RecordConflict


def api():
    bid, key = os.getenv('BILLOMAT_ID','').strip(), os.getenv('BILLOMAT_API_KEY','').strip()
    if not bid or not key:
        raise ValueError('Billomat-Zugang fehlt in der App-Konfiguration.')
    return BillomatClient(bid,key)


def normalize(value):
    return re.sub(r'[^\w]', '', str(value).casefold())


def customer_fields(source):
    result = {k: str(source.get(k, '')).strip() for k in FIELDS}
    if any(len(v)>300 for v in result.values()) or not all(result[k] for k in ('name','street','zip','city')):
        raise ValueError('Firmennamen und vollständige Geschäftsanschrift prüfen; höchstens 300 Zeichen je Feld.')
    result['country_code'] = result['country_code'].upper()
    if not re.fullmatch('[A-Z]{2}', result['country_code']):
        raise ValueError('Land als zweistelligen ISO-Ländercode angeben, z. B. DE.')
    if result['www'] and not safe_url(result['www']):
        raise ValueError('Website vollständig mit https:// angeben oder leer lassen.')
    return result


def duplicates(payload, clients):
    return [c for c in clients if normalize(c.get('name')) == normalize(payload['name']) or
            (normalize(c.get('street')) == normalize(payload['street']) and
             normalize(c.get('zip')) == normalize(payload['zip']) and
             normalize(c.get('name')) and normalize(payload['name']) in normalize(c.get('name')))]


def submit(store, identity, key, revision, client_api):
    draft = store.record(identity,'customer_draft',key)
    if not draft or draft['revision'] != revision:
        raise RecordConflict('Kundendaten wurden geändert. Bitte die aktuelle Vorschau bestätigen.')
    payload = customer_fields(draft['fields'])
    # Account-wide identity latch also covers duplicate requests from other tabs/drafts.
    lock = hashlib.sha256(normalize(payload['name']).encode()).hexdigest()
    previous = store.record(identity,'customer_submit',lock)
    if previous:
        if previous.get('fields') != payload:
            raise RecordConflict('Für diesen Firmennamen besteht bereits eine Übertragung mit anderen Daten. Billomat-Kundenbestand prüfen.')
        return previous
    existing = duplicates(payload, client_api.collection('clients','client'))
    if existing:
        return {'status':'duplicate','clients':existing}
    token = uuid.uuid4().hex
    def claim(value, db):
        if value:
            raise RecordConflict('Kundenanlage wird bereits verarbeitet. Status neu laden, nicht erneut anlegen.')
        import json
        row = db.execute('SELECT payload FROM records WHERE account=? AND kind=? AND id=?', (identity,'customer_draft',key)).fetchone()
        if not row or json.loads(row[0]) != draft:
            raise RecordConflict('Die Vorschau hat sich geändert. Bitte neu prüfen.')
        return dict(status='sending', token=token, fields=payload, draft=key, at=datetime.now(timezone.utc).isoformat())
    store.transact_record(identity,'customer_submit',lock,claim)
    try:
        result = client_api.create_client(payload)
        outcome = dict(status='created', client_id=str(result['id']), client_number=str(result.get('client_number','')))
    except CustomerWriteUncertain:
        outcome = dict(status='unknown')
    def finish(value, db):
        if not value or value.get('token') != token:
            raise RecordConflict('Übertragungsstatus geändert. Billomat-Kundenliste prüfen.')
        return dict(value, **outcome)
    return store.transact_record(identity,'customer_submit',lock,finish)


def register(app, base, ingress, escape, get_store):
    def csrf():
        session.setdefault('customers_csrf',secrets.token_urlsafe(32))
        return f'<input type="hidden" name="csrf" value="{escape(session["customers_csrf"])}">'
    def protect():
        if not secrets.compare_digest(request.form.get('csrf',''),session.get('customers_csrf','-')):
            abort(400,'Formular abgelaufen. Bitte neu laden.')
    def card_error(exc):
        return f'<p role="alert">{escape(exc)}</p>'
    def client_cards(clients):
        return ''.join(f'<div class="card"><h3>{escape(c.get("name") or c.get("client_number"))}</h3><p>{escape(c.get("street"))} · {escape(c.get("zip"))} {escape(c.get("city"))}</p><p>Billomat-Kundennummer: {escape(c.get("client_number"))} · ID {escape(c.get("id"))}{" · archiviert" if str(c.get("archived"))=="1" else ""}</p></div>' for c in clients[:30])

    @app.route('/billomat',methods=['GET','POST'])
    def billomat_status():
        store = get_store()
        message=''
        status=200
        if request.method=='POST':
            protect()
            try:
                data=catalog_snapshot(api().draft_catalog())
                store.put_record(account(),'catalog','shared',dict(data=data,at=datetime.now(timezone.utc).isoformat()))
                message='<p class="success">Billomat-Verbindung erfolgreich. Artikel und Kunden wurden geladen.</p>'
            except (ValueError,RuntimeError) as exc:
                from storage import StorageError
                if isinstance(exc,StorageError):
                    raise
                message=card_error('Billomat-Daten konnten nicht vollständig geladen werden. API-Konfiguration und Berechtigungen prüfen. Der letzte gespeicherte Katalog bleibt erhalten.')
                status=503
        saved=store.record(account(),'catalog','shared') or {}
        data=saved.get('data',{})
        return base('Billomat-Verbindung', f'<div class="card"><h1>Billomat-Verbindung</h1>{message}<p>Speichern sichert Ihre Eingaben. Dieser Abruf lädt die Stammdaten aus Billomat für neue Angebotsentwürfe und das Lager. Bestehende geprüfte Entwürfe behalten ihren bisherigen Datenstand.</p><p>Letzter erfolgreicher Abruf: {escape(saved.get("at") or "Noch nicht geladen")}</p><p>{len(data.get("articles",[]))} Artikel · {len(data.get("clients",[]))} Kunden</p><form method="post">{csrf()}<button class="btn">Artikel und Kunden jetzt laden</button></form><p><a href="{ingress("inventory")}">Zum Lager</a> · <a href="{ingress("customers")}">Kunden finden oder anlegen</a></p></div>'),status

    @app.route('/customers',methods=['GET','POST'])
    def customers_home():
        store=get_store()
        query=request.form.get('query',request.args.get('q','')).strip()[:200]
        message=''
        results=''
        if request.method=='POST':
            protect()
            action=request.form.get('action')
            try:
                if action=='manual':
                    key=uuid.uuid4().hex
                    store.put_record(account(),'customer_draft',key,dict(fields=dict.fromkeys(FIELDS,''),revision=uuid.uuid4().hex,source_url='',source_title='Manuelle Eingabe'))
                    return redirect(ingress('customers/'+key))
                if len(query)<3:
                    raise ValueError('Bitte mindestens drei Zeichen eingeben, möglichst Firmenname und Ort.')
                if action=='existing':
                    clients=api().collection('clients','client',{'name':query})
                    results=client_cards(clients)
                    message=f'<p>{len(clients)} Treffer in Billomat (bis zu 30 angezeigt).</p>'
                elif action=='web':
                    # Do not transmit stored customers or project notes to the web provider.
                    companies=research(query)
                    search_id=uuid.uuid4().hex
                    store.put_record(account(),'company_search',search_id,{'companies':companies})
                    for index,c in enumerate(companies):
                        results+=f'<div class="card"><h2>{escape(c["name"])}</h2><p>{escape(c["street"])} · {escape(c["zip"])} {escape(c["city"])} · {escape(c["country_code"])}</p><p>{escape(c["hint"])}</p><p>Quelle: <a target="_blank" rel="noopener noreferrer" href="{escape(c["source_url"])}">{escape(c["source_title"])}</a></p><form method="post" action="{ingress("customers/select")}">{csrf()}<input type="hidden" name="search" value="{search_id}"><input type="hidden" name="index" value="{index}"><button class="btn light">Diese Firma prüfen</button></form></div>'
                    message=f'<p>{len(companies)} belegte Firmenvorschläge. Anschrift und rechtliche Firma vor der Anlage prüfen.</p>'
                else:
                    abort(400)
            except (ValueError,SearchError,RuntimeError) as exc:
                from storage import StorageError
                if isinstance(exc,StorageError):
                    raise
                message=card_error(str(exc) if isinstance(exc,(ValueError,SearchError)) else 'Billomat-Suche fehlgeschlagen. Verbindung und API-Berechtigung prüfen.')
        ai='Web-Firmensuche verfügbar.' if os.getenv('OPENAI_API_KEY','').strip() else 'Web-Firmensuche benötigt noch den OpenAI-API-Schlüssel in der Home-Assistant-App-Konfiguration.'
        return base('Kundenassistent',f'<div class="card"><h1>Firma finden und als Kunde übernehmen</h1><p>Zuerst nach bestehenden Kunden suchen. Neue Kundendaten werden vor dem Anlegen vollständig angezeigt.</p>{message}<form method="post">{csrf()}<label>Firmenname und Ort<input name="query" value="{escape(query)}" maxlength="200" placeholder="Firmenname GmbH, Ort"></label><button class="btn" name="action" value="existing">In Billomat suchen</button><button class="btn light" name="action" value="web">Firma im Web suchen</button><button class="btn light" name="action" value="manual">Firmendaten manuell eingeben</button></form><p>{ai}</p><p>Bei Websuche wird ausschließlich der eingegebene Suchtext an OpenAI zur Internetrecherche übertragen. Es können API-Kosten entstehen. Keine Projektnotizen, Kundenlisten oder Billomat-Zugangsdaten werden übertragen.</p></div>{results}')

    @app.post('/customers/select')
    def customer_select():
        protect()
        saved=get_store().record(account(),'company_search',request.form.get('search',''))
        try:
            index=int(request.form.get('index',''))
            if index<0 or not saved:
                raise ValueError
            company=saved['companies'][index]
        except (ValueError,IndexError,KeyError):
            abort(400)
        key=uuid.uuid4().hex
        get_store().put_record(account(),'customer_draft',key,dict(fields={k:company[k] for k in FIELDS},source_url=company['source_url'],source_title=company['source_title'],revision=uuid.uuid4().hex))
        return redirect(ingress('customers/'+key))

    @app.route('/customers/<key>',methods=['GET','POST'])
    def customer_review(key):
        store=get_store()
        draft=store.record(account(),'customer_draft',key)
        if not draft:
            abort(404)
        message=''
        result=None
        status=200
        if request.method=='POST':
            protect()
            try:
                revision=request.form.get('revision','')
                if revision!=draft['revision']:
                    raise RecordConflict('Daten wurden geändert. Bitte neu laden.')
                if request.form.get('action')=='edit':
                    draft=dict(draft,ready=False,revision=uuid.uuid4().hex)
                    store.put_revision(account(),'customer_draft',key,draft,revision)
                    return redirect(ingress('customers/'+key))
                elif request.form.get('action')=='prepare':
                    fields=customer_fields(request.form)
                    draft=dict(draft,fields=fields,ready=True,revision=uuid.uuid4().hex)
                    store.put_revision(account(),'customer_draft',key,draft,revision)
                    return redirect(ingress('customers/'+key))
                elif request.form.get('action')=='create':
                    if not draft.get('ready') or request.form.get('confirmed')!='yes':
                        raise ValueError('Bitte die angezeigten Firmendaten ausdrücklich bestätigen.')
                    result=submit(store,account(),key,revision,api())
                else:
                    abort(400)
            except RecordConflict as exc:
                message=card_error(exc); status=409
            except ValueError as exc:
                message=card_error(exc); status=400
            except RuntimeError:
                message=card_error('Billomat-Prüfung fehlgeschlagen. Bei unklarem Übertragungsstatus die Kundenliste prüfen, nicht erneut anlegen.'); status=503
        lock=hashlib.sha256(normalize(draft['fields'].get('name')).encode()).hexdigest()
        result=result or store.record(account(),'customer_submit',lock)
        labels=dict(name='Exakter Firmenname',street='Straße und Hausnummer',zip='Postleitzahl',city='Ort',country_code='Land (ISO-Code, z. B. DE)',www='Website (optional, https://…)')
        fields=''.join(f'<label>{label}<input name="{k}" maxlength="300" value="{escape(draft["fields"].get(k))}" {"required" if k!="www" else ""}></label>' for k,label in labels.items())
        source=draft.get('source_url','')
        source_html=f'<p>Recherchequelle: <a target="_blank" rel="noopener noreferrer" href="{escape(source)}">{escape(draft.get("source_title") or source)}</a></p>' if safe_url(source) else '<p>Manuell erfasste Firmendaten.</p>'
        token=f'<input type="hidden" name="revision" value="{escape(draft["revision"])}">'
        body=f'<div class="card"><a href="{ingress("customers")}">← Kundenassistent</a><h1>Kundendaten prüfen</h1>{source_html}{message}'
        if result:
            if result['status']=='created':
                body+=f'<p class="success">Kunde in Billomat angelegt: {escape(result.get("fields",{}).get("name"))}. Kundennummer: {escape(result.get("client_number"))} · ID {escape(result["client_id"])}</p><p>Übertragene Anschrift: {escape(result.get("fields",{}).get("street"))}, {escape(result.get("fields",{}).get("zip"))} {escape(result.get("fields",{}).get("city"))}</p><p>Im Angebotsentwurf die Kundenliste neu laden und diesen Kunden auswählen.</p>'
            elif result['status']=='duplicate':
                body+='<p>Passende Kunden sind bereits in Billomat vorhanden. Es wurde kein neuer Kunde angelegt.</p>'+client_cards(result['clients'])
            else:
                body+='<p>Die Kundenanlage wurde bereits angestoßen; das Ergebnis ist noch nicht eindeutig bestätigt. Kein erneuter Versand. Bitte über „In Billomat suchen“ den Kundenbestand prüfen.</p>'
            body+=f'<p><a class="btn" href="{ingress("customers")}?q={quote(draft["fields"].get("name",""))}">Billomat-Kunden prüfen</a></p>'
        else:
            if not draft.get('ready'):
                body+=f'<form method="post">{csrf()}{token}{fields}<button class="btn light" name="action" value="prepare">Daten prüfen und Vorschau speichern</button></form>'
            if draft.get('ready'):
                summary=''.join(f'<tr><th>{labels[k]}</th><td>{escape(draft["fields"][k])}</td></tr>' for k in FIELDS)
                body+=f'<h2>Diese Daten werden an Billomat übertragen</h2><table>{summary}</table><p>Kundennummer und kaufmännische Vorgaben vergibt Billomat nach deinen Kontoeinstellungen. Es wird kein Angebot versandt.</p><form method="post">{csrf()}{token}<label><input style="width:auto" type="checkbox" name="confirmed" value="yes" required> Ja, das ist die richtige Firma. Ich bestätige die gespeicherten Daten oben und möchte sie als Kunden in meinem Billomat anlegen.</label><button class="btn" name="action" value="create">Bestätigten Kunden in Billomat anlegen</button></form>'
                body+=f'<form method="post">{csrf()}{token}<button class="btn light" name="action" value="edit">Firmendaten korrigieren</button></form>'
        return base('Kundenprüfung',body+'</div>'),status
