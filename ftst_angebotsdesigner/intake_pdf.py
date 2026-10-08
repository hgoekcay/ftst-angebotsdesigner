"""Read FTST AcroForm values in a bounded subprocess; never execute PDF actions."""
import io
import json
import subprocess
import sys
import threading
import re
from pathlib import Path

from intake_systems import SYSTEMS

MAX_BYTES = 5 * 1024 * 1024
_lock = threading.Lock()
LABELS = {
    'alarm': ['Bewegungsmelder innen', 'Bewegungsmelder außen', 'Tür-/Fensterkontakt', 'Innensirene', 'Außensirene', 'Bedienteil innen', 'Bedienteil außen', 'Zentrale (neu)', 'Funk-Repeater / Erweiterung', 'Weiteres Gerät / Zubehör'],
    'video': ['Kamera innen', 'Kamera außen', 'Rekorder / NVR', 'Speicher / Festplatte', 'PoE-Switch / Versorgung', 'Monitor / Bedienplatz', 'Montage / Einrichtung / Zubehör'],
    'access': ['Leser / Tastatur', 'Controller / Steuereinheit', 'Elektrischer Türöffner / Schloss', 'Netzteil / Pufferung', 'Türkontakt / Austrittstaster', 'Karten / Transponder', 'Software / Lizenzen / Einrichtung'],
    'cylinder': ['Doppelzylinder', 'Knaufzylinder', 'Halbzylinder', 'Elektronischer Zylinder', 'Schlüssel / Transponder', 'Beschlag / Schutzrosette', 'Montage / Programmierung / weiteres'],
    'intercom': ['Außenstation Audio / Video', 'Innenstation mit Bildschirm', 'Innenstation Audio', 'Netzteil / Busversorgung', 'IP-Gateway / App-Anbindung', 'Türöffner / Relaismodul', 'Zubehör / weitere Komponente'],
}


def read_upload(upload):
    raw = upload.stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES or not raw.startswith(b'%PDF-'):
        raise ValueError('Bitte eine ausgefüllte FTST-PDF mit höchstens 5 MB auswählen.')
    if not _lock.acquire(blocking=False):
        raise ValueError('Ein PDF wird bereits eingelesen. Bitte kurz warten.')
    try:
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--read'],
                                input=raw, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=12)
        data = json.loads(result.stdout) if result.returncode == 0 else {}
        if not isinstance(data, dict) or data.get('error') or data.get('system') not in SYSTEMS:
            raise ValueError(data.get('error') or 'PDF konnte nicht gelesen werden. Bitte den digitalen FTST-Bogen verwenden.')
        return data
    except (subprocess.TimeoutExpired, OSError, json.JSONDecodeError):
        raise ValueError('PDF konnte nicht rechtzeitig gelesen werden. Bitte erneut als ausfüllbare PDF speichern.') from None
    finally:
        _lock.release()


def extract(raw):
    from pypdf import PdfReader
    from pypdf.generic import TextStringObject, NameObject
    reader = PdfReader(io.BytesIO(raw), strict=True)
    if reader.is_encrypted:
        raise ValueError('Passwortgeschützte PDFs werden nicht eingelesen.')
    if len(reader.pages) != 2:
        raise ValueError('Bitte den vollständigen zweiseitigen FTST-Aufnahmebogen hochladen.')
    fields = reader.get_fields() or {}
    template = None
    system = None
    for key, values in SYSTEMS.items():
        expected = PdfReader(Path(__file__).parent / 'static' / f'FTST-Technikeraufnahme-{values[2]}.pdf').get_fields()
        if set(fields) == set(expected) and all(fields[n].get('/FT') == expected[n].get('/FT') for n in expected):
            template, system = expected, key
            break
    if template is None:
        raise ValueError('Keine unterstützten FTST-Formularfelder gefunden. Scans oder gedruckte PDFs bitte als Foto erfassen.')
    # Our templates have one flat widget per field. Reject ambiguous or detached values.
    widgets = {}
    for page in reader.pages:
        for ref in page.get('/Annots', []):
            widget = ref.get_object()
            if widget.get('/Subtype') != '/Widget':
                continue
            name = widget.get('/T')
            if name not in fields or name in widgets or widget.get('/Parent'):
                raise ValueError('PDF-Formularstruktur ist mehrdeutig. Bitte die unveränderte FTST-Vorlage verwenden.')
            widgets[name] = widget
    if set(widgets) != set(fields):
        raise ValueError('PDF-Formularfelder sind unvollständig.')
    values = {}
    for name, field in fields.items():
        value = field.get('/V', '')
        if widgets[name].get('/V', '') != value:
            raise ValueError('PDF enthält widersprüchliche Feldwerte. Bitte erneut speichern.')
        if not isinstance(value, (str, TextStringObject, NameObject)) or len(value) > 1500:
            raise ValueError('PDF enthält ungültige oder zu lange Feldwerte.')
        if field.get('/FT') == '/Btn':
            if value not in ('', '/Off', '/Yes'):
                raise ValueError('PDF enthält eine unbekannte Auswahl.')
            value = 'Ja' if value == '/Yes' else ''
        values[name] = str(value).strip()
    if sum(len(v) for v in values.values()) > 18000:
        raise ValueError('Bitte die Angaben im PDF kürzen (höchstens 18000 Zeichen).')
    if not any(values.values()):
        raise ValueError('Der Bogen enthält keine gespeicherten Eingaben. Bitte digital ausfüllen und speichern.')
    labels = {name: str(field.get('/TU') or name).replace('_', ' ') for name, field in template.items()}
    columns = {
        'kamera': ['ID', 'Ort / innen-außen', 'Anzahl (Detail)', 'Ziel / Distanz / Modell', 'Höhe / Leitung / Foto'],
        'tuer': ['Tür-ID', 'Ort / Türtyp', 'Schloss / Öffner / Leser', 'Gruppe / Zeitprofil', 'Besonderheit / Foto'],
        'zylinder': ['ID', 'Tür / Ort', 'Typ', 'A außen mm', 'B innen mm', 'Anzahl (Detail)', 'Knaufseite / Foto', 'Funktion / Hinweis'],
        'berechtigung': ['Person / Gruppe', 'Tür-IDs / Berechtigung', 'Medien', 'Reserve'],
    }
    for name in labels:
        match = re.fullmatch(r'(kamera|tuer|zylinder|berechtigung)_(\d+)_(\d+)', name)
        if match:
            prefix, row, col = match.groups()
            labels[name] = f'Detail {prefix} {row} – {columns[prefix][int(col)-1]}'
        for index, label in enumerate(LABELS[system], 1):
            for key, suffix in ((f'position_{index}_menge', 'Anzahl'), (f'position_{index}_ort', 'Ort'),
                                (f'position_{index}_variante', 'Variante'), (f'bedarf_{index}_2', 'Anzahl'),
                                (f'bedarf_{index}_3', 'Hinweis'), (f'komponente_{index}_anzahl', 'Anzahl'),
                                (f'komponente_{index}_detail', 'Detail')):
                if name == key:
                    labels[name] = label + ' – ' + suffix
    return {'system': system, 'values': values, 'labels': labels}


