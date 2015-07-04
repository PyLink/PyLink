import sys
import os
sys.path += [os.getcwd(), os.path.join(os.getcwd(), 'protocols')]
import unittest

import inspircd
import test_proto_common
from classes import ProtocolError

class TestInspIRCdProtocol(unittest.TestCase):
    def setUp(self):
        self.irc = test_proto_common.FakeIRC(inspircd)
        self.sdata = self.irc.serverdata
        
    def test_connect(self):
        self.irc.proto.connect(self.irc)
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

if __name__ == '__main__':
    unittest.main()
