"""Copy an already accepted frozen message to STRATO; never send SMTP here."""
import imaplib
import re
import ssl
import time

import offer_smtp


def quoted(value):
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def sent_folder(connection):
    status, rows = connection.list()
    if status != 'OK':
        raise ValueError('Folder discovery failed')
    folders = []
    for row in rows or []:
        if not isinstance(row, bytes):
            continue
        match = re.fullmatch(rb'\(([^)]*)\) (?:NIL|"(?:[^"\\]|\\.)*") (.+)', row)
        if match and b'\\sent' in match[1].lower().split():
            folder = match[2].decode('ascii')
            if folder.startswith('"') and folder.endswith('"'):
                folder = re.sub(r'\\(.)', r'\1', folder[1:-1])
            folders.append(folder)
    if len(folders) > 1:
        raise ValueError('Ambiguous sent folder')
    # STRATO's documented server folder, not the localized phone display name.
    return folders[0] if folders else 'Sent Items'


def copy_to_sent(raw, message_id, *, allow_append=True, sent_at=None):
    connection = None
    append_started = False
    try:
        if not offer_smtp.password() or not re.fullmatch(r'<[A-Za-z0-9_.@+-]+>', message_id):
            return 'failed' if allow_append else 'uncertain'
        connection = imaplib.IMAP4_SSL('imap.strato.de', 993,
                                      ssl_context=ssl.create_default_context(), timeout=20)
        connection.login(offer_smtp.SENDER, offer_smtp.password())
        folder = quoted(sent_folder(connection))
        status, _ = connection.select(folder, readonly=True)
        if status != 'OK':
            raise ValueError('Sent folder unavailable')
        status, matches = connection.uid('SEARCH', None, 'HEADER', 'Message-ID', quoted(message_id))
        if status != 'OK' or not matches or not isinstance(matches[0], bytes):
            raise ValueError('Search failed')
        if matches[0].strip():
            return 'saved'
        if not allow_append:
            return 'uncertain'
        append_started = True
        status, _ = connection.append(folder, r'\Seen', imaplib.Time2Internaldate(sent_at or time.time()), raw)
        return 'saved' if status == 'OK' else 'failed'
    except Exception:
        # No server text, credentials or message content in user-facing errors.
        return 'uncertain' if append_started or not allow_append else 'failed'
    finally:
        if connection:
            try:
                connection.logout()
            except Exception:
                pass
