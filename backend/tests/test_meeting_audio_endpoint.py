"""時間戳回放音檔串流端點契約測試（/api/app/meeting-audio）.

stdlib unittest，無 provider/network/credential。直接呼叫端點函數（repo 慣例，不用 TestClient）。
驗：合法音檔回 FileResponse + Accept-Ranges；帶 Range 回 206 + Content-Range（seek 真支援，
釘住 starlette 0.38 FileResponse 不支援 Range 的缺陷）；不可滿足 Range 回 416；非音訊副檔 400；
不存在 404。
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import routers.library as M  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from fastapi.responses import FileResponse, Response, StreamingResponse  # noqa: E402


class _Req:
    """Minimal Request stand-in: the endpoint only reads request.headers.get('range')."""
    def __init__(self, headers=None, query=None):
        self.headers = headers or {}
        self.query_params = query or {}


class MeetingAudioEndpoint(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _audio(self, size=4096):
        f = self.root / "meeting.m4a"
        f.write_bytes(b"\x00" * size)
        return f

    def test_no_range_returns_fileresponse_with_accept_ranges(self):
        resp = M.app_state_meeting_audio(str(self._audio()), _Req())
        self.assertIsInstance(resp, FileResponse)
        self.assertEqual(resp.media_type, "audio/m4a")
        self.assertEqual(resp.headers.get("accept-ranges"), "bytes")

    def test_range_returns_206_with_content_range(self):
        resp = M.app_state_meeting_audio(str(self._audio(4096)), _Req({"range": "bytes=0-1023"}))
        self.assertIsInstance(resp, StreamingResponse)
        self.assertEqual(resp.status_code, 206)
        self.assertEqual(resp.headers.get("content-range"), "bytes 0-1023/4096")
        self.assertEqual(resp.headers.get("content-length"), "1024")

    def test_unsatisfiable_range_returns_416(self):
        resp = M.app_state_meeting_audio(str(self._audio(100)), _Req({"range": "bytes=999-1999"}))
        self.assertIsInstance(resp, Response)
        self.assertEqual(resp.status_code, 416)

    def test_non_audio_extension_rejected_400(self):
        f = self.root / "notes.txt"
        f.write_text("not audio")
        with self.assertRaises(HTTPException) as ctx:
            M.app_state_meeting_audio(str(f), _Req())
        self.assertEqual(ctx.exception.status_code, 400)

    def test_missing_file_404(self):
        with self.assertRaises(HTTPException) as ctx:
            M.app_state_meeting_audio(str(self.root / "gone.mp3"), _Req())
        self.assertEqual(ctx.exception.status_code, 404)

    def test_configured_session_requires_path_bound_ticket(self):
        audio = self._audio()
        with mock.patch.dict("os.environ", {"YT_NOTE_APP_SESSION_TOKEN": "secret"}):
            ticket = M.app_state_meeting_audio_ticket(M.MeetingAudioTicketReq(audio_path=str(audio)))["ticket"]
            self.assertIsInstance(M.app_state_meeting_audio(str(audio), _Req(query={"ticket": ticket})), FileResponse)
            with self.assertRaises(HTTPException) as ctx:
                M.app_state_meeting_audio(str(audio), _Req(query={"ticket": "wrong"}))
            self.assertEqual(ctx.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()
