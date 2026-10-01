"""Current/next checks using an in-memory database, never the user's data."""
import sqlite3
import unittest
from datetime import date
from unittest.mock import Mock, patch

from backend import fastapi_test as api
from backend.app import activities, calender, database


class CurrentNextTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(':memory:')
        self.connection.executescript(database.sql_file.read_text())
        self.addCleanup(self.connection.close)
        date_patch = patch.object(calender, 'get_current_date', return_value=date(2026, 9, 10))
        time_patch = patch.object(calender, 'get_current_time', return_value='12:30')
        date_patch.start()
        time_patch.start()
        self.addCleanup(date_patch.stop)
        self.addCleanup(time_patch.stop)

    def add(self, name, start='11:00', end='13:00', **fields):
        values = dict(name=name, category='Study', activity_type='daily',
                      start_time=start, end_time=end)
        values.update(fields)
        activities.add_activity(self.connection, list(values), list(values.values()))

    def result(self):
        current, next_activity = calender.get_current_and_next_activities(self.connection)
        return [row[1] for row in current], next_activity[1] if next_activity else None

    def test_overlaps_and_earliest_next(self):
        self.add('Lab')
        self.add('Overlap', '12:00', '14:00')
        self.add('Study', '16:00', '17:00')
        self.add('Lecture', '14:00', '15:00')
        self.assertEqual(self.result(), (['Lab', 'Overlap'], 'Lecture'))

    def test_exact_boundaries(self):
        self.add('Finished', '11:00', '12:30')
        self.add('Starting now', '12:30', '13:30')
        self.assertEqual(self.result(), (['Starting now'], None))

    def test_missing_invalid_or_reversed_times_are_excluded(self):
        for start, end in [(None, None), ('14:00', None), (None, '15:00'),
                           ('bad', '15:00'), ('16:00', '14:00'), ('14:00', '14:00')]:
            self.add('Untimed or invalid', start, end)
        self.assertEqual(self.result(), ([], None))

    def test_recurrence_and_active_ranges_are_reused(self):
        self.add('Tomorrow', '14:00', '15:00', activity_type='one_time', date='2026-09-11')
        self.add('Other weekday', activity_type='weekly', weekday='Monday')
        self.add('Expired UoA', activity_type='weekly', weekday='Thursday',
                 active_start_date='2026-03-01', active_end_date='2026-06-30', source='UoA')
        self.add('Invalid date', activity_type='one_time', date='not-a-date')
        self.add('Today Canvas', activity_type='one_time', date='2026-09-10', source='Canvas')
        self.add('Today UoA', '14:00', '15:00', activity_type='weekly', weekday='Thursday',
                 active_start_date='2026-07-01', active_end_date='2026-11-01', source='UoA')
        self.assertEqual(self.result(), (['Today Canvas'], 'Today UoA'))

    def test_empty_and_finished_day(self):
        self.assertEqual(self.result(), ([], None))
        self.add('Finished', '09:00', '10:00')
        self.assertEqual(self.result(), ([], None))

    def test_time_values_are_compared_as_times(self):
        self.add('Morning', '9:00', '10:00')
        self.add('Current', ' 11:00 ', ' 13:00 ')
        self.add('Later', ' 14:00 ', '15:00')
        self.assertEqual(self.result(), (['Current'], 'Later'))

    def test_endpoint_shape_and_connection_cleanup(self):
        self.add('Lab', source='UoA')
        self.add('Overlap')
        self.add('Next', '14:00', '15:00', source='Canvas')
        # Resolve the real selector against SQLite, then check API mapping
        # and connection ownership independently.
        result = calender.get_current_and_next_activities(self.connection)
        connection = Mock()
        with patch.object(api, 'create_connection', return_value=connection), \
                patch.object(api, 'get_current_and_next_activities', return_value=result) as selector:
            response = api.current_and_next_activities()
        self.assertTrue(any(route.path == '/activities/current-next' and 'GET' in route.methods
                            for route in api.app.routes))
        self.assertEqual(len(response['current']), 2)
        self.assertEqual(response['current'][0]['source'], 'UoA')
        self.assertEqual(response['next']['name'], 'Next')
        selector.assert_called_once_with(connection)
        connection.close.assert_called_once()

    def test_endpoint_empty_values_are_null(self):
        with patch.object(api, 'create_connection', return_value=Mock()), \
                patch.object(api, 'get_current_and_next_activities', return_value=([], None)):
            response = api.current_and_next_activities()
        self.assertEqual(response, {'current': None, 'next': None})


if __name__ == '__main__':
    unittest.main()
