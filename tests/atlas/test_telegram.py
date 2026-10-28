import importlib.util
import sqlite3
import sys
from datetime import datetime, timezone
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

path = Path(__file__).parents[2] / 'ftst_atlas' / 'telegram_bridge.py'
spec = importlib.util.spec_from_file_location('telegram_bridge', path)
tg = importlib.util.module_from_spec(spec)
sys.path.insert(0, str(path.parent))
try:
    spec.loader.exec_module(tg)
finally:
    sys.path.pop(0)

class App:
    def __init__(self, path):
        self.path = path
        self.chat = Mock(return_value={'reply':'Antwort'})
        self.respond = self.chat
        with self.db() as db:
            db.executescript('CREATE TABLE profiles(user_id TEXT PRIMARY KEY,text TEXT); INSERT INTO profiles VALUES ("owner","Firma"); CREATE TABLE memories(user_id TEXT,text TEXT,source TEXT,created_at TEXT);')
    def db(self): return sqlite3.connect(self.path)
    def collection(self, table, uid): return [{'title':'Aufgabe '+uid,'done':False}]

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = App(str(Path(self.tmp.name)/'db'))
        self.options = {'telegram_enabled':True,'telegram_token':'123456:'+('a'*30),'telegram_user_id':'42','telegram_ha_user_id':'owner'}
        self.bridge = tg.TelegramBridge(self.app,self.options)
        self.bridge.call = Mock()
    def tearDown(self): self.tmp.cleanup()
    def update(self, i=1, text='Hallo', uid=42, kind='private'):
        return {'update_id':i,'message':{'date':int(time.time()),'chat':{'id':uid,'type':kind},'from':{'id':uid,'is_bot':False},'text':text}}
    def test_default_disabled_and_bad_profile(self):
        with patch.object(tg.threading,'Thread') as thread:
            self.assertIsNone(tg.start_bridge(self.app,{}))
            self.assertIsNone(tg.start_bridge(self.app,{**self.options,'telegram_ha_user_id':'wrong'}))
            thread.assert_not_called()
    def test_unauthorized_and_group_silent(self):
        self.bridge.handle(self.update(uid=7))
        self.bridge.handle(self.update(i=2,kind='group'))
        self.bridge.call.assert_not_called(); self.app.chat.assert_not_called()
    def test_profile_mapping_history(self):
        self.bridge.handle(self.update())
        self.app.chat.assert_called_once_with('Hallo','owner',history=[],mode='auto')
        self.assertEqual(self.bridge.call.call_args.args[1]['chat_id'],42)
        self.assertEqual(len(self.bridge.history),2)
    def test_online_and_local_modes_are_explicit(self):
        self.bridge.handle(self.update(text='/online Neue Kameras'))
        self.app.respond.assert_called_with('Neue Kameras', 'owner', history=[], mode='online')
        self.bridge.handle(self.update(i=2, text='/lokal Meine Aufgaben'))
        self.assertEqual(self.app.respond.call_args.kwargs['mode'], 'local')
        self.assertEqual(self.app.respond.call_args.args[0], 'Meine Aufgaben')

    def test_dedup_restart(self):
        self.bridge.handle(self.update())
        second = tg.TelegramBridge(self.app,self.options); second.call=Mock()
        second.handle(self.update())
        second.call.assert_not_called(); self.assertEqual(self.app.chat.call_count,1)
    def test_memory_explicit(self):
        self.bridge.handle(self.update(text='/remember Kamera'))
        with self.app.db() as db:
            self.assertEqual(db.execute('SELECT user_id,text FROM memories').fetchall(),[('owner','Kamera')])
        self.app.chat.assert_not_called()
    def test_discovery_only_self_id(self):
        b=tg.TelegramBridge(self.app,{**self.options,'telegram_user_id':''}); b.call=Mock()
        b.handle(self.update(text='Firmenwissen',uid=9)); b.call.assert_not_called()
        b.handle(self.update(i=2,text='/id',uid=9))
        self.assertEqual(b.call.call_args.args[1]['chat_id'],9)
        self.app.chat.assert_not_called()
    def test_transport_redacts_token(self):
        b=tg.TelegramBridge(self.app,self.options)
        b.opener.open=Mock(side_effect=RuntimeError(self.options['telegram_token']))
        with self.assertRaises(tg.TelegramError) as ctx: b.call('getUpdates',{})
        self.assertNotIn(self.options['telegram_token'],str(ctx.exception))
    def test_stale_and_consecutive_messages(self):
        old=self.update(); old['message']['date']=1
        self.bridge.handle(old); self.app.chat.assert_not_called()
        self.bridge.handle(self.update(i=2)); self.bridge.handle(self.update(i=3))
        self.assertEqual(self.app.chat.call_count,2)
    def test_tasks_alias_and_followup(self):
        self.bridge.handle(self.update(text="tasks"))
        self.app.chat.assert_not_called()
        self.assertIn("Aufgabe owner", self.bridge.call.call_args.args[1]["text"])
        self.bridge.handle(self.update(i=2, text="Was weißt du?"))
        self.app.chat.assert_called_once()
    def test_error_reply_no_exception(self):
        self.app.chat.side_effect=RuntimeError('SECRET')
        self.bridge.handle(self.update())
        self.assertNotIn('SECRET',str(self.bridge.call.call_args))

    def test_bookkeeping_commands_are_local_and_owner_scoped(self):
        for i, command in enumerate(('/op', '/belege', '/buchhaltung'), 1):
            with patch.object(tg, 'build_report', return_value={'safe': True}) as report, patch.object(tg, 'format_report', return_value='Bericht') as formatting:
                self.bridge.handle(self.update(i=i, text=command))
                report.assert_called_once_with(self.app, 'owner')
                self.assertEqual(formatting.call_args.args[1], ('op', 'belege', 'summary')[i-1])
                self.assertEqual(self.bridge.call.call_args.args[1]['text'], 'Bericht')
        self.app.respond.assert_not_called()
        with patch.object(tg, 'build_report', side_effect=RuntimeError('PRIVATE')):
            self.bridge.handle(self.update(i=5, text='/op'))
            self.assertNotIn('PRIVATE', self.bridge.call.call_args.args[1]['text'])

    def test_daily_default_disabled_wrong_owner_and_unbound(self):
        self.app.bookkeeping_sync = Mock()
        self.app.bookkeeping_sync.enabled_for.return_value = True
        with patch.object(tg, 'build_report') as report:
            self.bridge.daily_bookkeeping()
            report.assert_not_called()
            bridge = tg.TelegramBridge(self.app, {**self.options, 'bookkeeping_telegram_daily': True, 'telegram_user_id': ''})
            bridge.daily_bookkeeping()
            report.assert_not_called()
            self.app.bookkeeping_sync.enabled_for.return_value = False
            bridge.user_id = 42
            bridge.daily_bookkeeping()
            report.assert_not_called()

    def test_daily_berlin_time_restart_and_failure_dedup(self):
        self.app.bookkeeping_sync = Mock()
        self.app.bookkeeping_sync.enabled_for.return_value = True
        options = {**self.options, 'bookkeeping_telegram_daily': True, 'bookkeeping_telegram_time': '09:00'}
        bridge = tg.TelegramBridge(self.app, options); bridge.call = Mock()
        with patch.object(tg, 'build_report', return_value={}), patch.object(tg, 'format_report', return_value='Tagesbericht'):
            # Winter CET: 07:59 UTC is before 09:00 Berlin.
            bridge.daily_bookkeeping(datetime(2026, 10, 28, 7, 59, tzinfo=timezone.utc))
            bridge.call.assert_not_called()
            bridge.daily_bookkeeping(datetime(2026, 10, 28, 8, 0, tzinfo=timezone.utc))
            bridge.call.assert_called_once()
            restart = tg.TelegramBridge(self.app, options); restart.call = Mock()
            restart.daily_bookkeeping(datetime(2026, 10, 28, 12, tzinfo=timezone.utc))
            restart.call.assert_not_called()
            restart.call.side_effect = tg.TelegramError('unavailable')
            with self.assertRaises(tg.TelegramError):
                restart.daily_bookkeeping(datetime(2026, 10, 29, 8, tzinfo=timezone.utc))
            restart.daily_bookkeeping(datetime(2026, 10, 29, 9, tzinfo=timezone.utc))
            self.assertEqual(restart.call.call_count, 1)
            failed_restart = tg.TelegramBridge(self.app, options); failed_restart.call = Mock()
            failed_restart.daily_bookkeeping(datetime(2026, 10, 29, 10, tzinfo=timezone.utc))
            failed_restart.call.assert_not_called()
            with self.app.db() as db:
                states = db.execute('SELECT local_date,state FROM telegram_bookkeeping_daily ORDER BY local_date').fetchall()
            self.assertEqual(states, [('2026-10-28', 'sent'), ('2026-10-29', 'failed')])
            # Summer CEST: 07:00 UTC is already 09:00 Berlin.
            other = tg.TelegramBridge(self.app, options); other.call = Mock()
            other.daily_bookkeeping(datetime(2027, 7, 1, 7, tzinfo=timezone.utc))
            other.call.assert_called_once()

if __name__=='__main__': unittest.main()
