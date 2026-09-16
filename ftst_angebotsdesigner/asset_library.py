"""Bundled FTST originals; independent of the writable account data directory."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent / 'assets'
DEFAULT_LOGO = 'builtin-ftst-wide'

# Stable identifiers are stored in SQLite; filenames never come from HTTP input.
ASSETS = [
    ('ftst-wide', 'branding/FT SICHERHEITSTECHNIK - Logo.jpg', 'FT Sicherheitstechnik – Firmenlogo', 'Logo', 'Firmenlogo'),
    ('ftst-mail', 'branding/FT SICHERHEITSTECHNIK - Logommail.jpg', 'FT Sicherheitstechnik – kompakt', 'Logo', 'Firmenlogo'),
    ('ftst-square', 'branding/FT SICHERHEITSTECHNIK VIERECK_1.png', 'FT – quadratische Variante', 'Logo', 'Firmenlogo'),
    ('ftronics', 'branding/Ftronics LOGO.jpg', 'FTronics – Produktmarke für Kameras und eigene Produkte', 'Logo', 'Produktlogo'),
    ('access-card', 'branding/AdobeStock_174826735.jpeg', 'Zutritt mit Karte und Code', 'Zutrittskontrolle', 'Symbolfoto'),
    ('security', 'branding/AdobeStock_168786318.jpeg', 'Sicherheit statt Risiko', 'Kombination', 'Symbolfoto'),
    ('video-sign', 'branding/20180319_192228.png', 'FTST Video-Hinweisgrafik', 'Videoüberwachung', 'Hinweisgrafik'),
    ('video-entry', 'references/Yilik_Juwelier_Stuttgart_Hasan_Metim_20250901_171457494.jpg', 'Domekamera am Geschäftseingang', 'Videoüberwachung', 'FTST-Originalfoto'),
    ('video-shop', 'references/Yilik_Juwelier_Stuttgart_Hasan_Metin_20260901_145923335.jpg', 'Kameras im Juweliergeschäft', 'Videoüberwachung', 'FTST-Originalfoto'),
    ('access-cylinder', 'references/-P0Wb5YznBBarvYRcvIO.jpg', 'Elektronischer Türzylinder', 'Zutrittskontrolle', 'FTST-Originalfoto'),
    ('door-entry', 'references/Zerda_Gold_Rheinfelden_20260907_190456629.jpg', 'Ajax-Türstation und Bedienelement', 'Türsprechanlage', 'FTST-Originalfoto'),
    ('door-detail', 'references/Zerda_Gold_Rheinfelden_20260907_190646944.jpg', 'Ajax-Türstation im Detail', 'Türsprechanlage', 'FTST-Originalfoto'),
]


def catalog(store, identity):
    result = {
        'builtin-' + key: dict(path=str(ROOT / filename), title=title,
                              category=category, kind=kind, description='',
                              bundled=True)
        for key, filename, title, category, kind in ASSETS
        if (ROOT / filename).is_file()
    }
    for key, record in store.records(identity, 'image').items():
        path = store.directory / 'images' / (key + '.png')
        if not key.startswith('builtin-') and path.is_file():
            result[key] = dict(record, path=str(path), bundled=False)
    return result
