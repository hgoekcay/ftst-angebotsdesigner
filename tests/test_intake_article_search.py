"""Intake device types stay suggestions, and room names never select products."""
from copy import deepcopy
import re

import pytest

import app as module
from quote_drafts import candidates, fingerprint
from test_persistence import isolated_storage


@pytest.fixture
def articles():
    titles = [
        'Ajax MotionProtect weiß', 'Ajax MotionCam schwarz', 'Ajax DoorProtect',
        'Ajax HomeSiren', 'Ajax StreetSiren', 'Ajax KeyPad', 'Ajax KeyPad Indoor', 'Ajax KeyPad Outdoor',
        'Hub', 'Ajax Hub 2', 'Ajax Hub 2 Plus', 'Ajax Zentrale', 'Ajax ReX', 'Ajax ReX 2 für Hub',
        'Ajax Hub Batterie', 'Ajax Halterung für Hub', 'Ajax Netzteil für Hub 2', '12V PSU für Hub',
        'Ajax Hub Zubehör', 'Ajax FireProtect', 'Ajax ReX für Flur EG', 'Ajax Innenleuchte',
        'Ajax Außenleuchte', 'Ajax Montageort Schild',
    ]
    return [dict(id=str(index), title=title, article_number='ART-' + str(index), sales_price='123.45')
            for index, title in enumerate(titles)]


@pytest.mark.parametrize('requirement,expected', [
    ('Bewegungsmelder', {'Ajax MotionProtect weiß', 'Ajax MotionCam schwarz'}),
    ('Magnetkontakt', {'Ajax DoorProtect'}),
    ('Innensirene', {'Ajax HomeSiren'}),
    ('Außensirene', {'Ajax StreetSiren'}),
    ('Bedienteil innen', {'Ajax KeyPad', 'Ajax KeyPad Indoor'}),
    ('Bedienteil außen', {'Ajax KeyPad', 'Ajax KeyPad Outdoor'}),
    ('Zentrale', {'Hub', 'Ajax Hub 2', 'Ajax Hub 2 Plus', 'Ajax Zentrale'}),
])
@pytest.mark.parametrize('room', ['', ' · Raum / Montageort: Flur EG', ' · Raum / Montageort: Innenleuchte Montageort'])
def test_all_intake_shortcuts_match_device_families_without_room_only_hits(articles, requirement, expected, room):
    original = deepcopy(articles)
    result = candidates('Ajax ' + requirement + room, articles)
    assert {row['title'] for row in result} == expected
    assert all('article_id' not in row for row in result)
    assert articles == original


def test_central_search_alias_requires_ajax_context_and_keeps_exact_article_lookup(articles):
    assert 'Hub' not in {row['title'] for row in candidates('Zentrale', articles)}
    number = next(row['article_number'] for row in articles if row['title'] == 'Ajax ReX 2 für Hub')
    result = candidates(number + ' · Raum / Montageort: Flur EG', articles)
    assert [row['title'] for row in result] == ['Ajax ReX 2 für Hub']


@pytest.mark.parametrize('query,expected,excluded', [
    ('Netzteil für Ajax Zentrale', 'Ajax Netzteil für Hub 2', 'Ajax ReX 2 für Hub'),
    ('Ajax ReX Repeater für Zentrale', 'Ajax ReX 2 für Hub', 'Ajax Netzteil für Hub 2'),
    ('PSU für Ajax Zentrale', '12V PSU für Hub', 'Ajax ReX 2 für Hub'),
])
def test_explicitly_requested_hub_accessory_is_still_searchable(articles, query, expected, excluded):
    titles = {row['title'] for row in candidates(query, articles)}
    assert expected in titles
    assert excluded not in titles


def test_hub_suggestions_do_not_assign_article_or_change_quantity_and_price(monkeypatch, articles):
    monkeypatch.setenv('BILLOMAT_ID', 'intake-search')
    project = dict(title='Alarmanlage', notes='Zentrale im Flur')
    draft = dict(revision='saved', source=fingerprint(project), client_id='',
                 rows=[dict(description='Ajax Zentrale · Raum / Montageort: Flur EG', quantity='2', article_id='')],
                 catalog=dict(articles=articles, clients=[], units=[], taxes=[], settings={}))
    before = deepcopy(draft)
    store = module.offer_store()
    store.put_record('intake-search', 'project', 'one', project)
    store.put_record('intake-search', 'quote', 'one', draft)
    response = module.app.test_client().get('/projects/one/quote')
    assert response.status_code == 200
    options = re.search(r'<select id="article0" name="article_id">(.*?)</select>', response.text, re.S)[1]
    assert 'Hub 2' in options and 'ReX' not in options and 'Netzteil' not in options
    assert re.findall(r'<option value="([^"]*)" selected>', options) == ['']
    assert 'Raum / Montageort: Flur EG' in response.text
    assert store.record('intake-search', 'quote', 'one') == before
