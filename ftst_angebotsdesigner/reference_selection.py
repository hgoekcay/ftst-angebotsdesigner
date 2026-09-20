"""Local, deterministic reference suggestions; no paid AI calls."""
import re

MAX_REFERENCE_IMAGES = 4

TERMS = {
    'Alarmanlage': ('alarm', 'sirene', 'bewegungsmelder', 'bedienteil'),
    'Videoüberwachung': ('kamera', 'video'),
    'Türsprechanlage': ('türstation', 'türsprech'),
    'Zutrittskontrolle': ('zutritt', 'türzylinder'),
    'Rauchmeldeanlage': ('rauchmelder', 'rauchwarn', 'fireprotect'),
    'Brandwarnanlage': ('brandwarn', 'brandmelder'),
    'Smart Home': ('smart home', 'automation'),
}


def suggest(images, category, limit=MAX_REFERENCE_IMAGES):
    ranked = []
    for key, item in images.items():
        kind = item.get('kind', '')
        if item.get('category') == 'Logo' or kind in ('Symbolfoto', 'Hinweisgrafik'):
            continue
        text = ' '.join(str(item.get(k) or '') for k in ('title', 'description')).lower()
        exact = item.get('category') == category
        related = item.get('category') == 'Kombination' and any(t in text for t in TERMS.get(category, ()))
        if not (exact or related or category == 'Kombination'):
            continue
        # Prefer focused photos, then suitable combined installations.
        ranked.append((0 if exact else 1, str(item.get('title') or ''), key))
    chosen, seen, alternatives = [], set(), []
    for _, title, key in sorted(ranked):
        family = re.split(r'\s+[–—]\s+', title.lower())[0]
        if family in seen:
            alternatives.append(key)
        else:
            chosen.append(key)
            seen.add(family)
    return (chosen + alternatives)[:max(0, min(limit, MAX_REFERENCE_IMAGES))]
