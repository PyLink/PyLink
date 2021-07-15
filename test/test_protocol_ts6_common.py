"""
Tests for protocols/ts6_common
"""

import unittest

from pylinkirc.protocols import ts6_common

class TS6UIDGeneratorTest(unittest.TestCase):
    def setUp(self):
        self.uidgen = ts6_common.TS6UIDGenerator('123')

    def test_initial_UID(self):
        expected = [
            "123AAAAAA",
            "123AAAAAB",
            "123AAAAAC",
            "123AAAAAD",
            "123AAAAAE",
            "123AAAAAF",
        ]
        self.uidgen.counter = 0
        actual = [self.uidgen.next_uid() for i in range(6)]
        self.assertEqual(expected, actual)

    def test_rollover_first_num(self):
        expected = [
            "123AAAAAY",
            "123AAAAAZ",
            "123AAAAA0",
            "123AAAAA1",
            "123AAAAA2",
            "123AAAAA3",
        ]
        self.uidgen.counter = 24
        actual = [self.uidgen.next_uid() for i in range(6)]
        self.assertEqual(expected, actual)

    def test_rollover_second(self):
        expected = [
            "123AAAAA8",
            "123AAAAA9",
            "123AAAABA",
            "123AAAABB",
            "123AAAABC",
            "123AAAABD",
        ]
        self.uidgen.counter = 36 - 2
        actual = [self.uidgen.next_uid() for i in range(6)]
        self.assertEqual(expected, actual)

    def test_rollover_third(self):
        expected = [
            "123AAAE98",
            "123AAAE99",
            "123AAAFAA",
            "123AAAFAB",
            "123AAAFAC",
        ]
        self.uidgen.counter = 5*36**2 - 2
        actual = [self.uidgen.next_uid() for i in range(5)]
        self.assertEqual(expected, actual)

    def test_overflow(self):
        self.uidgen.counter = 36**6-1
        self.assertTrue(self.uidgen.next_uid())
        self.assertRaises(RuntimeError, self.uidgen.next_uid)

if __name__ == '__main__':
    unittest.main()
