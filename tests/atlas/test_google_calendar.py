import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).parents[2] / 'ftst_atlas'
sys.path.insert(0, str(ROOT))
try:
    import google_calendar as g
finally:
    sys.path.remove(str(ROOT))


class GoogleCalendarTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.oauth = Mock()
        self.oauth.status.return_value = {'connected': True, 'connection_id': 'connection-1'}
        self.oauth.access_token.return_value = 'private-token'
        self.options = {'calendar_enabled': True, 'calendar_provider': 'google', 'calendar_ha_user_id': 'owner'}
        self.client = g.GoogleCalendar(self.options, self.oauth, self.tmp.name)
        self.meta = {'id': 'team@example.invalid', 'timeZone': 'Europe/Berlin', 'accessRole': 'owner'}
        with patch.object(g, '_request', return_value=self.meta):
            self.client.select_calendar('owner', self.meta['id'])
        self.start, self.end = '2026-11-02T09:00:00+01:00', '2026-11-02T10:00:00+01:00'

    def tearDown(self):
        self.tmp.cleanup()

    def test_owner_selection_binding_and_persistence(self):
        self.assertTrue(self.client.status('owner')['enabled'])
        self.assertFalse(self.client.status('other')['enabled'])
        restored = g.GoogleCalendar(self.options, self.oauth, self.tmp.name)
        self.assertEqual(restored.status('owner'), self.client.status('owner'))
        self.assertEqual(self.client.path.stat().st_mode & 0o777, 0o600)
        self.oauth.status.return_value = {'connected': True, 'connection_id': 'new-account'}
        self.assertFalse(self.client.status('owner')['enabled'])
        with self.assertRaises(g.CalendarError):
            self.client.busy('owner', self.start, self.end)

    def test_calendar_list_pagination_writer_filter(self):
        with patch.object(g, '_request', side_effect=[{'items': [self.meta, {'id': 'read', 'accessRole': 'reader'}], 'nextPageToken': 'next'}, {'items': []}]) as request:
            calendars = self.client.list_calendars('owner')
            self.assertEqual(len(calendars), 1)
            self.assertIn('pageToken=next', request.call_args_list[1].args[1])
            self.assertEqual(set(calendars[0]), {'id', 'name', 'access_role'})

    def test_incomplete_list_fails_closed(self):
        with patch.object(g, '_request', return_value={'items': [], 'nextPageToken': 'same'}):
            with self.assertRaises(g.CalendarError):
                self.client.list_calendars('owner')

    def test_no_selection_of_readonly_or_alias(self):
        with patch.object(g, '_request', return_value={**self.meta, 'accessRole': 'reader'}):
            with self.assertRaises(g.CalendarError):
                self.client.select_calendar('owner', self.meta['id'])
        with self.assertRaises(g.CalendarError):
            self.client.select_calendar('owner', 'primary')

    def test_busy_pagination_recurring_and_all_day(self):
        entries = [{'start': {'date': '2026-10-25'}, 'end': {'date': '2026-10-26'}, 'summary': 'PRIVATE'},
                   {'start': {'dateTime': self.start}, 'end': {'dateTime': self.end}, 'transparency': 'transparent'},
                   {'status': 'cancelled'}]
        with patch.object(g, '_request', side_effect=[self.meta, {'items': entries, 'nextPageToken': 'p2'}, {'items': []}]) as request:
            busy = self.client.busy('owner', '2026-10-24T00:00:00Z', '2026-11-03T00:00:00Z')
            self.assertEqual(busy, [{'start': '2026-10-24T22:00:00+00:00', 'end': '2026-10-25T23:00:00+00:00'}])
            self.assertIn('singleEvents=true', request.call_args_list[1].args[1])
            self.assertIn('pageToken=p2', request.call_args_list[2].args[1])

    def test_busy_invalid_time_fails_closed(self):
        with patch.object(g, '_request', side_effect=[self.meta, {'items': [{'start': {'dateTime': '2026-11-02T09:00:00'}, 'end': {'dateTime': self.end}}]}]):
            with self.assertRaises(g.CalendarError):
                self.client.busy('owner', self.start, self.end)

    def test_create_deterministic_no_guests_then_readback(self):
        bid = 'a' * 48
        eid = self.client._event_id(self.meta['id'], bid)
        with patch.object(g, '_request', side_effect=[self.meta, {'id': eid}]) as request:
            result = self.client.create('owner', bid, self.start, self.end, 'Test Name')
            self.assertFalse(result['verified'])
            path, payload = request.call_args.args[1:]
            self.assertIn('sendUpdates=none', path)
            self.assertNotIn('attendees', payload)
            self.assertEqual(payload['id'], eid)
        event = {'id': eid, 'extendedProperties': {'private': {'atlas_booking_id': bid}}, 'start': {'dateTime': self.start}, 'end': {'dateTime': self.end}}
        with patch.object(g, '_request', return_value=event):
            self.assertTrue(self.client.find_booking('owner', bid, self.start, self.end)['verified'])
        with patch.object(g, '_request', return_value=None):
            self.assertIsNone(self.client.find_booking('owner', bid, self.start, self.end))
        with patch.object(g, '_request', return_value={**event, 'status': 'cancelled'}):
            self.assertIsNone(self.client.find_booking('owner', bid, self.start, self.end))
        with patch.object(g, '_request', return_value={**event, 'extendedProperties': {}}):
            with self.assertRaises(g.CalendarError):
                self.client.find_booking('owner', bid, self.start, self.end)

    def test_write_error_not_retried(self):
        with patch.object(g, '_request', side_effect=[self.meta, g.CalendarWriteUnknown('unknown')]) as request:
            with self.assertRaises(g.CalendarWriteUnknown):
                self.client.create('owner', 'a'*48, self.start, self.end, 'Test Name')
            self.assertEqual(request.call_count, 2)

    def test_http_fixed_origin_rejects_redirect_sanitized(self):
        conn = Mock()
        conn.getresponse.return_value.status = 302
        with patch.object(g.http.client, 'HTTPSConnection', return_value=conn) as factory:
            with self.assertRaises(g.CalendarError) as error:
                g._request('SECRET', 'users/me/calendarList')
            self.assertNotIn('SECRET', str(error.exception))
            self.assertEqual(factory.call_args.args[:2], ('www.googleapis.com', 443))
            self.assertEqual(conn.request.call_count, 1)
            conn.close.assert_called_once()

    def test_http_404_only_for_reconciliation(self):
        conn = Mock()
        conn.getresponse.return_value.status = 404
        with patch.object(g.http.client, 'HTTPSConnection', return_value=conn):
            self.assertIsNone(g._request('SECRET', 'calendars/id/events/event', missing=True))
            with self.assertRaises(g.CalendarError):
                g._request('SECRET', 'calendars/id/events')


if __name__ == '__main__':
    unittest.main()
