import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from log import log

import classes
import unittest

# Yes, we're going to even test the testing classes. Testception? I think so.
class TestFakeIRC(unittest.TestCase):
    def setUp(self):
        self.irc = classes.FakeIRC('unittest', classes.FakeProto())

    def testFakeIRC(self):
        self.irc.run('this should do nothing')
        self.irc.send('ADD this message')
        self.irc.send(':add THIS message too')
        msgs = self.irc.takeMsgs()
        self.assertEqual(['ADD this message', ':add THIS message too'],
            msgs)
        # takeMsgs() clears cached messages queue, so the next call should
        # return an empty list.
        msgs = self.irc.takeMsgs()
        self.assertEqual([], msgs)

    def testFakeIRCtakeCommands(self):
        msgs = ['ADD this message', ':9PY THIS message too']
        self.assertEqual(['ADD', 'THIS'], self.irc.takeCommands(msgs))

if __name__ == '__main__':
    unittest.main()
