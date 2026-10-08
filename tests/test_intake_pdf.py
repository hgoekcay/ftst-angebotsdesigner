from io import BytesIO
from pathlib import Path
import subprocess

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject
from werkzeug.datastructures import FileStorage

import intake_pdf as pdf
import project_intake as intake
from intake_systems import SYSTEMS
from test_persistence import isolated_storage  # noqa: F401
from test_project_intake import ui, fields, PATH, HEADERS  # noqa: F401


def filled(system='alarm', **values):
    source = Path(pdf.__file__).parent / 'static' / f'FTST-Technikeraufnahme-{SYSTEMS[system][2]}.pdf'
    writer = PdfWriter(clone_from=source)
    if values:
        writer.update_page_form_field_values(None, values, auto_regenerate=False)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


@pytest.mark.parametrize('system', list(SYSTEMS))
def test_all_templates_values_and_detail_counts_are_not_added(system):
    values = {'kunde' if system == 'intercom' else 'projekt': 'Müller & Söhne',
              'adresse' if system == 'intercom' else 'objektadresse': 'Türstraße 4'}
    count = 'position_1_menge' if system == 'alarm' else 'komponente_1_anzahl' if system == 'intercom' else 'bedarf_1_2'
    second = count.replace('_1_', '_2_')
    detail = {'alarm':'detail_1_menge', 'video':'kamera_1_3', 'access':'tuer_1_3', 'cylinder':'zylinder_1_6', 'intercom':'rufverteilung'}[system]
    values.update({count:'2', second:'0', detail:'2'})
    raw = filled(system, **values)
    parsed = pdf.read_upload(FileStorage(stream=BytesIO(raw), filename='form.pdf'))
    result = pdf.proposal(parsed, {})
    assert parsed['system'] == system
    assert result['fields']['customer_name'] == 'Müller & Söhne'
    assert result['fields']['object_address'] == 'Türstraße 4'
    assert [r['quantity'] for r in result['components']] == ['2']
    assert values[detail] in result['fields']['notes']
    assert result['review_required'] and result['status'] == 'review'
    assert result['fields']['manufacturer'] == ('Ajax' if system == 'alarm' else '')


def test_unknown_count_kept_as_evidence_and_requires_review(ui):
    client, store, model, original = ui
    data = fields(client, action='import_pdf', replace_intake='yes')
    data['intake_pdf'] = (BytesIO(filled(position_1_menge='ca. 6', zentrale_ja='/Yes', kontakt='test@example.com')), 'test.pdf')
    assert client.post(PATH, data=data).status_code == 303
    saved = store.record('one', intake.KIND, 'job-1')
    assert saved['fields']['central'] == 'yes'
    assert saved['components'][0]['quantity'] == ''
    assert 'ca. 6' in saved['components'][0]['evidence']
    assert 'test@example.com' in saved['fields']['notes']
    assert store.record('one', 'project', 'job-1') == original
    assert client.post(PATH, data=fields(client, action='apply', description=['Bewegungsmelder'], quantity=['6'])).status_code == 400
    model.assert_not_called()


def test_import_does_not_bypass_csrf_or_replace_or_revision(ui):
    client, store, _, original = ui
    for changes in ({'csrf':'bad'}, {'replace_intake':''}, {'revision':'stale'}):
        data = fields(client, action='import_pdf', replace_intake='yes', **{k:v for k,v in changes.items() if k != 'replace_intake'})
        if 'replace_intake' in changes:
            data['replace_intake'] = changes['replace_intake']
        data['intake_pdf'] = (BytesIO(filled(projekt='Test')), 'test.pdf')
        assert client.post(PATH, data=data).status_code in (400,409)
    assert store.record('one', intake.KIND, 'job-1') is None
    assert store.record('one', 'project', 'job-1') == original


def test_failed_import_preserves_saved_fields(ui):
    client, store, _, _ = ui
    assert client.post(PATH, data=fields(client)).status_code == 303
    before = store.record('one', intake.KIND, 'job-1')
    data = fields(client, action='import_pdf', replace_intake='yes')
    data['intake_pdf'] = (BytesIO(b'%PDF-broken'), 'test.pdf')
    response = client.post(PATH, data=data)
    assert response.status_code == 400 and 'Firma Test' in response.text
    assert store.record('one', intake.KIND, 'job-1') == before


def test_empty_encrypted_and_flattened_rejected():
    with pytest.raises(ValueError, match='keine gespeicherten'):
        pdf.extract(filled())
    writer = PdfWriter(clone_from=BytesIO(filled(projekt='Test')))
    writer.encrypt('secret')
    output = BytesIO(); writer.write(output)
    with pytest.raises(ValueError, match='Passwort'):
        pdf.extract(output.getvalue())
    writer = PdfWriter(clone_from=BytesIO(filled(projekt='Test')))
    writer.root_object.pop(NameObject('/AcroForm'))
    output = BytesIO(); writer.write(output)
    with pytest.raises(ValueError, match='Formularfelder'):
        pdf.extract(output.getvalue())


def test_limits_and_timeout(monkeypatch):
    with pytest.raises(ValueError, match='5 MB'):
        pdf.read_upload(FileStorage(stream=BytesIO(b'%PDF-'+b'x'*pdf.MAX_BYTES)))
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired('reader', 12)
    monkeypatch.setattr(pdf.subprocess, 'run', timeout)
    with pytest.raises(ValueError, match='rechtzeitig'):
        pdf.read_upload(FileStorage(stream=BytesIO(b'%PDF-')))
    assert pdf._lock.acquire(blocking=False)
    pdf._lock.release()


def test_html_is_data_and_checkbox_does_not_confirm(ui):
    client, store, _, _ = ui
    data = fields(client, action='import_pdf', replace_intake='yes')
    data['intake_pdf'] = (BytesIO(filled(projekt='<script>alert(1)</script>', position_1_menge='1', mengen_geprueft='/Yes')), 'form.pdf')
    assert client.post(PATH, data=data).status_code == 303
    page = client.get(PATH, headers=HEADERS).text
    assert '<script>alert(1)</script>' not in page
    assert '&lt;script&gt;' in page
    assert store.record('one', intake.KIND, 'job-1')['review_required']

