"""
Runs IRC parser tests from ircdocs/parser-tests.

This test suite runs static code only.
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
        with open(PARSER_DATA_PATH / 'mask-match.yaml') as f:
            cls.MASK_MATCH_TEST_DATA = yaml.safe_load(f)
        with open(PARSER_DATA_PATH / 'validate-hostname.yaml') as f:
            cls.VALIDATE_HOSTNAME_TEST_DATA = yaml.safe_load(f)

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

    def testHostMatch(self):
        for test in self.MASK_MATCH_TEST_DATA['tests']:
            mask = test['mask']

            # N.B.: utils.match_text() does Unicode case-insensitive match by default,
            # which might not be the right thing to do on IRC.
            # But irc.to_lower() isn't a static function so we're not testing it here...
            for match in test['matches']:
                with self.subTest():
                    self.assertTrue(utils.match_text(mask, match))

            for fail in test['fails']:
                with self.subTest():
                    self.assertFalse(utils.match_text(mask, fail))

    def testValidateHostname(self):
        for test in self.VALIDATE_HOSTNAME_TEST_DATA['tests']:
            with self.subTest():
                self.assertEqual(test['valid'], IRCCommonProtocol.is_server_name(test['host']),
                                 "Failed test for %r; should be %s" % (test['host'], test['valid']))


    # N.B. skipping msg-join tests because PyLink doesn't think about messages that way

    ### Custom test cases
    def testMessageSplitSpaces(self):
        # Test that tokenization ignores empty fields, but doesn't strip away other types of whitespace
        f = IRCCommonProtocol.parse_prefixed_args
        self.assertEqual(f(":foo PRIVMSG  #test :message"), ["foo", "PRIVMSG", "#test", "message"])
        self.assertEqual(f(":123LOLWUT NICK cursed\u3000nickname"), ["123LOLWUT", "NICK", "cursed\u3000nickname"])
        self.assertEqual(f(":123LOLWUT MODE ## +ov \x1f checking"),
                         ["123LOLWUT", "MODE", "##", "+ov", "\x1f", "checking"])
        self.assertEqual(f(":123LOLWUT MODE  ## +ov  \u3000  checking"),
                         ["123LOLWUT", "MODE", "##", "+ov", "\u3000", "checking"])

if __name__ == '__main__':
    unittest.main()
