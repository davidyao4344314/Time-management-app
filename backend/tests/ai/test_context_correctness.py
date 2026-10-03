"""Regression checks for routing and complete scheduling facts, without API calls."""
import unittest
from datetime import date
from unittest.mock import patch

from backend.app.ai.context.keywords import assess_stage_one
from backend.app.ai.context.intent import context_from_classification
from backend.app.ai.observations.formatting import observation_date_range
from backend.app.ai.observations.exams import build_exam_observation
from backend.app.ai.agent.reasoning import build_agent_messages
from backend.app.ai.observations.activities import build_activity_observation
from datetime import timedelta
import json


class ContextCorrectnessTests(unittest.TestCase):
    def test_limited_details_keep_all_busy_dates(self):
        def occurrences(connection, start):
            return [{'id':number, 'name':f'Class {number}',
                     'calendar_date':(start + timedelta(days=day)).isoformat(),
                     'start_time':f'{number+9:02}:00', 'end_time':f'{number+10:02}:00'}
                    for day in range(7) for number in range(4)]
        with patch('backend.app.ai.observations.activities.get_current_date', return_value=date(2026, 10, 3)), \
             patch('backend.app.ai.observations.activities.get_current_time', return_value='08:00'), \
             patch('backend.app.ai.observations.activities.get_current_and_next_activities', return_value=([], None)), \
             patch('backend.app.ai.observations.activities.get_week_activities', side_effect=occurrences):
            for scope in ('week', 'month'):
                result = build_activity_observation(None, scope)
                self.assertTrue(result['truncated'])
                self.assertGreater(result['count'], 20)
                self.assertEqual(len(result['upcoming_7d' if scope == 'week' else 'upcoming_month']), 20)
                self.assertEqual(result['busy'][result['period']['end']], [['09:00','13:00']])

    def test_empty_schedule_still_has_authoritative_clock(self):
        clock = {'date':'2026-10-04', 'time':'12:00', 'timezone':'Pacific/Auckland',
                 'as_of':'2026-10-04T12:00:00+13:00'}
        with patch('backend.app.ai.agent.reasoning.observation_clock', return_value=clock):
            payload = json.loads(build_agent_messages('Plan study tonight', {})[-1]['content'])
        self.assertEqual(payload['clock'], clock)
        self.assertEqual(payload['observations'], {})

    def test_requested_calendar_weeks(self):
        today = date(2026, 10, 3)
        for phrase, scope, start, end in (
            ('this week', 'this_week', date(2026, 9, 28), date(2026, 10, 4)),
            ('next week', 'next_week', date(2026, 10, 5), date(2026, 10, 11)),
            ('next few days', 'week', today, date(2026, 10, 9)),
            ('tomorrow', 'tomorrow', date(2026, 10, 4), date(2026, 10, 4)),
        ):
            selected = assess_stage_one(f'What am I doing {phrase}?')
            self.assertTrue(selected['confident'])
            self.assertEqual(selected['selection']['activities_scope'], scope)
            self.assertEqual(observation_date_range(today, scope), (start, end))

    def test_next_week_exams_exclude_current_week(self):
        exams = [(1, 'This week', '', '', '2026-10-04', None, None),
                 (2, 'Next week', '', '', '2026-10-05', None, None)]
        with patch('backend.app.ai.observations.exams.get_current_date', return_value=date(2026, 10, 3)), \
             patch('backend.app.ai.observations.exams.get_current_time', return_value='12:00'), \
             patch('backend.app.ai.observations.exams.get_all_exams', return_value=exams):
            result = build_exam_observation(None, scope='next_week')
        self.assertEqual([item['name'] for item in result['upcoming']], ['Next week'])
        self.assertEqual(context_from_classification({'intent':'exam_query', 'time_scope':'next_week',
            'include_activities':False, 'include_exams':True})['exam_scope'], 'next_week')
