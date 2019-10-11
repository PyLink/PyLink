"""
Test cases for utils.py
"""

import unittest

from pylinkirc import utils


class UtilsTestCase(unittest.TestCase):

    def test_strip_irc_formatting(self):
        # Some messages from http://modern.ircdocs.horse/formatting.html#examples
        self.assertEqual(utils.strip_irc_formatting(
            "I love \x033IRC! \x03It is the \x037best protocol ever!"),
            "I love IRC! It is the best protocol ever!")

        self.assertEqual(utils.strip_irc_formatting(
            "This is a \x1d\x0313,9cool \x03message"),
            "This is a cool message")

        self.assertEqual(utils.strip_irc_formatting(
            "Don't spam 5\x0313,8,6\x03,7,8, and especially not \x029\x02\x1d!"),
            "Don't spam 5,6,7,8, and especially not 9!")

        # Should not remove the ,
        self.assertEqual(utils.strip_irc_formatting(
            "\x0305,"),
            ",")
        self.assertEqual(utils.strip_irc_formatting(
            "\x038,,,,."),
            ",,,,.")

        # Numbers are preserved
        self.assertEqual(utils.strip_irc_formatting(
            "\x031234 "),
            "34 ")
        self.assertEqual(utils.strip_irc_formatting(
            "\x03\x1f12"),
            "12")

        self.assertEqual(utils.strip_irc_formatting(
            "\x0305t\x030,1h\x0307,02e\x0308,06 \x0309,13q\x0303,15u\x0311,14i\x0310,05c\x0312,04k\x0302,07 \x0306,08b\x0313,09r\x0305,10o\x0304,12w\x0307,02n\x0308,06 \x0309,13f\x0303,15o\x0311,14x\x0310,05 \x0312,04j\x0302,07u\x0306,08m\x0313,09p\x0305,10s\x0304,12 \x0307,02o\x0308,06v\x0309,13e\x0303,15r\x0311,14 \x0310,05t\x0312,04h\x0302,07e\x0306,08 \x0313,09l\x0305,10a\x0304,12z\x0307,02y\x0308,06 \x0309,13d\x0303,15o\x0311,14g\x0f"),
            "the quick brown fox jumps over the lazy dog")

    def test_remove_range(self):
        self.assertEqual(utils.remove_range(
            "1", [1,2,3,4,5,6,7,8,9]),
            [2,3,4,5,6,7,8,9])

        self.assertEqual(utils.remove_range(
            "2,4", [1,2,3,4,5,6,7,8,9]),
            [1,3,5,6,7,8,9])

        self.assertEqual(utils.remove_range(
            "1-4", [1,2,3,4,5,6,7,8,9]),
            [5,6,7,8,9])

        self.assertEqual(utils.remove_range(
            "1-3,7", [1,2,3,4,5,6,7,8,9]),
            [4,5,6,8,9])

        self.assertEqual(utils.remove_range(
            "1-3,5-9", [1,2,3,4,5,6,7,8,9]),
            [4])

        self.assertEqual(utils.remove_range(
            "1-2,3-5,6-9", [1,2,3,4,5,6,7,8,9]),
            [])

        # Anti-patterns, but should be legal
        self.assertEqual(utils.remove_range(
            "4,2", [1,2,3,4,5,6,7,8,9]),
            [1,3,5,6,7,8,9])
        self.assertEqual(utils.remove_range(
            "4,4,4", [1,2,3,4,5,6,7,8,9]),
            [1,2,3,5,6,7,8,9])

        # Empty subranges should be filtered away
        self.assertEqual(utils.remove_range(
            ",2,,4,", [1,2,3,4,5,6,7,8,9]),
            [1,3,5,6,7,8,9])

        # Not enough items
        with self.assertRaises(IndexError):
            utils.remove_range(
                "5", ["abcd", "efgh"])
        with self.assertRaises(IndexError):
            utils.remove_range(
                "1-5", ["xyz", "cake"])

        # Ranges going in reverse or invalid
        with self.assertRaises(ValueError):
            utils.remove_range(
                "5-2", [":)", ":D", "^_^"])
            utils.remove_range(
                "2-2", [":)", ":D", "^_^"])

        # 0th element
        with self.assertRaises(ValueError):
            utils.remove_range(
                "5,0", list(range(50)))

        # List can't contain None
        with self.assertRaises(ValueError):
            utils.remove_range(
                "1-2", [None, "", 0, False])

        # Malformed indices
        with self.assertRaises(ValueError):
            utils.remove_range(
                " ", ["some", "clever", "string"])
            utils.remove_range(
                " ,,, ", ["some", "clever", "string"])
            utils.remove_range(
                "a,b,c,1,2,3", ["some", "clever", "string"])

        # Malformed ranges
        with self.assertRaises(ValueError):
            utils.remove_range(
                "1,2-", [":)", ":D", "^_^"])
            utils.remove_range(
                "-", [":)", ":D", "^_^"])
            utils.remove_range(
                "1-2-3", [":)", ":D", "^_^"])
            utils.remove_range(
                "-1-2", [":)", ":D", "^_^"])
            utils.remove_range(
                "3--", [":)", ":D", "^_^"])
            utils.remove_range(
                "--5", [":)", ":D", "^_^"])
            utils.remove_range(
                "-3--5", ["we", "love", "emotes"])

    def test_get_hostname_type(self):
        self.assertEqual(utils.get_hostname_type("1.2.3.4"), 1)
        self.assertEqual(utils.get_hostname_type("192.168.0.1"), 1)
        self.assertEqual(utils.get_hostname_type("127.0.0.5"), 1)

        self.assertEqual(utils.get_hostname_type("0::1"), 2)
        self.assertEqual(utils.get_hostname_type("::1"), 2)
        self.assertEqual(utils.get_hostname_type("fc00::1234"), 2)
        self.assertEqual(utils.get_hostname_type("1111:2222:3333:4444:5555:6666:7777:8888"), 2)

        self.assertEqual(utils.get_hostname_type("example.com"), 0)
        self.assertEqual(utils.get_hostname_type("abc.mynet.local"), 0)
        self.assertEqual(utils.get_hostname_type("123.example"), 0)

        self.assertEqual(utils.get_hostname_type("123.456.789.000"), 0)
        self.assertEqual(utils.get_hostname_type("1::2::3"), 0)
        self.assertEqual(utils.get_hostname_type("1:"), 0)
        self.assertEqual(utils.get_hostname_type(":5"), 0)

    def test_parse_duration(self):
        # Base case: simple number
        self.assertEqual(utils.parse_duration("0"), 0)
        self.assertEqual(utils.parse_duration("256"), 256)

        # Not valid: not a positive integer
        with self.assertRaises(ValueError):
            utils.parse_duration("-5")
            utils.parse_duration("3.1416")

        # Not valid: wrong units or nonsense
        with self.assertRaises(ValueError):
            utils.parse_duration("")
            utils.parse_duration("3j")
            utils.parse_duration("5h6")  # stray number at end
            utils.parse_duration("5h3k")
            utils.parse_duration(" 6d ")
            utils.parse_duration("6.6d")  # we don't support monster math
            utils.parse_duration("zzzzzdstwataw")
            utils.parse_duration("3asdfjkl;")

        # Test all supported units
        self.assertEqual(utils.parse_duration("3s"), 3)
        self.assertEqual(utils.parse_duration("1m"), 60)
        self.assertEqual(utils.parse_duration("9h"), 9 * 60 * 60)
        self.assertEqual(utils.parse_duration("15d"), 15 * 24 * 60 * 60)
        self.assertEqual(utils.parse_duration("3w"), 3 * 7 * 24 * 60 * 60)

        # Composites
        self.assertEqual(utils.parse_duration("6m10s"), 6 * 60 + 10)
        self.assertEqual(utils.parse_duration("1d5h"), ((24+5) * 60 * 60))
        self.assertEqual(utils.parse_duration("2d3m4s"), (48 * 60 * 60 + 3 * 60 + 4))

        # Not valid: wrong order of units
        with self.assertRaises(ValueError):
            utils.parse_duration("4s3d")
            utils.parse_duration("1m5w")

    def test_match_text(self):
        f = utils.match_text  # glob, target

        # Base cases
        self.assertTrue(f("", ""))
        self.assertFalse(f("test", ""))
        self.assertFalse(f("", "abcdef"))
        self.assertFalse(f("", "*"))  # specified the wrong way
        self.assertFalse(f("", "?"))
        self.assertTrue(f("foo", "foo"))
        self.assertFalse(f("foo", "bar"))
        self.assertFalse(f("foo", "food"))

        # Test use of *
        self.assertTrue(f("*", "b"))
        self.assertTrue(f("*", "abc"))
        self.assertTrue(f("*", ""))
        self.assertTrue(f("*!*@*", "nick!user@host"))
        self.assertTrue(f("*@*", "rick!user@lost"))
        self.assertTrue(f("ni*!*@*st", "nick!user@roast"))
        self.assertFalse(f("nick!*abcdef*@*st*", "nick!user@roast"))
        self.assertTrue(f("*!*@*.overdrive.pw", "abc!def@abc.users.overdrive.pw"))

        # Test use of ?
        self.assertTrue(f("?", "b"))
        self.assertFalse(f("?", "abc"))
        self.assertTrue(f("Guest?????!???irc@users.overdrive.pw", "Guest12567!webirc@users.overdrive.pw"))
        self.assertFalse(f("Guest????!webirc@users.overdrive.pw", "Guest23457!webirc@users.overdrive.pw"))

    def test_match_text_complex(self):
        f = utils.match_text  # glob, target

        # Test combination of * and ?
        for glob in {"*?", "?*"}:
            self.assertTrue(f(glob, "a"))
            self.assertTrue(f(glob, "ab"))
            self.assertFalse(f(glob, ""))

        self.assertTrue(f("ba*??*ll", "basketball"))
        self.assertFalse(f("ba*??*ll", "ball"))
        self.assertFalse(f("ba*??*ll", "basketballs"))

        self.assertTrue(f("**", "fooBarBaz"))
        self.assertTrue(f("*?*?*?*", "cat"))
        self.assertTrue(f("*??****?*", "cat"))
        self.assertFalse(f("*??****?*?****", "MAP"))

    def test_match_text_casemangle(self):
        f = utils.match_text  # glob, target, manglefunc

        # We are case insensitive by default
        self.assertTrue(f("Test", "TEST"))
        self.assertTrue(f("ALPHA*", "alphabet"))

        # But we can override this preference
        self.assertFalse(f("Test", "TEST", None))
        self.assertFalse(f("*for*", "BEForE", None))
        self.assertTrue(f("*corn*", "unicorns", None))

        # Or specify some other filter func
        self.assertTrue(f('005', '5', lambda s: s.zfill(3)))
        self.assertTrue(f('*0*', '14', lambda s: s.zfill(6)))
        self.assertFalse(f('*9*', '14', lambda s: s.zfill(13)))
        self.assertTrue(f('*chin*', 'machine', str.upper))

    def test_merge_iterables(self):
        f = utils.merge_iterables
        self.assertEqual(f([], []), [])
        self.assertEqual(f({}, {}), {})
        self.assertEqual(f(set(), set()), set())

        self.assertEqual(f([1,2], [4,5,6]), [1,2,4,5,6])
        self.assertEqual(f({'a': 'b'}, {'c': 'd', 'e': 'f'}),
                         {'a': 'b', 'c': 'd', 'e': 'f'})
        self.assertEqual(f({0,1,2}, {1,3,5}),
                         {0,1,2,3,5})

        with self.assertRaises(ValueError):
            f([1,2,3], {'a': 'b'})  # mismatched type
        with self.assertRaises(ValueError):
            f([], set())  # mismatched type

if __name__ == '__main__':
    unittest.main()
