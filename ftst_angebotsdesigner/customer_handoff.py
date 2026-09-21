"""Explicit, account-scoped customer selection after reviewed customer creation."""
import json
import uuid
from datetime import datetime, timezone

from quote_drafts import catalog_snapshot, components, fingerprint
from storage import RecordConflict


def context(store, identity, project_id):
    if not project_id:
        return {}
    project = store.record(identity, 'project', project_id)
    if project is None:
        raise ValueError('Das zugehörige Projekt ist nicht verfügbar.')
    draft = store.record(identity, 'quote', project_id) or {}
    return dict(project=project_id, source=fingerprint(project), revision=draft.get('revision', ''))


def select_created(store, identity, customer, result, remote):
    target = customer.get('quote_context') or {}
    key = target.get('project')
    if (not key or not result or result.get('status') != 'created'
            or result.get('fields') != customer.get('fields')):
        raise ValueError('Nur einen eindeutig bestätigten Kunden in den zugehörigen Entwurf übernehmen.')
    project = store.record(identity, 'project', key)
    old = store.record(identity, 'quote', key)
    if (not project or fingerprint(project) != target.get('source')
            or (old or {}).get('revision', '') != target.get('revision')
            or store.record(identity, 'quote_transfer', key) or project.get('offer_id')):
        raise RecordConflict('Das Projekt oder der Entwurf wurde geändert oder bereits übertragen. Zum Angebot zurückkehren und die Kundenauswahl dort neu beginnen. Der angelegte Kunde bleibt in Billomat erhalten.')
    catalog = catalog_snapshot(remote.draft_catalog())
    selected = [c for c in catalog['clients'] if str(c.get('id')) == str(result.get('client_id'))
                and str(c.get('archived')) != '1']
    if len(selected) != 1:
        raise ValueError('Der neue Kunde ist noch nicht eindeutig im aktiven Billomat-Katalog verfügbar. Bitte später erneut übernehmen; keinen zweiten Kunden anlegen.')
    draft = dict(old or dict(rows=components(project), source=fingerprint(project)))
    draft.update(client_id=str(result['client_id']), catalog=catalog,
                 catalog_at=datetime.now(timezone.utc).isoformat(timespec='seconds'),
                 reviewed=False, tax_confirmed='', revision=uuid.uuid4().hex)
    def save(live, db):
        def record(kind):
            row = db.execute('SELECT payload FROM records WHERE account=? AND kind=? AND id=?',
                             (identity, kind, key)).fetchone()
            return json.loads(row[0]) if row else None
        if live != old or record('project') != project or record('quote_transfer'):
            raise RecordConflict('Projekt oder Kalkulation wurden während des Ladens geändert. Bitte zum Angebot zurückkehren und erneut prüfen.')
        return draft
    store.transact_record(identity, 'quote', key, save)
    return key
