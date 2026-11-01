import importlib.util
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('appointments', Path(__file__).parents[2] / 'ftst_atlas' / 'appointments.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class AppointmentsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dbfile = Path(self.tmp.name) / 'test.sqlite3'
        self.store = module.Appointments(lambda: sqlite3.connect(self.dbfile, timeout=10))
        self.clock = patch.object(module, '_now', return_value=datetime(2026, 11, 2, 7, 0, tzinfo=timezone.utc))
        self.clock.start()

    def tearDown(self):
        self.clock.stop()
        self.tmp.cleanup()

    def proposal(self, user='owner', index=0):
        slot = self.store.availability(user)[index]
        return self.store.propose(user, slot['id'], 'Demo Kunde')

    def test_calendar_local_timezone_bounds_and_explicit_demo_blocks(self):
        state = self.store.state('owner')
        self.assertTrue(state['demo'])
        self.assertTrue(state['busy'])
        self.assertEqual(state['bookings'], [])
        for slot in state['available']:
            dt = datetime.fromisoformat(slot['start'])
            self.assertEqual(dt.utcoffset(), timedelta(hours=1))
            self.assertLess(dt.weekday(), 5)
            self.assertIn(dt.hour, [9, 10, 11, 13, 14, 15, 16])
            self.assertLess(dt.date().isoformat(), '2026-11-16')
        self.assertFalse(set(s['id'] for s in state['available']) & set(s['id'] for s in state['busy']))
        self.assertEqual(self.store.availability('owner', '2026-11-07'), [])

    def test_proposal_is_not_booking_then_confirm_idempotent(self):
        proposal = self.proposal()
        self.assertEqual(self.store.bookings('owner'), [])
        self.assertIn(proposal['slot_id'], [s['id'] for s in self.store.availability('owner')])
        booking = self.store.confirm('owner', proposal['id'])
        self.assertEqual(self.store.confirm('owner', proposal['id']), booking)
        self.assertNotIn(proposal['slot_id'], [s['id'] for s in self.store.availability('owner')])
        self.assertEqual(len(self.store.bookings('owner')), 1)
        self.assertIsNone(self.store.state('owner')['proposal'])

    def test_changes_invalidate_old_confirmation(self):
        first = self.proposal()
        second = self.proposal(index=1)
        self.assertGreater(second['revision'], first['revision'])
        with self.assertRaises(module.AppointmentError): self.store.confirm('owner', first['id'])
        self.assertEqual(self.store.state('owner')['proposal']['id'], second['id'])
        self.assertEqual(self.store.confirm('owner', second['id'])['slot_id'], second['slot_id'])

    def test_expiry_and_cancellation_block_save(self):
        first = self.proposal()
        with patch.object(module, '_now', return_value=datetime(2026, 11, 2, 7, 11, tzinfo=timezone.utc)):
            with self.assertRaises(module.AppointmentError): self.store.confirm('owner', first['id'])
            self.assertIsNone(self.store.state('owner')['proposal'])
        second = self.proposal()
        self.store.cancel_proposal('owner', second['id'])
        with self.assertRaises(module.AppointmentError): self.store.confirm('owner', second['id'])
        self.assertEqual(self.store.bookings('owner'), [])

    def test_owner_isolation_and_demo_calendars_independent(self):
        first = self.proposal()
        with self.assertRaises(module.AppointmentError): self.store.confirm('other', first['id'])
        with self.assertRaises(module.AppointmentError): self.store.cancel_proposal('other', first['id'])
        self.assertIsNone(self.store.state('other')['proposal'])
        self.store.confirm('owner', first['id'])
        self.assertEqual(self.store.bookings('other'), [])
        other = self.store.propose('other', first['slot_id'], 'Other demo')
        self.store.confirm('other', other['id'])
        self.assertEqual(len(self.store.bookings('other')), 1)

    def test_concurrent_confirmation_only_creates_one_booking(self):
        first = self.proposal()
        with ThreadPoolExecutor(max_workers=4) as executor:
            bookings = list(executor.map(lambda _: self.store.confirm('owner', first['id']), range(8)))
        self.assertEqual(len({b['id'] for b in bookings}), 1)
        self.assertEqual(len(self.store.bookings('owner')), 1)
        with self.assertRaises(module.AppointmentError): self.store.propose('owner', first['slot_id'], 'Another')

    def test_strict_inputs_and_past_slots(self):
        for value in ('2026-11-01', '2026-11-16', '2026-11-02T09:00', 'no', 123):
            with self.assertRaises(module.AppointmentError): self.store.availability('owner', value)
        slot = self.store.availability('owner')[0]['id']
        for name in ('', 'x' * 101, 'Bad\nName', None):
            with self.assertRaises(module.AppointmentError): self.store.propose('owner', slot, name)
        for slot in ('invalid', '2026-11-02T12:00:00+01:00', '2026-11-02T09:30:00+01:00'):
            with self.assertRaises(module.AppointmentError): self.store.propose('owner', slot, 'Demo')
        with self.assertRaises(module.AppointmentError): self.store.availability('')

    def test_reopen_preserves_confirmed_booking(self):
        proposal = self.proposal()
        booking = self.store.confirm('owner', proposal['id'])
        reopened = module.Appointments(lambda: sqlite3.connect(self.dbfile))
        self.assertEqual(reopened.bookings('owner'), [booking])


if __name__ == '__main__':
    unittest.main()
