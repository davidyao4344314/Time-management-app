"""Test key storage using disposable .env files, never real credentials."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dotenv import dotenv_values
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.ai import config
from backend.app.api import ai


class KeyConfigurationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.env = Path(directory.name) / '.env'
        for p in (patch.object(config, 'AI_ENV_FILE', self.env), patch.dict(os.environ, {}, clear=True)):
            p.start()
            self.addCleanup(p.stop)
        app = FastAPI()
        app.include_router(ai.router)
        self.client = TestClient(app)

    def test_save_preserves_other_settings_and_returns_only_status(self):
        self.env.write_text('UNCHANGED_SETTING=preserve-me\n')
        key = 'sk-offline-test-placeholder-only'
        self.assertEqual(self.client.get('/ai/config/status').json(), {'configured': False})
        response = self.client.post('/ai/config', json={'api_key': key})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'configured': True})
        self.assertNotIn(key, response.text)
        self.assertEqual(dotenv_values(self.env)['UNCHANGED_SETTING'], 'preserve-me')
        self.assertEqual(dotenv_values(self.env)['OPENAI_API_KEY'], key)
        self.assertEqual(self.env.stat().st_mode & 0o777, 0o600)
        os.environ.pop('OPENAI_API_KEY')
        self.assertEqual(self.client.get('/ai/config/status').json(), {'configured': True})

    def test_invalid_key_does_not_replace_existing_configuration(self):
        config.save_openai_api_key('sk-existing-offline-placeholder')
        before = self.env.read_bytes()
        for value in ('', 'short', 'invalid secret with spaces'):
            response = self.client.post('/ai/config', json={'api_key': value})
            self.assertEqual(response.status_code, 400)
            self.assertEqual(self.env.read_bytes(), before)
        self.assertEqual(self.client.get('/ai/config/status').json(), {'configured': True})

    def test_symlink_refused_and_file_errors_do_not_leak_key(self):
        target = self.env.with_name('target')
        target.write_text('unchanged')
        self.env.symlink_to(target)
        key = 'sk-offline-test-placeholder-only'
        response = self.client.post('/ai/config', json={'api_key': key})
        self.assertEqual(response.status_code, 500)
        self.assertNotIn(key, response.text)
        self.assertEqual(target.read_text(), 'unchanged')


if __name__ == '__main__':
    unittest.main()
