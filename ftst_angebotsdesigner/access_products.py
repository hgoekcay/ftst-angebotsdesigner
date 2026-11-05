"""FTST access brands and review prompts; no guessed prices or accessory quantities."""
import re
from html import escape

SOURCES = {
    'bold': 'https://boldsmartlock.com/en-uk/products/bold-connect',
    'smartloxx': 'https://www.cdvi.de/de/unsere-produkte/multicontrol-als-platine/',
    'ekey': 'https://www.ekey.net/downloadcenter/',
}


def identify(title):
    text = str(title or '').lower()
    if re.search(r'\b(montage|installation|einrichtung|inbetriebnahme|reparatur)\b', text):
        return None
    primary = re.split(r'\b(?:für|fuer|kompatibel|passend|geeignet|compatible|for)\b', text)[0]
    brands = [brand for brand in SOURCES if re.search(r'\b' + brand + r'\b', primary)]
    if len(brands) != 1:
        return None
    brand = brands[0]
    if brand == 'bold':
        if re.search(r'\bconnect\b', primary):
            return brand, 'gateway', 'Bold Connect'
        if re.search(r'\b(clicker|case|halterung|adapter|netzteil)\b', primary):
            return brand, 'accessory', 'Bold Zubehör'
        if re.search(r'\b(elite|smart\s*lock|smart\s*cylinder|zylinder|schloss)\b', primary):
            return brand, 'lock', 'Bold Schließzylinder – Modell/Maß prüfen'
    elif brand == 'smartloxx':
        if re.search(r'\b(multi\s*control(?:ler)?|mc)\b', primary):
            return brand, 'controller', 'Smartloxx multiControl – Platine/Gehäuse prüfen'
        if re.search(r'\b(z1(?:-\d+)*|sl1(?:-\d+)*|schloss|zylinder|schließzylinder|schliesszylinder)\b', primary):
            return brand, 'lock', 'Smartloxx Zylinder – Modell/Maß prüfen'
    elif brand == 'ekey':
        if re.search(r'\b(controller|steuereinheit|erweiterungsmodul)\b', primary):
            return brand, 'controller', 'ekey Controller – Serie prüfen'
        if re.search(r'\b(fingerprint|fingerprintleser|fingerleser|xline|sline|dline)\b', primary):
            return brand, 'reader', 'ekey Fingerprint – Serie/Einbauform prüfen'
    return brand, 'unknown', brand + ' – genaue Komponente prüfen'


def product_image(title):
    # Exact standalone item only; unknown generations, sets and compatibility
    # descriptions must be assigned a reviewed picture instead.
    if re.fullmatch(r'\s*bold\s+connect\s*', str(title or ''), re.IGNORECASE):
        return 'bold-connect'
    return None


def review_html(items):
    products = [identify(item.get('title') or item.get('description')) for item in items]
    brands = {product[0] for product in products if product}
    if not brands:
        return ''
    notes = []
    if 'bold' in brands:
        notes.append(('bold', 'Fernzugriff gewünscht? Bold Connect als eigene Billomat-Position prüfen. '
                      'Vorhandene Connects, WLAN/Stromversorgung und Abstand zu den Türen aufnehmen; '
                      'nicht automatisch ein Connect pro Schloss rechnen. Zylindermaß und genaue Modellvariante festlegen.'))
    if 'smartloxx' in brands:
        notes.append(('smartloxx', 'Alarmanlagenkopplung oder externe Freigabe/Sperre gewünscht? Passende multiControl-Ausführung '
                      '(Platine oder Gehäuse), Versorgung, Schnittstellen und gegebenenfalls Freischaltungen prüfen. '
                      'Vorhandene Komponenten und Set-Lieferumfang berücksichtigen; keine pauschale Kompatibilitätszusage.'))
    if 'ekey' in brands:
        notes.append(('ekey', 'Fingerprint-Serie und Einbauform festlegen. Dazu passenden Controller, Versorgung, '
                      'Kabel und Türöffner/Motorschloss prüfen. Bei Sets enthaltene Teile nicht nochmals berechnen.'))
    return ('<section class="card"><h2>Zutritt: System und Zubehör prüfen</h2><ul>' + ''.join(
        '<li><strong>' + escape(brand) + '</strong>: ' + escape(note) + ' <a href="' + SOURCES[brand] +
        '" target="_blank" rel="noopener noreferrer">Herstellerinformation</a></li>' for brand, note in notes) +
        '</ul><p>Benötigte Komponenten als eigene Positionen mit tatsächlicher Menge und dem passenden Billomat-Artikel auswählen. '
        'Erst dann werden sie mit euren Verkaufspreisen eingerechnet. Zubehörbilder müssen die tatsächlich angebotene Variante zeigen.</p></section>')
