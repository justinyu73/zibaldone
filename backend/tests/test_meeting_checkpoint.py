"""會議 ASR checkpoint 讀取契約——回歸鎖（此函式曾斷裂成永遠回 None、retry 重轉錄）。"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services import meetings as M  # noqa: E402


class MeetingCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"YT_NOTE_ASR_ROOT": self.tmp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_roundtrip_returns_transcript(self):
        # 用與 on_transcript 相同的落盤格式寫入 → 讀回必須是 transcript 本文
        key = "k1"
        M._meeting_checkpoint_path(key).write_text(
            json.dumps({"schema_version": M._MEETING_CHECKPOINT_SCHEMA,
                        "transcript": "逐字稿內容"}, ensure_ascii=False),
            encoding="utf-8")
        self.assertEqual(M._read_meeting_checkpoint(key), "逐字稿內容")

    def test_missing_file_returns_none(self):
        self.assertIsNone(M._read_meeting_checkpoint("nope"))

    def test_corrupt_file_returns_none(self):
        key = "k2"
        M._meeting_checkpoint_path(key).write_text("not json", encoding="utf-8")
        self.assertIsNone(M._read_meeting_checkpoint(key))


if __name__ == "__main__":
    unittest.main()
