import sys
import os
sys.path.append(os.getcwd())
import unittest
import itertools
from copy import deepcopy

import utils
import classes
import conf
import world

def dummyf():
    pass

class TestUtils(unittest.TestCase):
    def setUp(self):
        self.irc = classes.FakeIRC('fakeirc', classes.FakeProto, conf.testconf)

    def testTS6UIDGenerator(self):
        uidgen = utils.TS6UIDGenerator('9PY')
        self.assertEqual(uidgen.next_uid(), '9PYAAAAAA')
        self.assertEqual(uidgen.next_uid(), '9PYAAAAAB')

    def test_add_cmd(self):
        # Without name specified, add_cmd adds a command with the same name
        # as the function
        utils.add_cmd(dummyf)
        utils.add_cmd(dummyf, 'TEST')
        # All command names should be automatically lowercased.
        self.assertIn('dummyf', world.commands)
        self.assertIn('test', world.commands)
        self.assertNotIn('TEST', world.commands)

    def test_add_hook(self):
        utils.add_hook(dummyf, 'join')
        self.assertIn('JOIN', world.hooks)
        # Command names stored in uppercase.
        self.assertNotIn('join', world.hooks)
        self.assertIn(dummyf, world.hooks['JOIN'])

    def testIsNick(self):
        self.assertFalse(utils.isNick('abcdefgh', nicklen=3))
        self.assertTrue(utils.isNick('aBcdefgh', nicklen=30))
        self.assertTrue(utils.isNick('abcdefgh1'))
        self.assertTrue(utils.isNick('ABC-def'))
        self.assertFalse(utils.isNick('-_-'))
        self.assertFalse(utils.isNick(''))
        self.assertFalse(utils.isNick(' i lost the game'))
        self.assertFalse(utils.isNick(':aw4t*9e4t84a3t90$&*6'))
        self.assertFalse(utils.isNick('9PYAAAAAB'))
        self.assertTrue(utils.isNick('_9PYAAAAAB\\'))

    def testIsChannel(self):
        self.assertFalse(utils.isChannel(''))
        self.assertFalse(utils.isChannel('lol'))
        self.assertTrue(utils.isChannel('#channel'))
        self.assertTrue(utils.isChannel('##ABCD'))

    def testIsServerName(self):
        self.assertFalse(utils.isServerName('Invalid'))
        self.assertTrue(utils.isServerName('services.'))
        self.assertFalse(utils.isServerName('.s.s.s'))
        self.assertTrue(utils.isServerName('Hello.world'))
        self.assertFalse(utils.isServerName(''))
        self.assertTrue(utils.isServerName('pylink.overdrive.pw'))
        self.assertFalse(utils.isServerName(' i lost th.e game'))

    def testJoinModes(self):
        res = utils.joinModes({('+l', '50'), ('+n', None), ('+t', None)})
        # Sets are orderless, so the end mode could be scrambled in a number of ways.
        # Basically, we're looking for a string that looks like '+ntl 50' or '+lnt 50'.
        possible = ['+%s 50' % ''.join(x) for x in itertools.permutations('lnt', 3)]
        self.assertIn(res, possible)

        # Without any arguments, make sure there is no trailing space.
        self.assertEqual(utils.joinModes({('+t', None)}), '+t')

        # The +/- in the mode is not required; if it doesn't exist, assume we're
        # adding modes always.
        self.assertEqual(utils.joinModes([('t', None), ('n', None)]), '+tn')

        # An empty query should return just '+'
        self.assertEqual(utils.joinModes(set()), '+')

        # More complex query now with both + and - modes being set
        res = utils.joinModes([('+l', '50'), ('-n', None)])
        self.assertEqual(res, '+l-n 50')

        # If one modepair in the list lacks a +/- prefix, just follow the
        # previous one's.
        res = utils.joinModes([('+l', '50'), ('-n', None), ('m', None)])
        self.assertEqual(res, '+l-nm 50')
        res = utils.joinModes([('+l', '50'), ('m', None)])
        self.assertEqual(res, '+lm 50')
        res = utils.joinModes([('l', '50'), ('-m', None)])
        self.assertEqual(res, '+l-m 50')

        # Rarely in real life will we get a mode string this complex.
        # Let's make sure it works, just in case.
        res = utils.joinModes([('-o', '9PYAAAAAA'), ('+l', '50'), ('-n', None),
                               ('-m', None), ('+k', 'hello'),
                               ('+b', '*!*@*.badisp.net')])
        self.assertEqual(res, '-o+l-nm+kb 9PYAAAAAA 50 hello *!*@*.badisp.net')

    def _reverseModes(self, query, expected, target='#PyLink', oldobj=None):
        res = utils.reverseModes(self.irc, target, query, oldobj=oldobj)
        self.assertEqual(res, expected)

    def testReverseModes(self):
        # Initialize the channe, first.
        utils.applyModes(self.irc, '#PyLink', [])
        # Strings.
        self._reverseModes("+mk-t test", "-mk+t test")
        self._reverseModes("ml-n 111", "-ml+n")
        # Lists.
        self._reverseModes([('+m', None), ('+r', None), ('+l', '3')],
                           {('-m', None), ('-r', None), ('-l', None)})
        # Sets.
        self._reverseModes({('s', None)}, {('-s', None)})
        # Combining modes with an initial + and those without
        self._reverseModes({('s', None), ('+R', None)}, {('-s', None), ('-R', None)})

    def testReverseModesUser(self):
        self._reverseModes({('+i', None), ('l', 'asfasd')}, {('-i', None), ('-l', 'asfasd')},
                           target=self.irc.pseudoclient.uid)

    def testReverseModesExisting(self):
        utils.applyModes(self.irc, '#PyLink', [('+m', None), ('+l', '50'), ('+k', 'supersecret'),
                                             ('+o', '9PYAAAAAA')])

        self._reverseModes({('+i', None), ('+l', '3')}, {('-i', None), ('+l', '50')})
        self._reverseModes('-n', '+n')
        self._reverseModes('-l', '+l 50')
        self._reverseModes('+k derp', '+k supersecret')
        self._reverseModes('-mk *', '+mk supersecret')

        self.irc.proto.spawnClient("tester2")
        oldobj = deepcopy(self.irc.channels['#PyLink'])

        # Existing modes are ignored.
        self._reverseModes([('+t', None)], set())
        self._reverseModes('+n', '+')
        #self._reverseModes('+oo 9PYAAAAAB 9PYAAAAAA', '-o 9PYAAAAAB', oldobj=oldobj)
        self._reverseModes('+o 9PYAAAAAA', '+')
        self._reverseModes('+vM 9PYAAAAAA', '-M')

        # Ignore unsetting prefixmodes/list modes that were never set.
        self._reverseModes([('-v', '10XAAAAAA')], set())
        self._reverseModes('-ob 10XAAAAAA derp!*@*', '+')
        utils.applyModes(self.irc, '#PyLink', [('+b', '*!user@badisp.tk')])
        self._reverseModes('-bb *!*@* *!user@badisp.tk', '+b *!user@badisp.tk')

if __name__ == '__main__':
    unittest.main()
