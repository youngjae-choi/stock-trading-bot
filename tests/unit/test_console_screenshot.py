"""콘솔 어시스턴트 스크린샷 저장(append_screenshot) 단위 테스트.

DOM 스크린샷 dataURL을 파일로 저장하고 MD에 이미지 참조·절대경로를 append하는지 검증.
CLI의 Claude가 그 경로를 Read해 실제 UI를 본다.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from backend.services import console_chat_store as store

# 1x1 투명 PNG
_PNG_1x1 = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


class AppendScreenshotTest(unittest.TestCase):
    def _with_tmp(self, tmp: str):
        return patch.object(store, "_CHAT_DIR", Path(tmp) / "console_chat")

    def test_saves_png_and_appends_md_reference(self):
        with TemporaryDirectory() as tmp, self._with_tmp(tmp):
            res = store.append_screenshot(
                image_data_url=_PNG_1x1, screen_id="dashboard", note="런처 겹침 확인",
            )
            self.assertTrue(res["ok"])
            self.assertTrue(res["image"].startswith("shots/shot_"))
            self.assertTrue(res["image"].endswith(".png"))
            # 실제 파일 저장됨
            img = Path(res["image_path"])
            self.assertTrue(img.exists())
            self.assertEqual(img.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")  # PNG 시그니처
            self.assertEqual(res["bytes"], img.stat().st_size)
            # MD에 절대경로 + 이미지참조 + 노트 append
            md = (Path(tmp) / "console_chat").glob("console_chat_*.md")
            md_text = next(md).read_text(encoding="utf-8")
            self.assertIn("![screenshot](shots/shot_", md_text)
            self.assertIn(str(img), md_text)
            self.assertIn("런처 겹침 확인", md_text)
            self.assertIn("@dashboard", md_text)

    def test_jpeg_dataurl_saved_as_jpg(self):
        jpeg_url = "data:image/jpeg;base64," + _PNG_1x1.split(",", 1)[1]
        with TemporaryDirectory() as tmp, self._with_tmp(tmp):
            res = store.append_screenshot(image_data_url=jpeg_url, screen_id="x")
            self.assertTrue(res["image"].endswith(".jpg"))

    def test_rejects_non_dataurl(self):
        with TemporaryDirectory() as tmp, self._with_tmp(tmp):
            with self.assertRaises(ValueError):
                store.append_screenshot(image_data_url="not-an-image")

    def test_rejects_oversize(self):
        with TemporaryDirectory() as tmp, self._with_tmp(tmp), \
             patch.object(store, "_MAX_IMAGE_BYTES", 1):
            with self.assertRaises(ValueError):
                store.append_screenshot(image_data_url=_PNG_1x1)

    def test_prune_removes_old_shots(self):
        import os
        import time
        with TemporaryDirectory() as tmp, self._with_tmp(tmp):
            store.append_screenshot(image_data_url=_PNG_1x1, screen_id="x")
            old = store._shots_dir() / "shot_20200101_000000.png"
            old.write_bytes(b"x")
            # 8일 전으로 mtime 조작 → 보존기간(7일) 초과
            past = time.time() - 8 * 86400
            os.utime(old, (past, past))
            store._prune_old_shots()
            self.assertFalse(old.exists())


if __name__ == "__main__":
    unittest.main()
