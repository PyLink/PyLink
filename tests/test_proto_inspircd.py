import sys
import os
sys.path += [os.getcwd(), os.path.join(os.getcwd(), 'protocols')]
import unittest

import inspircd
import classes
import world

import tests_common

world.testing = inspircd

class InspIRCdTestCase(tests_common.CommonProtoTestCase):
    def testCheckRecvpass(self):
        # Correct recvpass here.
        self.irc.run('SERVER somehow.someday abcd 0 0AL :Somehow Server - McMurdo Station, Antarctica')
        # Incorrect recvpass here; should raise ProtocolError.
        self.assertRaises(classes.ProtocolError, self.irc.run, 'SERVER somehow.someday BADPASS 0 0AL :Somehow Server - McMurdo Station, Antarctica')

    def testConnect(self):
        self.proto.connect()
        initial_messages = self.irc.takeMsgs()
        commands = self.irc.takeCommands(initial_messages)
        # SERVER pylink.unittest abcd 0 9PY :PyLink Service
        serverline = 'SERVER %s %s 0 %s :%s' % (
            self.sdata['hostname'], self.sdata['sendpass'], self.sdata['sid'],
            self.irc.botdata['serverdesc'])
        self.assertIn(serverline, initial_messages)
        self.assertIn('BURST', commands)
        self.assertIn('ENDBURST', commands)
        # Is it creating our lovely PyLink PseudoClient?
        self.assertIn('UID', commands)
        self.assertIn('FJOIN', commands)

    def testSpawnServer(self):
        super(InspIRCdTestCase, self).testSpawnServer()
        # Are we bursting properly?
        self.assertIn(':34Q ENDBURST', self.irc.takeMsgs())

    def testHandleSQuit(self):
        # Spawn a messy network map, just because!
        self.proto.spawnServer('level1.pylink', '34P')
        self.proto.spawnServer('level2.pylink', '34Q', uplink='34P')
        self.proto.spawnServer('level3.pylink', '34Z', uplink='34Q')
        self.proto.spawnServer('level4.pylink', '34Y', uplink='34Z')
        self.assertEqual(self.irc.servers['34Y'].uplink, '34Z')
        s4u = self.proto.spawnClient('person1', 'person', 'users.overdrive.pw', server='34Y').uid
        s3u = self.proto.spawnClient('person2', 'person', 'users.overdrive.pw', server='34Z').uid
        self.proto.joinClient(s3u, '#pylink')
        self.proto.joinClient(s4u, '#pylink')
        self.irc.run(':34Z SQUIT 34Y :random squit messsage')
        self.assertNotIn(s4u, self.irc.users)
        self.assertNotIn('34Y', self.irc.servers)
        # Netsplits are obviously recursive, so all these should be removed.
        self.proto.handle_squit('9PY', 'SQUIT', ['34P'])
        self.assertNotIn(s3u, self.irc.users)
        self.assertNotIn('34P', self.irc.servers)
        self.assertNotIn('34Q', self.irc.servers)
        self.assertNotIn('34Z', self.irc.servers)

    def testHandleServer(self):
        self.irc.run('SERVER whatever.net abcd 0 10X :something')
        self.assertIn('10X', self.irc.servers)
        self.assertEqual('whatever.net', self.irc.servers['10X'].name)
        self.irc.run(':10X SERVER test.server * 1 0AL :testing raw message syntax')
        self.assertIn('0AL', self.irc.servers)
        self.assertEqual('test.server', self.irc.servers['0AL'].name)

    def testHandleUID(self):
        self.irc.run(':10X UID 10XAAAAAB 1429934638 GL 0::1 hidden-7j810p.9mdf.lrek.0000.0000.IP gl 0::1 1429934638 +Wioswx +ACGKNOQXacfgklnoqvx :realname')
        self.assertIn('10XAAAAAB', self.irc.servers['10X'].users)
        u = self.irc.users['10XAAAAAB']
        self.assertEqual('GL', u.nick)

        expected = {'uid': '10XAAAAAB', 'ts': '1429934638', 'nick': 'GL',
                    'realhost': '0::1', 'ident': 'gl', 'ip': '0::1',
                    'host': 'hidden-7j810p.9mdf.lrek.0000.0000.IP'}
        hookdata = self.irc.takeHooks()[0][-1]
        self.assertEqual(hookdata, expected)

    def testHandleKill(self):
        self.irc.takeMsgs()  # Ignore the initial connect messages
        self.u = self.irc.pseudoclient.uid
        self.irc.run(':{u} KILL {u} :killed'.format(u=self.u))
        msgs = self.irc.takeMsgs()
        commands = self.irc.takeCommands(msgs)
        hookdata = self.irc.takeHooks()[0][-1]
        self.assertEqual(hookdata['target'], self.u)
        self.assertEqual(hookdata['text'], 'killed')
        self.assertNotIn(self.u, self.irc.users)

    def testHandleKick(self):
        self.irc.takeMsgs()  # Ignore the initial connect messages
        self.irc.run(':{u} KICK #pylink {u} :kicked'.format(u=self.irc.pseudoclient.uid))
        hookdata = self.irc.takeHooks()[0][-1]
        self.assertEqual(hookdata['target'], self.u)
        self.assertEqual(hookdata['text'], 'kicked')
        self.assertEqual(hookdata['channel'], '#pylink')

    def testHandleFJoinUsers(self):
        self.irc.run(':10X FJOIN #Chat 1423790411 + :,10XAAAAAA ,10XAAAAAB')
        self.assertEqual({'10XAAAAAA', '10XAAAAAB'}, self.irc.channels['#chat'].users)
        self.assertIn('#chat', self.irc.users['10XAAAAAA'].channels)
        # Sequential FJOINs must NOT remove existing users
        self.irc.run(':10X FJOIN #Chat 1423790412 + :,10XAAAAAC')
        # Join list can be empty too, in the case of permanent channels with 0 users.
        self.irc.run(':10X FJOIN #Chat 1423790413 +nt :')

    def testHandleFJoinModes(self):
        self.irc.run(':10X FJOIN #Chat 1423790411 +nt :,10XAAAAAA ,10XAAAAAB')
        self.assertEqual({('n', None), ('t', None)}, self.irc.channels['#chat'].modes)
        # Sequential FJOINs must NOT remove existing modes
        self.irc.run(':10X FJOIN #Chat 1423790412 + :,10XAAAAAC')
        self.assertEqual({('n', None), ('t', None)}, self.irc.channels['#chat'].modes)

    def testHandleFJoinModesWithArgs(self):
        self.irc.run(':10X FJOIN #Chat 1423790414 +nlks 10 t0psekrit :,10XAAAAAA ,10XAAAAAB')
        self.assertEqual({('n', None), ('s', None), ('l', '10'), ('k', 't0psekrit')},
                         self.irc.channels['#chat'].modes)

    def testHandleFJoinPrefixes(self):
        self.irc.run(':10X FJOIN #Chat 1423790418 +nt :ov,10XAAAAAA v,10XAAAAAB ,10XAAAAAC')
        self.assertEqual({('n', None), ('t', None)}, self.irc.channels['#chat'].modes)
        self.assertEqual({'10XAAAAAA', '10XAAAAAB', '10XAAAAAC'}, self.irc.channels['#chat'].users)
        self.assertIn('10XAAAAAA', self.irc.channels['#chat'].prefixmodes['ops'])
        self.assertEqual({'10XAAAAAA', '10XAAAAAB'}, self.irc.channels['#chat'].prefixmodes['voices'])

    def testHandleFJoinHook(self):
        self.irc.run(':10X FJOIN #PyLink 1423790418 +ls 10 :ov,10XAAAAAA v,10XAAAAAB ,10XAAAAAC')
        hookdata = self.irc.takeHooks()[0][-1]
        expected = {'modes': [('+l', '10'), ('+s', None)],
                    'channel': '#pylink',
                    'users': ['10XAAAAAA', '10XAAAAAB', '10XAAAAAC'],
                    'ts': 1423790418}
        self.assertEqual(expected, hookdata)

    def testHandleFMode(self):
        # Default channels start with +nt
        self.irc.run(':70M FMODE #pylink 1423790412 -nt')
        self.assertEqual(set(), self.irc.channels['#pylink'].modes)
        self.irc.takeHooks()

        self.irc.run(':70M FMODE #pylink 1423790412 +ikl herebedragons 100')
        self.assertEqual({('i', None), ('k', 'herebedragons'), ('l', '100')}, self.irc.channels['#pylink'].modes)
        self.irc.run(':70M FMODE #pylink 1423790413 -ilk+m herebedragons')
        self.assertEqual({('m', None)}, self.irc.channels['#pylink'].modes)

        hookdata = self.irc.takeHooks()
        expected = [['70M', 'FMODE', {'target': '#pylink', 'modes':
                                      [('+i', None), ('+k', 'herebedragons'),
                                       ('+l', '100')], 'ts': 1423790412}
                    ],
                    ['70M', 'FMODE', {'target': '#pylink', 'modes':
                                      [('-i', None), ('-l', None),
                                       ('-k', 'herebedragons'), ('+m', None)],
                                       'ts': 1423790413}]
                   ]
        self.assertEqual(expected, hookdata)

    def testHandleFModeWithPrefixes(self):
        self.irc.run(':70M FJOIN #pylink 123 +n :o,10XAAAAAA ,10XAAAAAB')
        # Prefix modes are stored separately, so they should never show up in .modes
        self.assertNotIn(('o', '10XAAAAAA'), self.irc.channels['#pylink'].modes)
        self.assertEqual({'10XAAAAAA'}, self.irc.channels['#pylink'].prefixmodes['ops'])
        self.irc.run(':70M FMODE #pylink 123 +lot 50 %s' % self.u)
        self.assertIn(self.u, self.irc.channels['#pylink'].prefixmodes['ops'])
        modes = {('l', '50'), ('n', None), ('t', None)}
        self.assertEqual(modes, self.irc.channels['#pylink'].modes)
        self.irc.run(':70M FMODE #pylink 123 -o %s' % self.u)
        self.assertEqual(modes, self.irc.channels['#pylink'].modes)
        self.assertNotIn(self.u, self.irc.channels['#pylink'].prefixmodes['ops'])
        # Test hooks
        hookdata = self.irc.takeHooks()
        expected = [['70M', 'FJOIN', {'channel': '#pylink', 'ts': 123, 'modes': [('+n', None)],
                                      'users': ['10XAAAAAA', '10XAAAAAB']}],
                    ['70M', 'FMODE', {'target': '#pylink', 'modes': [('+l', '50'), ('+o', '9PYAAAAAA'), ('+t', None)], 'ts': 123}],
                    ['70M', 'FMODE', {'target': '#pylink', 'modes': [('-o', '9PYAAAAAA')], 'ts': 123}]]
        self.assertEqual(expected, hookdata)

    def testHandleFModeRemovesOldParams(self):
        self.irc.run(':70M FMODE #pylink 1423790412 +l 50')
        self.assertIn(('l', '50'), self.irc.channels['#pylink'].modes)
        self.irc.run(':70M FMODE #pylink 1423790412 +l 30')
        self.assertIn(('l', '30'), self.irc.channels['#pylink'].modes)
        self.assertNotIn(('l', '50'), self.irc.channels['#pylink'].modes)
        hookdata = self.irc.takeHooks()
        expected = [['70M', 'FMODE', {'target': '#pylink', 'modes': [('+l', '50')], 'ts': 1423790412}],
                    ['70M', 'FMODE', {'target': '#pylink', 'modes': [('+l', '30')], 'ts': 1423790412}]]
        self.assertEqual(expected, hookdata)

    def testHandleFJoinResetsTS(self):
        curr_ts = self.irc.channels['#pylink'].ts
        self.irc.run(':70M FJOIN #pylink 5 + :')
        self.assertEqual(self.irc.channels['#pylink'].ts, 5)

    def testHandleFTopic(self):
        self.irc.run(':70M FTOPIC #pylink 1434510754 GLo|o|!GLolol@escape.the.dreamland.ca :Some channel topic')
        self.assertEqual(self.irc.channels['#pylink'].topic, 'Some channel topic')

    def testHandleTopic(self):
        self.irc.connect()
        self.irc.run(':9PYAAAAAA TOPIC #PyLink :test')
        self.assertEqual(self.irc.channels['#pylink'].topic, 'test')
        hookdata = self.irc.takeHooks()[0][-1]
        self.assertEqual(type(hookdata['ts']), int)
        self.assertEqual(hookdata['topic'], 'test')
        self.assertEqual(hookdata['channel'], '#pylink')

    def testHandleMessages(self):
        for m in ('NOTICE', 'PRIVMSG'):
            self.irc.run(':70MAAAAAA %s #dev :afasfsa' % m)
            hookdata = self.irc.takeHooks()[0][-1]
            self.assertEqual(hookdata['target'], '#dev')
            self.assertEqual(hookdata['text'], 'afasfsa')

    def testHandlePart(self):
        hookdata = self.irc.takeHooks()
        self.irc.run(':9PYAAAAAA PART #pylink')
        hookdata = self.irc.takeHooks()[0][-1]
        self.assertEqual(hookdata['channels'], ['#pylink'])
        self.assertEqual(hookdata['text'], '')

    def testHandleQuit(self):
        self.irc.takeHooks()
        self.irc.run(':10XAAAAAB QUIT :Quit: quit message goes here')
        hookdata = self.irc.takeHooks()[0][-1]
        self.assertEqual(hookdata['text'], 'Quit: quit message goes here')
        self.assertNotIn('10XAAAAAB', self.irc.users)
        self.assertNotIn('10XAAAAAB', self.irc.servers['10X'].users)

    def testHandleServer(self):
        self.irc.run(':00A SERVER test.server * 1 00C :testing raw message syntax')
        hookdata = self.irc.takeHooks()[-1][-1]
        self.assertEqual(hookdata['name'], 'test.server')
        self.assertEqual(hookdata['sid'], '00C')
        self.assertEqual(hookdata['text'], 'testing raw message syntax')
        self.assertIn('00C', self.irc.servers)

    def testHandleNick(self):
        self.irc.run(':9PYAAAAAA NICK PyLink-devel 1434744242')
        hookdata = self.irc.takeHooks()[0][-1]
        expected = {'newnick': 'PyLink-devel', 'oldnick': 'PyLink', 'ts': 1434744242}
        self.assertEqual(hookdata, expected)
        self.assertEqual('PyLink-devel', self.irc.users['9PYAAAAAA'].nick)

    def testHandleSave(self):
        self.irc.run(':9PYAAAAAA NICK Derp_ 1433728673')
        self.irc.run(':70M SAVE 9PYAAAAAA 1433728673')
        hookdata = self.irc.takeHooks()[-1][-1]
        self.assertEqual(hookdata, {'target': '9PYAAAAAA', 'ts': 1433728673, 'oldnick': 'Derp_'})
        self.assertEqual('9PYAAAAAA', self.irc.users['9PYAAAAAA'].nick)

    def testHandleInvite(self):
        self.irc.run(':10XAAAAAA INVITE 9PYAAAAAA #blah 0')
        hookdata = self.irc.takeHooks()[-1][-1]
        del hookdata['ts']
        self.assertEqual(hookdata, {'target': '9PYAAAAAA', 'channel': '#blah'})

    def testHandleOpertype(self):
        self.irc.run('SERVER whatever. abcd 0 10X :Whatever Server - Hellas Planitia, Mars')
        self.irc.run(':10X UID 10XAAAAAB 1429934638 GL 0::1 '
                     'hidden-7j810p.9mdf.lrek.0000.0000.IP gl 0::1 1429934638 '
                     '+Wioswx +ACGKNOQXacfgklnoqvx :realname')
        self.irc.run(':10XAAAAAB OPERTYPE Network_Owner')
        self.assertIn(('o', None), self.irc.users['10XAAAAAB'].modes)

if __name__ == '__main__':
    unittest.main()
