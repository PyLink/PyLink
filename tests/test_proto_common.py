import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main
import classes
from collections import defaultdict
import unittest

class FakeIRC(main.Irc):
    def __init__(self, proto):
        self.connected = False
        self.users = {}
        self.channels = defaultdict(classes.IrcChannel)
        self.name = 'fakeirc'
        self.servers = {}
        self.proto = proto

        self.serverdata = {'netname': 'fakeirc',
                             'ip': '0.0.0.0',
                             'port': 7000,
                             'recvpass': "abcd",
                             'sendpass': "abcd",
                             'protocol': "testingonly",
                             'hostname': "pylink.unittest",
                             'sid': "9PY",
                             'channels': ["#pylink"],
                          }
        self.conf = {'server': self.serverdata}
        ip = self.serverdata["ip"]
        port = self.serverdata["port"]
        self.sid = self.serverdata["sid"]
        self.socket = None
        self.messages = []
        
    def run(self, data):
        """Queues a message to the fake IRC server."""
        print('-> ' + data)
        self.proto.handle_events(self, data)

    def send(self, data):
        self.messages.append(data)
        print('<- ' + data)

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
        self.irc = FakeIRC(FakeProto())

    def testFakeIRC(self):
        self.irc.run('this should do nothing')
        self.irc.send('ADD this message')
        self.irc.send(':add THIS message too')
        msgs = self.irc.takeMsgs()
        self.assertEqual(['ADD this message', ':add THIS message too'],
            msgs)

    def testFakeIRC_takeMsgs(self):
        msgs = ['ADD this message', ':9PY THIS message too']
        self.assertEqual(['ADD', 'THIS'], self.irc.takeCommands(msgs))

if __name__ == '__main__':
    unittest.main()
