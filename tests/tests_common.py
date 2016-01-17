import sys
import os
sys.path += [os.getcwd(), os.path.join(os.getcwd(), 'protocols')]
import unittest

import world
import utils
import classes
import conf

world.started.set()

class PluginTestCase(unittest.TestCase):
    def setUp(self):
        proto = utils.getProtocolModule(world.testing_ircd)
        self.irc = classes.FakeIRC('unittest', proto, conf.testconf)
        self.proto = self.irc.proto
        self.irc.connect()
        self.sdata = self.irc.serverdata
        self.u = self.irc.pseudoclient.uid
        self.maxDiff = None
        # Dummy servers/users used in tests below.
        self.proto.spawnServer('whatever.', sid='10X')
        for x in range(3):
            self.proto.spawnClient('user%s' % x, server='10X')

class CommonProtoTestCase(PluginTestCase):
    def testJoinClient(self):
        u = self.u
        self.proto.join(u, '#Channel')
        self.assertIn(u, self.irc.channels['#channel'].users)
        # Non-existant user.
        self.assertRaises(LookupError, self.proto.join, '9PYZZZZZZ', '#test')

    def testKickClient(self):
        target = self.proto.spawnClient('soccerball', 'soccerball', 'abcd').uid
        self.proto.join(target, '#pylink')
        self.assertIn(self.u, self.irc.channels['#pylink'].users)
        self.assertIn(target, self.irc.channels['#pylink'].users)
        self.proto.kickClient(self.u, '#pylink', target, 'Pow!')
        self.assertNotIn(target, self.irc.channels['#pylink'].users)

    def testModeClient(self):
        testuser = self.proto.spawnClient('testcakes')
        self.irc.takeMsgs()
        self.proto.modeClient(self.u, testuser.uid, [('+i', None), ('+w', None)])
        self.assertEqual({('i', None), ('w', None)}, testuser.modes)

        # Default channels start with +nt
        self.assertEqual({('n', None), ('t', None)}, self.irc.channels['#pylink'].modes)
        self.proto.modeClient(self.u, '#pylink', [('+s', None), ('+l', '30')])
        self.assertEqual({('s', None), ('l', '30'), ('n', None), ('t', None)}, self.irc.channels['#pylink'].modes)

        cmds = self.irc.takeCommands(self.irc.takeMsgs())
        self.assertEqual(cmds, ['MODE', 'FMODE'])

    def testNickClient(self):
        self.proto.nickClient(self.u, 'NotPyLink')
        self.assertEqual('NotPyLink', self.irc.users[self.u].nick)

    def testPartClient(self):
        u = self.u
        self.proto.join(u, '#channel')
        self.proto.partClient(u, '#channel')
        self.assertNotIn(u, self.irc.channels['#channel'].users)

    def testQuitClient(self):
        u = self.proto.spawnClient('testuser3', 'moo', 'hello.world').uid
        self.proto.join(u, '#channel')
        self.assertRaises(LookupError, self.proto.quitClient, '9PYZZZZZZ', 'quit reason')
        self.proto.quitClient(u, 'quit reason')
        self.assertNotIn(u, self.irc.channels['#channel'].users)
        self.assertNotIn(u, self.irc.users)
        self.assertNotIn(u, self.irc.servers[self.irc.sid].users)

    def testSpawnClient(self):
        u = self.proto.spawnClient('testuser3', 'moo', 'hello.world').uid
        # Check the server index and the user index
        self.assertIn(u, self.irc.servers[self.irc.sid].users)
        self.assertIn(u, self.irc.users)
        # Raise ValueError when trying to spawn a client on a server that's not ours
        self.assertRaises(ValueError, self.proto.spawnClient, 'abcd', 'user', 'dummy.user.net', server='44A')
        # Unfilled args should get placeholder fields and not error.
        self.proto.spawnClient('testuser4')

    def testSpawnClientOnServer(self):
        self.proto.spawnServer('subserver.pylink', '34Q')
        u = self.proto.spawnClient('person1', 'person', 'users.overdrive.pw', server='34Q')
        # We're spawning clients on the right server, hopefully...
        self.assertIn(u.uid, self.irc.servers['34Q'].users)
        self.assertNotIn(u.uid, self.irc.servers[self.irc.sid].users)

    def testSpawnServer(self):
        # Incorrect SID length
        self.assertRaises(Exception, self.proto.spawnServer, 'subserver.pylink', '34Q0')
        self.proto.spawnServer('subserver.pylink', '34Q')
        # Duplicate server name
        self.assertRaises(Exception, self.proto.spawnServer, 'Subserver.PyLink', '34Z')
        # Duplicate SID
        self.assertRaises(Exception, self.proto.spawnServer, 'another.Subserver.PyLink', '34Q')
        self.assertIn('34Q', self.irc.servers)
