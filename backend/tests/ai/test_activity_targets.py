"""Explicit targets remain reachable beyond the compact twenty-item window."""
import sqlite3
import unittest
from contextlib import closing

from backend.app import database
from backend.app.ai.context.activity_targets import requested_activity_ids
from backend.app.ai.observations.activities import build_activity_observation
from backend.app.planner.activities import add_activity


class ActivityTargetTests(unittest.TestCase):
    def test_literal_ids_are_bounded_and_do_not_capture_exam_ids(self):
        self.assertEqual(requested_activity_ids('Edit activity ID 21 and activity #22.'), [21, 22])
        self.assertEqual(requested_activity_ids('Exam ID 21; study for 30 minutes.'), [])
        self.assertEqual(requested_activity_ids('activity ID 21 activity ID 21'), [21])
        self.assertEqual(requested_activity_ids(' '.join(f'activity ID {n}' for n in range(1, 8))), [1, 2, 3])
        self.assertEqual(requested_activity_ids('activity ID 9999999999999999999'), [])

    def test_twenty_first_target_is_read_without_expanding_normal_details(self):
        with closing(sqlite3.connect(':memory:')) as connection:
            database.create_tables(connection)
            for index in range(21):
                add_activity(connection, ['name','category','activity_type','source','external_id'],
                    [f'Study {index}', 'Study', 'daily', 'UoA', 'private-identifier'])
            observation = build_activity_observation(connection, scope='all', activity_ids=[21, 99])
            self.assertEqual(observation['count'], 21)
            self.assertEqual(len(observation['all_activities']), 20)
            self.assertTrue(observation['truncated'])
            self.assertEqual(observation['requested_activities'][0]['id'], 21)
            self.assertEqual(observation['missing_activity_ids'], [99])
            self.assertNotIn('external_id', observation['requested_activities'][0])
            self.assertNotIn('source', observation['requested_activities'][0])

