"""Local-only service check with explicit synthetic test, no customer records."""
import os
import secrets
import time
from flask import request, session, abort
from local_ai import status, extract_local
from project_ai import AIError

SAMPLE='Es werden 4 Kameras und 2 Bewegungsmelder benötigt. Montage ist noch ungeklärt.'


def register(app,base,ingress,escape):
    @app.route('/ai',methods=['GET','POST'])
    def ai_status():
        session.setdefault('ai_csrf',secrets.token_urlsafe(32))
        message=''
        if request.method=='POST':
            if not secrets.compare_digest(request.form.get('csrf',''),session['ai_csrf']):
                abort(400)
            started=time.monotonic()
            try:
                result=extract_local(SAMPLE)
                rows=''.join(f'<li>{escape(str(c["quantity"]))} × {escape(c["description"])} · Beleg: {escape(c["evidence"])}</li>' for c in result['components'])
                message=f'<h2>Lokaler Test abgeschlossen</h2><p>Dauer: {time.monotonic()-started:.1f} Sekunden. Keine Cloud-KI verwendet.</p><p>{escape(result["summary"])}</p><ul>{rows}</ul><p>Ergebnis mit dem Beispieltext vergleichen; dies ist keine automatische fachliche Freigabe.</p>'
            except AIError as exc:
                message=f'<p role="alert">{escape(exc)}</p>'
        provider='Lokale Text-KI' if os.getenv('AI_PROVIDER','openai')=='ollama' else 'OpenAI (Cloud)'
        return base('KI-Status',f'<div class="card"><h1>KI-Status</h1><p>Projektanalyse: {provider}</p><p>{escape(status())}</p><p>Die Web-Firmensuche ist eine separate Online-Funktion und benötigt weiterhin ihren API-Zugang. Lokale Textanalyse recherchiert nicht im Internet.</p><h2>Test ohne Kundendaten</h2><p>{escape(SAMPLE)}</p><form method="post"><input type="hidden" name="csrf" value="{escape(session["ai_csrf"])}"><button class="btn">Lokale KI mit diesem Beispiel testen</button></form>{message}<p><a href="{ingress("projects")}">Zu den Projekten</a></p></div>')
