from copy import deepcopy

import pytest

from quote_drafts import candidates


@pytest.mark.parametrize('label', ['Ajax Tür-/Fensterkontakt', 'Ajax Fensterkontakte', 'Ajax Tür/Fensterkontakt'])
def test_pdf_contact_labels_find_ajax_contact_family(label):
    articles = [dict(id='1', title='DOOR-PROTECT'), dict(id='2', title='Door Protect Plus'),
                dict(id='3', title='Ajax MotionProtect'), dict(id='4', title='Dahua Fensterkontakt')]
    assert {row['id'] for row in candidates(label, articles)} == {'1', '2'}


@pytest.mark.parametrize('query', ['Dahua', '2 Dahua', 'Dahua unbekanntes Gerät'])
def test_dahua_brand_does_not_suggest_unrelated_catalogue(query):
    articles = [dict(id='1', title='Dahua Außenstation'), dict(id='2', title='Dahua Kamera')]
    assert candidates(query, articles) == []


def test_supported_manufacturers_do_not_cross_match_and_catalogue_is_unchanged():
    articles = [dict(id='1', title='Dahua Türkontakt'), dict(id='2', title='Ajax Türkontakt'),
                dict(id='3', title='Türkontakt', article_number='D-3')]
    before = deepcopy(articles)
    assert {row['id'] for row in candidates('Dahua Türkontakt', articles)} == {'1', '3'}
    assert {row['id'] for row in candidates('Ajax Türkontakt', articles)} == {'2'}
    assert candidates('D-3', articles) == [articles[2]]
    assert articles == before


def test_dahua_device_term_is_required_but_brandless_titles_remain_searchable():
    articles = [dict(id='1', title='Dahua Außenstation'), dict(id='2', title='Dahua Kamera'),
                dict(id='3', title='Außenstation Video'), dict(id='4', title='Ajax Außenstation')]
    assert {row['id'] for row in candidates('Dahua Außenstation', articles)} == {'1', '3'}

