from copy import deepcopy
from datetime import date, timedelta
import pytest
from ftst_product_images import PRODUCT_SLUGS, product_image
from website_portal import product_visual, snapshot


@pytest.mark.parametrize('slug', PRODUCT_SLUGS)
def test_each_public_model_gets_only_its_own_image(slug):
    code = slug.upper()
    expected = 'ftst-' + slug
    assert product_image('FTronics ' + code) == expected
    assert product_image('FTronics ' + code.replace('-', '')) == expected
    assert product_image('FTronics ' + code.replace('-', ' ')) == expected
    assert product_visual('FTronics ' + code) == {'product_image_id': expected}


@pytest.mark.parametrize('title,description', [
    ('FC-8D-PRO und FC-8D-ZOOM', ''),
    ('FC-8D', 'Modell: FC-8D-PRO'),
    ('FC-8D-PRO', 'Alternativ FC-8D-ZOOM'),
    ('FC-8D-PRO2', ''), ('FC8DPRO2', ''), ('FC-8D-ULTRA', ''),
    ('FC-8D PLUS', ''), ('FC-8D PRO2', ''),
    ('FN-128', ''), ('FC-8D-PRO', 'Unbekanntes Modell FC-9D'),
    ('Kamera', 'Kompatibel mit FC-8D-PRO'),
    ('Halterung für FC-8D-PRO', ''),
    ('Kamera', 'Passend für FC-8D-ZOOM'),
    ('Recorder', 'Unterstützt FC-8D und FC-8D-PRO'),
    ('Kamera', 'Compatible with FC-8D-PRO'),
])
def test_unknown_conflicting_and_compatibility_only_models_get_no_photo(title, description):
    assert product_image(title, description) is None
    assert product_visual(title, description) == {}


def test_primary_model_remains_exact_with_compatibility_targets():
    assert product_image('FC-8D-PRO', 'Kompatibel mit FN-16 und FC-8D') == 'ftst-fc-8d-pro'
    assert product_image('FS-30 Halterung', 'Passend für FC-8D-PRO') == 'ftst-fs-30'
    assert product_image('IP-Kamera', 'Modell: FC-8D-ZOOM. Kompatibel mit FN-16.') == 'ftst-fc-8d-zoom'
    assert product_image('Rekorder', 'FTronics FN-64 Pro; unterstützt FC-8D') == 'ftst-fn-64-pro'


def test_fc8d_family_never_shares_image():
    assert len({product_image('FC-8D'), product_image('FC-8D-PRO'), product_image('FC-8D-ZOOM')}) == 3
    assert product_visual('FC-8D-PRO', 'weiß') == {'product_image_id': 'ftst-fc-8d-pro'}
    assert product_visual('FC-8D-ZOOM', 'schwarz') == {'product_image_id': 'ftst-fc-8d-zoom'}


def test_camera_recorder_accessory_snapshot_fixed_and_editable_images_without_price_changes():
    today = date.today()
    offer = dict(id=42, date=str(today), validity_date=str(today+timedelta(days=7)),
                 status='OPEN', title='Synthetisches Kamerasystem', total_net='300.00', total_gross='357.00',
                 client={'name': 'Synthetischer Test'}, items=[
                     dict(title='FTronics FC-8D-PRO Kamera', description='', quantity=1, unit_price='100.00', total_net='100.00'),
                     dict(title='FTronics FN-16 Rekorder', description='Kompatibel mit FC-8D und FC-8D-ZOOM', quantity=1, unit_price='100.00', total_net='100.00'),
                     dict(title='FTronics FS-30 Zubehör', description='Passend für FC-8D-PRO', quantity=1, unit_price='100.00', total_net='100.00')])
    original = deepcopy(offer)
    snap = snapshot(offer, 1, ['position-1', 'position-3'])
    assert snap['lines'][0]['options'][0]['product_image_id'] == 'ftst-fc-8d-pro'
    assert snap['lines'][1]['product_image_id'] == 'ftst-fn-16'
    assert snap['lines'][2]['options'][0]['product_image_id'] == 'ftst-fs-30'
    assert snap['totals'] == {'net':'300.00', 'tax':'57.00', 'gross':'357.00'}
    assert offer == original


def test_existing_ajax_mapping_kept():
    assert product_visual('Ajax MotionProtect weiß')['product_image_id'] == 'ax-motion-protect-w'
    assert product_visual('Ajax Superior GlassProtect weiß')['product_image_id'] == 'ax-superior-glass-protect-w'
    assert product_visual('TAG/Chip')['product_image_id'] == 'ax-tag-w'
    assert product_visual('Ajax DoorProtect')['product_image_note'].startswith('Beispielabbildung')


@pytest.mark.parametrize('suffix',['',' weiß',' schwarz'])
def test_art1020_day_night_camera_never_becomes_ajax_tag(suffix):
    from website_portal import product_image as any_product_image
    title='[ART-1020] 8MP Bulletkamera mit Fixobjektiv 2,8mm Tag/Nacht KI(Personenerkennung,Fahrzeugerkennung'+suffix
    description='FTronics 8MP 4K; 1/2 CMOS; 0.01 Lux; Fixobjektiv 2.8; 120 WDR; 40m IR; IK10/IP67; 25bps'
    assert any_product_image(title,description) is None
    assert product_visual(title,description)=={}


@pytest.mark.parametrize('title',['Tag/Nacht Kamera weiß','Tag Nacht Kamera weiß','Tag-Nacht Camera schwarz',
                                  'Tag DayNight Recorder weiß','RFID Tag Kamera weiß'])
def test_camera_context_never_replaced_by_tag_chip(title):
    assert product_visual(title)=={}


@pytest.mark.parametrize('title',['Ajax TAG','TAG/Chip','RFID Tag','[ART-42] Ajax TAG','[ART-42] TAG/Chip'])
def test_primary_tag_product_still_has_labelled_example(title):
    assert product_visual(title)=={'product_image_id':'ax-tag-w','product_image_note':'Beispielabbildung; Farbe nach Abstimmung.'}


@pytest.mark.parametrize('title',['[ART-125] 4 Kanal Aufzeichnungsgerät','[ART-1033] Switch 4PoE + 2Uplink 100Mbps 60W',
                                  '[ART-151] 2TB HDD','[ART-1045] Polyester IP65 Box',
                                  '[ART-109] Werkzeuglos RJ45 CAT5/6/7','[ART-857] Cat6 CCA grau'])
def test_generic_hardware_needs_reviewed_manual_picture(title):
    assert product_visual(title)=={}


@pytest.mark.parametrize('title',['FC-8D/PRO','FC-8D / ZOOM','FN-8/16','FC-8D PRO MINI','FC-8D PRO ZOOM'])
def test_slashed_or_stacked_variant_names_never_fall_back_to_base(title):
    assert product_visual(title)=={}
