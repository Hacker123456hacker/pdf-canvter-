import unittest

from agent import parse_gemini_json


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


if __name__ == "__main__":
    unittest.main()
