#!/usr/bin/env python

import inspircd
import unittest
import world
import coreplugin

import tests_common

world.testing = inspircd

class CorePluginTestCase(tests_common.PluginTestCase):
    @unittest.skip("Test doesn't work yet.")
    def testKillRespawn(self):
        self.irc.run(':9PY KILL {u} :test'.format(u=self.u))
        hooks = self.irc.takeHooks()

        # Make sure we're respawning our PseudoClient when its killed
        print(hooks)
        spmain = [h for h in hooks if h[1] == 'PYLINK_SPAWNMAIN']
        self.assertTrue(spmain, 'PYLINK_SPAWNMAIN hook was never sent!')

        msgs = self.irc.takeMsgs()
        commands = self.irc.takeCommands(msgs)
        self.assertIn('UID', commands)
        self.assertIn('FJOIN', commands)

        # Also make sure that we're updating the irc.pseudoclient field
        self.assertNotEqual(self.irc.pseudoclient.uid, spmain[0]['olduser'])

    def testKickrejoin(self):
        self.proto.kickClient(self.irc, self.u, '#pylink', self.u, 'test')
        msgs = self.irc.takeMsgs()
        commands = self.irc.takeCommands(msgs)
        self.assertIn('FJOIN', commands)
