from werkzeug.datastructures import MultiDict
import app as module
from asset_library import catalog
from test_persistence import client, isolated_storage
from test_baseline import raw


def test_selection_groups_sources_and_saved_counter(client):
    keys = ['builtin-video-entry', 'builtin-access-card']
    assert client.post('/offer/42/references', data=MultiDict([('images', k) for k in keys])).status_code == 302
    page = module.app.test_client().get('/offer/42/references').text
    assert '<h2>Videoüberwachung</h2>' in page
    assert '<h2>Zutrittskontrolle</h2>' in page
    assert 'Eigene Montage · FTST' in page
    assert 'Symbolbild · Adobe Stock' in page
    assert 'aria-live="polite">2</span>' in page
    assert page.count('checked') >= 2
    assert 'value="builtin-ftst-wide"' not in page


def test_selection_limit_and_empty_selection_without_javascript(client):
    keys = list(catalog(module.offer_store(), 'test'))
    assert len(keys) >= 9
    assert client.post('/offer/42/references', data=MultiDict([('images', k) for k in keys[:4]])).status_code == 302
    for count in (5, 8, 9):
        assert client.post('/offer/42/references', data=MultiDict([('images', k) for k in keys[:count]])).status_code == 400
        assert module.offer_store().records('test', 'offer_images')['42']['ids'] == keys[:4]
    repeated = keys[:4] + keys[:4]
    assert client.post('/offer/42/references', data=MultiDict([('images', k) for k in repeated])).status_code == 302
    assert module.offer_store().records('test', 'offer_images')['42']['ids'] == keys[:4]
    assert client.post('/offer/42/references', data={}).status_code == 302
    assert module.offer_store().records('test', 'offer_images')['42']['ids'] == []


def test_legacy_selection_limits_valid_unique_images_without_rewriting(client):
    import materials
    store = module.offer_store()
    keys = list(catalog(store, 'test'))[:8]
    original = ['missing', keys[0], keys[0], *keys[1:]]
    store.put_record('test', 'offer_images', '42', {'ids': original})
    offer = materials.enrich({'id': '42', 'offer_type': 'Alarmanlage'}, store)
    assert offer['reference_image_ids'] == keys[:4]
    assert len(offer['reference_images']) == 4
    assert offer['reference_selection_limited']
    assert store.records('test', 'offer_images')['42']['ids'] == original
    page = client.get('/offer/42/references').text
    assert 'von maximal 4 Bildern' in page
    assert 'auf einer einzigen Referenzseite' in page
    assert 'ältere Auswahl enthält mehr als vier Bilder' in page
    assert store.records('test', 'offer_images')['42']['ids'] == original


def test_library_groups_logos_and_escapes_upload_titles(client, tmp_path):
    from materials import image_groups
    from markupsafe import escape
    markup = image_groups({'x': {'title': '<script>bad</script>', 'category': '<b>Area</b>'}}, lambda p: '/' + p, escape, [])
    assert '<script>bad</script>' not in markup
    assert '&lt;script&gt;' in markup
    assert '&lt;b&gt;Area&lt;/b&gt;' in markup
    page = client.get('/materials').text
    assert 'Logos &amp; Marken' in page
    assert 'FTronics · Produktmarke' in page
