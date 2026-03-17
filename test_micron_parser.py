#!/usr/bin/env python3
"""
Unit tests for the Micron markup parser.

Run with: python test_micron_parser.py
"""

import unittest
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import parser functions from main.py
from main import parse_micron, FG_COLOR, BG_COLOR, LNK_COLOR


class TestMicronParser(unittest.TestCase):
    """Test cases for the Micron markup parser."""

    # ── Basic formatting ─────────────────────────────────────────────────────

    def test_plain_text(self):
        """Test plain text without formatting."""
        result = parse_micron("Hello World")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["type"], "text")
        self.assertEqual(result[0]["segments"][0]["text"], "Hello World")

    def test_empty_lines(self):
        """Test empty lines produce blank elements."""
        result = parse_micron("Line 1\n\nLine 2")
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]["type"], "text")
        self.assertEqual(result[1]["type"], "blank")
        self.assertEqual(result[2]["type"], "text")

    def test_cache_header_stripped(self):
        """Test that #!c= header is stripped."""
        result = parse_micron("#!c=3600\nHello")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["segments"][0]["text"], "Hello")

    # ── Headings ─────────────────────────────────────────────────────────────

    def test_heading_level_1(self):
        """Test >H1 heading."""
        result = parse_micron(">Heading 1")
        self.assertEqual(result[0]["type"], "text")
        self.assertEqual(result[0]["heading"], 1)
        self.assertEqual(result[0]["segments"][0]["text"], "Heading 1")

    def test_heading_level_2(self):
        """Test >>H2 heading."""
        result = parse_micron(">>Heading 2")
        self.assertEqual(result[0]["type"], "text")
        self.assertEqual(result[0]["heading"], 2)

    def test_heading_level_3(self):
        """Test >>>H3 heading."""
        result = parse_micron(">>>Heading 3")
        self.assertEqual(result[0]["type"], "text")
        self.assertEqual(result[0]["heading"], 3)

    # ── Bold, Italic, Underline ──────────────────────────────────────────────

    def test_bold_toggle(self):
        """Test bold formatting with `!...`!."""
        result = parse_micron("Normal `!bold`! normal")
        self.assertEqual(len(result[0]["segments"]), 3)
        self.assertFalse(result[0]["segments"][0]["bold"])
        self.assertTrue(result[0]["segments"][1]["bold"])
        self.assertFalse(result[0]["segments"][2]["bold"])

    def test_italic_toggle(self):
        """Test italic formatting with `*...*."""
        result = parse_micron("Normal `*italic`* normal")
        self.assertEqual(len(result[0]["segments"]), 3)
        self.assertFalse(result[0]["segments"][0]["italic"])
        self.assertTrue(result[0]["segments"][1]["italic"])
        self.assertFalse(result[0]["segments"][2]["italic"])

    def test_underline_toggle(self):
        """Test underline formatting with `_...`_. """
        result = parse_micron("Normal `_under`_ normal")
        self.assertEqual(len(result[0]["segments"]), 3)
        self.assertFalse(result[0]["segments"][0]["underline"])
        self.assertTrue(result[0]["segments"][1]["underline"])
        self.assertFalse(result[0]["segments"][2]["underline"])

    def test_combined_formatting(self):
        """Test combined bold and italic."""
        result = parse_micron("`!`*bold italic`*`!")
        self.assertEqual(len(result[0]["segments"]), 1)
        seg = result[0]["segments"][0]
        self.assertTrue(seg["bold"])
        self.assertTrue(seg["italic"])

    # ── Colors ───────────────────────────────────────────────────────────────

    def test_foreground_color(self):
        """Test foreground color with `Fxxx...`f."""
        result = parse_micron("Normal `Ff00red`f normal")
        self.assertEqual(len(result[0]["segments"]), 3)
        # Check red color (approximately)
        fg = result[0]["segments"][1]["fg"]
        self.assertGreater(fg[0], 0.9)  # Red component high
        self.assertLess(fg[1], 0.1)     # Green component low

    def test_background_color(self):
        """Test background color with `Bxxx...`b."""
        result = parse_micron("Normal `B00fblue bg`b normal")
        self.assertEqual(len(result[0]["segments"]), 3)
        bg = result[0]["segments"][1]["bg"]
        self.assertGreater(bg[2], 0.9)  # Blue component high

    def test_grayscale_color(self):
        """Test grayscale color with `gXX."""
        result = parse_micron("Normal `g80gray normal")
        self.assertEqual(len(result[0]["segments"]), 2)
        fg = result[0]["segments"][1]["fg"]
        # Grayscale should have equal RGB components
        self.assertAlmostEqual(fg[0], fg[1], places=2)
        self.assertAlmostEqual(fg[1], fg[2], places=2)

    def test_reset_all_formatting(self):
        """Test reset all formatting with ``."""
        result = parse_micron("`!bold `` normal")
        self.assertEqual(len(result[0]["segments"]), 2)
        self.assertTrue(result[0]["segments"][0]["bold"])
        self.assertFalse(result[0]["segments"][1]["bold"])

    # ── Alignment ────────────────────────────────────────────────────────────

    def test_center_alignment(self):
        """Test center alignment with `c."""
        result = parse_micron("`cCentered text")
        self.assertEqual(result[0]["align"], "center")

    def test_left_alignment(self):
        """Test left alignment with `l."""
        result = parse_micron("`lLeft aligned")
        self.assertEqual(result[0]["align"], "left")

    def test_right_alignment(self):
        """Test right alignment with `r."""
        result = parse_micron("`rRight aligned")
        self.assertEqual(result[0]["align"], "right")

    def test_reset_alignment(self):
        """Test reset alignment with `a."""
        result = parse_micron("`cCentered`a back to left")
        # Note: alignment is per-line in current implementation
        result2 = parse_micron("`a Left again")
        self.assertEqual(result2[0]["align"], "left")

    # ── Links ────────────────────────────────────────────────────────────────

    def test_simple_link(self):
        """Test simple link `[label`path]."""
        result = parse_micron("Check `[Click here`/page/test.mu]")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["type"], "text")
        self.assertEqual(result[1]["type"], "link")
        self.assertEqual(result[1]["label"], "Click here")
        self.assertEqual(result[1]["path"], "/page/test.mu")

    def test_link_with_node(self):
        """Test link with node address."""
        result = parse_micron("`[Remote`abc123:/page/index.mu]")
        link = result[0]
        self.assertEqual(link["type"], "link")
        self.assertEqual(link["node"], "abc123")
        self.assertEqual(link["path"], "/page/index.mu")

    def test_link_empty_label(self):
        """Test link where label equals path (no separate label)."""
        # Format: `[path] where path is both label and destination
        # Note: Micron link format is `[label`path], so for same label/path
        # you use `[path`path] or just let the parser use path as label
        result = parse_micron("`[/page/test.mu`/page/test.mu]")
        link = result[0]
        self.assertEqual(link["type"], "link")
        self.assertEqual(link["path"], "/page/test.mu")

    # ── Dividers ─────────────────────────────────────────────────────────────

    def test_divider_dashes(self):
        """Test divider with ---."""
        result = parse_micron("Text\n---\nMore")
        self.assertEqual(result[1]["type"], "divider")

    def test_divider_backtick(self):
        """Test divider with `-` (backtick-dash-backtick)."""
        result = parse_micron("Text\n`-`\nMore")
        self.assertEqual(result[1]["type"], "divider")

    # ── Comments ─────────────────────────────────────────────────────────────

    def test_comment_line_ignored(self):
        """Test comment lines are ignored."""
        result = parse_micron("Text\n# This is a comment\nMore")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["segments"][0]["text"], "Text")
        self.assertEqual(result[1]["segments"][0]["text"], "More")

    def test_cache_header_not_comment(self):
        """Test #! header is not treated as comment."""
        result = parse_micron("#!c=60\nHello")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["segments"][0]["text"], "Hello")

    # ── Literal mode ─────────────────────────────────────────────────────────

    def test_literal_mode(self):
        """Test literal mode `=...`=. """
        result = parse_micron("Before `=This is `!literal`= after")
        # Should have: text "Before ", literal element, text " after"
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]["type"], "text")
        self.assertEqual(result[1]["type"], "literal")
        self.assertEqual(result[1]["content"], "This is `!literal")
        self.assertEqual(result[2]["type"], "text")

    def test_literal_multiline(self):
        """Test multiline literal mode."""
        result = parse_micron("`=Line 1\nLine 2\nLine 3`=")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["type"], "literal")
        self.assertIn("Line 1", result[0]["content"])
        self.assertIn("Line 2", result[0]["content"])
        self.assertIn("Line 3", result[0]["content"])

    # ── Escape character ─────────────────────────────────────────────────────

    def test_escape_backtick(self):
        """Test escaping backtick with \\`."""
        result = parse_micron("Use \\` to escape")
        self.assertEqual(result[0]["segments"][0]["text"], "Use ` to escape")

    def test_escape_in_formatting(self):
        """Test escape prevents formatting."""
        result = parse_micron("Not \\`!bold\\! just text")
        # The escaped backtick should be literal
        self.assertIn("`", result[0]["segments"][0]["text"])

    # ── Edge cases ───────────────────────────────────────────────────────────

    def test_unclosed_bold(self):
        """Test unclosed bold formatting."""
        result = parse_micron("Text `!bold never closed")
        # Should apply bold to rest of line
        self.assertTrue(result[0]["segments"][1]["bold"])

    def test_empty_input(self):
        """Test empty input."""
        result = parse_micron("")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["type"], "blank")

    def test_only_whitespace(self):
        """Test whitespace-only lines."""
        result = parse_micron("   \n\t\n  ")
        # All should be blank elements
        for el in result:
            self.assertEqual(el["type"], "blank")

    def test_mixed_formatting_line(self):
        """Test multiple formatting types on one line."""
        result = parse_micron("`!bold`! `*italic`* `_under`_")
        segments = result[0]["segments"]
        # Segments: ["bold"(bold), " "(normal), "italic"(italic), " "(normal), "under"(underline)]
        self.assertTrue(segments[0]["bold"])
        self.assertTrue(segments[2]["italic"])
        self.assertTrue(segments[4]["underline"])


