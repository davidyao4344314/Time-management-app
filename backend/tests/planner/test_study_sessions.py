"""Exercise completion tracking through HTTP with a disposable database."""

import tempfile
import unittest
from contextlib import closing
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from backend.app import database
from backend.app.planner import study_sessions
from backend.app.server import app


class StudySessionTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.object(database, 'db_file', Path(directory) / 'sessions.db'))
        self.enterContext(patch.object(study_sessions, 'local_now', return_value=
            datetime(2026, 11, 11, 10, tzinfo=ZoneInfo('Pacific/Auckland'))))
        self.client = self.enterContext(TestClient(app))
        self.activity = self.client.post('/activities', json={
            'name': 'Revision', 'subject': 'COMPSCI 130', 'category': 'Study',
            'activity_type': 'daily', 'start_time': '09:00', 'end_time': '10:00',
        }).json()
        self.id = self.activity['id']
        self.path = f'/study-sessions/{self.id}/2026-11-11'

    def save(self, status='done', minutes=45, path=None):
        return self.client.put(path or self.path, json={'status': status, 'actual_minutes': minutes})

    def listing(self, day=None):
        response = self.client.get('/study-sessions', params={'session_date': day} if day else {})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_initial_listing_uses_application_date_without_creating_records(self):
        result = self.listing()
        self.assertEqual((result['date'], result['today']), ('2026-11-11', '2026-11-11'))
        self.assertIsNone(result['sessions'][0]['completion'])
        with closing(database.create_connection()) as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM study_sessions').fetchone(), (0,))

    def test_all_statuses_can_be_saved_corrected_and_cleared(self):
        for status, minutes in [('done', 60), ('partly_done', 25), ('missed', 0)]:
            with self.subTest(status=status):
                response = self.save(status, minutes)
                self.assertEqual(response.status_code, 200, response.text)
                completion = self.listing()['sessions'][0]['completion']
                self.assertEqual((completion['status'], completion['actual_minutes']), (status, minutes))
        self.assertEqual(self.client.delete(self.path).status_code, 204)
        self.assertIsNone(self.listing()['sessions'][0]['completion'])
        self.assertEqual(self.client.delete(self.path).status_code, 204)

    def test_daily_occurrences_and_repeated_saves_are_independent_and_idempotent(self):
        self.save()
        self.save()
        yesterday = f'/study-sessions/{self.id}/2026-11-10'
        self.assertEqual(self.save('missed', 0, yesterday).status_code, 200)
        self.assertEqual(self.listing('2026-11-10')['sessions'][0]['completion']['status'], 'missed')
        self.assertEqual(self.listing()['sessions'][0]['completion']['status'], 'done')
        with closing(database.create_connection()) as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM study_sessions').fetchone(), (2,))

    def test_one_time_and_bounded_weekly_dates_are_checked(self):
        one = self.client.post('/activities', json={
            'name': 'Practice', 'category': 'Study', 'activity_type': 'one_time', 'date': '2026-11-10',
        }).json()['id']
        self.assertEqual(self.save(path=f'/study-sessions/{one}/2026-11-11').status_code, 400)
        self.assertEqual(self.save(path=f'/study-sessions/{one}/2026-11-10').status_code, 200)
        with closing(database.create_connection()) as connection, connection:
            cursor = connection.execute("""INSERT INTO activities
                (name, category, activity_type, weekday, active_start_date, active_end_date)
                VALUES ('Weekly', 'Study', 'weekly', 'Wednesday', '2026-11-04', '2026-11-04')""")
            weekly = cursor.lastrowid
        self.assertEqual(self.save(path=f'/study-sessions/{weekly}/2026-11-04').status_code, 200)
        self.assertEqual(self.save(path=f'/study-sessions/{weekly}/2026-11-11').status_code, 400)
        self.assertEqual(self.save(path=f'/study-sessions/{weekly}/2026-11-03').status_code, 400)

    def test_invalid_values_future_dates_and_unknown_activities_do_not_write(self):
        for payload in [
            {'status': 'other', 'actual_minutes': 30},
            {'status': 'done', 'actual_minutes': -1},
            {'status': 'done', 'actual_minutes': 1441},
            {'status': 'done', 'actual_minutes': 1.5},
            {'status': 'done', 'actual_minutes': True},
            {'status': 'done', 'actual_minutes': '30'},
            {'status': 'done', 'actual_minutes': 0},
            {'status': 'partly_done', 'actual_minutes': 0},
            {'status': 'missed', 'actual_minutes': 10},
            {'status': 'done'},
        ]:
            with self.subTest(payload=payload):
                self.assertIn(self.client.put(self.path, json=payload).status_code, (400, 422))
        self.assertEqual(self.save(path=f'/study-sessions/{self.id}/2026-11-12').status_code, 400)
        self.assertEqual(self.client.get('/study-sessions?session_date=2026-11-12').status_code, 400)
        self.assertEqual(self.save(path=f'/study-sessions/{self.id}/invalid').status_code, 422)
        self.assertEqual(self.save(path='/study-sessions/9999/2026-11-11').status_code, 404)
        self.assertIsNone(self.listing()['sessions'][0]['completion'])

    def test_recorded_details_survive_schedule_edits_and_restart(self):
        self.save()
        with closing(database.create_connection()) as connection, connection:
            connection.execute("UPDATE activities SET name='Renamed', activity_type='one_time', date='2026-11-10' WHERE id=?", (self.id,))
        with TestClient(app) as client:
            session = client.get('/study-sessions?session_date=2026-11-11').json()['sessions'][0]
            self.assertEqual(session['name'], 'Revision')
            self.assertEqual(session['completion']['actual_minutes'], 45)
        self.assertEqual(self.save('partly_done', 20).status_code, 200)
        self.assertEqual(self.client.delete(self.path).status_code, 204)
        self.assertEqual(self.listing()['sessions'], [])

    def test_deleting_activity_removes_its_records(self):
        self.save()
        self.assertEqual(self.client.delete(f'/activities/{self.id}').status_code, 200)
        self.assertEqual(self.listing()['sessions'], [])
        with closing(database.create_connection()) as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM study_sessions').fetchone(), (0,))

    def test_database_failure_returns_safe_error(self):
        with patch('backend.app.api.study_sessions.create_connection', side_effect=database.sqlite3.OperationalError('private path')):
            response = self.save()
        self.assertEqual(response.status_code, 500)
        self.assertNotIn('private path', response.text)


if __name__ == '__main__':
    unittest.main()
