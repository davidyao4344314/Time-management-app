"""External ID tests use isolated SQLite, never the project database/feed."""
import sqlite3
import unittest
from datetime import date, datetime
from unittest.mock import patch

from backend import fastapi_test as api
from backend.app import activities, canvas_import, database, exams, ical_import, uoa_timetable_import


class ExternalIdTests(unittest.TestCase):
    def setUp(self):
        self.c = sqlite3.connect(':memory:')
        self.c.execute('PRAGMA foreign_keys=ON')
        self.c.executescript(database.sql_file.read_text())
        self.addCleanup(self.c.close)

    def event(self, uid, day=7):
        return {'name': 'COMPSCI 130 Lecture', 'external_id': uid,
                'start': datetime(2026, 9, day, 10), 'end': datetime(2026, 9, day, 11)}

    def test_canvas_and_manual_records(self):
        canvas_import.sort_out_canvas_events(self.c, [
            {'name': 'Exam', 'start': date(2026, 9, 7), 'external_id': 'canvas-exam'},
            {'name': 'Lab', 'start': date(2026, 9, 7), 'external_id': 'canvas-lab'},
        ])
        self.assertEqual(api.exam_to_dict(exams.get_all_exams(self.c)[0])['external_id'], 'canvas-exam')
        self.assertEqual(api.activity_to_dict(activities.get_all_activities(self.c)[0])['external_id'], 'canvas-lab')
        activities.add_activity(self.c, ['name', 'category', 'activity_type'], ['Manual', 'Study', 'daily'])
        exams.add_exam(self.c, ['name', 'category', 'date'], ['Manual', 'Study', '2026-09-07'])
        self.assertIsNone(activities.get_all_activities(self.c)[1][12])
        self.assertIsNone(exams.get_all_exams(self.c)[1][8])
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM uoa_activity_external_ids').fetchone()[0], 0)

    def test_uoa_keeps_all_uids_and_reuses_group_on_reimport(self):
        events = [self.event('uid-a'), self.event('uid-b', 14), self.event('uid-a')]
        result = uoa_timetable_import.import_uoa_timetable_to_activities(self.c, events)
        self.assertEqual(result['imported'], 1)
        self.assertEqual(result['mappings_added'], 2)
        rows = activities.get_all_activities(self.c)
        self.assertIsNone(rows[0][12])
        self.assertEqual(rows[0][9:11], ('2026-09-07', '2026-09-14'))
        self.assertEqual(self.c.execute('SELECT activity_id,external_id FROM uoa_activity_external_ids ORDER BY external_id').fetchall(), [(rows[0][0], 'uid-a'), (rows[0][0], 'uid-b')])
        result = uoa_timetable_import.import_uoa_timetable_to_activities(self.c, events[::-1])
        self.assertEqual(result['imported'], 0)
        self.assertEqual(result['mappings_added'], 0)
        self.assertEqual(rows, activities.get_all_activities(self.c))
        activities.delete_activity(self.c, rows[0][0])
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM uoa_activity_external_ids').fetchone()[0], 0)

    def test_missing_uid_and_existing_group(self):
        events = [self.event('later-uid')]
        schedules, _ = uoa_timetable_import.prepare_uoa_activity_ranges(events)
        old_id = activities.add_activity(self.c, *schedules[0])
        result = uoa_timetable_import.import_uoa_timetable_to_activities(self.c, events)
        self.assertEqual(result['imported'], 0)
        self.assertEqual(result['mappings_added'], 1)
        self.assertEqual(self.c.execute('SELECT activity_id FROM uoa_activity_external_ids').fetchone()[0], old_id)
        result = uoa_timetable_import.import_uoa_timetable_to_activities(self.c, [self.event(None, 21)])
        self.assertEqual(result['imported'], 1)
        self.assertEqual(result['mappings_added'], 0)

    def test_compound_uniqueness_and_foreign_key(self):
        first = activities.add_activity(self.c, ['name','category','activity_type'], ['First','University','weekly'])
        second = activities.add_activity(self.c, ['name','category','activity_type'], ['Second','University','weekly'])
        self.assertEqual(activities.save_uoa_external_ids(self.c, first, ['shared','shared']), 1)
        self.assertEqual(activities.save_uoa_external_ids(self.c, second, ['shared']), 1)
        with self.assertRaises(sqlite3.IntegrityError):
            activities.save_uoa_external_ids(self.c, 9999, ['invalid-link'])

    def test_parser_preserves_uid(self):
        content = b'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:example-uid\r\nSUMMARY:Exam\r\nDTSTART;VALUE=DATE:20260907\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n'
        with patch.object(ical_import.requests, 'get') as get:
            get.return_value.content = content
            parsed = ical_import.get_ical_events('https://example.test/test.ics')
            get.return_value.raise_for_status.assert_called_once()
        self.assertEqual(parsed[0]['external_id'], 'example-uid')

    def test_migration_preserves_rows_and_has_no_unique_external_column(self):
        c = sqlite3.connect(':memory:')
        self.addCleanup(c.close)
        legacy = database.sql_file.read_text().split('CREATE TABLE IF NOT EXISTS uoa_activity_external_ids')[0]
        c.executescript(legacy.replace(',\n    external_id TEXT', ''))
        activities.add_activity(c, ['name','category','activity_type'], ['Legacy','Study','daily'])
        exams.add_exam(c, ['name','category','date'], ['Legacy','Study','2026-09-07'])
        before = {table: c.execute(f'SELECT * FROM {table}').fetchall() for table in ('activities','exams')}
        database.add_external_id_storage(c)
        database.add_external_id_storage(c)
        for table in ('activities','exams'):
            after = c.execute(f'SELECT * FROM {table}').fetchall()
            self.assertEqual([row[:-1] for row in after], before[table])
            self.assertIsNone(after[0][-1])
            self.assertEqual(c.execute(f'PRAGMA index_list({table})').fetchall(), [])


if __name__ == '__main__':
    unittest.main()
