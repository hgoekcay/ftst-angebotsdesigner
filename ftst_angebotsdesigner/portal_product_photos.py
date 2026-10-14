"""Explicit account/offer/product-bound picture choices, frozen in new snapshots."""
import hashlib
import io
import json
from PIL import Image, ImageOps
from asset_library import catalog

KIND = 'website_portal_product_photos'
TARGET_BYTES = 128 * 1024


def product_identity(item):
    identity = {key: str(item.get(key) or '') for key in ('title', 'description', 'unit')}
    return hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def available(store, identity):
    return {key: image for key, image in catalog(store, identity).items() if image.get('category') != 'Logo'}


def remembered(store, identity, offer):
    saved = store.record(identity, KIND, str(offer['id'])) or {}
    images = available(store, identity)
    result = {}
    for n, item in enumerate(offer.get('items') or [], 1):
        entry = saved.get('position-' + str(n))
        if (isinstance(entry, dict) and entry.get('product_identity') == product_identity(item)
                and entry.get('asset_id') in images):
            result['position-' + str(n)] = entry['asset_id']
    return result


def normalized_png(path):
    """Strip private metadata, retain product content, and bound thumbnail bytes."""
    try:
        with Image.open(path) as original:
            image = ImageOps.exif_transpose(original)
            image = image.convert('RGBA' if image.mode in ('RGBA', 'LA') or 'transparency' in image.info else 'RGB')
            for bound in (800, 640, 512, 384, 256, 192, 128):
                thumb = image.copy()
                thumb.thumbnail((bound, bound))
                thumb.info.clear()
                output = io.BytesIO()
                thumb.save(output, format='PNG', optimize=True)
                payload = output.getvalue()
                if len(payload) <= TARGET_BYTES:
                    return payload
    except (OSError, ValueError, Image.DecompressionBombError):
        raise ValueError('Das ausgewählte Produktbild kann nicht kundengerecht aufbereitet werden.') from None
    raise ValueError('Das ausgewählte Produktbild lässt sich nicht ausreichend verkleinern.')


def apply(store, identity, offer, snapshot, choices, is_service):
    images = available(store, identity)
    descriptors, payload, binding = [], {}, {}
    lines = {line['id']: line for line in snapshot['lines']}
    allowed = {'position-' + str(n): item for n, item in enumerate(offer.get('items') or [], 1)
               if not is_service(item.get('title') or '')}
    if not set(choices) <= set(allowed):
        raise ValueError('Produktbilder dürfen nur vorhandenen Gerätepositionen zugeordnet werden.')
    for line_id, asset_id in choices.items():
        if not asset_id:
            continue
        if asset_id not in images:
            raise ValueError('Das Produktbild ist im angemeldeten Konto nicht verfügbar.')
        if len(descriptors) >= 30:
            raise ValueError('Höchstens 30 Produktbilder freigeben.')
        photo_id = 'product-' + str(len(descriptors) + 1)
        data = normalized_png(images[asset_id]['path'])
        item, line = allowed[line_id], lines[line_id]
        caption = 'Freigegebenes Produktbild: ' + str(item.get('title') or 'Komponente')
        descriptors.append(dict(id=photo_id, caption=caption[:300]))
        payload[photo_id] = data
        target = next(option for option in line['options'] if option['id'] == line['selected_option']) if line['editable'] else line
        target.pop('product_image_id', None)
        target.pop('product_image_note', None)
        target['product_photo_id'] = photo_id
        binding[line_id] = dict(product_identity=product_identity(item), asset_id=asset_id)
    if descriptors:
        snapshot['product_images'] = descriptors
    return payload, binding
