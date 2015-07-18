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
        self.irc = classes.FakeIRC('unittest', classes.FakeProto(), classes.testconf)
        self.irc.maxnicklen = 20
        self.irc.proto.__name__ = "test"
        self.f = relay.normalizeNick

    def testNormalizeNick(self):
        # Second argument simply states the suffix.
        self.assertEqual(self.f(self.irc, 'unittest', 'helloworld'), 'helloworld/unittest')
        self.assertEqual(self.f(self.irc, 'unittest', 'ObnoxiouslyLongNick'), 'Obnoxiously/unittest')
        self.assertEqual(self.f(self.irc, 'unittest', '10XAAAAAA'), '_10XAAAAAA/unittest')

    def testNormalizeNickConflict(self):
        self.assertEqual(self.f(self.irc, 'unittest', 'helloworld'), 'helloworld/unittest')
        self.irc.users['10XAAAAAA'] = classes.IrcUser('helloworld/unittest', 1234, '10XAAAAAA')
        # Increase amount of /'s by one
        self.assertEqual(self.f(self.irc, 'unittest', 'helloworld'), 'helloworld//unittest')
        self.irc.users['10XAAAAAB'] = classes.IrcUser('helloworld//unittest', 1234, '10XAAAAAB')
        # Cut off the nick, not the suffix if the result is too long.
        self.assertEqual(self.f(self.irc, 'unittest', 'helloworld'), 'helloworl///unittest')

    def testNormalizeNickRemovesSlashes(self):
        self.irc.proto.__name__ = "charybdis"
        self.assertEqual(self.f(self.irc, 'unittest', 'helloworld'), 'helloworld|unittest')
        self.assertEqual(self.f(self.irc, 'unittest', 'abcde/eJanus'), 'abcde|eJanu|unittest')
        self.assertEqual(self.f(self.irc, 'unittest', 'ObnoxiouslyLongNick'), 'Obnoxiously|unittest')