def proposal(data, project):
    from project_intake import initial, quantity, open_questions, TEXT_FIELDS
    system, values = data['system'], data['values']
    value = initial(project)
    fields = value['fields']
    fields.update(system_type=system, manufacturer='Ajax' if system == 'alarm' else '', notes='',
                  customer_name=values.get('kunde') or values.get('projekt') or '',
                  object_address=values.get('adresse') or values.get('objektadresse') or '',
                  variant=values.get('system_variante', ''),
                  installation=values.get('montage_aufwand') or values.get('montage') or '',
                  travel=values.get('anfahrt') or values.get('termin') or '')
    questions = ['PDF-Mengen und Varianten prüfen. Detailzeilen von Seite 2 nicht nochmals zur Gesamtmenge addieren.']
    if system == 'alarm':
        checked = [key for key in ('ja', 'nein', 'offen') if values.get('zentrale_' + key)]
        fields['central'] = {'ja': 'yes', 'nein': 'no'}.get(checked[0], 'unknown') if len(checked) == 1 else 'unknown'
    # Both pages are preserved as notes, including contact details and original quantity text.
    lines = []
    for name, text in values.items():
        if text:
            lines.append(data['labels'][name] + ': ' + text)
    fields['notes'] = 'Aus PDF übernommen (Detailzeilen nicht zusätzlich addieren):\n' + '\n'.join(lines)
    for index, label in enumerate(LABELS[system], 1):
        if system == 'alarm':
            count = values[f'position_{index}_menge']
            detail = values[f'position_{index}_variante']
            location = values[f'position_{index}_ort']
        elif system == 'intercom':
            count = values[f'komponente_{index}_anzahl']
            detail = values[f'komponente_{index}_detail']
            location = ''
        else:
            count, detail, location = values[f'bedarf_{index}_2'], values[f'bedarf_{index}_3'], ''
        if not (count or detail or location):
            continue
        try:
            from decimal import Decimal, InvalidOperation
            zero = bool(count) and Decimal(count.replace(',', '.')) == 0
        except InvalidOperation:
            zero = False
        if zero:
            continue
        try:
            number = quantity(count)
        except ValueError:
            number = ''
        description = label + (' – ' + detail if detail else '')
        if len(description) > 300 or len(location) > 150:
            raise ValueError('Bitte Varianten und Montageorte im PDF kürzen.')
        value['components'].append({'description': description, 'quantity': number, 'location': location,
                                    'evidence': f'PDF Seite 1, Position {index}; Menge: {count or "offen"}'[:500]})
    for key, (_, limit) in TEXT_FIELDS.items():
        if len(fields[key]) > limit:
            raise ValueError('Die PDF-Angaben sind für die Aufnahme zu lang. Bitte den Bogen kürzen; es wurde nichts überschrieben.')
    value.update(summary='Digital ausgefüllter FTST-Bogen: ' + SYSTEMS[system][0],
                 questions=open_questions(fields, questions), status='review', review_required=True,
                 slots=max(3, len(value['components'])), pdf_import=True)
    return value


if __name__ == '__main__':
    try:
        if sys.platform != 'win32':
            import resource
            resource.setrlimit(resource.RLIMIT_AS, (384 * 1024 * 1024, 384 * 1024 * 1024))
            resource.setrlimit(resource.RLIMIT_CPU, (8, 8))
        data = extract(sys.stdin.buffer.read(MAX_BYTES + 1))
    except ValueError as exc:
        data = {'error': str(exc)}
    except Exception:
        data = {'error': 'PDF konnte nicht gelesen werden. Bitte die digitale FTST-Vorlage verwenden.'}
    sys.stdout.buffer.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))

