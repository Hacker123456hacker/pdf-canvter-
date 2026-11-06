import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from agent import parse_gemini_json, vtt_to_srt


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
