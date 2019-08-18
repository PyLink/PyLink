import unittest

from pylinkirc.protocols import unreal

import protocol_test_fixture as ptf

class UnrealProtocolTest(ptf.BaseProtocolTest):
    proto_class = unreal.UnrealProtocol

    # In the future we will have protocol specific test cases here

if __name__ == '__main__':
    unittest.main()
