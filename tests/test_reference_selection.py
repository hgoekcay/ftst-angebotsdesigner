from reference_selection import suggest
import app as module
from test_persistence import client, isolated_storage
from test_baseline import raw


def test_four_relevant_photos_and_no_stock_or_logos():
    images = {str(n): {'category': 'Alarmanlage', 'title': f'Melder {n}'} for n in range(5)}
    images.update({'logo': {'category': 'Logo'}, 'stock': {'category': 'Alarmanlage', 'kind': 'Symbolfoto'},
                   'camera': {'category': 'Videoüberwachung', 'title': 'Kamera'}})
    assert suggest(images, 'Alarmanlage') == ['0', '1', '2', '3']
    assert suggest(images, 'Rauchmeldeanlage') == []


def test_combined_photos_require_relevant_content_and_prefer_variety():
    images = {'a': {'category': 'Kombination', 'title': 'Kamera und Alarmsirene – Nahansicht'},
              'b': {'category': 'Kombination', 'title': 'Kamera und Alarmsirene – Fassadenansicht'},
              'c': {'category': 'Kombination', 'title': 'Bewegungsmelder mit Kamera'},
              'd': {'category': 'Kombination', 'title': 'Türstation'}}
    assert suggest(images, 'Alarmanlage', 2) == ['c', 'b']
    assert 'd' not in suggest(images, 'Alarmanlage')


def test_manual_empty_selection_and_return_to_auto(client):
    store = module.offer_store()
    offer = {'id': '42', 'offer_type': 'Videoüberwachung'}
    import materials
    assert len(materials.enrich(offer, store)['reference_images']) == 2
    assert client.post('/offer/42/references', data={}).status_code == 302
    assert materials.enrich(offer, store)['reference_images'] == []
    assert not offer['reference_selection_auto']
    assert client.post('/offer/42/references', data={'action': 'auto'}).status_code == 302
    assert len(materials.enrich(offer, store)['reference_images']) == 2
    assert offer['reference_selection_auto']
