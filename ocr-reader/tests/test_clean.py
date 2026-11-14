"""Clean tests: one test per rule, plus idempotence and the
never-changes-words property.

Rule 5 (space before punctuation) merges two whitespace tokens
into one ("word ." becomes "word."), so the word property is
checked on alphanumeric word tokens, which no rule may change:
joining lines keeps the same words in the same order.
"""

import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from ocrreader.clean import clean_text  # noqa: E402

_WORD = re.compile(r"[A-Za-z0-9']+")

MESSY = ("hello  world .  \n"
         "\n"
         "\n"
         "\n"
         "the fox\n"
         "jumps\n")


class CleanRuleTests(unittest.TestCase):
    def test_rule_1_strips_trailing_whitespace(self):
        # Uppercase starts so rule 6 does not join the lines.
        cleaned, changes = clean_text("Hello   \nWorld\t")
        self.assertEqual(cleaned, "Hello\nWorld")
        self.assertEqual(
            changes, ["trimmed trailing whitespace on 2 lines"])

    def test_rule_2_collapses_blank_runs(self):
        cleaned, changes = clean_text("a\n\n\n\nb")
        self.assertEqual(cleaned, "a\n\nb")
        self.assertEqual(changes, ["removed 2 blank lines"])

    def test_rule_3_strips_leading_and_trailing_blanks(self):
        # Uppercase lines so rule 6 does not join them.
        cleaned, changes = clean_text("\n\nA\nB\n\n")
        self.assertEqual(cleaned, "A\nB")
        self.assertEqual(changes, ["removed 4 blank lines"])

    def test_rule_4_collapses_runs_of_spaces(self):
        cleaned, changes = clean_text("a  b   c")
        self.assertEqual(cleaned, "a b c")
        self.assertEqual(
            changes, ["collapsed 2 runs of extra spaces"])

    def test_rule_5_removes_space_before_punctuation(self):
        cleaned, changes = clean_text(
            "word . next , done ! really ? yes ; ok :")
        self.assertEqual(
            cleaned, "word. next, done! really? yes; ok:")
        self.assertEqual(
            changes, ["fixed 6 spaces before punctuation"])

    def test_rule_6_joins_wrapped_mid_sentence_lines(self):
        cleaned, changes = clean_text(
            "the quick brown\nfox jumps over\nthe lazy dog.")
        self.assertEqual(
            cleaned, "the quick brown fox jumps over the lazy dog.")
        self.assertEqual(changes, ["joined 2 wrapped lines"])

    def test_rule_6_joins_after_a_comma(self):
        cleaned, changes = clean_text("one,\ntwo")
        self.assertEqual(cleaned, "one, two")
        self.assertEqual(changes, ["joined 1 wrapped line"])

    def test_rule_6_does_not_join_before_uppercase(self):
        cleaned, changes = clean_text(
            "the quick brown\nFox jumps")
        self.assertEqual(cleaned, "the quick brown\nFox jumps")
        self.assertEqual(changes, [])

    def test_rule_6_does_not_join_after_a_period(self):
        cleaned, changes = clean_text("the dog.\nfox jumps")
        self.assertEqual(cleaned, "the dog.\nfox jumps")
        self.assertEqual(changes, [])

    def test_rule_6_does_not_join_across_a_blank_line(self):
        cleaned, changes = clean_text("brown\n\nfox")
        self.assertEqual(cleaned, "brown\n\nfox")
        self.assertEqual(changes, [])

    def test_combined_changes_list(self):
        cleaned, changes = clean_text(MESSY)
        self.assertEqual(cleaned, "hello world.\n\nthe fox jumps")
        self.assertEqual(changes, [
            "trimmed trailing whitespace on 1 line",
            "collapsed 1 run of extra spaces",
            "fixed 1 space before punctuation",
            "joined 1 wrapped line",
            "removed 3 blank lines",
        ])

    def test_empty_input_is_unchanged(self):
        self.assertEqual(clean_text(""), ("", []))

    def test_clean_text_reports_no_changes(self):
        cleaned, changes = clean_text(
            "Hello world.\nSecond line.")
        self.assertEqual(cleaned, "Hello world.\nSecond line.")
        self.assertEqual(changes, [])


class CleanPropertyTests(unittest.TestCase):
    def test_idempotent(self):
        once, _changes = clean_text(MESSY)
        twice, _changes2 = clean_text(once)
        self.assertEqual(twice, once)

    def test_idempotent_on_plain_text(self):
        text = "Plain text.\n\nSecond paragraph here."
        once, _changes = clean_text(text)
        twice, _changes2 = clean_text(once)
        self.assertEqual(twice, once)

    def test_never_changes_words(self):
        cleaned, _changes = clean_text(MESSY)
        self.assertEqual(_WORD.findall(cleaned),
                         _WORD.findall(MESSY))

    def test_never_changes_words_on_punctuation_heavy_text(self):
        text = ("wait . what , no ! really ? yes ; see : done .\n"
                "second  line  here\n")
        cleaned, _changes = clean_text(text)
        self.assertEqual(_WORD.findall(cleaned),
                         _WORD.findall(text))


if __name__ == "__main__":
    unittest.main()
