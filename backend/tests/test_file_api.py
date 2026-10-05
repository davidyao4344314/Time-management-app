"""Real multipart and signed-owner isolation against a temporary local database."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.app import database
from backend.app.api.files import router
from backend.app.infrastructure import identity


class FileAPITests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        for target, name, value in ((database, "db_file", Path(folder.name) / "test.db"),
                                    (identity, "IDENTITY_KEY_FILE", Path(folder.name) / "key")):
            patcher = patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app)
        self.other = TestClient(app)

    def test_upload_list_read_and_bounded_context_without_model_calls(self):
        with patch("backend.app.ai.agent.service.OpenAI", side_effect=AssertionError("No paid calls")):
            result = self.client.post("/files", files={"file": ("notes.txt", b"Recursion assignment question 4.", "text/plain")})
            self.assertEqual(result.status_code, 200, result.text)
            file = result.json()
            self.assertNotIn("text", file)
            self.assertEqual(self.client.get("/files").json()["files"], [file])
            loaded = self.client.get(f'/files/{file["file_id"]}').json()
            self.assertIn("question 4", loaded["text"])
            context = self.client.post("/files/context", json={"file_ids": [file["file_id"]]}).json()
            self.assertEqual(context["status"], "provided")
            self.assertEqual(context["count"], 1)
            self.assertEqual(self.client.post("/files/context", json={"filename": "missing.pdf"}).json()["status"], "empty")

    def test_known_file_id_cannot_bypass_signed_owner_isolation(self):
        file = self.client.post("/files", files={"file": ("notes.txt", b"Private notes", "text/plain")}).json()
        self.assertEqual(self.other.get(f'/files/{file["file_id"]}').status_code, 404)
        self.assertEqual(self.other.get("/files").json()["files"], [])
        self.assertEqual(self.other.post("/files/context", json={"file_ids": [file["file_id"]]}).json()["count"], 0)
        self.other.cookies.set("ai_owner", self.client.cookies.get("ai_owner"))
        self.assertEqual(self.other.get(f'/files/{file["file_id"]}').status_code, 404)

    def test_unsupported_empty_oversized_and_path_requests_are_rejected(self):
        for filename, data in (("notes.exe", b"not supported"), ("notes.txt", b""), ("../notes.txt", b"text")):
            result = self.client.post("/files", files={"file": (filename, data, "application/octet-stream")})
            self.assertEqual(result.status_code, 400)
        oversized = self.client.post("/files", files={"file": ("notes.txt", b"x" * (5 * 1024 * 1024 + 1))})
        self.assertEqual(oversized.status_code, 413)
        self.assertEqual(self.client.post("/files/context", json={"query": "../secret"}).status_code, 422)
        self.assertEqual(self.client.get("/files").json()["files"], [])


if __name__ == "__main__":
    unittest.main()
