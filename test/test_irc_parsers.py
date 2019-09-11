"""
Tests for IRC parsers.
"""
from pathlib import Path
import unittest

import yaml

PARSER_DATA_PATH = Path(__file__).parent.resolve() / 'parser-tests' / 'tests'
print(PARSER_DATA_PATH)
'''
spec = importlib.util.spec_from_file_location("parser_tests", PARSER_DATA_PATH / 'data.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

print(parser_tests)
'''

from pylinkirc.protocols.ircs2s_common import IRCCommonProtocol

class MessageParserTest(unittest.TestCase):

    def testMessageSplit(self):
        with open(PARSER_DATA_PATH / 'msg-split.yaml') as f:
            splittest_data = yaml.safe_load(f)

        for testdata in splittest_data['tests']:
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
                    # HACK: in PyLink, message tags are processed in handle_events(), which is a dynamic
                    # method that relies on command handlers being present. So we can't reasonably test
                    # them here (plus handle_events() outputs params as a command-specific dict instead of)
                    # lists)
                    self.assertEqual(atoms['tags'], IRCCommonProtocol.parse_message_tags(inp.split(" ")),
                                     "Parse test failed for message tags: %r" % inp)
                    _, inp = inp.split(" ", 1)
                if has_source:
                    parts = IRCCommonProtocol.parse_prefixed_args(inp)
                else:
                    parts = IRCCommonProtocol.parse_args(inp)
                self.assertEqual(expected, parts, "Parse test failed for string: %r" % inp)

if __name__ == '__main__':
    unittest.main()
