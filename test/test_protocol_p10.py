"""
Tests for protocols/p10
"""

import unittest

from pylinkirc.protocols import p10

class P10UIDGeneratorTest(unittest.TestCase):
    def setUp(self):
        self.uidgen = p10.P10UIDGenerator('HI')

    def test_initial_UID(self):
        expected = [
            "HIAAA",
            "HIAAB",
            "HIAAC",
            "HIAAD",
            "HIAAE",
            "HIAAF"
        ]
        self.uidgen.counter = 0
        actual = [self.uidgen.next_uid() for i in range(6)]
        self.assertEqual(expected, actual)

    def test_rollover_first_lowercase(self):
        expected = [
            "HIAAY",
            "HIAAZ",
            "HIAAa",
            "HIAAb",
            "HIAAc",
            "HIAAd",
        ]
        self.uidgen.counter = 24
        actual = [self.uidgen.next_uid() for i in range(6)]
        self.assertEqual(expected, actual)

    def test_rollover_first_num(self):
        expected = [
            "HIAAz",
            "HIAA0",
            "HIAA1",
            "HIAA2",
            "HIAA3",
            "HIAA4",
        ]
        self.uidgen.counter = 26*2-1
        actual = [self.uidgen.next_uid() for i in range(6)]
        self.assertEqual(expected, actual)

    def test_rollover_second(self):
        expected = [
            "HIAA8",
            "HIAA9",
            "HIAA[",
            "HIAA]",
            "HIABA",
            "HIABB",
            "HIABC",
            "HIABD",
        ]
        self.uidgen.counter = 26*2+10-2
        actual = [self.uidgen.next_uid() for i in range(8)]
        self.assertEqual(expected, actual)

    def test_rollover_third(self):
        expected = [
            "HIE]9",
            "HIE][",
            "HIE]]",
            "HIFAA",
            "HIFAB",
            "HIFAC",
        ]
        self.uidgen.counter = 5*64**2 - 3
        actual = [self.uidgen.next_uid() for i in range(6)]
        self.assertEqual(expected, actual)

    def test_overflow(self):
        self.uidgen.counter = 64**3-1
        self.assertTrue(self.uidgen.next_uid())
        self.assertRaises(RuntimeError, self.uidgen.next_uid)

if __name__ == '__main__':
    unittest.main()
