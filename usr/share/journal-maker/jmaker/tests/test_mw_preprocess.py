#!/usr/bin/python3 -Bsu
import unittest

from jmaker import mw_preprocess as mp


class TestPreprocess(unittest.TestCase):
    def test_chrome_dropped(self):
        self.assertEqual(mp.preprocess("{{Header}}x{{Footer}}").strip(), "x")

    def test_parser_function_dropped(self):
        self.assertEqual(mp.preprocess("a{{#seo:|description=z}}b"), "ab")

    def test_intro_unwrapped(self):
        out = mp.preprocess("{{intro|Lead text here.}}")
        self.assertIn("Lead text here.", out)

    def test_quotation_to_blockquote(self):
        out = mp.preprocess("{{quotation|quote=Q text|context=Source X}}")
        self.assertIn("<blockquote>", out)
        self.assertIn("Q text", out)
        self.assertIn("-- Source X", out)

    def test_anchor_show_becomes_heading(self):
        out = mp.preprocess("{{Anchor|show=true|A Label}}")
        self.assertIn("=== A Label ===", out)

    def test_anchor_only_is_empty(self):
        self.assertEqual(mp.preprocess("{{anchor|just-an-id}}").strip(), "")

    def test_unknown_template_raises(self):
        with self.assertRaises(mp.UnknownTemplate):
            mp.preprocess("{{SomeCustomThing|a|b}}")

    def test_split_respects_nested_links(self):
        segs = mp._split_args("quotation|quote=see [[Foo|bar]]|context=C")
        self.assertEqual(len(segs), 3)


if __name__ == "__main__":
    unittest.main()
