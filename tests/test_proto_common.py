import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from log import log

import main
import classes
from collections import defaultdict
import unittest

global testconf
testconf = {'server': 
            {'netname': 'fakeirc',
             'ip': '0.0.0.0',
             'port': 7000,
             'recvpass': "abcd",
             'sendpass': "abcd",
             'protocol': "null",
             'hostname': "pylink.unittest",
             'sid': "9PY",
             'channels': ["#pylink"],
            }
       }

class FakeIRC(main.Irc):
    def connect(self):
        self.messages = []
        self.socket = None

    def run(self, data):
        """Queues a message to the fake IRC server."""
        log.debug('<- ' + data)
        self.proto.handle_events(self, data)

    def send(self, data):
        self.messages.append(data)
        log.debug('-> ' + data)

    def takeMsgs(self):
        """Returns a list of messages sent by the protocol module since
        the last takeMsgs() call, so we can track what has been sent."""
        msgs = self.messages
        self.messages = []
        return msgs

    def takeCommands(self, msgs):
        """Returns a list of commands parsed from the output of takeMsgs()."""
        sidprefix = ':' + self.sid
        commands = []
        for m in msgs:
            args = m.split()
            if m.startswith(sidprefix):
                commands.append(args[1])
            else:
                commands.append(args[0])
        return commands

class FakeProto():
    """Dummy protocol module for testing purposes."""
    @staticmethod
    def handle_events(irc, data):
        pass

    @staticmethod
    def connect(irc):
        pass

# Yes, we're going to even test the testing classes. Testception? I think so.
class Test_TestProtoCommon(unittest.TestCase):
    def setUp(self):
        self.irc = FakeIRC(FakeProto(), testconf)

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
