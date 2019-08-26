import unittest
import unittest.mock

from pylinkirc.protocols import clientbot
from pylinkirc.classes import User

import protocol_test_fixture as ptf

class ClientbotProtocolTest(ptf.BaseProtocolTest):
    proto_class = clientbot.ClientbotWrapperProtocol

    def setUp(self):
        super().setUp()
        self.p.pseudoclient = self._make_user('PyLink', uid='ClientbotInternal@0')

    def test_get_UID(self):
        u_internal = self._make_user('you', uid='100')
        check = lambda inp, expected: self.assertEqual(self.p._get_UID(inp), expected)

        # External clients are returned by the matcher
        with unittest.mock.patch.object(self.proto_class, 'is_internal_client', return_value=False) as m:
            check('you', '100')    # nick to UID
            check('YOu', '100')
            check('100', '100')    # already a UID
            check('Test', 'Test')  # non-existent

        # Internal clients are ignored
        with unittest.mock.patch.object(self.proto_class, 'is_internal_client', return_value=True) as m:
            check('you', 'you')
            check('YOu', 'YOu')
            check('100', '100')    # already a UID
            check('Test', 'Test')  # non-existent


    # In the future we will have protocol specific test cases here

if __name__ == '__main__':
    unittest.main()
