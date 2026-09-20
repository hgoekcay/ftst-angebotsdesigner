from copy import deepcopy
import re

import pytest

import app as module
from quote_drafts import candidates, components, fingerprint
from test_persistence import isolated_storage


@pytest.fixture
def articles():
    names = [
        'Ajax MotionProtect weiß', 'Ajax MotionCam PhOD schwarz', 'Ajax MotionProtect Outdoor',
        'Ajax MotionProtect Indoor', 'Ajax DoorProtect weiß', 'DoorProtect Plus schwarz',
        'Ajax HomeSiren weiß', 'Ajax StreetSiren DoubleDeck',
        'Ajax KeyPad weiß', 'Ajax KeyPad Outdoor', 'Ajax KeyPad Indoor',
        'Ajax Hub 2', 'Ajax FireProtect 2', 'Ajax ReX', 'Ajax Außenleuchte',
        'Ajax MotionProtect Halterung', 'Ajax Hood MotionProtect Outdoor',
    ]
    return [dict(id=str(index), title=name, article_number='TEST-' + str(index))
            for index, name in enumerate(names, 1)]


def titles(query, articles):
    return [row['title'] for row in candidates(query, articles)]


@pytest.mark.parametrize(('query', 'expected'), [
    ('Ajax Bewegungsmelder', {'Ajax MotionProtect weiß', 'Ajax MotionCam PhOD schwarz',
                             'Ajax MotionProtect Outdoor', 'Ajax MotionProtect Indoor'}),
    ('Ajax Magnetkontakt', {'Ajax DoorProtect weiß', 'DoorProtect Plus schwarz'}),
    ('Ajax Sirene', {'Ajax HomeSiren weiß', 'Ajax StreetSiren DoubleDeck'}),
])
def test_confirmed_ajax_device_descriptions_suggest_only_relevant_families(articles, query, expected):
    assert set(titles(query, articles)) == expected


def test_outside_keypad_prefers_explicit_outdoor_and_keeps_unspecified_variant_manual(articles):
    found = titles('Ajax Außenbedienteil', articles)
    assert found[0] == 'Ajax KeyPad Outdoor'
    assert set(found) == {'Ajax KeyPad Outdoor', 'Ajax KeyPad weiß'}


@pytest.mark.parametrize(('query', 'expected'), [
    ('Ajax Außensirene', ['Ajax StreetSiren DoubleDeck']),
    ('Ajax Sirene innen', ['Ajax HomeSiren weiß']),
])
def test_explicit_siren_location_does_not_suggest_opposite_variant(articles, query, expected):
    assert titles(query, articles) == expected


def test_explicit_motion_location_ranks_named_variant_and_excludes_opposite(articles):
    outside = titles('Ajax Bewegungsmelder außen', articles)
    assert outside[0] == 'Ajax MotionProtect Outdoor'
    assert 'Ajax MotionProtect Indoor' not in outside
    assert 'Ajax MotionCam PhOD schwarz' in outside
    assert 'Ajax Hub 2' not in outside and 'Ajax Außenleuchte' not in outside


@pytest.mark.parametrize(('short', 'long'), [('BM', 'Bewegungsmelder'), ('MK', 'Magnetkontakt')])
def test_abbreviations_expand_only_when_ajax_was_confirmed(articles, short, long):
    assert candidates(short, articles) == []
    assert set(titles('Ajax ' + short, articles)) == set(titles('Ajax ' + long, articles))


@pytest.mark.parametrize('query', ['Ajax', '4 Ajax', 'Ajax unbekannte Komponente', ''])
def test_brand_or_quantity_alone_never_ranks_the_entire_ajax_catalog(articles, query):
    assert candidates(query, articles) == []


def test_search_returns_catalog_variants_unchanged_and_does_not_assign_article_or_quantity(articles):
    before = deepcopy(articles)
    rows = components({'notes': '2 Ajax BM + 3 Ajax MK'})
    for row in rows:
        candidates(row['description'], articles)
    assert [row['quantity'] for row in rows] == ['2', '3']
    assert all('article_id' not in row for row in rows)
    assert articles == before


def test_exact_article_number_still_selects_its_search_result(articles):
    assert candidates('TEST-12', articles) == [articles[11]]


def test_plain_product_family_search_still_lists_variants_without_brand_inference(articles):
    assert {'Ajax MotionProtect weiß', 'Ajax MotionProtect Outdoor'} <= set(titles('MotionProtect', articles))


def test_german_compound_catalog_titles_still_match_without_location_only_hits():
    articles = [dict(id='1', title='Ajax Außensirene'), dict(id='2', title='Ajax Außenbedienteil'),
                dict(id='3', title='Ajax Außen LED'), dict(id='4', title='Ajax Bewegungsmelder')]
    assert titles('Ajax Außensirene', articles) == ['Ajax Außensirene']
    assert titles('Ajax Außenbedienteil', articles) == ['Ajax Außenbedienteil']
    assert titles('Ajax Bewegungsmelder', articles) == ['Ajax Bewegungsmelder']


def test_quote_dropdown_shows_ajax_suggestions_but_no_automatic_selection(monkeypatch, articles):
    monkeypatch.setenv('BILLOMAT_ID', 'ajax-test')
    project = dict(title='Alarmanlage', notes='2 Ajax Bewegungsmelder')
    draft = dict(revision='saved', source=fingerprint(project), client_id='',
                 rows=[dict(description='Ajax Bewegungsmelder', quantity='2', article_id='')],
                 catalog=dict(articles=articles, clients=[], units=[], taxes=[], settings={}))
    store = module.offer_store()
    store.put_record('ajax-test', 'project', 'one', project)
    store.put_record('ajax-test', 'quote', 'one', draft)
    response = module.app.test_client().get('/projects/one/quote')
    assert response.status_code == 200
    options = re.search(r'<select id="article0" name="article_id">(.*?)</select>', response.text, re.S)[1]
    assert 'MotionProtect' in options and 'MotionCam' in options and 'Hub 2' not in options
    assert re.findall(r'<option value="([^"]*)" selected>', options) == ['']
    assert store.record('ajax-test', 'quote', 'one') == draft
