import importlib.util
import json
import platform
import sqlite3
import tempfile
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'skills/remote-qa/scripts/state.py'
spec = importlib.util.spec_from_file_location('remote_state', SCRIPT)
state = importlib.util.module_from_spec(spec)
spec.loader.exec_module(state)


class StateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = self.root / 'state.sqlite3'
        self.thread = str(uuid.uuid4())
        self.question = self.root / 'question.json'
        self.question.write_text(json.dumps(dict(project_name='无项目', thread_title='Test thread', context='Test context', question='Salty or sweet?', options=['Salty', 'Sweet'])), encoding='utf-8')

    def call(self, *args, thread=None):
        return state.run(state.parser().parse_args(['--db', str(self.db), '--thread', thread or self.thread, *args]))

    def enable(self):
        return self.call('enable', '--recipient', 'receiver@example.com', '--sender-account', 'sender@example.com')

    def create(self):
        return self.call('create', '--input', str(self.question))

    def sent(self, q):
        self.call('mail', '--qid', q['qid'], '--state', 'sending')
        self.call('mail', '--qid', q['qid'], '--state', 'sent', '--message-id', 'sent-id', '--gmail-thread-id', 'gmail-thread')

    def test_first_use_requires_recipient_and_verified_account(self):
        self.assertFalse(self.call('status')['configured'])
        with self.assertRaises(ValueError): self.call('enable')
        with self.assertRaises(ValueError): self.call('enable', '--recipient', 'receiver@example.com')
        with self.assertRaises(ValueError): self.create()
        self.enable()
        self.assertEqual(self.create()['recipient'], 'receiver@example.com')

    def test_reuse_and_new_conversation(self):
        self.enable()
        self.assertEqual(self.call('enable')['recipient'], 'receiver@example.com')
        self.call('disable')
        self.assertEqual(self.call('enable')['recipient'], 'receiver@example.com')
        with self.assertRaises(ValueError): self.call('enable', thread=str(uuid.uuid4()))

    def test_device_refreshed_at_send_and_time_snapshot(self):
        self.enable()
        q = self.create()
        with patch.object(state.platform, 'node', return_value='sending-device'), patch.object(state.platform, 'system', return_value='TestOS'):
            self.call('mail', '--qid', q['qid'], '--state', 'sending')
        mail = self.call('render', '--qid', q['qid'])
        self.assertIn('sending-device（TestOS）', mail['body'])
        self.assertIn(self.thread, mail['body'])
        self.assertIn('无项目', mail['body'])
        self.assertIn('(UTC', mail['body'])
        self.assertEqual(mail['to'], 'receiver@example.com')

    def test_pending_blocks_configuration_change(self):
        self.enable()
        self.create()
        with self.assertRaises(ValueError): self.create()
        with self.assertRaises(ValueError): self.call('enable', '--recipient', 'other@example.com')
        self.assertEqual(self.call('status')['recipient'], 'receiver@example.com')

    def test_uncertain_send_and_sender_validation(self):
        self.enable()
        q = self.create()
        self.call('mail', '--qid', q['qid'], '--state', 'sending')
        self.call('mail', '--qid', q['qid'], '--state', 'uncertain')
        with self.assertRaises(ValueError): self.call('mail', '--qid', q['qid'], '--state', 'sending')
        self.call('mail', '--qid', q['qid'], '--state', 'sent', '--message-id', 'sent', '--gmail-thread-id', 'gmail')
        with self.assertRaises(ValueError): self.call('claim', '--qid', q['qid'], '--source', 'email', '--answer', 'A', '--evidence-id', 'reply', '--sender', 'wrong@example.com')

    def test_concurrent_claims_and_mode_persists(self):
        self.enable()
        q = self.create()
        self.sent(q)
        gate = threading.Barrier(2)
        def claim(source):
            gate.wait()
            return self.call('claim', '--qid', q['qid'], '--source', source, '--answer', source, '--evidence-id', source, '--sender', 'receiver@example.com')
        with ThreadPoolExecutor(max_workers=2) as pool:
            answers = list(pool.map(claim, ['screen', 'email']))
        self.assertEqual(sum(v['accepted'] for v in answers), 1)
        self.assertTrue(self.call('status')['enabled'])
        self.assertFalse(self.call('claim', '--qid', q['qid'], '--source', 'screen', '--answer', 'late', '--evidence-id', 'late')['accepted'])

    def test_disable_and_thread_isolation(self):
        self.enable()
        q = self.create()
        with self.assertRaises(ValueError): self.call('get', '--qid', q['qid'], thread=str(uuid.uuid4()))
        self.call('disable')
        self.assertEqual(self.call('status')['pending'], [])
        self.call('enable')
        self.assertFalse(self.call('claim', '--qid', q['qid'], '--source', 'screen', '--answer', 'A', '--evidence-id', 'old')['accepted'])

    def test_legacy_mode_does_not_inherit_address(self):
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute('CREATE TABLE modes (thread TEXT PRIMARY KEY, enabled INTEGER NOT NULL, automation_id TEXT)')
            conn.execute('INSERT INTO modes VALUES(?,1,NULL)', (self.thread,))
        status = self.call('status')
        self.assertFalse(status['enabled'])
        self.assertIsNone(status['recipient'])
        with self.assertRaises(ValueError): self.call('enable')


if __name__ == '__main__':
    unittest.main()