class TestMicronParserIntegration(unittest.TestCase):
    """Integration tests with realistic page content."""

    def test_index_page_example(self):
        """Test parsing a realistic index.mu page."""
        content = """#!c=3600
`!Welcome to RNS Page Node`!

This is a standalone page node server.

`-`

`>Features`<
* Static page serving
* Dynamic pages
* File downloads

`cCentered text`a
"""
        result = parse_micron(content)

        # Should have heading, text, divider, heading, text, centered text
        self.assertGreater(len(result), 5)

        # First element should be the welcome heading (bold)
        self.assertTrue(result[0]["segments"][0]["bold"])

        # Should have a divider
        dividers = [el for el in result if el["type"] == "divider"]
        self.assertEqual(len(dividers), 1)

    def test_navigation_links(self):
        """Test page with navigation links."""
        content = """`>Navigation`<
* `[Home`/page/index.mu]
* `[About`/page/about.mu]
* `[Files`/file/]
"""
        result = parse_micron(content)

        # Should have heading and multiple links
        links = [el for el in result if el["type"] == "link"]
        self.assertEqual(len(links), 3)
        self.assertEqual(links[0]["path"], "/page/index.mu")
        self.assertEqual(links[1]["path"], "/page/about.mu")


if __name__ == "__main__":
    unittest.main(verbosity=2)
