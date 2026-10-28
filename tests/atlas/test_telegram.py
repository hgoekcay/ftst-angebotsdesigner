import importlib.util
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

path = Path(__file__).parents[2] / 'ftst_atlas' / 'telegram_bridge.py'
spec = importlib.util.spec_from_file_location('telegram_bridge', path)
tg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tg)

class App:
    def __init__(self, path):
        self.path = path
        self.chat = Mock(return_value={'reply':'Antwort'})
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
        self.app.chat.assert_called_once_with('Hallo','owner',history=[])
        self.assertEqual(self.bridge.call.call_args.args[1]['chat_id'],42)
        self.assertEqual(len(self.bridge.history),2)
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
    def test_stale_and_rate_limit(self):
        old=self.update(); old['message']['date']=1
        self.bridge.handle(old); self.app.chat.assert_not_called()
        self.bridge.handle(self.update(i=2)); self.bridge.handle(self.update(i=3))
        self.assertEqual(self.app.chat.call_count,1)
    def test_error_reply_no_exception(self):
        self.app.chat.side_effect=RuntimeError('SECRET')
        self.bridge.handle(self.update())
        self.assertNotIn('SECRET',str(self.bridge.call.call_args))

if __name__=='__main__': unittest.main()
