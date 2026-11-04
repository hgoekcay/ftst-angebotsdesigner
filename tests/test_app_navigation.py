import app as module
from app_navigation import navigation


def test_bottom_tabs_and_ingress_links_are_present():
    client = module.app.test_client()
    response = client.get('/more', headers={'X-Ingress-Path': '/api/hassio_ingress/test'})
    assert response.status_code == 200
    for path in ('offers', 'materials', 'company', 'more', 'email-settings'):
        assert 'href="/api/hassio_ingress/test/' + path + '"' in response.text
    assert 'aria-label="Hauptnavigation"' in response.text
    assert 'aria-current="page"' in response.text


def test_customer_portal_returns_to_exact_offer_without_history():
    with module.app.test_request_context('/offer/42/portal'):
        back, tabs = navigation(module.ingress)
        assert 'href="/offer/42"' in back
        assert 'href="/offers" aria-current="page"' in tabs
        assert 'history' not in back


def test_deep_pages_use_existing_get_parent_or_home():
    for path, expected in [('/offer/42', '/offers'), ('/email-delivery/key/document', '/email-delivery/key'),
                           ('/customers/42/edit', '/customers/42'), ('/email-settings', '/')]:
        with module.app.test_request_context(path):
            back, _ = navigation(module.ingress)
            assert 'href="' + expected + '"' in back


def test_mobile_layout_hides_top_menu_and_reserves_bottom_space():
    from pathlib import Path
    css = (Path(module.__file__).parent / 'static/apple-design.css').read_text()
    assert '.appnav{display:none!important}' in css
    assert 'grid-template-columns:repeat(4,minmax(0,1fr))' in css
    assert '100px + env(safe-area-inset-bottom,0px)' in css
