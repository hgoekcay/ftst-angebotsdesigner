import pytest

import project_intake as intake
from intake_systems import SYSTEMS
from test_persistence import isolated_storage  # noqa: F401
from test_project_intake import ui, fields, PATH, HEADERS  # noqa: F401


@pytest.mark.parametrize('system', list(SYSTEMS))
def test_answered_defaults_disappear_custom_questions_stay_and_reopen(system):
    original = intake.initial({})['fields']
    original['system_type'] = system
    original['manufacturer'] = '' if system != 'alarm' else 'Ajax'
    questions = intake.open_questions(original) + ['Leitungsweg mit Kunde klären.', 'Welche Serie passt zur vorhandenen Leitung?']
    answered = dict(original, central='yes', siren='no', installation='3 Stunden', variant='Geprüfte Serie',
                    manufacturer='Dahua' if system != 'alarm' else 'Ajax', system_details='Bestand geprüft')
    assert intake.open_questions(answered, questions) == questions[-2:]
    reopened = dict(answered, variant='')
    assert intake.open_questions(reopened, questions) == questions[-2:] + intake.required_questions(reopened)


def test_legacy_stale_questions_display_without_mutation_then_save(ui):
    client, store, _, project = ui
    record = intake.initial(project)
    record['questions'] = intake.open_questions(record['fields']) + ['Zugang am Montag klären.']
    record['fields'].update(central='yes', siren='no', variant='Jeweller', installation='3 Stunden')
    store.put_record('one', intake.KIND, 'job-1', record)
    page = client.get(PATH, headers=HEADERS).text
    assert 'Ist eine Ajax-Zentrale vorhanden oder wird eine neue benötigt?' not in page
    assert 'Zugang am Montag klären.' in page
    assert store.record('one', intake.KIND, 'job-1') == record
    result = client.post(PATH, data=fields(client, central='yes', siren='no', variant='Jeweller',
                        installation='3 Stunden', questions='\n'.join(record['questions'])))
    assert result.status_code == 303
    assert store.record('one', intake.KIND, 'job-1')['questions'] == ['Zugang am Montag klären.']
    assert store.record('one', 'project', 'job-1') == project


def test_custom_questions_survive_handoff_and_missing_defaults_cannot_be_deleted(ui):
    client, store, _, _ = ui
    result = client.post(PATH, data=fields(client, action='apply', reviewed='yes',
                         description=['Bewegungsmelder'], quantity=['2'], evidence=['Geprüft'],
                         central='yes', siren='no', installation='3 Stunden', variant='Jeweller',
                         questions='Ist eine Ajax-Zentrale vorhanden oder wird eine neue benötigt?\nZugang klären.'))
    assert result.status_code == 303
    project = store.record('one', 'project', 'job-1')
    assert project['analysis']['questions'] == ['Zugang klären.']
    assert 'Offen: Ist eine Ajax-Zentrale' not in project['notes']
    assert 'Offen: Zugang klären.' in project['notes']
    assert intake.open_questions(dict(intake.initial({})['fields']), [])

