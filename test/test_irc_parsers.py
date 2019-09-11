"""
Tests for IRC parsers.
"""
from pathlib import Path
import unittest

import yaml

PARSER_DATA_PATH = Path(__file__).parent.resolve() / 'parser-tests' / 'tests'
print(PARSER_DATA_PATH)

from pylinkirc import utils
from pylinkirc.protocols.ircs2s_common import IRCCommonProtocol

class MessageParserTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(PARSER_DATA_PATH / 'msg-split.yaml') as f:
            cls.MESSAGE_SPLIT_TEST_DATA = yaml.safe_load(f)
        with open(PARSER_DATA_PATH / 'userhost-split.yaml') as f:
            cls.USER_HOST_SPLIT_TEST_DATA = yaml.safe_load(f)

    def testMessageSplit(self):
        for testdata in self.MESSAGE_SPLIT_TEST_DATA['tests']:
            inp = testdata['input']
            atoms = testdata['atoms']

            with self.subTest():
                expected = []
                has_source = False
                if 'source' in atoms:
                    has_source = True
                    expected.append(atoms['source'])

                if 'verb' in atoms:
                    expected.append(atoms['verb'])

                if 'params' in atoms:
                    expected.extend(atoms['params'])

                if 'tags' in atoms:
                    # Remove message tags before parsing
                    _, inp = inp.split(" ", 1)

                if has_source:
                    parts = IRCCommonProtocol.parse_prefixed_args(inp)
                else:
                    parts = IRCCommonProtocol.parse_args(inp)
                self.assertEqual(expected, parts, "Parse test failed for string: %r" % inp)

    @unittest.skip("Not quite working yet")
    def testMessageTags(self):
        for testdata in self.MESSAGE_SPLIT_TEST_DATA['tests']:
            inp = testdata['input']
            atoms = testdata['atoms']

            with self.subTest():
                if 'tags' in atoms:
                    self.assertEqual(atoms['tags'], IRCCommonProtocol.parse_message_tags(inp.split(" ")),
                                     "Parse test failed for message tags: %r" % inp)

    def testUserHostSplit(self):
        for test in self.USER_HOST_SPLIT_TEST_DATA['tests']:
            inp = test['source']
            atoms = test['atoms']

            with self.subTest():
                if 'nick' not in atoms or 'user' not in atoms or 'host' not in atoms:
                    # Trying to parse a hostmask with missing atoms is an error in split_hostmask()
                    with self.assertRaises(ValueError):
                        utils.split_hostmask(inp)
                else:
                    expected = [atoms['nick'], atoms['user'], atoms['host']]
                    self.assertEqual(expected, utils.split_hostmask(inp))

if __name__ == '__main__':
    unittest.main()
