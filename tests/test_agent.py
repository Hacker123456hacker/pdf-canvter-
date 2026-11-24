import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from agent import make_slides, make_thumbnail, parse_gemini_json, validate_video_probe, vtt_to_srt, write_approximate_srt
from PIL import Image


class GeminiResponseTests(unittest.TestCase):
    def test_parses_plain_json(self):
        data = parse_gemini_json('{"title":"Test","narration":"नमस्ते","slides":["एक","दो"]}')
        self.assertEqual(data["title"], "Test")
        self.assertEqual(data["slides"], ["एक", "दो"])

    def test_parses_markdown_fenced_json_with_prose(self):
        raw = 'Result:\n```json\n{"title":"Test","narration":"Voice","slides":["A"]}\n```'
        data = parse_gemini_json(raw)
        self.assertEqual(data["narration"], "Voice")

    def test_rejects_missing_required_fields(self):
        with self.assertRaisesRegex(ValueError, "narration"):
            parse_gemini_json('{"title":"Test","slides":["A"]}')

    def test_rejects_invalid_slides(self):
        with self.assertRaisesRegex(ValueError, "slides"):
            parse_gemini_json('{"title":"Test","narration":"Voice","slides":"not a list"}')


class VideoQualityTests(unittest.TestCase):
    def good_probe(self):
        return {
            "format": {"duration": "42.5"},
            "streams": [
                {"codec_type": "video", "codec_name": "h264", "width": 1080, "height": 1920},
                {"codec_type": "audio", "codec_name": "aac"},
            ],
        }

    def test_accepts_valid_vertical_video_with_audio(self):
        report = validate_video_probe(self.good_probe(), file_size=500_000)
        self.assertEqual(report["width"], 1080)
        self.assertEqual(report["height"], 1920)
        self.assertEqual(report["duration"], 42.5)

    def test_rejects_video_without_audio(self):
        probe = self.good_probe()
        probe["streams"] = probe["streams"][:1]
        with self.assertRaisesRegex(RuntimeError, "no audio"):
            validate_video_probe(probe, file_size=500_000)

    def test_rejects_wrong_resolution(self):
        probe = self.good_probe()
        probe["streams"][0]["width"] = 1280
        with self.assertRaisesRegex(RuntimeError, "resolution"):
            validate_video_probe(probe, file_size=500_000)

    def test_rejects_out_of_range_duration(self):
        probe = self.good_probe()
        probe["format"]["duration"] = "12"
        with self.assertRaisesRegex(RuntimeError, "duration"):
            validate_video_probe(probe, file_size=500_000)

    def test_rejects_tiny_file(self):
        with self.assertRaisesRegex(RuntimeError, "too small"):
            validate_video_probe(self.good_probe(), file_size=10)


class SubtitleTests(unittest.TestCase):
    def test_converts_webvtt_to_srt(self):
        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "voice.vtt"
            target = Path(tmp) / "voice.srt"
            source.write_text(
                "WEBVTT\n\n00:00:00.000 --> 00:00:00.500\nनमस्ते दुनिया\n",
                encoding="utf-8",
            )
            self.assertTrue(vtt_to_srt(source, target))
            output = target.read_text(encoding="utf-8")
            self.assertIn("00:00:00,000 --> 00:00:00,500", output)
            self.assertIn("नमस्ते दुनिया", output)

    def test_rejects_empty_webvtt(self):
        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "empty.vtt"
            target = Path(tmp) / "empty.srt"
            source.write_text("WEBVTT\n\n", encoding="utf-8")
            self.assertFalse(vtt_to_srt(source, target))
            self.assertEqual(target.read_text(encoding="utf-8"), "")


class ThumbnailTests(unittest.TestCase):
    def test_creates_1280x720_thumbnail(self):
        with TemporaryDirectory() as tmp:
            scene = Path(tmp) / "scene.jpg"
            Image.new("RGB", (360, 640), (30, 60, 90)).save(scene)
            thumb = make_thumbnail("भगवान श्रीकृष्ण का संदेश", scene, {"video": {}})
            try:
                with Image.open(thumb) as result:
                    self.assertEqual(result.size, (1280, 720))
                    self.assertEqual(result.format, "JPEG")
            finally:
                thumb.unlink(missing_ok=True)


