import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

spec = importlib.util.spec_from_file_location('atlas_ha_calendar_test', Path(__file__).parents[2] / 'ftst_atlas/ha_calendar.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
OPTIONS = {'calendar_enabled': True, 'calendar_ha_user_id': 'owner', 'calendar_entity_id': 'calendar.business'}
START = '2026-11-02T09:00:00+01:00'
END = '2026-11-02T10:00:00+01:00'
ID = 'booking_123456'


def event(start=START, end=END, **extra):
    return dict(start={'dateTime': start}, end={'dateTime': end}, **extra)


def response_events(events):
    return [{'entity_id': 'calendar.business', 'state': 'off'}, events]


class CalendarTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(m.os.environ, {'SUPERVISOR_TOKEN': 'private-token'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.client = m.HACalendar(OPTIONS)

    def test_disabled_foreign_missing_token_invalid_entity_do_not_contact_provider(self):
        with patch.object(m, '_request') as request:
            clients = [(m.HACalendar(dict(OPTIONS, calendar_enabled=False)), 'owner'),
                       (self.client, 'foreign'), (m.HACalendar(dict(OPTIONS, calendar_entity_id='calendar.x/../../states')), 'owner')]
            with patch.dict(m.os.environ, {'SUPERVISOR_TOKEN': ''}):
                clients.append((m.HACalendar(OPTIONS), 'owner'))
            for client, user in clients:
                self.assertFalse(client.status(user)['enabled'])
                self.assertNotIn('calendar_entity_id', client.status(user))
                with self.assertRaises(m.CalendarError):
                    client.busy(user, START, END)
                with self.assertRaises(m.CalendarError):
                    client.create(user, ID, START, END, 'Test')
            request.assert_not_called()

    def test_status_is_configured_not_verified_and_scoped(self):
        status = self.client.status('owner')
        self.assertEqual(status['state'], 'configured_unverified')
        self.assertEqual(status['calendar_entity_id'], 'calendar.business')
        self.assertNotIn('private-token', json.dumps(status))

    def test_timed_overlap_exclusive_bounds_and_title_redaction(self):
        events = [event(summary='private'), event('2026-11-02T08:00:00+01:00', START),
                  event(END, '2026-11-02T11:00:00+01:00'),
                  event(transparency='transparent'), event(status='cancelled')]
        with patch.object(m, '_request', side_effect=response_events(events)):
            result = self.client.busy('owner', START, END)
        self.assertEqual(result, [{'start': '2026-11-02T08:00:00+00:00', 'end': '2026-11-02T09:00:00+00:00'}])
        self.assertNotIn('private', json.dumps(result))

    def test_all_day_exclusive_end_and_dst(self):
        data = [{'start': {'date': '2026-10-25'}, 'end': {'date': '2026-10-26'}}]
        with patch.object(m, '_request', side_effect=response_events(data)):
            result = self.client.busy('owner', '2026-10-25T00:00:00+02:00', '2026-10-26T00:00:00+01:00')
        self.assertEqual(result, [{'start': '2026-10-24T22:00:00+00:00', 'end': '2026-10-25T23:00:00+00:00'}])

    def test_malformed_event_list_or_time_fails_closed(self):
        for result in [{}, [None], [{'start': START}], [event('2026-11-02T09:00:00')], [event(END, START)]]:
            with self.subTest(result=result), patch.object(m, '_request', side_effect=response_events(result)):
                with self.assertRaises(m.CalendarError):
                    self.client.busy('owner', START, END)

    def test_find_matches_exact_marker_and_interval_not_substring(self):
        marker = 'ATLAS-Buchung: ' + ID
        with patch.object(m, '_request', side_effect=response_events([event(description=marker + '-other')])):
            self.assertIsNone(self.client.find_booking('owner', ID, START, END))
        with patch.object(m, '_request', side_effect=response_events([event(description='prefix\n' + marker + '\ntext')])):
            self.assertTrue(self.client.find_booking('owner', ID, START, END)['verified'])
        with patch.object(m, '_request', side_effect=response_events([event(description=marker), event(description=marker)])):
            with self.assertRaises(m.CalendarError):
                self.client.find_booking('owner', ID, START, END)

    def test_unavailable_calendar_never_means_free(self):
        with patch.object(m, '_request', return_value={'entity_id': 'calendar.business', 'state': 'unavailable'}) as request:
            with self.assertRaises(m.CalendarError):
                self.client.busy('owner', START, END)
            self.assertEqual(request.call_count, 1)

    def test_create_single_service_no_guests_no_claim_of_verified(self):
        with patch.object(m, '_request', return_value=[]) as request:
            result = self.client.create('owner', ID, START, END, 'Test Person')
        self.assertFalse(result['verified'])
        self.assertTrue(result['accepted'])
        self.assertEqual(request.call_count, 1)
        token, path, payload = request.call_args.args
        self.assertEqual(path, 'services/calendar/create_event')
        self.assertEqual(payload['entity_id'], 'calendar.business')
        self.assertEqual(payload['description'], 'ATLAS-Buchung: ' + ID)
        self.assertEqual(set(payload), {'entity_id', 'summary', 'description', 'start_date_time', 'end_date_time'})

    def test_invalid_input_never_writes(self):
        with patch.object(m, '_request') as request:
            for args in [(ID, START, END, ''), ('bad/path', START, END, 'Test'),
                         (ID, END, START, 'Test'), (ID, '2026-11-02T09:00:00', END, 'Test'),
                         (ID, START, '2027-01-01T00:00:00+00:00', 'Test')]:
                with self.assertRaises(m.CalendarError):
                    self.client.create('owner', *args)
            request.assert_not_called()

    def test_transport_fixed_internal_host_no_redirect_and_no_retry(self):
        conn = MagicMock()
        conn.getresponse.return_value.status = 302
        with patch.object(m.http.client, 'HTTPConnection', return_value=conn) as http:
            with self.assertRaises(m.CalendarWriteUnknown) as caught:
                m._request('private-token', 'services/calendar/create_event', {})
        self.assertNotIn('private-token', str(caught.exception))
        self.assertEqual(http.call_args.args, ('supervisor', 80))
        self.assertEqual(conn.request.call_count, 1)
        self.assertEqual(conn.request.call_args.args[:2], ('POST', '/core/api/services/calendar/create_event'))
        conn.close.assert_called_once()

    def test_transport_timeout_and_oversized_write_are_unknown(self):
        for failure in ['timeout', 'oversize', 'invalid-json']:
            conn = MagicMock()
            conn.getresponse.return_value.status = 200
            conn.getresponse.return_value.getheader.return_value = None
            if failure == 'timeout':
                conn.getresponse.side_effect = TimeoutError('private-token')
            else:
                conn.getresponse.return_value.read1.side_effect = [b'x' * (m.MAX_BYTES + 1), b''] if failure == 'oversize' else [b'{', b'']
            with patch.object(m.http.client, 'HTTPConnection', return_value=conn):
                with self.assertRaises(m.CalendarWriteUnknown):
                    m._request('private-token', 'services/calendar/create_event', {})
            conn.close.assert_called_once()

    def test_slow_body_hits_absolute_deadline_and_cannot_confirm_write(self):
        conn = MagicMock()
        conn.getresponse.return_value.status = 200
        conn.getresponse.return_value.getheader.return_value = None
        conn.getresponse.return_value.read1.return_value = b' '
        with patch.object(m.http.client, 'HTTPConnection', return_value=conn), patch.object(m, 'monotonic', side_effect=[0, 1, 21]):
            with self.assertRaises(m.CalendarWriteUnknown):
                m._request('private-token', 'services/calendar/create_event', {})
        self.assertEqual(conn.getresponse.return_value.read1.call_count, 1)
        conn.close.assert_called_once()

    def test_truncated_success_is_not_verified(self):
        conn = MagicMock()
        conn.getresponse.return_value.status = 200
        conn.getresponse.return_value.getheader.return_value = '20'
        conn.getresponse.return_value.read1.side_effect = [b'[]', b'']
        with patch.object(m.http.client, 'HTTPConnection', return_value=conn):
            with self.assertRaises(m.CalendarWriteUnknown):
                m._request('private-token', 'services/calendar/create_event', {})


if __name__ == '__main__':
    unittest.main()
