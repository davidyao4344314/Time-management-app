"""Source metadata and migration tests; never use the project database."""
import sqlite3
import unittest
from datetime import date, datetime

from backend import fastapi_test as api
from backend.app import activities, calender, canvas_import, database, exams, uoa_timetable_import


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.addCleanup(self.connection.close)

    def test_new_records_and_api_sources(self):
        self.connection.executescript(database.sql_file.read_text())
        # Even a manually chosen import-like category must default to Manual.
        activities.add_activity(self.connection,
            ['name', 'category', 'activity_type', 'date'],
            ['Manual task', 'Canvas', 'one_time', '2026-09-10'])
        exams.add_exam(self.connection, ['name', 'category', 'date'],
                       ['Manual exam', 'Canvas', '2026-09-10'])
        canvas_import.sort_out_canvas_events(self.connection, [
            {'name': 'Lab [COMPSCI 130]', 'start': date(2026, 9, 10)},
            {'name': 'Exam [COMPSCI 130]', 'start': date(2026, 9, 10)},
        ])
        uoa_timetable_import.import_uoa_timetable_to_activities(self.connection, [{
            'name': 'COMPSCI 130 Lecture',
            'start': datetime(2026, 9, 10, 10), 'end': datetime(2026, 9, 10, 11),
        }])
        database.add_record_sources(self.connection)
        activity_rows = activities.get_all_activities(self.connection)
        exam_rows = exams.get_all_exams(self.connection)
        self.assertEqual([api.activity_to_dict(row)['source'] for row in activity_rows], ['Manual', 'Canvas', 'UoA'])
        self.assertEqual([api.exam_to_dict(row)['source'] for row in exam_rows], ['Manual', 'Canvas'])
        weekly = calender.get_week_activities(self.connection, date(2026, 9, 7))
        self.assertEqual({row['source'] for row in weekly}, {'Manual', 'Canvas', 'UoA'})
        self.assertEqual(activity_rows[2][9:11], ('2026-09-10', '2026-09-10'))
        self.assertNotIn('source', activities.get_clomuns(self.connection, 'activities'))

    def test_existing_rows_migrate_without_changing_fields_or_ids(self):
        legacy_schema = database.sql_file.read_text().replace(",\n    source TEXT NOT NULL DEFAULT 'Manual'", '')
        legacy_schema = legacy_schema.replace(",\n    external_id TEXT", '')
        legacy_schema = legacy_schema.split('CREATE TABLE IF NOT EXISTS uoa_activity_external_ids')[0]
        self.connection.executescript(legacy_schema)
        rows = [
            ('Canvas UoA exam in a name', 'Study', 'weekly', None, None),
            ('Imported lab', 'Canvas', 'one_time', None, None),
            ('Imported class', 'University', 'weekly', '2026-07-20', '2026-10-19'),
            ('Uncertain university activity', 'University', 'weekly', None, None),
        ]
        self.connection.executemany('INSERT INTO activities (name,category,activity_type,active_start_date,active_end_date) VALUES (?,?,?,?,?)', rows)
        self.connection.execute("INSERT INTO exams (name,category,date) VALUES ('Imported exam','Canvas','2026-09-10')")
        self.connection.execute("INSERT INTO exams (name,category,date) VALUES ('Canvas in name','Study','2026-09-10')")
        self.connection.commit()
        before = {table: self.connection.execute(f'SELECT * FROM {table}').fetchall() for table in ('activities', 'exams')}
        database.add_record_sources(self.connection)
        for table in ('activities', 'exams'):
            after = self.connection.execute(f'SELECT * FROM {table}').fetchall()
            self.assertEqual([row[:-1] for row in after], before[table])
        self.assertEqual([r[-1] for r in activities.get_all_activities(self.connection)], ['Manual', 'Canvas', 'UoA', 'Manual'])
        self.assertEqual([r[-1] for r in exams.get_all_exams(self.connection)], ['Canvas', 'Manual'])
        # Running the migration again must never reclassify a Manual record.
        self.connection.execute("UPDATE activities SET source='Manual' WHERE category='Canvas'")
        self.connection.commit()
        database.add_record_sources(self.connection)
        self.assertEqual(activities.get_all_activities(self.connection)[1][-1], 'Manual')

    def test_existing_empty_sources_use_manual_without_name_guessing(self):
        schema = database.sql_file.read_text().replace("source TEXT NOT NULL DEFAULT 'Manual'", 'source TEXT')
        self.connection.executescript(schema)
        self.connection.execute("INSERT INTO activities (name,category,activity_type,source) VALUES ('Canvas','Canvas','daily',NULL)")
        self.connection.execute("INSERT INTO exams (name,category,date,source) VALUES ('UoA','University','2026-09-10','')")
        self.connection.commit()
        database.add_record_sources(self.connection)
        self.assertEqual(activities.get_all_activities(self.connection)[0][11], 'Manual')
        self.assertEqual(exams.get_all_exams(self.connection)[0][7], 'Manual')


if __name__ == '__main__':
    unittest.main()