class SceneAlignmentTests(unittest.TestCase):
    def test_missing_scene_image_does_not_reuse_another_scenes_photo(self):
        import agent
        with TemporaryDirectory() as tmp:
            original_work = agent.WORK
            agent.WORK = Path(tmp)
            try:
                first = Path(tmp) / "first.jpg"
                Image.new("RGB", (80, 120), (255, 0, 0)).save(first)
                scenes = make_slides(
                    ["scene one", "scene two"],
                    {"video": {"width": 80, "height": 120}},
                    [first, None],
                )
                self.assertEqual(len(scenes), 2)
                with Image.open(scenes[0]) as a, Image.open(scenes[1]) as b:
                    self.assertGreater(a.getpixel((40, 60))[0], 240)
                    self.assertLess(a.getpixel((40, 60))[1], 20)
                    self.assertNotEqual(b.getpixel((40, 60)), (255, 0, 0))
            finally:
                agent.WORK = original_work
                for p in Path(tmp).glob("slide_*.jpg"):
                    p.unlink(missing_ok=True)


class RegressionTests(unittest.TestCase):
    def test_whitespace_patterns_collapse_and_split(self):
        import re
        self.assertEqual(re.sub(r"\s+", " ", "one   two"), "one two")
        self.assertEqual(re.split(r"(?<=[.!?])\s+", "First. Second"), ["First.", "Second"])

    def test_empty_gemini_candidate_text_uses_fallback_error_not_index_error(self):
        from unittest.mock import Mock, patch
        import agent
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"candidates": [{"content": {"parts": []}}]}
        env = {
            "GEMINI_API_KEY": "dummy",
            "GEMINI_API_KEY_2": "",
            "GEMINI_API_KEY_3": "",
            "GEMINI_MODEL": "test-model",
            "GEMINI_FALLBACK_MODELS": "",
        }
        with patch.dict("os.environ", env, clear=False), patch("agent.requests.post", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "generation failed"):
                agent.gemini("test")

    def test_config_example_defaults_to_public_upload(self):
        import json
        config = json.loads(
            (Path(__file__).resolve().parents[1] / "config.example.json").read_text(encoding="utf-8")
        )
        self.assertEqual(config["channel"]["privacy_status"], "public")


if __name__ == "__main__":
    unittest.main()


class FallbackSubtitleTests(unittest.TestCase):
    def test_approximate_srt_covers_audio_end(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "fallback.srt"
            self.assertTrue(write_approximate_srt("पहला वाक्य। दूसरा वाक्य।", 30.0, target))
            data = target.read_text(encoding="utf-8")
            self.assertIn("00:00:30,000", data)
            self.assertIn("दूसरा वाक्य।", data)


class OpenRouterFallbackTests(unittest.TestCase):
    def test_extracts_chat_completion_text(self):
        from unittest.mock import Mock, patch
        import agent
        response = Mock()
        response.ok = True
        response.json.return_value = {"model": "test/model", "choices": [{"message": {"content": '{"title":"Test"}'}}]}
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "dummy", "OPENROUTER_MODEL": "test/model"}, clear=False), patch("agent.requests.post", return_value=response):
            raw = agent.openrouter_generate("Return JSON")
        self.assertIn('"title":"Test"', raw)


class GroqFallbackTests(unittest.TestCase):
    def test_groq_extracts_chat_completion_text(self):
        from unittest.mock import Mock, patch
        import agent
        response = Mock()
        response.ok = True
        response.json.return_value = {"model": "test-groq", "choices": [{"message": {"content": '{"title":"Test"}'}}]}
        with patch.dict("os.environ", {"GROQ_API_KEY": "dummy", "GROQ_MODEL": "test-groq"}, clear=False), patch("agent.requests.post", return_value=response):
            raw = agent.groq_generate("Return JSON")
        self.assertIn('"title":"Test"', raw)
