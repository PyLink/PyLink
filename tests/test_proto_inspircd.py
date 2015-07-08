import sys
import os
sys.path += [os.getcwd(), os.path.join(os.getcwd(), 'protocols')]
import unittest
import time

import inspircd
import classes
import utils

class TestProtoInspIRCd(unittest.TestCase):
    def setUp(self):
        self.irc = classes.FakeIRC(inspircd, classes.testconf)
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

    def testCheckRecvpass(self):
        # Correct recvpass here.
        self.irc.run('SERVER somehow.someday abcd 0 0AL :Somehow Server - McMurdo Station, Antarctica')
        # Incorrect recvpass here; should raise ProtocolError.
        self.assertRaises(classes.ProtocolError, self.irc.run, 'SERVER somehow.someday BADPASS 0 0AL :Somehow Server - McMurdo Station, Antarctica')

    def testSpawnClient(self):
        u = self.proto.spawnClient(self.irc, 'testuser3', 'moo', 'hello.world').uid
        # Check the server index and the user index
        self.assertIn(u, self.irc.servers[self.irc.sid].users)
        self.assertIn(u, self.irc.users)
        # Raise ValueError when trying to spawn a client on a server that's not ours
        self.assertRaises(ValueError, self.proto.spawnClient, self.irc, 'abcd', 'user', 'dummy.user.net', server='44A')
        # Unfilled args should get placeholder fields and not error.
        self.proto.spawnClient(self.irc, 'testuser4')

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
        self.irc.run(':34Z SQUIT 34Y :random squit messsage')
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

    def testHandleServer(self):
        self.irc.run('SERVER whatever.net abcd 0 10X :something')
        self.assertIn('10X', self.irc.servers)
        self.assertEqual('whatever.net', self.irc.servers['10X'].name)
        self.irc.run(':10X SERVER test.server * 1 0AL :testing raw message syntax')
        self.assertIn('0AL', self.irc.servers)
        self.assertEqual('test.server', self.irc.servers['0AL'].name)

    def testHandleUID(self):
        self.irc.run('SERVER whatever.net abcd 0 10X :something')
        self.irc.run(':10X UID 10XAAAAAB 1429934638 GL 0::1 hidden-7j810p.9mdf.lrek.0000.0000.IP gl 0::1 1429934638 +Wioswx +ACGKNOQXacfgklnoqvx :realname')
        self.assertIn('10XAAAAAB', self.irc.servers['10X'].users)
        self.assertIn('10XAAAAAB', self.irc.users)
        u = self.irc.users['10XAAAAAB']
        self.assertEqual('GL', u.nick)

    def testHandleKill(self):
        self.irc.takeMsgs()  # Ignore the initial connect messages
        olduid = self.irc.pseudoclient.uid
        self.irc.run(':{u} KILL {u} :killed'.format(u=olduid))
        msgs = self.irc.takeMsgs()
        commands = self.irc.takeCommands(msgs)
        # Make sure we're respawning our PseudoClient when its killed
        self.assertIn('UID', commands)
        self.assertIn('FJOIN', commands)
        # Also make sure that we're updating the irc.pseudoclient field
        self.assertNotEqual(self.irc.pseudoclient.uid, olduid)

    def testHandleKick(self):
        self.irc.takeMsgs()  # Ignore the initial connect messages
        self.irc.run(':{u} KICK #pylink {u} :kicked'.format(u=self.irc.pseudoclient.uid))
        # Ditto above
        msgs = self.irc.takeMsgs()
        commands = self.irc.takeCommands(msgs)
        self.assertIn('FJOIN', commands)

    def testHandleFjoinUsers(self):
        self.irc.run(':70M FJOIN #Chat 1423790411 + :,10XAAAAAA ,10XAAAAAB')
        self.assertEqual({'10XAAAAAA', '10XAAAAAB'}, self.irc.channels['#chat'].users)
        # self.assertIn('10XAAAAAB', self.irc.channels['#chat'].users)
        # Sequential FJOINs must NOT remove existing users
        self.irc.run(':70M FJOIN #Chat 1423790412 + :,10XAAAAAC')
        # Join list can be empty too, in the case of permanent channels with 0 users.
        self.irc.run(':70M FJOIN #Chat 1423790413 +nt :')

    def testHandleFjoinModes(self):
        self.irc.run(':70M FJOIN #Chat 1423790411 +nt :,10XAAAAAA ,10XAAAAAB')
        self.assertEqual({('n', None), ('t', None)}, self.irc.channels['#chat'].modes)
        # Sequential FJOINs must NOT remove existing modes
        self.irc.run(':70M FJOIN #Chat 1423790412 + :,10XAAAAAC')
        self.assertEqual({('n', None), ('t', None)}, self.irc.channels['#chat'].modes)

    def testHandleFjoinModesWithArgs(self):
        self.irc.run(':70M FJOIN #Chat 1423790414 +nlks 10 t0psekrit :,10XAAAAAA ,10XAAAAAB')
        self.assertEqual({('n', None), ('s', None), ('l', '10'), ('k', 't0psekrit')},
                         self.irc.channels['#chat'].modes)

    def testHandleFjoinPrefixes(self):
        self.irc.run(':70M FJOIN #Chat 1423790418 +nt :ov,10XAAAAAA v,10XAAAAAB ,10XAAAAAC')
        self.assertEqual({('n', None), ('t', None)}, self.irc.channels['#chat'].modes)
        self.assertEqual({'10XAAAAAA', '10XAAAAAB', '10XAAAAAC'}, self.irc.channels['#chat'].users)
        self.assertIn('10XAAAAAA', self.irc.channels['#chat'].prefixmodes['ops'])
        self.assertEqual({'10XAAAAAA', '10XAAAAAB'}, self.irc.channels['#chat'].prefixmodes['voices'])

    def testHandleFmode(self):
        self.irc.run(':70M FJOIN #pylink 1423790411 +n :o,10XAAAAAA ,10XAAAAAB')
        self.irc.run(':70M FMODE #pylink 1423790412 +ikl herebedragons 100')
        self.assertEqual({('i', None), ('k', 'herebedragons'), ('l', '100'), ('n', None)}, self.irc.channels['#pylink'].modes)
        self.irc.run(':70M FMODE #pylink 1423790413 -ilk+m herebedragons')
        self.assertEqual({('m', None), ('n', None)}, self.irc.channels['#pylink'].modes)

    def testHandleFmodeWithPrefixes(self):
        self.irc.run(':70M FJOIN #pylink 1423790411 +n :o,10XAAAAAA ,10XAAAAAB')
        # Prefix modes are stored separately, so they should never show up in .modes
        self.assertNotIn(('o', '10XAAAAAA'), self.irc.channels['#pylink'].modes)
        self.assertEqual({'10XAAAAAA'}, self.irc.channels['#pylink'].prefixmodes['ops'])
        self.irc.run(':70M FMODE #pylink 1423790412 +lot 50 %s' % self.u)
        self.assertIn(self.u, self.irc.channels['#pylink'].prefixmodes['ops'])
        modes = {('l', '50'), ('n', None), ('t', None)}
        self.assertEqual(modes, self.irc.channels['#pylink'].modes)
        self.irc.run(':70M FMODE #pylink 1423790413 -o %s' % self.u)
        self.assertEqual(modes, self.irc.channels['#pylink'].modes)
        self.assertNotIn(self.u, self.irc.channels['#pylink'].prefixmodes['ops'])

    def testFmodeRemovesOldParams(self):
        self.irc.run(':70M FMODE #pylink 1423790412 +l 50')
        self.assertEqual({('l', '50')}, self.irc.channels['#pylink'].modes)
        self.irc.run(':70M FMODE #pylink 1423790412 +l 30')
        self.assertEqual({('l', '30')}, self.irc.channels['#pylink'].modes)

    def testFjoinResetsTS(self):
        curr_ts = self.irc.channels['#pylink'].ts
        self.irc.run(':70M FJOIN #pylink 5 + :')
        self.assertEqual(self.irc.channels['#pylink'].ts, 5)

    def testHandleFTopic(self):
        self.irc.run(':70M FTOPIC #pylink 1434510754 GLo|o|!GLolol@escape.the.dreamland.ca :Some channel topic')
        self.assertEqual(self.irc.channels['#pylink'].topic, 'Some channel topic')

    def testHandleTopic(self):
        self.irc.connect()
        utils.add_hook(self.irc.dummyhook, 'TOPIC')
        self.irc.run(':9PYAAAAAA TOPIC #PyLink :test')
        self.assertEqual(self.irc.channels['#pylink'].topic, 'test')
        hookdata = self.irc.takeHooks()[0]
        # Setter is a nick here, not an UID - this is to be consistent
        # with FTOPIC above, which sends the nick/prefix of the topic setter.
        self.assertTrue(utils.isNick(hookdata.get('setter')))
        self.assertEqual(type(hookdata['ts']), int)
        self.assertEqual(hookdata['topic'], 'test')
        self.assertEqual(hookdata['channel'], '#pylink')

if __name__ == '__main__':
    unittest.main()
