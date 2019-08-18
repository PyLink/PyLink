import unittest

from pylinkirc.protocols import inspircd

import protocol_test_fixture as ptf

class InspIRCdProtocolTest(ptf.BaseProtocolTest):
    proto_class = inspircd.InspIRCdProtocol

    # In the future we will have protocol specific test cases here

if __name__ == '__main__':
    unittest.main()
