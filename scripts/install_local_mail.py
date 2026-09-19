#!/usr/bin/env python3
"""Run on HA Advanced SSH only. No secrets are printed or copied off the server."""
import argparse
import json
import os
from pathlib import Path
import secrets
import shutil
import sys
import urllib.request

DESIGNER = '76b650ab_ftst_angebotsdesigner'
MAIL = 'local_ftst_strato_mail'
RECOVERY = Path('/share/ftst-local-mail-recovery-0.12.0')
VERSIONS = {DESIGNER: '0.12.0', MAIL: '0.3.0'}
ROOT = Path(__file__).resolve().parent.parent
HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def api(path, payload=None, timeout=900):
    token = os.environ.get('SUPERVISOR_TOKEN')
    if not token:
        raise RuntimeError('Supervisor-Zugang fehlt.')
    req = urllib.request.Request('http://supervisor' + path,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    with HTTP.open(req, timeout=timeout) as response:
        result = json.load(response)
    if result.get('result') != 'ok':
        raise RuntimeError('Supervisor-Aufruf fehlgeschlagen; keine Geheimnisse ausgeben.')
    return result.get('data', {})


def info(slug):
    return api('/addons/' + slug + '/info')


def private_write(path, content):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as file:
        file.write(content)


def backup():
    for slug, version in ((DESIGNER, '0.10.0'), (MAIL, '0.2.0')):
        if info(slug)['version'] != version:
            raise RuntimeError('Installierter Ausgangsstand abweichend; zuerst prüfen.')
    RECOVERY.mkdir(mode=0o700, exist_ok=False)
    password = secrets.token_urlsafe(48)
    private_write(RECOVERY / 'backup-password', password)
    result = api('/backups/new/partial', {'name': 'FTST vor lokaler Mail-Verbindung 0.12.0',
        'password': password, 'addons': [DESIGNER, MAIL], 'homeassistant': False, 'folders': [],
        'compressed': True})
    slug = result['slug']
    details = api('/backups/' + slug + '/info')
    if not details.get('protected'):
        raise RuntimeError('Verschlüsselte Sicherung nicht bestätigt.')
    private_write(RECOVERY / 'backup.json', json.dumps({'slug': slug, 'protected': True}))
    print('Verschlüsselte Sicherung bestätigt: ' + slug, flush=True)


def deploy():
    if not (RECOVERY / 'backup.json').is_file():
        raise RuntimeError('Bestätigte Sicherung fehlt.')
    source, target = ROOT / 'ftst_strato_mail', Path('/addons/ftst_strato_mail')
    if not source.is_dir() or not target.is_dir() or target.is_symlink():
        raise RuntimeError('Lokale Mail-App-Quelle fehlt oder Ziel unerwartet.')
    prior = RECOVERY / 'mail-source-0.2.0'
    stage = Path('/addons/.ftst_strato_mail-0.3.0-stage')
    old = Path('/addons/.ftst_strato_mail-0.2.0-old')
    if prior.exists() or stage.exists() or old.exists():
        raise RuntimeError('Installation bereits begonnen; Zustand zuerst prüfen.')
    shutil.copytree(source, stage, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copytree(target, prior)
    target.rename(old)
    try:
        stage.rename(target)
    except OSError:
        old.rename(target)
        raise
    shutil.rmtree(old)  # The same source is retained under RECOVERY, outside the app store.
    api('/store/reload', {})
    for slug, version in VERSIONS.items():
        current = info(slug)
        if current.get('version_latest') != version:
            raise RuntimeError('Erwartete neue Version nicht im App-Store; angehalten.')
        if current['version'] != version:
            print('Aktualisierung: ' + slug, flush=True)
            api('/store/addons/' + slug + '/update', {'backup': False})
        if info(slug)['version'] != version:
            raise RuntimeError('Version nach Update nicht bestätigt.')
    print('Beide App-Versionen bestätigt.', flush=True)


def connect():
    details = {slug: info(slug) for slug in VERSIONS}
    if any(details[slug]['version'] != version for slug, version in VERSIONS.items()):
        raise RuntimeError('Zuerst beide Apps aktualisieren.')
    options = {slug: details[slug]['options'] for slug in VERSIONS}
    if not options[MAIL].get('password') or not options[DESIGNER].get('billomat_id'):
        raise RuntimeError('Bestehende Optionen nicht zugänglich oder unvollständig.')
    if options[MAIL].get('email') != 'info@ftst.eu' or options[MAIL].get('folder', 'INBOX') != 'INBOX':
        raise RuntimeError('Unerwartetes Postfach; nicht umkonfigurieren.')
    token = options[MAIL].get('bridge_token') or secrets.token_urlsafe(48)
    new_mail = dict(options[MAIL], bridge_token=token)
    new_designer = dict(options[DESIGNER], strato_provider='bridge', strato_bridge_token=token,
        strato_imap_enabled=True, strato_auto_import=True, strato_auto_ai=True, strato_poll_seconds=300)
    for slug, values in ((MAIL, new_mail), (DESIGNER, new_designer)):
        result = api('/addons/' + slug + '/options/validate', values)
        if result.get('valid') is not True:
            raise RuntimeError('Neue Optionen nicht gültig; keine Änderung.')
    api('/addons/' + MAIL + '/options', {'options': new_mail})
    try:
        api('/addons/' + DESIGNER + '/options', {'options': new_designer})
    except Exception:
        api('/addons/' + MAIL + '/options', {'options': options[MAIL]})
        raise
    for slug in (MAIL, DESIGNER):
        api('/addons/' + slug + '/restart', {})
    print('Interne Verbindung und Automatik konfiguriert; Startpunkt noch in der App setzen.', flush=True)


def verify():
    details = info(MAIL)
    token = details['options'].get('bridge_token', '')
    req = urllib.request.Request('http://local-ftst-strato-mail:8098/internal/mail/checkpoint',
        headers={'Authorization': 'Bearer ' + token})
    with HTTP.open(req, timeout=85) as response:
        result = json.load(response)
    if not isinstance(result.get('uidvalidity'), int) or not isinstance(result.get('after_uid'), int):
        raise RuntimeError('Interner Verbindungstest fehlgeschlagen.')
    print('Interne Verbindung und STRATO-Checkpoint erfolgreich, keine Nachrichteninhalte ausgegeben.')
    for slug in VERSIONS:
        data = info(slug)
        print(slug, data['version'], data['state'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['backup', 'deploy', 'connect', 'verify'])
    args = parser.parse_args()
    os.umask(0o077)
    try:
        {'backup': backup, 'deploy': deploy, 'connect': connect, 'verify': verify}[args.action]()
    except Exception:
        # Supervisor errors may include submitted options: never print exception details.
        print('Schritt fehlgeschlagen. Gesicherter Ausgangsstand bleibt verfügbar; Status lokal prüfen.', file=sys.stderr)
        raise SystemExit(1) from None
