"""Recipient review and links to explicit server or device delivery."""
from html import escape


def messages(offer):
    number = str(offer.get('offer_number') or offer.get('number') or offer['id'])
    subject = 'Ihr Leistungsvorschlag ' + number + ' – FT Sicherheitstechnik'
    email = (
        'Sehr geehrte Damen und Herren,\n\n'
        'vielen Dank für Ihr Interesse an unseren Sicherheitslösungen. '
        'Im Anhang erhalten Sie Ihren persönlichen Leistungsvorschlag ' + number + '.\n\n'
        'Darin haben wir die vorgesehenen Geräte, Leistungen und Konditionen übersichtlich '
        'für Sie zusammengestellt. So können Sie in Ruhe prüfen, wie die vorgeschlagene '
        'Lösung zu Ihrem Objekt und Ihren Anforderungen passt.\n\n'
        'Gerne besprechen wir den Leistungsvorschlag mit Ihnen und klären offene Fragen '
        'zur Ausstattung, Bedienung oder Umsetzung. Falls Sie Änderungen wünschen, '
        'passen wir die Planung gemeinsam an.\n\n'
        'Antworten Sie uns einfach auf diese E-Mail oder rufen Sie uns an. '
        'Einen Termin für ein kurzes Beratungsgespräch können Sie auch hier wählen:\n'
        'https://tidycal.com/ftsicherheit/erstberatung\n\n'
        'Wir freuen uns auf Ihre Rückmeldung.\n\n'
        'Mit freundlichen Grüßen\nFT Sicherheitstechnik\n\n'
        'Hafenbahnstraße 15\n68305 Mannheim\n'
        'USt-ID: DE301351179\nTelefon: +49 621 159 647 34\n'
        'Mobil: +49 176 329 563 00\nE-Mail: info@ftst.eu')
    whatsapp = ('Guten Tag, hier ist Ihr Leistungsvorschlag ' + number + ' als PDF. '
                'Bei Fragen melden Sie sich gerne. Viele Grüße, FT Sicherheitstechnik')
    return subject, email, whatsapp


def panel(offer, ingress):
    if offer.get('is_draft'):
        return ''
    client = offer.get('client') or {}
    def value(*keys):
        return next((str(client[k]).strip() for k in keys
                     if isinstance(client.get(k), (str, int)) and str(client[k]).strip()), '')
    oid = str(offer['id'])
    subject, email_text, whatsapp_text = messages(offer)
    e = lambda v: escape(str(v), quote=True)
    return f'''<section class="card" data-offer-delivery data-pdf-url="{e(ingress('offer/' + oid + '/pdf'))}" data-filename="{e('FTST-Leistungsvorschlag-' + oid + '.pdf')}">
<h2>Leistungsvorschlag versenden</h2><p>Kundendaten aus Billomat prüfen oder für diesen Versand ergänzen. E-Mail direkt mit PDF-Anhang vorbereiten oder die PDF über Ihre E-Mail-App bzw. WhatsApp teilen.</p>
<p><a class="btn" style="background:#16803c" href="{e(ingress('offer/' + oid + '/email'))}">E-Mail mit PDF direkt versenden</a></p>
<div class="grid"><div class="field"><label for="delivery-email">E-Mail des Kunden</label><input id="delivery-email" type="email" autocomplete="off" value="{e(value('email', 'email_address'))}"></div>
<div class="field"><label for="delivery-phone">WhatsApp-Nummer des Kunden</label><input id="delivery-phone" type="tel" autocomplete="off" placeholder="+49 …" value="{e(value('mobile', 'mobile_phone', 'phone', 'phone_number'))}"><p class="small">Deutsche Nummern mit 0 werden in +49 umgewandelt. Andere Länder bitte mit +Ländervorwahl eingeben.</p></div></div>
<div class="field"><label for="delivery-subject">Betreff</label><input id="delivery-subject" value="{e(subject)}" maxlength="200"></div>
<details><summary>E-Mail-Text prüfen und bearbeiten</summary><div class="field"><label for="delivery-email-text">Ausführliche E-Mail</label><textarea id="delivery-email-text" style="min-height:300px" maxlength="4000">{e(email_text)}</textarea></div></details>
<div class="field"><label for="delivery-whatsapp-text">Kurzer WhatsApp-Text</label><textarea id="delivery-whatsapp-text" maxlength="1000">{e(whatsapp_text)}</textarea></div>
<button class="btn" type="button" data-deliver="email">PDF für E-Mail vorbereiten</button>
<button class="btn" style="background:#16803c" type="button" data-deliver="whatsapp">PDF für WhatsApp vorbereiten</button>
<p class="small">Danach „PDF an WhatsApp teilen“ wählen, WhatsApp öffnen und den Kunden auswählen. Ein reiner Chat-Link überträgt keine Datei.</p>
<div data-delivery-result aria-live="polite"></div></section>'''
