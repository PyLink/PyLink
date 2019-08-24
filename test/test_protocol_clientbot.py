import unittest

from pylinkirc.protocols import clientbot
from pylinkirc.classes import User

import protocol_test_fixture as ptf

class UnrealProtocolTest(ptf.BaseProtocolTest):
    proto_class = clientbot.ClientbotWrapperProtocol

    def setUp(self):
        super().setUp()
        self.p.pseudoclient = self._make_user('PyLink', uid='ClientbotInternal@0')

    # In the future we will have protocol specific test cases here

if __name__ == '__main__':
    unittest.main()
