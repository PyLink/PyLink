"""
ngircd.py: PyLink protocol module for ngIRCd.
"""
##
# Server protocol docs for ngIRCd can be found at:
#     https://github.com/ngircd/ngircd/blob/master/doc/Protocol.txt
# and https://tools.ietf.org/html/rfc2813
##

import time
import re

from pylinkirc import utils, conf, __version__
from pylinkirc.classes import *
from pylinkirc.log import log
from pylinkirc.protocols.ircs2s_common import *

S2S_BUFSIZE = 510

class NgIRCdProtocol(IRCS2SProtocol):
    def __init__(self, irc):
        super().__init__(irc)

        self.conf_keys -= {'sid', 'sidrange'}
        self.casemapping = 'ascii'  # This is the default; it's actually set on server negotiation
        self.hook_map = {'NJOIN': 'JOIN'}

        # Track whether we've received end-of-burst from the uplink.
        self.has_eob = False

        self.uidgen = utils.PUIDGenerator("PUID")
        self._caps = {}
        self._use_builtin_005_handling = True

    ### Commands

    def post_connect(self):
        self.send('PASS %s 0210-IRC+ PyLink|%s:CHLMoX' % (self.serverdata['sendpass'], __version__))
        self.send("SERVER %s 1 :%s" % (self.serverdata['hostname'],
                                       self.serverdata.get('serverdesc') or conf.conf['pylink']['serverdesc']));
        self.sid = self.serverdata['hostname']

        self._caps.clear()

    def spawn_client(self, nick, ident='null', host='null', realhost=None, modes=set(),
            server=None, ip='0.0.0.0', realname=None, ts=None, opertype='IRC Operator',
            manipulatable=False):
        """
        Spawns a new client with the given options.

        Note: No nick collision / valid nickname checks are done here; it is
        up to plugins to make sure they don't introduce anything invalid.

        Note 2: IP and realhost are ignored because ngIRCd does not send them.
        """
        server = server or self.sid
        if not self.is_internal_server(server):
            raise ValueError('Server %r is not a PyLink server!' % server)

        realname = realname or conf.conf['bot']['realname']

        uid = self.uidgen.next_uid(prefix=nick)
        userobj = self.users[uid] = User(nick, ts, uid, server, ident=ident, host=host, realname=realname,
                                         manipulatable=manipulatable, opertype=opertype)

        self.apply_modes(uid, modes)
        self.servers[server].users.add(uid)

        # <- :ngircd.midnight.local NICK GL 1 ~gl localhost 1 +io :realname
        self._send_with_prefix(server, 'NICK %s 1 %s %s 1 %s :%s' % (nick, ident, host, self.join_modes(modes), realname))
        return userobj


    def spawn_server(self, name, sid=None, uplink=None, desc=None, endburst_delay=0):
        '''
        """
        Spawns a server off a PyLink server.

        * desc (server description) defaults to the one in the config.
        * uplink defaults to the main PyLink server.
        * SID is set equal to the server name for ngIRCd.
        """
        # -> :0AL SID test.server 1 0XY :some silly pseudoserver
        uplink = uplink or self.sid
        name = name.lower()

        desc = desc or self.serverdata.get('serverdesc') or conf.conf['bot']['serverdesc']

        if sid in self.servers:
            raise ValueError('A server named %r already exists!' % sid)

        if not self.is_internal_server(uplink):
            raise ValueError('Server %r is not a PyLink server!' % uplink)

        if not utils.isServerName(name):
            raise ValueError('Invalid server name %r' % name)


        self._send_with_prefix(uplink, 'SID %s 1 %s :%s' % (name, sid, desc))
        self.servers[sid] = Server(uplink, name, internal=True, desc=desc)
        return sid
        '''

    def join(self, client, channel):
        channel = self.to_lower(channel)
        if not self.is_internal_client(client):
            raise LookupError('No such PyLink client exists.')
        self._send_with_prefix(client, "JOIN %s" % channel)
        self.channels[channel].users.add(client)
        self.users[client].channels.add(channel)

    ### Handlers

    def handle_pass(self, source, command, args):
        """
        Handles phase one of the ngIRCd login process (password auth and version info).
        """
        # PASS is step one of server introduction, and is used to send the server info and password.
        # <- :ngircd.midnight.local PASS xyzpassword 0210-IRC+ ngIRCd|24~3-gbc728f92:CHLMSXZ PZ
        recvpass = args[0]
        if recvpass != self.serverdata['recvpass']:
            raise ProtocolError("RECVPASS from uplink does not match configuration!")

        assert 'IRC+' in args[1], "Linking to non-ngIRCd server using this protocol module is not supported"

    def handle_server(self, source, command, args):
        """
        Handles the SERVER command, used to introduce SID-less servers.
        """
        # <- :ngircd.midnight.local SERVER ngircd.midnight.local 1 :ngIRCd dev server
        servername = args[0].lower()
        serverdesc = args[-1]

        self.servers[servername] = Server(servername, servername, desc=serverdesc)

        if self.uplink is None:
            self.uplink = servername
            log.debug('(%s) Got %s as uplink', self.name, servername)
        else:
            # Only send the SERVER hook if this isn't the initial connection.
            return {'name': servername, 'sid': None, 'text': serverdesc}

    def handle_nick(self, source, command, args):
        # <- :ngircd.midnight.local NICK GL 1 ~gl localhost 1 +io :realname
        nick = args[0]
        assert source in self.servers, "Server %r tried to introduce nick %r but isn't in the servers index?" % (source, nick)

        ident = args[2]
        host = args[3]
        uid = self.uidgen.next_uid(prefix=nick)
        realname = args[-1]

        ts = int(time.time())
        self.users[uid] = User(nick, ts, uid, source, ident=ident, host=host, realname=realname)
        parsedmodes = self.parse_modes(uid, [args[5]])
        self.apply_modes(uid, parsedmodes)

        # Add the nick to the list of users on its server; this is used for SQUIT tracking
        self.servers[source].users.add(uid)

        return {'uid': uid, 'ts': ts, 'nick': nick, 'realhost': host, 'host': host, 'ident': ident,
                'parse_as': 'UID', 'ip': '0.0.0.0'}

    def handle_ping(self, source, command, args):
        if source == self.uplink:
            # Note: SID = server name here
            self._send_with_prefix(self.sid, 'PONG %s :%s' % (self.sid, args[-1]), queue=False)

            if not self.has_eob:
                # Treat the first PING we receive as end of burst.
                self.has_eob = True
                self.connected.set()

                # Return the endburst hook.
                return {'parse_as': 'ENDBURST'}

    def handle_376(self, source, command, args):
        # 376 is used to denote end of server negotiation - we send our info back at this point.
        # <- :ngircd.midnight.local 005 pylink-devel.int NETWORK=ngircd-test :is my network name
        # <- :ngircd.midnight.local 005 pylink-devel.int RFC2812 IRCD=ngIRCd CHARSET=UTF-8 CASEMAPPING=ascii PREFIX=(qaohv)~&@%+ CHANTYPES=#&+ CHANMODES=beI,k,l,imMnOPQRstVz CHANLIMIT=#&+:10 :are supported on this server
        # <- :ngircd.midnight.local 005 pylink-devel.int CHANNELLEN=50 NICKLEN=21 TOPICLEN=490 AWAYLEN=127 KICKLEN=400 MODES=5 MAXLIST=beI:50 EXCEPTS=e INVEX=I PENALTY :are supported on this server
        def f(numeric, msg):
            self._send_with_prefix(self.sid, '%s %s %s' % (numeric, self.uplink, msg))
        f('005', 'NETWORK=%s :is my network name' % self.get_full_network_name())
        f('005', 'RFC2812 IRCD=PyLink CHARSET=UTF-8 CASEMAPPING=%s PREFIX=%s CHANTYPES=# '
          'CHANMODES=%s,%s,%s,%s :are supported on this server' % (self.casemapping, self._caps['PREFIX'],
          self.cmodes['*A'], self.cmodes['*B'], self.cmodes['*C'], self.cmodes['*D']))
        f('005', 'CHANNELLEN NICKLEN=%s EXCEPTS=E INVEX=I :are supported on this server' % self.maxnicklen)

        # 376 (end of MOTD) marks the end of extended server negotiation per
        # https://github.com/ngircd/ngircd/blob/master/doc/Protocol.txt#L103-L112
        f('376', ":End of server negotiation, happy PyLink'ing!")

    def handle_chaninfo(self, source, command, args):
        # https://github.com/ngircd/ngircd/blob/722afc1b810cef74dbd2738d71866176fd974ec2/doc/Protocol.txt#L146-L159
        # CHANINFO has 3 styles depending on the amount of information applicable to a channel:
        #    CHANINFO <channel> +<modes>
        #    CHANINFO <channel> +<modes> <topic>
        #    CHANINFO <channel> +<modes> <key> <limit> <topic>
        # If there is no key, the key is "*". If there is no limit, the limit is "0".

        channel = self.to_lower(args[0])
        # Get rid of +l and +k in the initial parsing; we handle that later by looking at the CHANINFO arguments
        modes = self.parse_modes(channel, args[1].replace('l', '').replace('k', ''))

        if len(args) >= 3:
            topic = args[-1]
            if topic:
                log.debug('(%s) handle_chaninfo: setting topic for %s to %r', self.name, channel, topic)
                self.channels[channel].topic = topic
                self.channels[channel].topicset = True

        if len(args) >= 5:
            key = args[2]
            limit = args[3]
            if key != '*':
                modes.append(('+k', key))
            if limit != '0':
                modes.append(('+l', limit))

        self.apply_modes(channel, modes)

    def handle_njoin(self, source, command, args):
        # <- :ngircd.midnight.local NJOIN #test :tester,@%GL

        channel = self.to_lower(args[0])
        chandata = self.channels[channel].deepcopy()
        namelist = []

        # Reverse the modechar->modeprefix mapping for quicker lookup
        prefixchars = {v: k for k, v in self.prefixmodes.items()}
        for userpair in args[1].split(','):
            # Some regex magic to split the prefix from the nick.
            r = re.search(r'([%s]*)(.*)' % ''.join(self.prefixmodes.values()), userpair)
            user = self._get_UID(r.group(2))
            modeprefix = r.group(1)

            if modeprefix:
                modes = {('+%s' % prefixchars[mode], user) for mode in modeprefix}
                self.apply_modes(channel, modes)
            namelist.append(user)

            # Final bits of state tracking. (I hate having to do this everywhere...)
            self.users[user].channels.add(channel)
            self.channels[channel].users.add(user)

        return {'channel': channel, 'users': namelist, 'modes': [], 'channeldata': chandata}


Class = NgIRCdProtocol
