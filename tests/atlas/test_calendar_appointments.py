import sys
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
import sqlite3

ROOT = str(Path(__file__).resolve().parents[2] / 'ftst_atlas')
sys.path.insert(0, ROOT)
try:
    from appointments import AppointmentError
    from calendar_appointments import CalendarAppointments
finally:
    sys.path.remove(ROOT)


class Provider:
    def __init__(self):
        self.scope = 'calendar.company'
        self.intervals = []
        self.created = []
        self.confirmed = {}
        self.fail_read = False
        self.fail_create = False
        self.visible = True
        self.entered = None
        self.release = None

    def status(self, user):
        return {'enabled': user == 'owner', 'calendar_entity_id': self.scope}

    def busy(self, user, start, end):
        if self.fail_read:
            raise OSError('private upstream information')
        return self.intervals

    def create(self, user, booking_id, start, end, name):
        self.created.append(booking_id)
        if self.entered:
            self.entered.set()
            self.release.wait(3)
        if self.fail_create:
            raise TimeoutError('private upstream information')
        self.confirmed[booking_id] = {'booking_id': booking_id, 'start': start, 'end': end, 'verified': True}

    def find_booking(self, user, booking_id, start, end):
        return self.confirmed.get(booking_id) if self.visible else None


class CalendarAppointmentsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / 'calendar.db')
        self.provider = Provider()
        self.factory = lambda: sqlite3.connect(self.path, timeout=5)
        self.app = CalendarAppointments(self.factory, self.provider)
        now = datetime(2026, 11, 2, 7, 0, tzinfo=timezone.utc)
        self.patch1 = patch('appointments._now', return_value=now)
        self.patch2 = patch('calendar_appointments._now', return_value=now)
        self.patch1.start()
        self.patch2.start()

    def tearDown(self):
        self.patch2.stop()
        self.patch1.stop()
        self.tmp.cleanup()

    def proposal(self):
        slot = self.app.availability('owner')[0]
        return self.app.propose('owner', slot['id'], 'Testkunde')

    def test_real_availability_no_demo_blocks_and_all_day_conflict(self):
        slots = self.app.availability('owner', '2026-11-02')
        self.assertEqual(len(slots), 8)
        self.assertFalse(slots[0]['demo'])
        self.provider.intervals = [{'start': '2026-11-01T23:00:00+00:00', 'end': '2026-11-02T23:00:00+00:00'}]
        self.assertEqual(self.app.availability('owner', '2026-11-02'), [])
        self.assertEqual(len(self.app.availability('owner', '2026-11-03')), 8)

    def test_failed_read_never_exposes_free_slots(self):
        self.provider.fail_read = True
        state = self.app.state('owner')
        self.assertEqual(state['available'], [])
        self.assertFalse(state['provider_status']['availability_verified'])
        self.assertNotIn('private', state['notice'])
        with self.assertRaises(AppointmentError):
            self.app.propose('owner', '2026-11-02T09:00:00+01:00', 'Testkunde')

    def test_explicit_confirm_verified_and_idempotent(self):
        p = self.proposal()
        self.assertEqual(self.provider.created, [])
        booking = self.app.confirm('owner', p['id'])
        self.assertEqual(booking['status'], 'confirmed')
        self.assertEqual(self.app.confirm('owner', p['id']), booking)
        self.assertEqual(len(self.provider.created), 1)
        self.assertEqual(self.app.state('owner')['proposal'], None)

    def test_ambiguous_write_survives_restart_without_retry(self):
        p = self.proposal()
        self.provider.fail_create = True
        b = self.app.confirm('owner', p['id'])
        self.assertEqual(b['status'], 'unknown')
        restarted = CalendarAppointments(self.factory, self.provider)
        self.provider.fail_create = False
        self.assertEqual(restarted.confirm('owner', p['id'])['status'], 'unknown')
        self.assertEqual(len(self.provider.created), 1)
        self.assertNotIn(b['slot_id'], {s['id'] for s in restarted.availability('owner')})
        self.provider.confirmed[b['id']] = {'booking_id': b['id'], 'start': b['start'], 'end': b['end'], 'verified': True}
        self.assertEqual(restarted.reconcile('owner', p['id'])['status'], 'confirmed')
        self.assertEqual(len(self.provider.created), 1)

    def test_accepted_write_without_readback_is_unknown(self):
        self.provider.visible = False
        p = self.proposal()
        b = self.app.confirm('owner', p['id'])
        self.assertEqual(b['status'], 'unknown')
        self.provider.visible = True
        self.assertEqual(self.app.reconcile('owner', p['id'])['status'], 'confirmed')

    def test_concurrent_confirmation_sends_once(self):
        p = self.proposal()
        self.provider.entered = threading.Event()
        self.provider.release = threading.Event()
        errors = []
        def run():
            try:
                self.app.confirm('owner', p['id'])
            except Exception as exc:
                errors.append(exc)
        thread = threading.Thread(target=run)
        thread.start()
        self.assertTrue(self.provider.entered.wait(2))
        # Another instance simulates an overlapping HTTP request / restarted worker.
        second = CalendarAppointments(self.factory, self.provider)
        self.assertEqual(second.confirm('owner', p['id'])['status'], 'unknown')
        self.provider.release.set()
        thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len(self.provider.created), 1)
        self.assertEqual(self.app.bookings('owner')[0]['status'], 'confirmed')

    def test_owner_and_calendar_scope_isolation(self):
        p = self.proposal()
        for action in [lambda: self.app.state('other'), lambda: self.app.confirm('other', p['id']),
                       lambda: self.app.bookings('other'), lambda: self.app.reconcile('other', p['id']),
                       lambda: self.app.cancel_proposal('other', p['id'])]:
            with self.assertRaises(AppointmentError):
                action()
        self.provider.scope = 'calendar.changed'
        self.assertIsNone(self.app.state('owner')['proposal'])
        with self.assertRaises(AppointmentError):
            self.app.confirm('owner', p['id'])
        self.assertEqual(self.provider.created, [])

    def test_changed_preference_and_new_conflict_block_stale_confirm(self):
        first = self.proposal()
        second = self.proposal()
        with self.assertRaises(AppointmentError):
            self.app.confirm('owner', first['id'])
        self.provider.intervals = [{'start': second['start'], 'end': second['end']}]
        with self.assertRaises(AppointmentError):
            self.app.confirm('owner', second['id'])
        self.assertEqual(self.provider.created, [])

    def test_wrong_readback_interval_does_not_confirm(self):
        p = self.proposal()
        self.provider.visible = False
        b = self.app.confirm('owner', p['id'])
        self.provider.visible = True
        self.provider.confirmed[b['id']]['end'] = '2026-11-02T15:00:00+01:00'
        self.assertEqual(self.app.reconcile('owner', p['id'])['status'], 'unknown')


if __name__ == '__main__':
    unittest.main()
