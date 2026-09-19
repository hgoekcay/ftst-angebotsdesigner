"""Private bearer-authenticated intake, isolated from public OAuth routes."""
import asyncio
import hmac
import json
import re
from datetime import date

from starlette.responses import JSONResponse
from strato_worker import BridgeUIDValidityChanged

INTERNAL_HOST = b'local-ftst-strato-mail:8098'
MAX_BODY = 4096


class InternalBridge:
    def __init__(self, app, token, runner, accounts=None):
        self.app, self.token, self.runner = app, token, runner
        self.accounts = accounts or (lambda: [{'id': 'primary', 'email': 'info@ftst.eu', 'folder': 'INBOX'}])

    @property
    def state(self):
        return self.app.state

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or not scope['path'].startswith('/internal/'):
            return await self.app(scope, receive, send)

        async def reply(status, error=None, result=None):
            response = JSONResponse(result if result is not None else {'error': error}, status_code=status,
                                    headers={'Cache-Control': 'no-store'})
            await response(scope, receive, send)

        headers = scope.get('headers', [])
        hosts = [v.lower() for k, v in headers if k.lower() == b'host']
        if (not self.token or hosts != [INTERNAL_HOST]
                or any(k.lower() == b'origin' for k, v in headers)):
            return await reply(404, 'not_found')
        auth = [v for k, v in headers if k.lower() == b'authorization']
        expected = b'Bearer ' + self.token.encode('ascii')
        if len(auth) != 1 or not hmac.compare_digest(auth[0], expected):
            return await reply(401, 'unauthorized')
        path, method = scope['path'], scope['method']
        if scope.get('query_string'):
            return await reply(400, 'invalid_request')
        if path == '/internal/mail/accounts' and method == 'GET':
            # Explicit allowlist, even if an internal resolver accidentally includes secrets.
            return await reply(200, result={'accounts': [{k: a[k] for k in ('id', 'email', 'folder')}
                                                        for a in self.accounts()]})
        if path == '/internal/mail/checkpoint' and method == 'GET':
            operation, arguments = 'bridge_checkpoint', {}
        elif path in ('/internal/mail/batch', '/internal/mail/checkpoint') and method == 'POST':
            content_types = [v.split(b';', 1)[0].strip().lower() for k, v in headers if k.lower() == b'content-type']
            if content_types != [b'application/json']:
                return await reply(415, 'json_required')
            try:
                body = bytearray()
                async with asyncio.timeout(10):
                    while True:
                        event = await receive()
                        if event['type'] != 'http.request':
                            return await reply(400, 'invalid_request')
                        body.extend(event.get('body', b''))
                        if len(body) > MAX_BODY:
                            return await reply(413, 'request_too_large')
                        if not event.get('more_body', False):
                            break
                arguments = json.loads(body)
                if not isinstance(arguments, dict):
                    raise ValueError()
                if path == '/internal/mail/checkpoint':
                    if set(arguments) - {'account_id', 'expected_email', 'expected_folder'} or 'account_id' not in arguments:
                        raise ValueError()
                    operation = 'bridge_checkpoint'
                else:
                    if (set(arguments) - {'uidvalidity', 'after_uid', 'since', 'account_id', 'expected_email', 'expected_folder'}
                            or not {'uidvalidity', 'after_uid', 'since'} <= set(arguments)):
                        raise ValueError()
                    for key, minimum in [('uidvalidity', 1), ('after_uid', 0)]:
                        if type(arguments[key]) is not int or not minimum <= arguments[key] <= 4294967295:
                            raise ValueError()
                    since = arguments['since']
                    if not isinstance(since, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', since):
                        raise ValueError()
                    date.fromisoformat(since)
                    operation = 'bridge_batch'
            except TimeoutError:
                return await reply(408, 'request_timeout')
            except (ValueError, UnicodeError):
                return await reply(400, 'invalid_request')
        else:
            return await reply(404, 'not_found')
        account_id = arguments.get('account_id', 'primary')
        if not isinstance(account_id, str) or not re.fullmatch(r'[a-z0-9_-]{1,40}', account_id):
            return await reply(400, 'invalid_request')
        matches = [a for a in self.accounts() if a['id'] == account_id]
        if len(matches) != 1:
            return await reply(404, 'account_not_found')
        supplied = {'expected_email', 'expected_folder'} & set(arguments)
        if supplied:
            if supplied != {'expected_email', 'expected_folder'}:
                return await reply(400, 'invalid_request')
            email, folder = arguments.pop('expected_email'), arguments.pop('expected_folder')
            if not isinstance(email, str) or not isinstance(folder, str):
                return await reply(400, 'invalid_request')
            if email != matches[0]['email'] or folder != matches[0]['folder']:
                return await reply(409, 'source_changed')
        try:
            result = await asyncio.to_thread(self.runner, operation, arguments)
        except BridgeUIDValidityChanged:
            return await reply(409, 'uidvalidity_changed')
        except Exception:
            return await reply(502, 'mail_operation_failed')
        return await reply(200, result=result)
