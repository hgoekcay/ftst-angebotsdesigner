"""Explicit STRATO delivery. No background sends and no automatic SMTP retries."""
import os
import smtplib
import ssl

SENDER = 'info@ftst.eu'
HOST = 'smtp.strato.de'


def password():
    dedicated = os.getenv('STRATO_SMTP_PASSWORD', '')
    return dedicated or (os.getenv('STRATO_IMAP_PASSWORD', '')
                         if os.getenv('STRATO_PROVIDER', 'direct') == 'direct' else '')


def configured():
    return os.getenv('STRATO_SMTP_ENABLED', '').lower() == 'true' and bool(password())


def connection():
    if not configured():
        raise ValueError('SMTP ist nicht eingerichtet.')
    smtp = smtplib.SMTP_SSL(HOST, 465, context=ssl.create_default_context(), timeout=20)
    try:
        smtp.login(SENDER, password())
    except Exception:
        smtp.close()
        raise
    return smtp


def check():
    """Only authenticate; no MAIL, RCPT or DATA commands."""
    smtp = None
    try:
        smtp = connection()
        return True
    except Exception:
        return False
    finally:
        if smtp:
            smtp.close()


def deliver(recipient, message):
    """Return accepted, failed or uncertain. DATA ambiguity is never retried."""
    smtp = None
    data_started = False
    try:
        smtp = connection()
        code, _ = smtp.mail(SENDER)
        if code != 250:
            return 'failed'
        code, _ = smtp.rcpt(recipient)
        if code not in (250, 251):
            return 'failed'
        data_started = True
        code, _ = smtp.data(message)
        return 'accepted' if code == 250 else 'failed'
    except smtplib.SMTPDataError:
        return 'failed'
    except Exception:
        return 'uncertain' if data_started else 'failed'
    finally:
        if smtp:
            try:
                smtp.close()
            except Exception:
                pass
