"""Public FTST/FTronics photos by exact product model, never by camera category."""
import re

# Must be released by the public portal before this mapping is activated in HA.
# Identity source: https://www.ftsicherheitstechnik.com/produkte/<slug>
PRODUCT_SLUGS = (
    'fc-8d-pro', 'fc-8d-zoom', 'fc-6z-mini', 'fb-8a-pro', 'fb-8a-max',
    'ft-8c-pro', 'ft-8p-dual', 'fp-8t-20x', 'fn-16', 'fs-30', 'fc-8d',
    'fb-8b', 'fp-8s-25x', 'fe-6l', 'fn-8', 'fn-32', 'fn-64-pro', 'fr-8x',
)
MODELS = {slug.replace('-', '').upper(): 'ftst-' + slug for slug in PRODUCT_SLUGS}
# Read the entire contiguous model token, including unknown extensions. FC-8D-PRO2
# must not accidentally match either FC-8D or FC-8D-PRO.
MODEL_TOKEN = re.compile(
    r'(?<![A-Za-z0-9])(?:FC|FB|FT|FP|FN|FS|FE|FR)[ _-]*[0-9]+[A-Za-z0-9]*'
    r'(?:[-_][A-Za-z0-9]+)*(?![A-Za-z0-9])', re.IGNORECASE)
SPACE_SUFFIX = re.compile(r'^\s+(PRO\d*|ZOOM\d*|MINI\d*|MAX\d*|DUAL\d*|[0-9]+X|PLUS|ULTRA|LITE)(?![A-Za-z0-9])', re.IGNORECASE)
COMPATIBILITY = re.compile(
    r'\b(?:kompatibel|compatible|compatibility|passend\s+f[uü]r|geeignet\s+f[uü]r|'
    r'f[uü]r|for\s+use\s+with|works\s+with|supports?|unterst[uü]tzt)\b', re.IGNORECASE)


def model_tokens(text):
    tokens = set()
    for clause in re.split(r'[\n.;]', str(text or '')):
        # Compatibility targets and replacement suggestions are not the sold model.
        marker = COMPATIBILITY.search(clause)
        if marker:
            clause = clause[:marker.start()]
        for match in MODEL_TOKEN.finditer(clause):
            token = match.group(0)
            remainder = clause[match.end():]
            while True:
                suffix = SPACE_SUFFIX.match(remainder)
                if not suffix: break
                token += suffix.group(1)
                remainder = remainder[suffix.end():]
            # Slashed variant/channel choices are not one uniquely sold model.
            if re.match(r'^\s*/\s*(?:[0-9]+[A-Za-z0-9]*|PRO|ZOOM|MINI|MAX|DUAL|PLUS|ULTRA|LITE)(?![A-Za-z0-9])', remainder, re.IGNORECASE):
                token += '/AMBIGUOUS'
            tokens.add(re.sub(r'[ _-]', '', token).upper())
    return tokens


def product_image(title, description=''):
    """One known exact identity across primary title/description, or no picture."""
    models = model_tokens(title) | model_tokens(description)
    if len(models) != 1:
        return None
    return MODELS.get(next(iter(models)))
