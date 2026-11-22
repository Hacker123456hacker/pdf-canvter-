import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from agent import parse_gemini_json, validate_video_probe, vtt_to_srt


class GeminiResponseTests(unittest.TestCase):
    def test_parses_plain_json(self):
        data = parse_gemini_json(
            '{"title":"Test","narration":"नमस्ते","slides":["एक","दो"]}'
        )
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


if __name__ == "__main__":
    unittest.main()
