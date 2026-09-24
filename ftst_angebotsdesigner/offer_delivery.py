"""Recipient review and device-assisted delivery; never sends on the server."""
from html import escape


def panel(offer, ingress):
    if offer.get('is_draft'):
        return ''
    client = offer.get('client') or {}
    def value(*keys):
        return next((str(client[k]).strip() for k in keys
                     if isinstance(client.get(k), (str, int)) and str(client[k]).strip()), '')
    oid = str(offer['id'])
    number = offer.get('offer_number') or offer.get('number') or oid
    subject = 'Ihr Angebot ' + str(number) + ' – FT Sicherheitstechnik'
    text = ('Guten Tag,\n\nanbei erhalten Sie Ihr Angebot ' + str(number) +
            '. Bei Fragen sind wir gerne für Sie da.\n\nFreundliche Grüße\nFT Sicherheitstechnik')
    e = lambda v: escape(str(v), quote=True)
    return f'''<section class="card" data-offer-delivery data-pdf-url="{e(ingress('offer/' + oid + '/pdf'))}" data-filename="{e('FTST-Angebot-' + oid + '.pdf')}">
<h2>Angebot versenden</h2><p>Kundendaten aus Billomat prüfen oder für diesen Versand ergänzen. Gesendet wird anschließend in Ihrer E-Mail-App oder WhatsApp.</p>
<div class="grid"><div class="field"><label for="delivery-email">E-Mail des Kunden</label><input id="delivery-email" type="email" autocomplete="off" value="{e(value('email', 'email_address'))}"></div>
<div class="field"><label for="delivery-phone">WhatsApp-Nummer des Kunden</label><input id="delivery-phone" type="tel" autocomplete="off" placeholder="+49 …" value="{e(value('mobile', 'mobile_phone', 'phone', 'phone_number'))}"><p class="small">Deutsche Nummern mit 0 werden in +49 umgewandelt. Andere Länder bitte mit +Ländervorwahl eingeben.</p></div></div>
<div class="field"><label for="delivery-subject">Betreff</label><input id="delivery-subject" value="{e(subject)}" maxlength="200"></div>
<div class="field"><label for="delivery-text">Nachricht</label><textarea id="delivery-text" maxlength="4000">{e(text)}</textarea></div>
<button class="btn" type="button" data-deliver="email">Per E-Mail versenden</button>
<button class="btn" style="background:#16803c" type="button" data-deliver="whatsapp">Per WhatsApp versenden</button>
<div data-delivery-result aria-live="polite"></div></section>'''
