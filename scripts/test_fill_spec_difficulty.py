import unittest

import fill_spec_difficulty as fsd


class SlugFromUrlTests(unittest.TestCase):
    def test_slug_or_none(self):
        cases = [
            ("leetcode url", "https://leetcode.com/problems/median-of-two-sorted-arrays/",
             "median-of-two-sorted-arrays"),
            ("kattis url", "https://open.kattis.com/problems/lostmap", None),
            ("leetcode url without a slug", "https://leetcode.com/problems/", None),
        ]
        for label, url, expected in cases:
            with self.subTest(label):
                self.assertEqual(fsd.slug_from_url(url), expected)


class InsertDifficultyTests(unittest.TestCase):
    def test_insertion(self):
        cases = [
            ("LF", "number: 4\nurl: https://x/\nstatement: |\n  hi\n",
             "number: 4\nurl: https://x/\ndifficulty: Hard\nstatement: |\n  hi\n"),
            ("CRLF", "number: 4\r\nurl: https://x/\r\nstatement: |\r\n  hi\r\n",
             "number: 4\r\nurl: https://x/\r\ndifficulty: Hard\r\nstatement: |\r\n  hi\r\n"),
            ("key already exists", "url: https://x/\ndifficulty: Easy\n",
             "url: https://x/\ndifficulty: Easy\n"),
        ]
        for label, text, expected in cases:
            with self.subTest(label):
                self.assertEqual(fsd.insert_difficulty(text, "Hard"), expected)


if __name__ == "__main__":
    unittest.main()
