import pytest
from access_products import identify, review_html
from website_portal import category
from access_products import product_image


@pytest.mark.parametrize('title,role,cat', [
    ('Bold Connect', 'gateway', 'access'), ('Bold Elite SX-33', 'lock', 'lock'),
    ('Bold Smart Lock', 'lock', 'lock'), ('Smartloxx Z1-33', 'lock', 'lock'),
    ('Smartloxx Multi Controller im Gehäuse', 'controller', 'access'),
    ('Smartloxx multiControl Platine', 'controller', 'access'),
    ('ekey xLine Fingerprint', 'reader', 'access'), ('ekey Controller REG', 'controller', 'access'),
    ('Bold Clicker', 'accessory', 'other'), ('Smartloxx', 'unknown', 'other')])
def test_brand_components_keep_their_own_role(title, role, cat):
    assert identify(title)[1] == role
    assert category(title) == cat


def test_compatibility_and_service_are_not_sold_model():
    assert identify('Netzteil für Bold Connect') is None
    assert identify('Montage Smartloxx Zylinder') is None
    assert identify('Bold / Smartloxx Schloss') is None
    assert category('Montage Smartloxx Zylinder') == 'service'


def test_review_does_not_mutate_prices_or_duplicate_prompts():
    items = [{'title': 'Bold Elite', 'quantity': 3}, {'title': 'Bold Connect', 'quantity': 1}]
    before = repr(items)
    html = review_html(items)
    assert html.count('<strong>bold</strong>') == 1
    assert 'nicht automatisch ein Connect pro Schloss' in html
    assert repr(items) == before
    assert review_html([{'title': 'Ajax Hub'}]) == ''


def test_connect_photo_is_not_used_for_locks_sets_or_unknown_generations():
    assert product_image('Bold Connect') == 'bold-connect'
    for title in ('Bold Connect 2', 'Bold Elite mit Connect', 'Netzteil für Bold Connect', 'Smartloxx multiControl'):
        assert product_image(title) is None
