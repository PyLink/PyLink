"""
A test fixture for PyLink protocol modules.
"""
import time
import unittest
import collections
import itertools
from unittest.mock import patch

from pylinkirc import conf, world
from pylinkirc.log import log
from pylinkirc.classes import User, Server, Channel

class DummySocket():
    def __init__(self):
        #self.recv_messages = collections.deque()
        self.sent_messages = collections.deque()

    @staticmethod
    def connect(address):
        return
    '''
    def recv(bufsize, *args):
        if self.recv_messages:
            data = self.recv_messages.popleft()
            print('<-', data)
            return data
        else:
            return None
    '''

    def recv(self, bufsize, *args):
        raise NotImplementedError

    def send(self, data):
        print('->', data)
        self.sent_messages.append(data)

class BaseProtocolTest(unittest.TestCase):
    proto_class = None
    netname = 'test'
    serverdata = conf.conf['servers'][netname]

    def setUp(self):
        if not self.proto_class:
            raise RuntimeError("Must set target protocol module in proto_class")
        self.p = self.proto_class(self.netname)

        # Stub connect() and the socket for now...
        self.p.connect = lambda self: None
        self.p.socket = DummySocket()

        if self.serverdata:
            self.p.serverdata = self.serverdata

    def _make_user(self, nick, uid, ts=None, sid=None, **kwargs):
        """
        Creates a user for testing.
        """
        if ts is None:
            ts = int(time.time())
        userobj = User(self.p, nick, ts, uid, sid, **kwargs)
        self.p.users[uid] = userobj
        return userobj

    ### STATEKEEPING FUNCTIONS

    def test_nick_to_uid(self):
        self.assertEqual(self.p.nick_to_uid('TestUser'), None)

        self._make_user('TestUser', 'testuid1')

        self.assertEqual(self.p.nick_to_uid('TestUser'), 'testuid1')
        self.assertEqual(self.p.nick_to_uid('TestUser', multi=True), ['testuid1'])
        self.assertEqual(self.p.nick_to_uid('BestUser'), None)
        self.assertEqual(self.p.nick_to_uid('RestUser', multi=True), [])

        self._make_user('TestUser', 'testuid2')
        self.assertEqual(self.p.nick_to_uid('TestUser', multi=True), ['testuid1', 'testuid2'])

    def test_is_internal(self):
        self.p.servers['internalserver'] = Server(self.p, None, 'internal.server', internal=True)
        self.p.sid = 'internalserver'
        self.p.servers['externalserver'] = Server(self.p, None, 'external.server', internal=False)

        iuser = self._make_user('someone', 'uid1', sid='internalserver')
        euser = self._make_user('sometwo', 'uid2', sid='externalserver')

        self.assertTrue(self.p.is_internal_server('internalserver'))
        self.assertFalse(self.p.is_internal_server('externalserver'))
        self.assertTrue(self.p.is_internal_client('uid1'))
        self.assertFalse(self.p.is_internal_client('uid2'))

    def test_is_manipulatable(self):
        self.p.servers['serv1'] = Server(self.p, None, 'myserv.local', internal=True)
        iuser = self._make_user('yes', 'uid1', sid='serv1', manipulatable=True)
        euser = self._make_user('no', 'uid2', manipulatable=False)

        self.assertTrue(self.p.is_manipulatable_client('uid1'))
        self.assertFalse(self.p.is_manipulatable_client('uid2'))

    def test_get_service_bot(self):
        self.assertFalse(self.p.get_service_bot('nonexistent'))

        regular_user = self._make_user('Guest12345', 'Guest12345@1')
        service_user = self._make_user('MyServ', 'MyServ@2')
        service_user.service = 'myserv'

        self.assertFalse(self.p.get_service_bot('Guest12345@1'))

        with patch.dict(world.services, {'myserv': 'myserv instance'}, clear=True):
            self.assertEqual(self.p.get_service_bot('MyServ@2'), 'myserv instance')

    def test_to_lower(self):
        check = lambda inp, expected: self.assertEqual(self.p.to_lower(inp), expected)
        check_unchanged = lambda inp: self.assertEqual(self.p.to_lower(inp), inp)

        check('BLAH!', 'blah!')
        check('BLAH!', 'blah!')  # since we memoize
        check_unchanged('zabcdefghijklmnopqrstuvwxy')
        check('123Xyz !@#$%^&*()-=+', '123xyz !@#$%^&*()-=+')

        if self.p.casemapping == 'rfc1459':
            check('hello [] {} |\\ ~^', 'hello [] [] \\\\ ^^')
            check('{Test Case}', '[test case]')
        else:
            check_unchanged('hello [] {} |\\ ~^')
            check('{Test Case}', '{test case}')

    def test_is_nick(self):
        assertT = lambda inp: self.assertTrue(self.p.is_nick(inp))
        assertF = lambda inp: self.assertFalse(self.p.is_nick(inp))

        assertT('test')
        assertT('PyLink')
        assertT('[bracketman]')
        assertT('{RACKETman}')
        assertT('bar|tender')
        assertT('\\bar|bender\\')
        assertT('jlu5|ovd')
        assertT('B')
        assertT('`')
        assertT('Hello123')
        assertT('test-')
        assertT('test-test')
        assertT('_jkl9')
        assertT('_-jkl9')

        assertF('')
        assertF('?')
        assertF('nick@network')
        assertF('Space flight')
        assertF(' ')
        assertF(' Space blight')
        assertF('0')
        assertF('-test')
        assertF('#lounge')
        assertF('\\bar/bender\\')
        assertF('jlu5/ovd') # Technically not valid, but some IRCds don't care ;)
        assertF('100AAAAAC') # TS6 UID

        self.assertFalse(self.p.is_nick('longnicklongnicklongnicklongnicklongnicklongnick', nicklen=20))
        self.assertTrue(self.p.is_nick('ninechars', nicklen=9))
        self.assertTrue(self.p.is_nick('ChanServ', nicklen=20))
        self.assertTrue(self.p.is_nick('leneight', nicklen=9))
        self.assertFalse(self.p.is_nick('bitmonster', nicklen=9))
        self.assertFalse(self.p.is_nick('ninecharsplus', nicklen=12))

    def test_is_channel(self):
        assertT = lambda inp: self.assertTrue(self.p.is_channel(inp))
        assertF = lambda inp: self.assertFalse(self.p.is_channel(inp))

        assertT('#test')
        assertT('#')
        assertT('#a#b#c')

        assertF('nick!user@host')
        assertF('&channel')  # we don't support these yet
        assertF('lorem ipsum')

    def test_is_server_name(self):
        self.assertTrue(self.p.is_server_name('test.local'))
        self.assertTrue(self.p.is_server_name('IRC.example.com'))
        self.assertTrue(self.p.is_server_name('services.'))
        self.assertFalse(self.p.is_server_name('.org'))
        self.assertFalse(self.p.is_server_name('bacon'))

    def test_is_hostmask(self):
        assertT = lambda inp: self.assertTrue(self.p.is_hostmask(inp))
        assertF = lambda inp: self.assertFalse(self.p.is_hostmask(inp))

        assertT('nick!user@host')
        assertT('abc123!~ident@ip1-2-3-4.example.net')

        assertF('brick!user')
        assertF('user@host')
        assertF('!@')
        assertF('!')
        assertF('@abcd')
        assertF('#channel')
        assertF('test.host')
        assertF('nick ! user @ host')
        assertF('alpha!beta@example.net#otherchan') # Janus workaround

    def test_get_SID(self):
        self.p.servers['serv1'] = Server(self.p, None, 'myserv.local', internal=True)

        check = lambda inp, expected: self.assertEqual(self.p._get_SID(inp), expected)
        check('myserv.local', 'serv1')
        check('MYSERV.local', 'serv1')
        check('serv1', 'serv1')
        check('other.server', 'other.server')

    def test_get_UID(self):
        u = self._make_user('you', uid='100')
        check = lambda inp, expected: self.assertEqual(self.p._get_UID(inp), expected)

        check('you', '100')    # nick to UID
        check('YOu', '100')
        check('100', '100')    # already a UID
        check('Test', 'Test')  # non-existent

    def test_get_hostmask(self):
        u = self._make_user('lorem', 'testUID', ident='ipsum', host='sit.amet')
        self.assertEqual(self.p.get_hostmask(u.uid), 'lorem!ipsum@sit.amet')

    def test_get_friendly_name(self):
        u = self._make_user('lorem', 'testUID', ident='ipsum', host='sit.amet')
        s = self.p.servers['mySID'] = Server(self.p, None, 'irc.example.org')
        c = self.p._channels['#abc'] = Channel('#abc')

        self.assertEqual(self.p.get_friendly_name(u.uid), 'lorem')
        self.assertEqual(self.p.get_friendly_name('#abc'), '#abc')
        self.assertEqual(self.p.get_friendly_name('mySID'), 'irc.example.org')

    # TODO: _squit wrapper

    ### MISC UTILS
    def test_get_service_option(self):
        f = self.p.get_service_option
        self.assertEqual(f('myserv', 'myopt'), None)  # No value anywhere
        self.assertEqual(f('myserv', 'myopt', default=0), 0)

        # Define global option
        with patch.dict(conf.conf, {'myserv': {'youropt': True, 'myopt': 1234}}):
            self.assertEqual(f('myserv', 'myopt'), 1234)  # Read global option

            # Both global and local options exist
            with patch.dict(self.p.serverdata, {'myserv_myopt': 2345}):
                self.assertEqual(f('myserv', 'myopt'), 2345)  # Read local option
                self.assertEqual(f('myserv', 'myopt', global_option='youropt'), 2345)

            # Custom global_option setting
            self.assertEqual(f('myserv', 'abcdef', global_option='youropt'), True)

        # Define local option
        with patch.dict(self.p.serverdata, {'myserv_myopt': 998877}):
            self.assertEqual(f('myserv', 'myopt'), 998877)  # Read local option
            self.assertEqual(f('myserv', 'myopt', default='unused'), 998877)

    def test_get_service_options_list(self):
        f = self.p.get_service_options
        self.assertEqual(f('myserv', 'items', list), [])  # No value anywhere

        # Define global option
        with patch.dict(conf.conf, {'myserv': {'items': [1, 10, 100], 'empty': []}}):
            self.assertEqual(f('myserv', 'items', list), [1, 10, 100])  # Global value only
            self.assertEqual(f('myserv', 'empty', list), [])

            # Both global and local options exist
            with patch.dict(self.p.serverdata, {'myserv_items': [2, 4, 6, 8], 'empty': []}):
                self.assertEqual(f('myserv', 'items', list), [1, 10, 100, 2, 4, 6, 8])
                # Custom global_option setting
                self.assertEqual(f('myserv', 'items', list, global_option='nonexistent'), [2, 4, 6, 8])
                self.assertEqual(f('myserv', 'empty', list), [])

        # Define local option
        with patch.dict(self.p.serverdata, {'myserv_items': [1, 0, 0, 3]}):
            self.assertEqual(f('myserv', 'items', list), [1, 0, 0, 3])  # Read local option

    def test_get_service_options_dict(self):
        f = self.p.get_service_options
        self.assertEqual(f('chanman', 'items', dict), {})  # No value anywhere

        # This is just mildly relevant test data, it's not actually used anywhere.
        globalopt = {'o': '@', 'v': '+', 'a': '!', 'h': '%'}
        localopt  = {'a': '&', 'q': '~'}
        # Define global option
        with patch.dict(conf.conf, {'chanman': {'prefixes': globalopt, 'empty': {}}}):
            self.assertEqual(f('chanman', 'prefixes', dict), globalopt)  # Global value only
            self.assertEqual(f('chanman', 'empty', dict), {})

            # Both global and local options exist
            with patch.dict(self.p.serverdata, {'chanman_prefixes': localopt, 'empty': {}}):
                self.assertEqual(f('chanman', 'prefixes', dict), {**globalopt, **localopt})

                self.assertEqual(f('chanman', 'items', dict), {})  # No value anywhere
                self.assertEqual(f('chanman', 'empty', dict), {})

        # Define local option
        with patch.dict(self.p.serverdata, {'chanman_prefixes': localopt}):
            self.assertEqual(f('chanman', 'prefixes', dict), localopt)  # Read local option

    ### MODE HANDLING
    def test_parse_modes_channel_rfc(self):
        # These are basic tests that only use RFC 1459 defined modes.
        # IRCds supporting more complex modes can define new test cases if needed.
        u = self._make_user('testuser', uid='100')

        c = self.p.channels['#testruns'] = Channel(self.p, name='#testruns')

        self.assertEqual(
            self.p.parse_modes('#testruns', ['+m']),
            [('+m', None)]
        )
        self.assertEqual(
            self.p.parse_modes('#testruns', ['+l', '3']),
            [('+l', '3')]
        )
        self.assertEqual(
            self.p.parse_modes('#testruns', ['+ntl', '59']),
            [('+n', None), ('+t', None), ('+l', '59')]
        )
        self.assertEqual(
            self.p.parse_modes('#testruns', ['+k-n', 'test']),
            [('+k', 'test'), ('-n', None)]
        )

        self.assertEqual(
            self.p.parse_modes('#testruns', ['+o', '102']),  # unknown UID
            []
        )

        c.users.add(u)
        u.channels.add(c)

        self.assertEqual(
            self.p.parse_modes('#testruns', ['+o', '100']),
            [('+o', '100')]
        )
        self.assertEqual(
            self.p.parse_modes('#testruns', ['+vip', '100']),
            [('+v', '100'), ('+i', None), ('+p', None)]
        )

    def test_parse_modes_channel_rfc2(self):
        # These are basic tests that only use RFC 1459 defined modes.
        # IRCds supporting more complex modes can define new test cases if needed.
        c = self.p.channels['#testruns'] = Channel(self.p, name='#testruns')

        # Note: base case is not defined and raises AssertionError

        self.assertEqual(
            self.p.parse_modes('#testruns', ['+m']),   # add modes
            [('+m', None)]
        )
        self.assertEqual(
            self.p.parse_modes('#testruns', ['-tn']),  # remove modes
            [('-t', None), ('-n', None)]
        )
        self.assertEqual(
            self.p.parse_modes('#TESTRUNS', ['-tn']),  # different case target
            [('-t', None), ('-n', None)]
        )
        self.assertEqual(
            self.p.parse_modes('#testruns', ['+l', '3']),  # modes w/ arguments
            [('+l', '3')]
        )
        self.assertEqual(
            self.p.parse_modes('#testruns', ['+nlt', '59']),  # combination
            [('+n', None), ('+l', '59'), ('+t', None)]
        )
        self.assertEqual(
            self.p.parse_modes('#testruns', ['+k-n', 'test']),  # swapping +/-
            [('+k', 'test'), ('-n', None)]
        )
        self.assertEqual(
            self.p.parse_modes('#testruns', ['n-s']),  # sloppy syntax
            [('+n', None), ('-s', None)]
        )
        self.assertEqual(
            self.p.parse_modes('#testruns', ['+bmi', '*!test@example.com']),
            [('+b', '*!test@example.com'), ('+m', None), ('+i', None)]
        )

    def test_parse_modes_prefixmodes_rfc(self):
        c = self.p.channels['#testruns'] = Channel(self.p, name='#testruns')
        self.assertEqual(
            self.p.parse_modes('#testruns', ['+ov', '102', '101']),  # unknown UIDs are ignored
            []
        )
        u = self._make_user('test100', uid='100')
        c.users.add(u)
        u.channels.add(c)

        self.assertEqual(
            self.p.parse_modes('#testruns', ['+o', '100']),
            [('+o', '100')]
        )
        self.assertEqual(
            self.p.parse_modes('#testruns', ['+vip', '100']),
            [('+v', '100'), ('+i', None), ('+p', None)]
        )
        self.assertEqual(
            self.p.parse_modes('#testruns', ['-o+bn', '100', '*!test@example.com']),
            [('-o', '100'), ('+b', '*!test@example.com'), ('+n', None)]
        )
        self.assertEqual(
            # 2nd user missing
            self.p.parse_modes('#testruns', ['+oovv', '100', '102', '100', '102']),
            [('+o', '100'), ('+v', '100')]
        )

        u2 = self._make_user('test102', uid='102')
        c.users.add(u2)
        u2.channels.add(c)

        self.assertEqual(
            # two users interleaved
            self.p.parse_modes('#testruns', ['+oovv', '100', '102', '100', '102']),
            [('+o', '100'), ('+o', '102'), ('+v', '100'), ('+v', '102')]
        )

        self.assertEqual(
            # Mode cycle
            self.p.parse_modes('#testruns', ['+o-o', '100', '100']),
            [('+o', '100'), ('-o', '100')]
        )

    def test_parse_modes_channel_ban_complex(self):
        c = self.p.channels['#testruns'] = Channel(self.p, name='#testruns')
        self.assertEqual(
            # add first ban, but don't remove second because it doesn't exist
            self.p.parse_modes('#testruns', ['+b-b', '*!*@test1', '*!*@test2']),
            [('+b', '*!*@test1')],
            "First ban should have been added, and second ignored"
        )
        self.p.apply_modes('#testruns', [('+b', '*!*@test1')])
        self.assertEqual(
            # remove first ban because it matches case
            self.p.parse_modes('#testruns', ['-b', '*!*@test1']),
            [('-b', '*!*@test1')],
            "First ban should have been removed (same case)"
        )
        self.assertEqual(
            # remove first ban despite different case
            self.p.parse_modes('#testruns', ['-b', '*!*@TEST1']),
            [('-b', '*!*@test1')],
            "First ban should have been removed (different case)"
        )
        self.p.apply_modes('#testruns', [('+b', '*!*@Test2')])
        self.assertEqual(
            # remove second ban despite different case
            self.p.parse_modes('#testruns', ['-b', '*!*@test2']),
            [('-b', '*!*@Test2')],
            "Second ban should have been removed (different case)"
        )

    def test_parse_modes_channel_ban_cycle(self):
        c = self.p.channels['#testruns'] = Channel(self.p, name='#testruns')
        self.assertEqual(
            self.p.parse_modes('#testruns', ['+b-b', '*!*@example.com', '*!*@example.com']),
            [('+b', '*!*@example.com'), ('-b', '*!*@example.com')],
            "Cycling a ban +b-b should remove it"
        )
        self.assertEqual(
            self.p.parse_modes('#testruns', ['-b+b', '*!*@example.com', '*!*@example.com']),
            [('+b', '*!*@example.com')],
            "Cycling a ban -b+b should add it"
        )
        self.assertEqual(
            self.p.parse_modes('#testruns', ['+b-b', '*!*@example.com', '*!*@Example.com']),
            [('+b', '*!*@example.com'), ('-b', '*!*@example.com')],
            "Cycling a ban +b-b should remove it (different case)"
        )
        self.assertEqual(
            self.p.parse_modes('#testruns', ['+b-b', '*!*@Example.com', '*!*@example.com']),
            [('+b', '*!*@Example.com'), ('-b', '*!*@Example.com')],
            "Cycling a ban +b-b should remove it (different case)"
        )

    def test_parse_modes_channel_prefixmode_has_nick(self):
        c = self.p.channels['#'] = Channel(self.p, name='#')
        u = self._make_user('mynick', uid='myuid')
        c.users.add(u)
        u.channels.add(c)

        self.assertEqual(
            self.p.parse_modes('#', ['+o', 'myuid']),
            [('+o', 'myuid')],
            "+o on UID should be registered"
        )
        self.assertEqual(
            self.p.parse_modes('#', ['+o', 'mynick']),
            [('+o', 'myuid')],
            "+o on nick should be registered"
        )
        self.assertEqual(
            self.p.parse_modes('#', ['+o', 'MyUiD']),
            [],
            "+o on wrong case UID should be ignored"
        )
        self.assertEqual(
            self.p.parse_modes('#', ['+o', 'MyNick']),
            [('+o', 'myuid')],
            "+o on different case nick should be registered"
        )

        self.assertEqual(
            self.p.parse_modes('#', ['-o', 'myuid']),
            [('-o', 'myuid')],
            "-o on UID should be registered"
        )
        self.assertEqual(
            self.p.parse_modes('#', ['-o', 'mynick']),
            [('-o', 'myuid')],
            "-o on nick should be registered"
        )

    # TODO: check the output of parse_modes() here too
    def test_parse_modes_channel_key(self):
        c = self.p.channels['#pylink'] = Channel(self.p, name='#pylink')
        c.modes = {('k', 'foobar')}

        modes = self.p.parse_modes('#pylink', ['-k', 'foobar'])
        self.assertEqual(modes, [('-k', 'foobar')], "Parse result should include -k")

        modes = self.p.parse_modes('#pylink', ['-k', 'aBcDeF'])
        self.assertEqual(modes, [], "Incorrect key removal should be ignored")

        modes = self.p.parse_modes('#pylink', ['+k', 'aBcDeF'])
        self.assertEqual(modes, [('+k', 'aBcDeF')], "Parse result should include +k (replace key)")

        # Mismatched case - treat this as remove
        # Some IRCds allow this (Unreal, P10), others do not (InspIRCd). However, if such a message
        # makes actually its way to us it is most likely valid.
        # Note: Charybdis and ngIRCd do -k * removal instead so this case will never happen there
        modes = self.p.parse_modes('#pylink', ['-k', 'FooBar'])
        self.assertEqual(modes, [('-k', 'foobar')], "Parse result should include -k (different case)")

        modes = self.p.parse_modes('#pylink', ['-k', '*'])
        self.assertEqual(modes, [('-k', 'foobar')], "Parse result should include -k (-k *)")

    def test_parse_modes_user_rfc(self):
        u = self._make_user('testuser', uid='100')

        self.assertEqual(
            self.p.parse_modes('100', ['+i-w+x']),
            [('+i', None), ('-w', None), ('+x', None)]
        )
        self.assertEqual(
            # Sloppy syntax, but OK
            self.p.parse_modes('100', ['wx']),
            [('+w', None), ('+x', None)]
        )

    def test_apply_modes_channel_simple(self):
        c = self.p.channels['#'] = Channel(self.p, name='#')

        self.p.apply_modes('#', [('+m', None)])
        self.assertEqual(c.modes, {('m', None)})

        self.p.apply_modes('#', [])  # No-op
        self.assertEqual(c.modes, {('m', None)})

        self.p.apply_modes('#', [('-m', None)])
        self.assertFalse(c.modes)  # assert is empty

    def test_apply_modes_channel_add_remove(self):
        c = self.p.channels['#'] = Channel(self.p, name='#')

        self.p.apply_modes('#', [('+i', None)])
        self.assertEqual(c.modes, {('i', None)})

        self.p.apply_modes('#', [('+n', None), ('-i', None)])
        self.assertEqual(c.modes, {('n', None)})

        c = self.p.channels['#Magic'] = Channel(self.p, name='#Magic')
        self.p.apply_modes('#Magic', [('+m', None), ('+n', None), ('+i', None)])
        self.assertEqual(c.modes, {('m', None), ('n', None), ('i', None)}, "Modes should be added")

        self.p.apply_modes('#Magic', [('-i', None), ('-n', None)])
        self.assertEqual(c.modes, {('m', None)}, "Modes should be removed")

    def test_apply_modes_channel_remove_nonexistent(self):
        c = self.p.channels['#abc'] = Channel(self.p, name='#abc')
        self.p.apply_modes('#abc', [('+t', None)])
        self.assertEqual(c.modes, {('t', None)})

        self.p.apply_modes('#abc', [('-n', None), ('-i', None)])
        self.assertEqual(c.modes, {('t', None)})

    def test_apply_modes_channel_limit(self):
        c = self.p.channels['#abc'] = Channel(self.p, name='#abc')
        self.p.apply_modes('#abc', [('+t', None), ('+l', '30')])
        self.assertEqual(c.modes, {('t', None), ('l', '30')})

        self.p.apply_modes('#abc', [('+l', '55')])
        self.assertEqual(c.modes, {('t', None), ('l', '55')})

        self.p.apply_modes('#abc', [('-l', None)])
        self.assertEqual(c.modes, {('t', None)})

    def test_apply_modes_channel_key(self):
        c = self.p.channels['#pylink'] = Channel(self.p, name='#pylink')
        self.p.apply_modes('#pylink', [('+k', 'password123'), ('+s', None)])
        self.assertEqual(c.modes, {('s', None), ('k', 'password123')})

        self.p.apply_modes('#pylink', [('+k', 'qwerty')])
        self.assertEqual(c.modes, {('s', None), ('k', 'qwerty')})

        self.p.apply_modes('#pylink', [('-k', 'abcdef')])
        # Trying to remove with wrong key is a no-op
        self.assertEqual(c.modes, {('s', None), ('k', 'qwerty')})

        self.p.apply_modes('#pylink', [('-k', 'qwerty')])
        self.assertEqual(c.modes, {('s', None)})

        self.p.apply_modes('#pylink', [('+k', 'qwerty')])
        self.assertEqual(c.modes, {('s', None), ('k', 'qwerty')})
        self.p.apply_modes('#pylink', [('-k', 'QWERTY')])  # Remove with different case
        self.assertEqual(c.modes, {('s', None)})

        self.p.apply_modes('#pylink', [('+k', '12345')])  # Replace existing key
        self.assertEqual(c.modes, {('s', None), ('k', '12345')})

    def test_apply_modes_channel_ban(self):
        c = self.p.channels['#Magic'] = Channel(self.p, name='#Magic')
        self.p.apply_modes('#Magic', [('+b', '*!*@test.host'), ('+b', '*!*@best.host')])
        self.assertEqual(c.modes, {('b', '*!*@test.host'), ('b', '*!*@best.host')}, "Bans should be added")

        # This should be a no-op
        self.p.apply_modes('#Magic', [('-b', '*!*non-existent')])
        self.assertEqual(c.modes, {('b', '*!*@test.host'), ('b', '*!*@best.host')}, "Trying to unset non-existent ban should be no-op")

        # Simple removal
        self.p.apply_modes('#Magic', [('-b', '*!*@test.host')])
        self.assertEqual(c.modes, {('b', '*!*@best.host')}, "Ban on *!*@test.host be removed (same case as original)")

        # Removal but different case than original
        self.p.apply_modes('#Magic', [('-b', '*!*@BEST.HOST')])
        self.assertFalse(c.modes, "Ban on *!*@best.host should be removed (different case)")

    def test_apply_modes_channel_ban_multiple(self):
        c = self.p.channels['#Magic'] = Channel(self.p, name='#Magic')
        self.p.apply_modes('#Magic', [('+b', '*!*@test.host'), ('+b', '*!*@best.host'), ('+b', '*!*@guest.host')])
        self.assertEqual(c.modes, {('b', '*!*@test.host'), ('b', '*!*@best.host'), ('b', '*!*@guest.host')},
                         "Bans should be added")

        self.p.apply_modes('#Magic', [('-b', '*!*@best.host'), ('-b', '*!*@guest.host'), ('-b', '*!*@test.host')])
        self.assertEqual(c.modes, set(), "Bans should be removed")

    def test_apply_modes_channel_mode_cycle(self):
        c = self.p.channels['#Magic'] = Channel(self.p, name='#Magic')
        self.p.apply_modes('#Magic', [('+b', '*!*@example.net'), ('-b', '*!*@example.net')])
        self.assertEqual(c.modes, set(), "Ban should have been removed (same case)")

        self.p.apply_modes('#Magic', [('+b', '*!*@example.net'), ('-b', '*!*@Example.net')])
        self.assertEqual(c.modes, set(), "Ban should have been removed (different case)")

        u = self._make_user('nick', uid='user')
        c.users.add(u.uid)
        u.channels.add(c)

        self.p.apply_modes('#Magic', [('+o', 'user'), ('-o', 'user')])
        self.assertEqual(c.modes, set(), "No prefixmodes should have been set")
        self.assertFalse(c.is_op('user'))
        self.assertFalse(c.get_prefix_modes('user'))

    def test_apply_modes_channel_prefixmodes(self):
        # Make some users
        c = self.p.channels['#staff'] = Channel(self.p, name='#staff')
        u1 = self._make_user('user100', uid='100')
        u2 = self._make_user('user101', uid='101')
        c.users.add(u1.uid)
        u1.channels.add(c)
        c.users.add(u2.uid)
        u2.channels.add(c)

        # Set modes
        self.p.apply_modes('#staff', [('+o', '100'), ('+v', '101'), ('+t', None)])
        self.assertEqual(c.modes, {('t', None)})

        # State checks, lots of them... TODO: move this into Channel class tests
        self.assertTrue(c.is_op('100'))
        self.assertTrue(c.is_op_plus('100'))
        self.assertFalse(c.is_halfop('100'))
        self.assertTrue(c.is_halfop_plus('100'))
        self.assertFalse(c.is_voice('100'))
        self.assertTrue(c.is_voice_plus('100'))
        self.assertEqual(c.get_prefix_modes('100'), ['op'])

        self.assertTrue(c.is_voice('101'))
        self.assertTrue(c.is_voice_plus('101'))
        self.assertFalse(c.is_halfop('101'))
        self.assertFalse(c.is_halfop_plus('101'))
        self.assertFalse(c.is_op('101'))
        self.assertFalse(c.is_op_plus('101'))
        self.assertEqual(c.get_prefix_modes('101'), ['voice'])

        self.assertFalse(c.prefixmodes['owner'])
        self.assertFalse(c.prefixmodes['admin'])
        self.assertEqual(c.prefixmodes['op'], {'100'})
        self.assertFalse(c.prefixmodes['halfop'])
        self.assertEqual(c.prefixmodes['voice'], {'101'})

        self.p.apply_modes('#staff', [('-o', '100')])
        self.assertEqual(c.modes, {('t', None)})
        self.assertFalse(c.get_prefix_modes('100'))
        self.assertEqual(c.get_prefix_modes('101'), ['voice'])

    def test_apply_modes_user(self):
        u = self._make_user('nick', uid='user')
        self.p.apply_modes('user', [('+o', None), ('+w', None)])
        self.assertEqual(u.modes, {('o', None), ('w', None)})
        self.p.apply_modes('user', [('-o', None), ('+i', None)])
        self.assertEqual(u.modes, {('i', None), ('w', None)})

    def test_reverse_modes_simple(self):
        c = self.p.channels['#foobar'] = Channel(self.p, name='#foobar')
        c.modes = {('m', None), ('n', None)}

        # This function supports both strings and mode lists

        # Base cases
        for inp in {'', '+', '-'}:
            self.assertEqual(self.p.reverse_modes('#foobar', inp), '+')
        out = self.p.reverse_modes('#foobar', [])
        self.assertEqual(out, [])

        # One simple
        out = self.p.reverse_modes('#foobar', '+t')
        self.assertEqual(out, '-t')
        out = self.p.reverse_modes('#foobar', [('+t', None)])
        self.assertEqual(out, [('-t', None)])

        out = self.p.reverse_modes('#foobar', '+m')
        self.assertEqual(out, '+', 'Calling reverse_modes() on an already set mode is a no-op')

        out = self.p.reverse_modes('#foobar', [('+m', None)])
        self.assertEqual(out, [], 'Calling reverse_modes() on an already set mode is a no-op')

        out = self.p.reverse_modes('#foobar', [('-i', None)])
        self.assertEqual(out, [], 'Calling reverse_modes() on non-existent mode is a no-op')

    def test_reverse_modes_multi(self):
        c = self.p.channels['#foobar'] = Channel(self.p, name='#foobar')
        c.modes = {('t', None), ('n', None)}

        # reverse_modes should ignore modes that were already set
        out = self.p.reverse_modes('#foobar', '+nt')
        self.assertEqual(out, '+')

        out = self.p.reverse_modes('#foobar', [('+m', None), ('+i', None)])
        self.assertEqual(out, [('-m', None), ('-i', None)])

        out = self.p.reverse_modes('#foobar', '+mint')
        self.assertEqual(out, '-mi')  # Ignore +nt since it already exists

        out = self.p.reverse_modes('#foobar', '+m-t')
        self.assertEqual(out, '-m+t')

        out = self.p.reverse_modes('#foobar', '+mn-t')
        self.assertEqual(out, '-m+t')

        out = self.p.reverse_modes('#foobar', [('+m', None), ('+n', None), ('-t', None)])
        self.assertEqual(out, [('-m', None), ('+t', None)])

    def test_reverse_modes_bans(self):
        c = self.p.channels['#foobar'] = Channel(self.p, name='#foobar')
        c.modes = {('t', None), ('n', None), ('b', '*!*@example.com')}

        out = self.p.reverse_modes('#foobar', [('+b', '*!*@test')])
        self.assertEqual(out, [('-b', '*!*@test')], "non-existent ban should be removed")
        out = self.p.reverse_modes('#foobar', '+b *!*@example.com')
        self.assertEqual(out, '+', "+b existing ban should be no-op")

        out = self.p.reverse_modes('#foobar', '+b *!*@Example.com')
        self.assertEqual(out, '+', "Should ignore attempt to change case of ban mode")

        out = self.p.reverse_modes('#foobar', '-b *!*@example.com')
        self.assertEqual(out, '+b *!*@example.com', "-b existing ban should reset it")

        out = self.p.reverse_modes('#foobar', '-b *!*@Example.com')
        self.assertEqual(out, '+b *!*@example.com', "-b existing ban should reset it using original case")

        out = self.p.reverse_modes('#foobar', '-b *!*@*')
        self.assertEqual(out, '+', "Removing non-existent ban is no-op")

        out = self.p.reverse_modes('#foobar', '+bbbm 1 2 3')
        self.assertEqual(out, '-bbbm 1 2 3')

    def test_reverse_modes_limit(self):
        c = self.p.channels['#foobar'] = Channel(self.p, name='#foobar')
        c.modes = {('t', None), ('n', None), ('l', '50')}

        out = self.p.reverse_modes('#foobar', [('+l', '100')])
        self.assertEqual(out, [('+l', '50')], "Setting +l should reset original mode")

        out = self.p.reverse_modes('#foobar', [('-l', None)])
        self.assertEqual(out, [('+l', '50')], "Unsetting +l should reset original mode")

        out = self.p.reverse_modes('#foobar', [('+l', '50')])
        self.assertEqual(out, [], "Setting +l with original value is no-op")

        c.modes.clear()
        out = self.p.reverse_modes('#foobar', [('+l', '111'), ('+m', None)])
        self.assertEqual(out, [('-l', None), ('-m', None)], "Setting +l on channel without it should remove")

    def test_reverse_modes_prefixmodes(self):
        c = self.p.channels['#foobar'] = Channel(self.p, name='#foobar')
        c.modes = {('t', None), ('n', None)}
        u = self._make_user('nick', uid='user')
        u.channels.add(c)
        c.users.add(u)
        c.prefixmodes['op'].add(u.uid)

        out = self.p.reverse_modes('#foobar', '-o user')
        self.assertEqual(out, '+o user')
        out = self.p.reverse_modes('#foobar', '+o user')
        self.assertEqual(out, '+')
        out = self.p.reverse_modes('#foobar', '+ov user user')
        self.assertEqual(out, '-v user')  # ignore +o
        out = self.p.reverse_modes('#foobar', '-ovt user user')
        self.assertEqual(out, '+ot user')  # ignore -v

    def test_reverse_modes_cycle_simple(self):
        c = self.p.channels['#weirdstuff'] = Channel(self.p, name='#weirdstuff')
        c.modes = {('t', None), ('n', None)}

        out = self.p.reverse_modes('#weirdstuff', '+n-n')  # +- cycle existing mode
        self.assertEqual(out, '+n')
        out = self.p.reverse_modes('#weirdstuff', '-n+n')  # -+ cycle existing mode
        self.assertEqual(out, '+n')  # Ugly but OK

        out = self.p.reverse_modes('#weirdstuff', '+m-m')  # +- cycle non-existent mode
        self.assertEqual(out, '-m')
        out = self.p.reverse_modes('#weirdstuff', '-m+m')  # -+ cycle non-existent mode
        self.assertEqual(out, '-m')  # Ugly but OK

    def test_reverse_modes_cycle_bans(self):
        c = self.p.channels['#weirdstuff'] = Channel(self.p, name='#weirdstuff')
        c.modes = {('t', None), ('n', None), ('b', '*!*@test.host')}

        out = self.p.reverse_modes('#weirdstuff', '+b-b *!*@test.host *!*@test.host')  # +- cycle existing ban
        self.assertEqual(out, '+b *!*@test.host')
        out = self.p.reverse_modes('#weirdstuff', '-b+b *!*@test.host *!*@test.host')  # -+ cycle existing ban
        self.assertEqual(out, '+b *!*@test.host')  # Ugly but OK

        out = self.p.reverse_modes('#weirdstuff', '+b-b *!*@* *!*@*')  # +- cycle existing ban
        self.assertEqual(out, '-b *!*@*')
        out = self.p.reverse_modes('#weirdstuff', '-b+b *!*@* *!*@*')  # -+ cycle existing ban
        self.assertEqual(out, '-b *!*@*')  # Ugly but OK

    def test_reverse_modes_cycle_arguments(self):
        # All of these cases are ugly, sometimes unsetting modes that don't exist...
        c = self.p.channels['#weirdstuff'] = Channel(self.p, name='#weirdstuff')

        out = self.p.reverse_modes('#weirdstuff', '+l-l 30')
        self.assertEqual(out, '-l')
        out = self.p.reverse_modes('#weirdstuff', '-l+l 30')
        self.assertEqual(out, '-l')

        out = self.p.reverse_modes('#weirdstuff', '+k-k aaaaaaaaaaaa aaaaaaaaaaaa')
        self.assertEqual(out, '-k aaaaaaaaaaaa')
        out = self.p.reverse_modes('#weirdstuff', '-k+k aaaaaaaaaaaa aaaaaaaaaaaa')
        self.assertEqual(out, '-k aaaaaaaaaaaa')

        c.modes = {('l', '555'), ('k', 'NO-PLEASE')}
        out = self.p.reverse_modes('#weirdstuff', '+l-l 30')
        self.assertEqual(out, '+l 555')
        out = self.p.reverse_modes('#weirdstuff', '-l+l 30')
        self.assertEqual(out, '+l 555')

        out = self.p.reverse_modes('#weirdstuff', '+k-k aaaaaaaaaaaa aaaaaaaaaaaa')
        self.assertEqual(out, '+k NO-PLEASE')
        out = self.p.reverse_modes('#weirdstuff', '-k+k aaaaaaaaaaaa aaaaaaaaaaaa')
        self.assertEqual(out, '+k NO-PLEASE')

    def test_reverse_modes_cycle_prefixmodes(self):
        # All of these cases are ugly, sometimes unsetting modes that don't exist...
        c = self.p.channels['#weirdstuff'] = Channel(self.p, name='#weirdstuff')
        u = self._make_user('nick', uid='user')
        u.channels.add(c)
        c.users.add(u)

        # user not already opped
        out = self.p.reverse_modes('#weirdstuff', '+o-o user user')
        self.assertEqual(out, '-o user')
        out = self.p.reverse_modes('#weirdstuff', '-o+o user user')
        self.assertEqual(out, '-o user')

        c.prefixmodes['op'].add(u.uid)

        # user was opped
        out = self.p.reverse_modes('#weirdstuff', '+o-o user user')
        self.assertEqual(out, '+o user')
        out = self.p.reverse_modes('#weirdstuff', '-o+o user user')
        self.assertEqual(out, '+o user')

    def test_join_modes(self):
        # join_modes operates independently of state; the input just has to be valid modepairs
        check = lambda inp, expected, sort=False: self.assertEqual(self.p.join_modes(inp, sort=sort), expected)

        check([], '+')  # base case

        check([('+b', '*!*@test')], '+b *!*@test')
        check([('-S', None)], '-S')
        check([('+n', None), ('+t', None)], '+nt')
        check([('+t', None), ('+n', None)], '+tn')
        check([('+t', None), ('+n', None)], '+nt', sort=True)

        check([('-n', None), ('-s', None)], '-ns')

        check([('+q', '*'), ('-q', '*')], '+q-q * *')
        check([('+l', '5'), ('-n', None), ('+R', None)], '+l-n+R 5')

        # Sloppy syntax: assume leading mode is + if not otherwise stated
        check([('o', '100AAAAAC'), ('m', None), ('-v', '100AAAAAC')], '+om-v 100AAAAAC 100AAAAAC')

    def test_wrap_modes_small(self):
        # wrap_modes is also state independent; it only calls join_modes

        N_USERS = 5
        modes = [('+m', None)] + [('-b', 'user%s!*@example.org' % num) for num in range(N_USERS)]
        wr = self.p.wrap_modes(modes, 200)
        log.debug('wrap_modes input: %s', modes)
        log.debug('wrap_modes output: %s', wr)

        self.assertEqual(len(wr), 1)  # no split should have occurred
        self.assertEqual(wr[0], self.p.join_modes(modes))

    def test_wrap_modes_split_length_limit(self):
        # wrap_modes is also state independent; it only calls join_modes
        N_USERS = 50

        modes = [('+o', 'user%s' % num) for num in range(N_USERS)]
        wr = self.p.wrap_modes(modes, 120)
        log.debug('wrap_modes input: %s', modes)
        log.debug('wrap_modes output: %s', wr)

        self.assertTrue(len(wr) > 1)  # we should have induced a split

        for s in wr:
            # Check that each split item starts with the right mode char
            self.assertTrue(s.startswith('+oooo'))

        all_args = itertools.chain.from_iterable(s.split() for s in wr)
        for num in range(N_USERS):
            # Check that no users are missing
            self.assertIn('user%s' % num, all_args)

    def test_wrap_modes_split_max_modes(self):
        # wrap_modes is also state independent; it only calls join_modes
        N_USERS = 50
        N_MAX_PER_MSG = 8

        modes = [('+v', 'user%s' % num) for num in range(N_USERS)]
        wr = self.p.wrap_modes(modes, 200, N_MAX_PER_MSG)
        log.debug('wrap_modes input: %s', modes)
        log.debug('wrap_modes output: %s', wr)

        self.assertTrue(len(wr) > 1)  # we should have induced a split

        splits = [s.split() for s in wr]
        for s in splits:
            # Check that each message sets <= N_MAX_PER_MSG modes
            self.assertTrue(len(s[0]) <= (N_MAX_PER_MSG + 1))  # add 1 to account for leading +
            self.assertTrue(s[0].startswith('+'))
            self.assertTrue(s[0].endswith('v'))

        all_args = itertools.chain.from_iterable(splits)
        for num in range(N_USERS):
            # Check that no users are missing
            self.assertIn('user%s' % num, all_args)

    # TODO: test type coersion if channel or mode targets are ints
