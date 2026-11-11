"""Fresh completion context using real read-only SQLite and mocked model replies."""

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from backend.app import database
from backend.app.planner import study_sessions
from backend.app.ai.observations import study_sessions as observation
from backend.app.ai.observations.collect import collect_agent_observations
from backend.app.ai.context import selection
from backend.app.ai.context.study_history import requests_study_history
from backend.app.ai.agent import service
from backend.app.ai.agent.context_recovery import read_observation
from backend.app.ai.agent.followup import prepare_followup


class StudySessionObservationTests(unittest.TestCase):
    def setUp(self):
        folder = self.enterContext(tempfile.TemporaryDirectory())
        self.path = Path(folder) / 'test.db'
        self.enterContext(patch.object(database, 'db_file', self.path))
        now = datetime(2026, 11, 11, 10, tzinfo=ZoneInfo('Pacific/Auckland'))
        for module in (study_sessions, observation):
            self.enterContext(patch.object(module, 'local_now', return_value=now))
        database.initialize_database((('008_study_sessions', study_sessions.migrate),))
        self.writer = self.enterContext(closing(database.create_connection()))
        self.activity_id = self.add_activity()
        self.reader = self.enterContext(closing(sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True)))

    def add_activity(self, name='Revision', category='Study', **fields):
        data = {'name': name, 'category': category, 'subject': 'COMPSCI 130', 'activity_type': 'daily', **fields}
        with self.writer:
            return self.writer.execute(
                f"INSERT INTO activities ({', '.join(data)}) VALUES ({', '.join('?' for _ in data)})",
                tuple(data.values())).lastrowid

    def test_outcomes_minutes_and_automatic_missed_match_home_without_writes(self):
        study_sessions.save_session(self.writer, self.activity_id, date(2026, 11, 10), 'partly_done', 25)
        lecture = self.add_activity('Lecture', 'University')
        study_sessions.save_session(self.writer, lecture, date(2026, 11, 10), 'done', 60)
        self.add_activity('Practice')
        before = self.reader.total_changes
        result = observation.build_study_session_observation(self.reader, 'yesterday')
        self.assertEqual(result['period'], {'start': '2026-11-10', 'end': '2026-11-10'})
        self.assertEqual(result['counts'], {'done': 1, 'partly_done': 1, 'missed': 1, 'unrecorded': 0})
        self.assertEqual(result['actual_minutes'], 85)
        self.assertEqual(result['recorded_count'], 2)
        self.assertEqual(result['automatic_missed_count'], 1)
        groups = {item['category']: item['actual_minutes'] for item in result['by_subject_category']}
        self.assertEqual(groups, {'Study': 25, 'University': 60})
        self.assertEqual(self.reader.total_changes, before)
        self.assertEqual(self.writer.execute('SELECT count(*) FROM study_sessions').fetchone(), (2,))

    def test_today_unrecorded_minutes_are_unknown_and_manual_missed_is_distinct(self):
        result = observation.build_study_session_observation(self.reader, 'today')
        self.assertEqual(result['sessions'][0]['status'], 'unrecorded')
        self.assertIsNone(result['sessions'][0]['actual_minutes'])
        study_sessions.save_session(self.writer, self.activity_id, date(2026, 11, 11), 'missed', 0)
        result = observation.build_study_session_observation(self.reader, 'today')
        self.assertFalse(result['sessions'][0]['automatic'])
        self.assertEqual(result['recorded_count'], 1)

    def test_date_scopes_and_bounded_totals_with_truncated_details(self):
        today = date(2026, 11, 11)
        for text, first, last in [
            ('last week', '2026-11-02', '2026-11-08'),
            ('this week', '2026-11-09', '2026-11-11'),
            ('last month', '2026-10-01', '2026-10-31'),
            ('this month', '2026-11-01', '2026-11-11'),
            ('on 2026-10-12', '2026-10-12', '2026-10-12'),
            ('', '2026-11-05', '2026-11-11'),
        ]:
            start, end, limited = observation.history_period(text, today)
            self.assertEqual((start.isoformat(), end.isoformat(), limited), (first, last, False))
        result = observation.build_study_session_observation(self.reader, 'past 90 days')
        self.assertTrue(result['period_limited'])
        self.assertEqual(result['count'], 31)
        self.assertEqual(result['automatic_missed_count'], 30)
        self.assertEqual(result['counts']['unrecorded'], 1)
        self.assertTrue(result['truncated'])
        self.assertLessEqual(len(result['sessions']), 20)
        self.assertLessEqual(len(json.dumps(result['sessions'], ensure_ascii=False)), 6000)

    def test_saved_snapshot_survives_definition_changes(self):
        study_sessions.save_session(self.writer, self.activity_id, date(2026, 11, 10), 'done', 45)
        with self.writer:
            self.writer.execute("UPDATE activities SET name='Moved', activity_type='one_time', date='2026-11-11' WHERE id=?", (self.activity_id,))
        result = observation.build_study_session_observation(self.reader, 'yesterday')
        self.assertEqual(result['sessions'][0]['name'], 'Revision')
        self.assertEqual(result['sessions'][0]['actual_minutes'], 45)

    def test_explicit_exclusions_prevent_history_reads(self):
        for message in ("Don't use my activities; show my missed sessions yesterday.",
                        'Ignore my study history; give generic study advice.'):
            selected = selection.select_agent_context(Mock(), message, [], 'mock')
            history = Mock(side_effect=AssertionError('Excluded history was read'))
            context = collect_agent_observations(self.reader, selected,
                activity_builder=Mock(), exam_builder=Mock(return_value={}), study_history_builder=history)
            self.assertNotIn('activities', context)
            history.assert_not_called()

    def test_history_questions_route_without_a_classifier_and_mixed_requests_keep_exams(self):
        for message in ('Which activities did I complete yesterday?', 'What have I finished today?',
                        'Show my missed sessions last week.', 'How much time did I study last month?'):
            self.assertTrue(requests_study_history(message), message)
            client = Mock()
            selected = selection.select_agent_context(client, message, [], 'mock')
            self.assertEqual(selected, {'activities_scope': 'today', 'include_exams': False, 'exam_scope': None})
            client.responses.parse.assert_not_called()
        self.assertFalse(requests_study_history('Explain why students miss study sessions.'))
        selected = selection.select_agent_context(Mock(), 'Show my missed sessions and exams this week.', [], 'mock')
        self.assertIsNotNone(selected['activities_scope'])
        self.assertTrue(selected['include_exams'])

    def test_agent_receives_history_and_inspector_only_exposes_aggregates(self):
        study_sessions.save_session(self.writer, self.activity_id, date(2026, 11, 10), 'done', 45)
        with patch.object(service, 'is_openai_api_key_configured', return_value=True), \
             patch.dict(service.os.environ, {'OPENAI_API_KEY': 'offline-test-key'}), \
             patch.object(service, 'get_agent_model_settings', return_value={'model': 'mock', 'reasoning_effort': 'none'}), \
             patch.object(service, 'OpenAI') as factory:
            client = factory.return_value.__enter__.return_value
            client.responses.parse.return_value = SimpleNamespace(status='completed', output_parsed={
                'message': 'Your recorded study time was 45 minutes.', 'actions': [], 'memory_request': None, 'missing_context': []})
            result = service.get_agent_proposal(self.reader, 'What did I finish yesterday?', include_context=True)
        self.assertEqual(client.responses.parse.call_count, 1)
        payload = json.loads(client.responses.parse.call_args.kwargs['input'][-1]['content'])
        history = payload['observations']['activities']['study_sessions']
        self.assertEqual(history['actual_minutes'], 45)
        self.assertEqual(history['sessions'][0]['status'], 'done')
        metadata = result['agent_context']['study_session_context']
        self.assertEqual(metadata['actual_minutes'], 45)
        self.assertNotIn('sessions', metadata)
        self.assertEqual(result['actions'], [])
        self.assertEqual(self.reader.total_changes, 0)

    def test_missing_storage_is_unavailable_not_empty(self):
        connection = self.enterContext(closing(sqlite3.connect(':memory:')))
        result = read_observation(observation.build_study_session_observation, connection, 'yesterday')
        self.assertEqual(result, {'status': 'unavailable'})

    def test_calendar_recovery_preserves_already_read_history(self):
        history = {'status': 'provided', 'count': 1, 'actual_minutes': 45}
        context = {'activities': {'count': 0, 'study_sessions': history}}
        trace = {'attempts': 0, 'requests': []}
        action = {'tool': 'add_activity', 'arguments': {'name': 'Study', 'category': 'Study', 'subject': None,
            'activity_type': 'one_time', 'date': '2026-11-12', 'weekday': None, 'start_time': '12:00', 'end_time': '13:00'}}
        read_schedule = Mock(return_value={'count': 0, 'checked_dates': ['2026-11-12'], 'busy': {}})
        result = prepare_followup({'actions': [action], 'missing_context': [], 'memory_request': None},
            context=context, context_status={'activities': 'provided'},
            selection={'activities_scope': 'today'}, session_id=None, excluded_sources=(), trace=trace,
            lookups=[], include_context=True, collect=Mock(), read_schedule=read_schedule, read_memory=Mock())
        self.assertIsNone(result.clarification)
        self.assertEqual(context['activities']['study_sessions'], history)


if __name__ == '__main__':
    unittest.main()
