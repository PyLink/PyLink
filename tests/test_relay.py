import sys
import os
cwd = os.getcwd()
sys.path += [cwd, os.path.join(cwd, 'plugins')]
import unittest

import utils
import classes
import relay

def dummyf():
    pass

class TestRelay(unittest.TestCase):
    def setUp(self):
        self.irc = classes.FakeIRC('unittest', classes.FakeProto())
        self.irc.maxnicklen = 20
        self.f = lambda nick: relay.normalizeNick(self.irc, 'unittest', nick)
        # Fake our protocol name to something that supports slashes in nicks.
        # relay uses a whitelist for this to prevent accidentally introducing
        # bad nicks:
        self.irc.proto.__name__ = "inspircd"

    def testNormalizeNick(self):
        # Second argument simply states the suffix.
        self.assertEqual(self.f('helloworld'), 'helloworld/unittest')
        self.assertEqual(self.f('ObnoxiouslyLongNick'), 'Obnoxiously/unittest')
        self.assertEqual(self.f('10XAAAAAA'), '_10XAAAAAA/unittest')

    def testNormalizeNickConflict(self):
        self.assertEqual(self.f('helloworld'), 'helloworld/unittest')
        self.irc.users['10XAAAAAA'] = classes.IrcUser('helloworld/unittest', 1234, '10XAAAAAA')
        # Increase amount of /'s by one
        self.assertEqual(self.f('helloworld'), 'helloworld//unittest')
        self.irc.users['10XAAAAAB'] = classes.IrcUser('helloworld//unittest', 1234, '10XAAAAAB')
        # Cut off the nick, not the suffix if the result is too long.
        self.assertEqual(self.f('helloworld'), 'helloworl///unittest')

    def testNormalizeNickRemovesSlashes(self):
        self.irc.proto.__name__ = "charybdis"
        try:
            self.assertEqual(self.f('helloworld'), 'helloworld|unittest')
            self.assertEqual(self.f('abcde/eJanus'), 'abcde|eJanu|unittest')
            self.assertEqual(self.f('ObnoxiouslyLongNick'), 'Obnoxiously|unittest')
        finally:
            self.irc.proto.__name__ = "inspircd"
