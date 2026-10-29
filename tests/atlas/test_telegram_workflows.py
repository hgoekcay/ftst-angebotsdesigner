"""Workflow entry points reuse bridge fixtures without inheriting unrelated tests."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock

import test_telegram as fixtures

tg = fixtures.tg
spec = importlib.util.spec_from_file_location("workflow_test_jobs", Path(__file__).parents[2] / "ftst_atlas" / "jobs.py")
jobs_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(jobs_module)
JobQueue = jobs_module.JobQueue


class TelegramWorkflowTests(unittest.TestCase):
    setUp = fixtures.Tests.setUp
    tearDown = fixtures.Tests.tearDown
    update = fixtures.Tests.update

    def prepare(self):
        self.app.jobs = JobQueue(self.app.db, Mock())
        self.app.workflows = Mock()
        self.app.workflows.submit.side_effect = lambda owner, payload: self.app.jobs.submit(owner, payload)
        self.app.bookkeeping_sync = Mock()
        self.app.bookkeeping_sync.enabled_for.return_value = True

    def reply(self):
        return self.bridge.call.call_args.args[1]['text']

    def test_explicit_submission_owner_month_and_update_dedup(self):
        self.prepare()
        update = self.update(text='/vorbereiten 2026-10')
        self.bridge.handle(update)
        self.app.workflows.submit.assert_called_once_with('owner', {'workflow': 'bookkeeping', 'month': '2026-10'})
        ident = self.app.jobs.list('owner')[0]['id']
        self.assertIn('/auftrag ' + ident, self.reply())
        self.assertIn('eingereiht', self.reply())
        restart = tg.TelegramBridge(self.app, self.options)
        restart.call = Mock()
        restart.handle(update)
        restart.call.assert_not_called()
        self.assertEqual(self.app.workflows.submit.call_count, 1)
        self.app.respond.assert_not_called()

    def test_briefing_submission_and_help(self):
        self.prepare()
        self.bridge.handle(self.update(text='/briefing'))
        self.app.workflows.submit.assert_called_once_with('owner', {'workflow': 'briefing'})
        self.bridge.handle(self.update(i=2, text='/help'))
        for command in ('/briefing', '/vorbereiten', '/auftraege', '/auftrag'):
            self.assertIn(command, self.reply())

    def test_bad_months_and_disabled_bookkeeping_never_submit(self):
        self.prepare()
        for i, text in enumerate(('/vorbereiten', '/vorbereiten 2026-00', '/vorbereiten 2026-13', '/vorbereiten 0000-01', '/vorbereiten 2026-1', '/vorbereiten 2026-10 extra'), 1):
            self.bridge.handle(self.update(i=i, text=text))
            self.assertIn('YYYY-MM', self.reply())
        self.app.workflows.submit.assert_not_called()
        self.app.bookkeeping_sync.enabled_for.return_value = False
        self.bridge.handle(self.update(i=10, text='/vorbereiten 2026-10'))
        self.assertIn('nicht freigegeben', self.reply())
        self.app.workflows.submit.assert_not_called()

    def test_owner_private_fresh_gates_apply_to_submission(self):
        self.prepare()
        self.bridge.handle(self.update(text='/briefing', uid=7))
        self.bridge.handle(self.update(i=2, text='/briefing', kind='group'))
        stale = self.update(i=3, text='/briefing')
        stale['message']['date'] = 1
        self.bridge.handle(stale)
        unbound = tg.TelegramBridge(self.app, {**self.options, 'telegram_user_id': ''})
        unbound.call = Mock()
        unbound.handle(self.update(i=4, text='/briefing'))
        self.app.workflows.submit.assert_not_called()
        self.bridge.call.assert_not_called()
        unbound.call.assert_not_called()

    def test_list_and_lookup_enforce_owner_and_unknown_ids(self):
        self.prepare()
        own = self.app.jobs.submit('owner', {'message': 'Mein Briefing'})
        other = self.app.jobs.submit('someone-else', {'message': 'PRIVATE OTHER'})
        self.bridge.handle(self.update(text='/auftraege'))
        self.assertIn('Mein Briefing', self.reply())
        self.assertIn('wartet', self.reply())
        self.assertNotIn('PRIVATE OTHER', self.reply())
        for i, ident in enumerate((other['id'], 'unknown'), 2):
            self.bridge.handle(self.update(i=i, text='/auftrag ' + ident))
            self.assertIn('nicht gefunden', self.reply())
        self.bridge.handle(self.update(i=4, text='/auftrag ' + own['id']))
        self.assertIn('Mein Briefing', self.reply())
        self.assertIn('wartet', self.reply())

    def test_progress_result_bounded_and_artifact_url_omitted(self):
        self.prepare()
        job = {'id': 'job', 'title': 'Vorbereitung', 'status': 'completed',
               'steps': [{'label': 'Belege prüfen', 'status': 'completed'}],
               'result': {'workflow': 'bookkeeping', 'reply': 'Bericht ' * 1000,
                          'artifact': {'url': '/api/hassio_ingress/SECRET/download'}}}
        self.app.jobs = Mock()
        self.app.jobs.get.return_value = job
        self.bridge.handle(self.update(text='/auftrag job'))
        self.app.jobs.get.assert_called_once_with('owner', 'job')
        self.assertIn('Belege prüfen: abgeschlossen', self.reply())
        self.assertIn('gekürzt', self.reply())
        self.assertIn('in ATLAS beim Auftrag herunterladen', self.reply())
        self.assertNotIn('SECRET', self.reply())
        self.assertLessEqual(len(self.reply()), 4000)
        self.app.bookkeeping_sync.enabled_for.return_value = False
        self.bridge.handle(self.update(i=2, text='/auftrag job'))
        self.assertIn('nicht freigegeben', self.reply())
        self.assertNotIn('Bericht', self.reply())

    def test_safe_errors_and_invalid_lookup_do_not_expose_internal_errors(self):
        self.prepare()
        self.app.workflows.submit.side_effect = RuntimeError('PRIVATE TOKEN')
        self.bridge.handle(self.update(text='/briefing'))
        self.assertNotIn('PRIVATE TOKEN', self.reply())
        self.assertIn('nicht verfügbar', self.reply())
        self.bridge.handle(self.update(text='/briefing'))
        self.app.workflows.submit.assert_called_once()
        self.bridge.handle(self.update(i=2, text='/auftrag ../secret'))
        self.assertIn('Nutze /auftrag ID', self.reply())
        self.bridge.handle(self.update(i=3, text='/briefing extra'))
        self.assertIn('ohne weitere Angaben', self.reply())


if __name__ == '__main__':
    unittest.main()
