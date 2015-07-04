import sys
import os
sys.path += [os.getcwd(), os.path.join(os.getcwd(), 'protocols')]
import unittest
import time

import inspircd
from . import test_proto_common
from classes import ProtocolError
import utils

class TestInspIRCdProtocol(unittest.TestCase):
    def setUp(self):
        self.irc = test_proto_common.FakeIRC(inspircd)
        self.proto = self.irc.proto
        self.sdata = self.irc.serverdata
        # This is to initialize ourself as an internal PseudoServer, so we can spawn clients
        self.proto.connect(self.irc)
        self.u = self.irc.pseudoclient.uid

    def test_connect(self):
        initial_messages = self.irc.takeMsgs()
        commands = self.irc.takeCommands(initial_messages)

        # SERVER pylink.unittest abcd 0 9PY :PyLink Service
        serverline = 'SERVER %s %s 0 %s :PyLink Service' % (
            self.sdata['hostname'], self.sdata['sendpass'], self.sdata['sid'])
        self.assertIn(serverline, initial_messages)
        self.assertIn('BURST', commands)
        self.assertIn('ENDBURST', commands)
        # Is it creating our lovely PyLink PseudoClient?
        self.assertIn('UID', commands)
        self.assertIn('FJOIN', commands)

    def test_checkRecvpass(self):
        # Correct recvpass here.
        self.irc.run('SERVER somehow.someday abcd 0 0AL :Somehow Server - McMurdo Station, Antarctica')
        # Incorrect recvpass here; should raise ProtocolError.
        self.assertRaises(ProtocolError, self.irc.run, 'SERVER somehow.someday BADPASS 0 0AL :Somehow Server - McMurdo Station, Antarctica')

    def testSpawnClient(self):
        u = self.proto.spawnClient(self.irc, 'testuser3', 'moo', 'hello.world').uid
        # Check the server index and the user index
        self.assertIn(u, self.irc.servers[self.irc.sid].users)
        self.assertIn(u, self.irc.users)
        # Raise ValueError when trying to spawn a client on a server that's not ours
        self.assertRaises(ValueError, self.proto.spawnClient, self.irc, 'abcd', 'user', 'dummy.user.net', server='44A')

    def testJoinClient(self):
        u = self.u
        self.proto.joinClient(self.irc, u, '#Channel')
        self.assertIn(u, self.irc.channels['#channel'].users)
        # Non-existant user.
        self.assertRaises(LookupError, self.proto.joinClient, self.irc, '9PYZZZZZZ', '#test')
        # Invalid channel.
        self.assertRaises(ValueError, self.proto.joinClient, self.irc, u, 'aaaa')

    def testPartClient(self):
        u = self.u
        self.proto.joinClient(self.irc, u, '#channel')
        self.proto.partClient(self.irc, u, '#channel')
        self.assertNotIn(u, self.irc.channels['#channel'].users)

    def testQuitClient(self):
        u = self.proto.spawnClient(self.irc, 'testuser3', 'moo', 'hello.world').uid
        self.proto.joinClient(self.irc, u, '#channel')
        self.assertRaises(LookupError, self.proto.quitClient, self.irc, '9PYZZZZZZ', 'quit reason')
        self.proto.quitClient(self.irc, u, 'quit reason')
        self.assertNotIn(u, self.irc.channels['#channel'].users)
        self.assertNotIn(u, self.irc.users)
        self.assertNotIn(u, self.irc.servers[self.irc.sid].users)
        pass

    def testKickClient(self):
        target = self.proto.spawnClient(self.irc, 'soccerball', 'soccerball', 'abcd').uid
        self.proto.joinClient(self.irc, target, '#pylink')
        self.assertIn(self.u, self.irc.channels['#pylink'].users)
        self.assertIn(target, self.irc.channels['#pylink'].users)
        self.proto.kickClient(self.irc, self.u, '#pylink', target, 'Pow!')
        self.assertNotIn(target, self.irc.channels['#pylink'].users)

    def testNickClient(self):
        self.proto.nickClient(self.irc, self.u, 'NotPyLink')
        self.assertEqual('NotPyLink', self.irc.users[self.u].nick)

if __name__ == '__main__':
    unittest.main()
