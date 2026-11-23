import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from creator_upgrades import (
    build_seo_metadata, is_duplicate_topic, remember_topic,
    split_srt_word_by_word, topic_fingerprint, write_analytics_dashboard,
)


class CreatorUpgradeTests(unittest.TestCase):
    def test_wordwise_srt_splits_words_and_preserves_total_timing(self):
        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "in.srt"
            target = Path(tmp) / "out.srt"
            source.write_text("1\n00:00:00,000 --> 00:00:02,000\nनमस्ते दुनिया मित्रों\n", encoding="utf-8")
            self.assertEqual(split_srt_word_by_word(source, target), 3)
            result = target.read_text(encoding="utf-8")
            self.assertIn("नमस्ते", result)
            self.assertIn("दुनिया", result)
            self.assertIn("मित्रों", result)
            self.assertIn("00:00:02,000", result)
            self.assertEqual(result.count(" --> "), 3)

    def test_topic_history_detects_normalized_duplicates(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "state" / "topics.json"
            remember_topic("श्री कृष्ण का संदेश", path)
            self.assertTrue(is_duplicate_topic("श्री   कृष्ण का संदेश!", path))
            self.assertFalse(is_duplicate_topic("हनुमान जी की सीख", path))

    def test_seo_metadata_is_bounded_and_deduplicated(self):
        data = build_seo_metadata({"title": "  A " * 80, "tags": ["Bhakti", "bhakti", "Krishna"]})
        self.assertLessEqual(len(data["title"]), 95)
        self.assertEqual(data["tags"], ["Bhakti", "Krishna"])

    def test_dashboard_is_written_without_credentials(self):
        with TemporaryDirectory() as tmp:
            path = write_analytics_dashboard(tmp)
            self.assertTrue(path.exists())
            self.assertIn("Analytics API not configured", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
