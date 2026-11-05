import pytest
from website_portal import category, snapshot, suggested_building_type
from test_website_portal import offer


@pytest.mark.parametrize('title,expected', [('Alarmanlage Wohnhaus', 'residential'), ('Industrie Lagerhalle', 'industrial'),
                                         ('Kameras Büro', 'commercial'), ('Alarmanlage', 'neutral'),
                                         ('Wohnhaus und Lagerhalle', 'neutral')])
def test_building_proposal_uses_explicit_project_description(title, expected):
    source = offer()
    source['title'] = title
    assert suggested_building_type(source) == expected


def test_company_name_does_not_imply_industry_and_owner_can_override():
    source = offer()
    source['client']['company'] = 'Industrie Muster GmbH'
    assert suggested_building_type(source) == 'neutral'
    assert snapshot(source, 1, building_type='industrial')['building_type'] == 'industrial'
    with pytest.raises(ValueError):
        snapshot(source, 1, building_type='unsafe')


@pytest.mark.parametrize('title,expected', [('Elektronischer Schließzylinder', 'lock'), ('Smart Lock', 'lock'),
                                         ('Zutrittsleser', 'access'), ('Türöffner', 'access'),
                                         ('Montage Türschloss', 'service'), ('Ajax DoorProtect', 'contact')])
def test_access_and_lock_visuals_do_not_replace_service_or_contact(title, expected):
    assert category(title) == expected
