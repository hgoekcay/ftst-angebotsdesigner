"""Mobile-first server-rendered chat and factual review cards."""
import quote_drafts as quotes
from offer_chat import client_name
from customers import customer_fields


def render(chat, key, draft, project, transfer, release, mail, csrf, identity, ingress, e, version):
    revision = chat['revision']
    fields = ('<input type="hidden" name="csrf" value="' + e(csrf) + '">'
              '<input type="hidden" name="account" value="' + e(identity) + '">'
              '<input type="hidden" name="revision" value="' + e(revision) + '">')
    fields += '<input type="hidden" name="draft_revision" value="' + e((draft or {}).get('revision', '')) + '"><input type="hidden" name="transfer_token" value="' + e((transfer or {}).get('token', '')) + '">'
    busy = bool(chat.get('job'))
    disabled = ' disabled' if busy else ''

    def form(action, label, content='', confirm=''):
        check = '<label class="chat-check"><input type="checkbox" name="confirm" value="yes" required> ' + e(confirm) + '</label>' if confirm else ''
        return '<form method="post">' + fields + content + check + '<button class="btn" name="action" value="' + action + '"' + disabled + '>' + e(label) + '</button></form>'

    def option(value, label, selected):
        return '<option value="' + e(value) + '"' + (' selected' if str(value) == str(selected) else '') + '>' + e(label) + '</option>'

    body = '''<style>
.chat-layout{display:grid;grid-template-columns:minmax(0,1.2fr) minmax(0,1fr);gap:20px;align-items:start}
.chat-layout>*{min-width:0}.chat-log{display:flex;flex-direction:column;gap:14px;margin:20px 0;max-height:65vh;overflow-y:auto}
.chat-bubble{white-space:pre-wrap;overflow-wrap:anywhere;padding:16px;border-radius:14px;background:#f0f4f1;max-width:95%}
.chat-bubble.user{align-self:flex-end;background:#e1efdf}.chat-bubble strong{display:block;font-size:12px;color:#526056;margin-bottom:8px}
.chat-layout .btn{background:#16803c;white-space:normal;max-width:100%;margin:6px 4px 6px 0}
.chat-layout input,.chat-layout select,.chat-layout textarea{min-width:0;max-width:100%;box-sizing:border-box}
.chat-layout label{font-size:12px;letter-spacing:.04em}.chat-check{display:flex;gap:10px;align-items:start;margin:14px 0}.chat-check input{width:20px;flex:none}
.chat-item{padding:12px 0;border-bottom:1px solid #ddd}.chat-total{font-size:22px;color:#16803c;font-weight:700}
.chat-voice{display:flex;gap:8px;flex-wrap:wrap}.chat-layout button:disabled{opacity:.5}.chat-layout iframe{width:100%;height:620px;border:1px solid #ddd}
@media(max-width:760px){.chat-layout{grid-template-columns:minmax(0,1fr)}.chat-layout .card{padding:20px}.chat-log{max-height:50vh}.chat-bubble{max-width:100%}}
</style>'''
    body += '<p><a href="' + ingress('chat') + '">← Alle Chats</a></p><h1>FTST Chat</h1><div class="chat-layout" data-chat-status="' + ingress('chat/' + key + '/status') + '" data-busy="' + ('1' if busy else '0') + '">'
    body += '<section class="card"><h2>' + e(chat['title']) + '</h2><p class="small">Lokale KI · Ajax für Alarmanlagen · Preise aus Billomat</p><div class="chat-log" role="log" aria-label="Gespräch">'
    for msg in chat['messages']:
        role = 'user' if msg['role'] == 'user' else 'assistant'
        body += '<div class="chat-bubble ' + role + '"><strong>' + ('Du' if role == 'user' else 'FTST Assistent') + '</strong>' + e(msg['text']) + '</div>'
    body += '</div>'
    if busy:
        body += '<p role="status">Ich bearbeite deine Anfrage. Du kannst diese Seite offen lassen; das Ergebnis erscheint automatisch.</p>'
    body += '<details><summary>Bilder hinzufügen</summary><p>Bis vier Bilder gemeinsam, zusammen 20 MB. JPG, PNG oder WebP. Die Bilder bleiben im Chat und erscheinen nicht automatisch als Referenzbilder im Kunden-PDF.</p><form method="post" enctype="multipart/form-data">' + fields + '<label for="chat-images">Fotos oder Technikerzettel auswählen</label><input id="chat-images" name="images" type="file" multiple accept="image/jpeg,image/png,image/webp" required' + disabled + '><button class="btn" name="action" value="images"' + disabled + '>Bilder hochladen</button></form></details>'
    if chat.get('attachments'):
        body += '<div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px">'
        for index, attachment in enumerate(chat['attachments'], 1):
            url = ingress('chat/' + key + '/images/' + attachment['id'])
            body += '<div><a href="' + url + '" target="_blank" rel="noopener"><img src="' + url + '" alt="Chatbild ' + str(index) + '" loading="lazy" style="width:100%;height:150px;object-fit:contain"></a>'
            body += form('photo', 'Bildtext erkennen', '<input type="hidden" name="photo_id" value="' + e(attachment['id']) + '">') + '</div>'
        body += '</div>'
    if chat.get('photo_result'):
        body += '<details open><summary>Erkannter Bildtext – bitte prüfen</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere">' + e(chat['photo_result']) + '</pre></details>'
    body += '<form method="post" data-chat-message>' + fields + '<label for="chat-message">Deine Nachricht</label><textarea id="chat-message" name="message" maxlength="2000" rows="5" placeholder="Erstelle einen Leistungsvorschlag für …: 6 Bewegungsmelder, 2 Türkontakte …" required' + disabled + '>' + e(chat.get('transcript', '')) + '</textarea><button class="btn" name="action" value="message"' + disabled + '>Nachricht senden</button></form>'
    body += '<details><summary>Sprachnotiz aufnehmen oder hochladen</summary><p>Bis 2 Minuten / 12 MB. Erkennung lokal mit Whisper. Den erkannten Text vor dem Senden prüfen.</p><form method="post" enctype="multipart/form-data" data-chat-audio>' + fields + '<input type="hidden" name="action" value="voice"><input type="file" name="audio" accept="audio/*,.m4a,.mp4,.webm" required' + disabled + '><div class="chat-voice"><button type="button" class="btn" data-record' + disabled + '>Aufnahme starten</button><button type="button" class="btn" data-stop disabled>Aufnahme beenden</button></div><p data-voice-status role="status"></p><button class="btn" type="submit"' + disabled + '>Sprachnotiz erkennen</button></form><p class="small">Falls das Mikrofon in der Home-Assistant-App nicht verfügbar ist: eine vorhandene Aufnahme hochladen oder die Diktierfunktion deiner Handytastatur verwenden.</p></details></section>'
    body += '<aside><section class="card"><h2>Dein Leistungsvorschlag</h2>'
    if not draft:
        body += '<p>Hier erscheinen Kunde, Artikel und Kalkulation nach deiner ersten Nachricht.</p>'
    else:
        state = chat['state']
        result = quotes.calculate(draft)
        if not transfer:
            opts = option('', 'Kunden auswählen', draft.get('client_id'))
            for c in draft['catalog']['clients']:
                if str(c.get('archived')) != '1':
                    opts += option(c['id'], str(c.get('client_number') or '') + ' · ' + client_name(c), draft.get('client_id'))
            content = '<label for="chat-customer">Billomat-Kunde</label><select name="client_id" id="chat-customer">' + opts + '</select>'
            for i, row in enumerate(draft['rows']):
                matches = quotes.candidates(row['description'], draft['catalog']['articles'])
                selected = next((a for a in draft['catalog']['articles'] if str(a['id']) == row.get('article_id')), None)
                if selected and selected not in matches:
                    matches.insert(0, selected)
                # Keep every catalogue article reachable when names differ from the note.
                suggested = {str(a['id']) for a in matches}
                matches += sorted((a for a in draft['catalog']['articles'] if str(a['id']) not in suggested), key=lambda a: str(a.get('title') or '').casefold())
                opts = option('', 'Bitte passende Variante wählen', row.get('article_id')) + ''.join(option(a['id'], str(a.get('article_number') or '') + ' · ' + str(a.get('title') or ''), row.get('article_id')) for a in matches)
                content += '<label for="chat-search-' + str(i) + '">Artikel suchen</label><input type="search" id="chat-search-' + str(i) + '" data-article-search="chat-article-' + str(i) + '" placeholder="Artikelname oder Nummer">'
                content += '<div class="chat-item"><p>' + e(row['description']) + '</p><label for="chat-qty-' + str(i) + '">Menge</label><input id="chat-qty-' + str(i) + '" name="quantity" inputmode="decimal" value="' + e(row['quantity']) + '"><label for="chat-article-' + str(i) + '">Artikelvariante</label><select id="chat-article-' + str(i) + '" name="article_id">' + opts + '</select></div>'
            content += '<label class="chat-check"><input type="checkbox" name="tax_confirmed" value="yes"' + (' checked' if draft.get('tax_confirmed') == 'yes' else '') + '> Bei länderabhängiger Steuerregel gelten die Artikelsteuersätze für diesen Auftrag.</label>'
            body += form('select', 'Auswahl übernehmen', content)
            body += form('catalog', 'Billomat-Daten aktualisieren')
        for line in result['lines']:
            body += '<p>' + e(line['quantity']) + ' × ' + e(line['title']) + '<br>' + quotes.display_money(line['net']) + ' ' + e(result['currency']) + ' netto</p>'
        if result['total']:
            body += '<p class="chat-total">' + quotes.display_money(result['total']['gross']) + ' ' + e(result['currency']) + ' brutto</p><p>Netto ' + quotes.display_money(result['total']['net']) + ' · Steuer ' + quotes.display_money(result['total']['tax']) + '</p>'
            body += '<p><a class="btn" data-pdf="FTST-Chat-Entwurf.pdf" href="' + ingress('chat/' + key + '/pdf') + '?revision=' + e(revision) + '">PDF-Entwurf prüfen</a></p>'
            if not transfer:
                if not draft.get('reviewed'):
                    body += form('review', 'Ja, die Kalkulation passt', confirm='Artikelvarianten, Mengen, Montage, Anfahrt, Zubehör und Konditionen geprüft.')
                else:
                    body += form('create', 'Geprüften Entwurf in Billomat anlegen', confirm='PDF-Entwurf und Kunde geprüft. Genau diesen Entwurf in Billomat anlegen.')
        else:
            body += '<ul>' + ''.join('<li>' + e(p) + '</li>' for p in result['problems']) + '</ul>'
        if not transfer and not draft.get('client_id'):
            body += '<h3>Neukunde</h3><p>Name und vollständige Anschrift kannst du im Chat ergänzen.</p>'
            try:
                fields_customer = customer_fields(dict(state, www=''))
                body += '<p>' + '<br>'.join(e(fields_customer[k]) for k in ('name', 'street', 'zip', 'city', 'country_code')) + '</p>'
                body += form('customer', 'Diesen Kunden in Billomat anlegen', confirm='Kundendaten geprüft; neuen Kunden anlegen und übernehmen.')
            except ValueError:
                body += '<p>Noch benötigt: vollständiger Name, Straße, Postleitzahl, Ort und Land (z. B. Deutschland).</p>'
        body += '<p><a href="' + ingress('projects/' + key + '/quote') + '">Ausführlichen Entwurf öffnen</a></p>'
    body += '</section>'
    if transfer:
        body += '<section class="card"><h2>Billomat & Versand</h2>'
        if transfer['status'] != 'created':
            body += '<p>Übertragung noch nicht eindeutig bestätigt.</p>' + form('transfer_status', 'Status in Billomat prüfen')
        elif not release:
            body += '<p>Der Billomat-Entwurf wurde angelegt. Freigeben vergibt die Angebotsnummer; es wird noch keine E-Mail verschickt.</p>' + form('release', 'Leistungsvorschlag in Billomat freigeben', confirm='Genau diesen geprüften Entwurf freigeben.')
        elif release['status'] != 'open':
            body += '<p>' + e(release.get('label', 'Freigabe noch ungeklärt.')) + '</p>' + form('release_status', 'Freigabestatus prüfen')
        else:
            body += '<p>Leistungsvorschlag ' + e(release['offer_number']) + ' freigegeben.</p>'
            body += form('mail', 'E-Mail mit PDF vorbereiten', '<label for="chat-email">Empfänger</label><input id="chat-email" name="recipient" type="email" required value="' + e(chat['state'].get('recipient', '')) + '">')
        if mail:
            body += '<p><strong>E-Mail vorbereitet für ' + e(mail['recipient']) + '</strong></p><a class="btn" href="' + ingress('email-delivery/' + mail['id']) + '">E-Mail & PDF prüfen und senden</a><p>Auf der nächsten Seite bestätigst du den Versand ausdrücklich. Ein allgemeines „passt so“ im Chat verschickt keine Nachricht.</p>'
        body += '</section>'
    body += '</aside></div><script defer src="' + ingress('ui-assets/' + version + '/offer-chat.js') + '"></script>'
    return body
