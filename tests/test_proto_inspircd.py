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

    def testSpawnServer(self):
        # Incorrect SID length
        self.assertRaises(Exception, self.proto.spawnServer, self.irc, 'subserver.pylink', '34Q0')
        self.proto.spawnServer(self.irc, 'subserver.pylink', '34Q')
        # Duplicate server name
        self.assertRaises(Exception, self.proto.spawnServer, self.irc, 'Subserver.PyLink', '34Z')
        # Duplicate SID
        self.assertRaises(Exception, self.proto.spawnServer, self.irc, 'another.Subserver.PyLink', '34Q')
        self.assertIn('34Q', self.irc.servers)
        # Are we bursting properly?
        self.assertIn(':34Q ENDBURST', self.irc.takeMsgs())

    def testSpawnClientOnServer(self):
        self.proto.spawnServer(self.irc, 'subserver.pylink', '34Q')
        u = self.proto.spawnClient(self.irc, 'person1', 'person', 'users.overdrive.pw', server='34Q')
        # We're spawning clients on the right server, hopefully...
        self.assertIn(u.uid, self.irc.servers['34Q'].users)
        self.assertNotIn(u.uid, self.irc.servers[self.irc.sid].users)

    def testSquit(self):
        # Spawn a messy network map, just because!
        self.proto.spawnServer(self.irc, 'level1.pylink', '34P')
        self.proto.spawnServer(self.irc, 'level2.pylink', '34Q', uplink='34P')
        self.proto.spawnServer(self.irc, 'level3.pylink', '34Z', uplink='34Q')
        self.proto.spawnServer(self.irc, 'level4.pylink', '34Y', uplink='34Z')
        self.assertEqual(self.irc.servers['34Y'].uplink, '34Z')
        s4u = self.proto.spawnClient(self.irc, 'person1', 'person', 'users.overdrive.pw', server='34Y').uid
        s3u = self.proto.spawnClient(self.irc, 'person2', 'person', 'users.overdrive.pw', server='34Z').uid
        self.proto.joinClient(self.irc, s3u, '#pylink')
        self.proto.joinClient(self.irc, s4u, '#pylink')
        self.proto.handle_squit(self.irc, '9PY', 'SQUIT', ['34Y'])
        self.assertNotIn(s4u, self.irc.users)
        self.assertNotIn('34Y', self.irc.servers)
        # Netsplits are obviously recursive, so all these should be removed.
        self.proto.handle_squit(self.irc, '9PY', 'SQUIT', ['34P'])
        self.assertNotIn(s3u, self.irc.users)
        self.assertNotIn('34P', self.irc.servers)
        self.assertNotIn('34Q', self.irc.servers)
        self.assertNotIn('34Z', self.irc.servers)

    def testRSquit(self):
        u = self.proto.spawnClient(self.irc, 'person1', 'person', 'users.overdrive.pw')
        u.identified = 'admin'
        self.proto.spawnServer(self.irc, 'level1.pylink', '34P')
        self.irc.run(':%s RSQUIT level1.pylink :some reason' % self.u)
        # No SQUIT yet, since the 'PyLink' client isn't identified
        self.assertNotIn('SQUIT', self.irc.takeCommands(self.irc.takeMsgs()))
        # The one we just spawned however, is.
        self.irc.run(':%s RSQUIT level1.pylink :some reason' % u.uid)
        self.assertIn('SQUIT', self.irc.takeCommands(self.irc.takeMsgs()))
        self.assertNotIn('34P', self.irc.servers)

if __name__ == '__main__':
    unittest.main()
