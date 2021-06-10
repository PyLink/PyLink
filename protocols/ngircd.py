"""
ngircd.py: PyLink protocol module for ngIRCd.
"""
##
# Server protocol docs for ngIRCd can be found at:
#     https://github.com/ngircd/ngircd/blob/master/doc/Protocol.txt
# and https://tools.ietf.org/html/rfc2813
##

import re
import time

from pylinkirc import __version__, conf, utils
from pylinkirc.classes import *
from pylinkirc.log import log
from pylinkirc.protocols.ircs2s_common import *

__all__ = ['NgIRCdProtocol']


class NgIRCdProtocol(IRCS2SProtocol):
    def __init__(self, irc):
        super().__init__(irc)

        self.conf_keys -= {'sid', 'sidrange'}
        self.casemapping = 'ascii'  # This is the default; it's actually set on server negotiation
        self.hook_map = {'NJOIN': 'JOIN'}

        # Track whether we've received end-of-burst from the uplink.
        self.has_eob = False

        self._caps = {}
        self._use_builtin_005_handling = True

        # ngIRCd has no TS tracking.
        self.protocol_caps.discard('has-ts')

        # Slash in nicks is problematic; while it works for basic things like JOIN and messages,
        # attempts to set user modes fail.
        self.protocol_caps |= {'slash-in-hosts', 'underscore-in-hosts'}

    ### Commands

    def post_connect(self):
        self.send('PASS %s 0210-IRC+ PyLink|%s:CHLMoX' % (self.serverdata['sendpass'], __version__))

        # Note: RFC 2813 mandates another server token value after the hopcount (1), but ngIRCd
        # doesn't follow that behaviour per https://github.com/ngircd/ngircd/issues/224
        self.send("SERVER %s 1 :%s" % (self.serverdata['hostname'],
                                       self.serverdata.get('serverdesc') or conf.conf['pylink']['serverdesc']))

        self._uidgen = PUIDGenerator('PUID')

        # The first "SID" this generator should return is 2, because server token 1 is implied to be
        # the main PyLink server. RFC2813 has no official definition of SIDs, but rather uses
        # integer tokens in the SERVER and NICK (user introduction) commands to keep track of which
        # user exists on which server. Why did they do it this way? Who knows!
        self._sidgen = PUIDGenerator('PSID', start=1)
        self.sid = self._sidgen.next_sid(prefix=self.serverdata['hostname'])

        self._caps.clear()

        self.cmodes.update({
            'banexception': 'e',
            'invex': 'I',
            'noinvite': 'V',
            'nokick': 'Q',
            'nonick': 'N',
            'operonly': 'O',
            'permanent': 'P',
            'registered': 'r',
            'regmoderated': 'M',
            'regonly': 'R',
            'sslonly': 'z'
        })

        self.umodes.update({
            'away': 'a',
            'bot': 'B',
            'cloak': 'x',
            'deaf_commonchan': 'C',
            'floodexempt': 'F',
            'hidechans': 'I',
            'privdeaf': 'b',
            'registered': 'R',
            'restricted': 'r',
            'servprotect': 'q',
            'sno_clientconnections': 'c'
        })

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
        assert '@' in server, "Need PSID for spawn_client, not pure server name!"
        if not self.is_internal_server(server):
            raise ValueError('Server %r is not a PyLink server!' % server)

        realname = realname or conf.conf['pylink']['realname']

        uid = self._uidgen.next_uid(prefix=nick)
        userobj = self.users[uid] = User(self, nick, ts or int(time.time()), uid, server,
                                         ident=ident, host=host, realname=realname,
                                         manipulatable=manipulatable, opertype=opertype,
                                         realhost=host)

        self.apply_modes(uid, modes)
        self.servers[server].users.add(uid)

        # Grab our server token; this is used instead of server name to denote where the client is.
        server_token = server.rsplit('@')[-1]
        # <- :ngircd.midnight.local NICK jlu5 1 ~jlu5 localhost 1 +io :realname
        self._send_with_prefix(server, 'NICK %s %s %s %s %s %s :%s' % (nick, self.servers[server].hopcount,
                               ident, host, server_token, self.join_modes(modes), realname))
        return userobj

    def spawn_server(self, name, sid=None, uplink=None, desc=None):
        """
        Spawns a server off a PyLink server.

        * desc (server description) defaults to the one in the config.
        * uplink defaults to the main PyLink server.
        * SID is set equal to the server name for ngIRCd, as server UIDs are not used.
        """
        uplink = uplink or self.sid
        assert uplink in self.servers, "Unknown uplink %r?" % uplink
        name = name.lower()
        sid = self._sidgen.next_sid(prefix=name)

        desc = desc or self.serverdata.get('serverdesc') or conf.conf['pylink']['serverdesc']

        if sid in self.servers:
            raise ValueError('A server named %r already exists!' % sid)

        if not self.is_internal_server(uplink):
            raise ValueError('Server %r is not a PyLink server!' % uplink)

        if not self.is_server_name(name):
            raise ValueError('Invalid server name %r' % name)

        # https://tools.ietf.org/html/rfc2813#section-4.1.2
        # We need to store a server token to introduce clients on the right server. Since this is just
        # a number, we can simply use the counter in our PSID generator for this.
        server_token = sid.rsplit('@')[-1]
        self.servers[sid] = Server(self, uplink, name, internal=True, desc=desc)
        self._send_with_prefix(uplink, 'SERVER %s %s %s :%s' % (name, self.servers[sid].hopcount, server_token, desc))
        return sid

    def away(self, source, text):
        """Sends an AWAY message from a PyLink client. If the text is empty, away status is unset."""
        if not self.is_internal_client(source):
            raise LookupError('No such PyLink client exists.')

        # Away status is denoted on ngIRCd with umode +a.
        modes = self.users[source].modes
        if text and (('a', None) not in modes):
            # Set umode +a if it isn't already set
            self.mode(source, source, [('+a', None)])
        elif ('a', None) in modes:
            # Ditto, only unset the mode if it *was* set.
            self.mode(source, source, [('-a', None)])
        self.users[source].away = text

    def join(self, client, channel):

        if not self.is_internal_client(client):
            raise LookupError('No such PyLink client exists.')

        self._send_with_prefix(client, "JOIN %s" % channel)
        self._channels[channel].users.add(client)
        self.users[client].channels.add(channel)

    def kill(self, source, target, reason):
        """Sends a kill from a PyLink client/server."""
        if (not self.is_internal_client(source)) and \
                (not self.is_internal_server(source)):
            raise LookupError('No such PyLink client/server exists.')

        # Follow ngIRCd's formatting of the kill messages for the most part
        self._send_with_prefix(source, 'KILL %s :KILLed by %s: %s' % (self._expandPUID(target),
                               self.get_friendly_name(source), reason))

        # Implicitly remove our own client if one was the target.
        if self.is_internal_client(target):
            self._remove_client(target)

    def knock(self, numeric, target, text):
        raise NotImplementedError('KNOCK is not supported on ngIRCd.')

    def mode(self, source, target, modes, ts=None):
        """Sends mode changes from a PyLink client/server. The TS option is not used on ngIRCd."""

        if (not self.is_internal_client(source)) and \
                (not self.is_internal_server(source)):
            raise LookupError('No such PyLink client/server %r exists' % source)

        self.apply_modes(target, modes)
        modes = list(modes)  # Work around TypeError in the expand PUID section

        if self.is_channel(target):
            msgprefix = ':%s MODE %s ' % (self._expandPUID(source), target)
            bufsize = self.S2S_BUFSIZE - len(msgprefix)

            # Expand PUIDs when sending outgoing prefix modes.
            for idx, mode in enumerate(modes):
                if mode[0][-1] in self.prefixmodes:
                    log.debug('(%s) mode: expanding PUID of mode %s', self.name, str(mode))
                    modes[idx] = (mode[0], self._expandPUID(mode[1]))

            for modestr in self.wrap_modes(modes, bufsize, max_modes_per_msg=12):
                self.send(msgprefix + modestr)
        else:
            joinedmodes = self.join_modes(modes)
            self._send_with_prefix(source, 'MODE %s %s' % (self._expandPUID(target), joinedmodes))

    def nick(self, source, newnick):
        """Changes the nick of a PyLink client."""
        if not self.is_internal_client(source):
            raise LookupError('No such PyLink client exists.')

        self._send_with_prefix(source, 'NICK %s' % newnick)

        self.users[source].nick = newnick

        # Update the nick TS for consistency with other protocols (it isn't actually used in S2S)
        self.users[source].ts = int(time.time())

    def sjoin(self, server, channel, users, ts=None, modes=set()):
        """Sends an SJOIN for a group of users to a channel.

        The sender should always be a Server ID (SID). TS is optional, and defaults
        to the one we've stored in the channel state if not given.
        <users> is a list of (prefix mode, UID) pairs:

        Example uses:
            sjoin('100', '#test', [('', 'user0@0'), ('o', user1@1'), ('v', 'someone@2')])
            sjoin(self.sid, '#test', [('o', self.pseudoclient.uid)])
        """

        server = server or self.sid
        if not server:
            raise LookupError('No such PyLink client exists.')
        log.debug('(%s) sjoin: got %r for users', self.name, users)

        njoin_prefix = ':%s NJOIN %s :' % (self._expandPUID(server), channel)
        # Format the user list into strings such as @user1, +user2, user3, etc.
        nicks_to_send = []
        for userpair in users:
            prefixes, uid = userpair

            if uid not in self.users:
                log.warning('(%s) Trying to NJOIN missing user %s?', self.name, uid)
                continue
            elif uid in self._channels[channel].users:
                # Don't rejoin users already in the channel, this causes errors with ngIRCd.
                continue

            self._channels[channel].users.add(uid)
            self.users[uid].channels.add(channel)

            self.apply_modes(channel, (('+%s' % prefix, uid) for prefix in userpair[0]))

            nicks_to_send.append(''.join(self.prefixmodes[modechar] for modechar in userpair[0]) + \
                                 self._expandPUID(userpair[1]))

        if nicks_to_send:
            # Use 13 args max per line: this is equal to the max of 15 minus the command name and target channel.
            for message in utils.wrap_arguments(njoin_prefix, nicks_to_send, self.S2S_BUFSIZE, separator=',', max_args_per_line=13):
                self.send(message)

        if modes:
            # Burst modes separately if there are any.
            log.debug("(%s) sjoin: bursting modes %r for channel %r now", self.name, modes, channel)
            self.mode(server, channel, modes)

    def set_server_ban(self, source, duration, user='*', host='*', reason='User banned'):
        """
        Sets a server ban.
        """
        # <- :jlu5 GLINE *!*@bad.user 3d :test
        assert not (user == host == '*'), "Refusing to set ridiculous ban on *@*"
        self._send_with_prefix(source, 'GLINE *!%s@%s %s :%s' % (user, host, duration, reason))

    def update_client(self, target, field, text):
        """Updates the ident, host, or realname of any connected client."""
        field = field.upper()

        if field not in ('IDENT', 'HOST', 'REALNAME', 'GECOS'):
            raise NotImplementedError("Changing field %r of a client is "
                                      "unsupported by this protocol." % field)

        real_target = self._expandPUID(target)
        if field == 'IDENT':
            self.users[target].ident = text
            self._send_with_prefix(self.sid, 'METADATA %s user :%s' % (real_target, text))

            if not self.is_internal_client(target):
                # If the target wasn't one of our clients, send a hook payload for other plugins to listen to.
                self.call_hooks([self.sid, 'CHGIDENT', {'target': target, 'newident': text}])

        elif field == 'HOST':
            self.users[target].host = text

            if self.is_internal_client(target):
                # For our own clients, replace the real host.
                self._send_with_prefix(self.sid, 'METADATA %s host :%s' % (real_target, text))
            else:
                # For others, update the cloaked host and force a umode +x.
                self._send_with_prefix(self.sid, 'METADATA %s cloakhost :%s' % (real_target, text))

                if ('x', None) not in self.users[target].modes:
                    log.debug('(%s) Forcing umode +x on %r as part of cloak setting', self.name, target)
                    self.mode(self.sid, target, [('+x', None)])

                self.call_hooks([self.sid, 'CHGHOST', {'target': target, 'newhost': text}])

        elif field in ('REALNAME', 'GECOS'):
            self.users[target].realname = text
            self._send_with_prefix(self.sid, 'METADATA %s info :%s' % (real_target, text))

            if not self.is_internal_client(target):
                self.call_hooks([self.sid, 'CHGNAME', {'target': target, 'newgecos': text}])

    ### Handlers

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

        channel = args[0]
        # Get rid of +l and +k in the initial parsing; we handle that later by looking at the CHANINFO arguments
        modes = self.parse_modes(channel, args[1].replace('l', '').replace('k', ''))

        if len(args) >= 3:
            topic = args[-1]
            if topic:
                log.debug('(%s) handle_chaninfo: setting topic for %s to %r', self.name, channel, topic)
                self._channels[channel].topic = topic
                self._channels[channel].topicset = True

        if len(args) >= 5:
            key = args[2]
            limit = args[3]
            if key != '*':
                modes.append(('+k', key))
            if limit != '0':
                modes.append(('+l', limit))

        self.apply_modes(channel, modes)

    def handle_join(self, source, command, args):
        # RFC 2813 is odd to say the least... https://tools.ietf.org/html/rfc2813#section-4.2.1
        # Basically, we expect messages of the forms:
        # <- :jlu5 JOIN #test\x07o
        # <- :jlu5 JOIN #moretest
        for chanpair in args[0].split(','):
            # Normalize channel case.
            try:
                channel, status = chanpair.split('\x07', 1)
                if status in 'ov':
                    self.apply_modes(channel, [('+' + status, source)])
            except ValueError:
                channel = chanpair

            c = self._channels[channel]

            self.users[source].channels.add(channel)
            self._channels[channel].users.add(source)

            # Call hooks manually, because one JOIN command have multiple channels.
            self.call_hooks([source, command, {'channel': channel, 'users': [source], 'modes': c.modes}])

    def handle_kill(self, source, command, args):
        """Handles incoming KILLs."""

        # ngIRCd sends QUIT after KILL for its own clients, so we shouldn't process this by itself
        # unless we're the target.
        killed = self._get_UID(args[0])
        if self.is_internal_client(killed):
            return super().handle_kill(source, command, args)
        else:
            log.debug("(%s) Ignoring KILL to %r as it isn't meant for us; we should see a QUIT soon",
                      self.name, killed)

    def _check_cloak_change(self, target):
        u = self.users[target]
        old_host = u.host

        if ('x', None) in u.modes and u.cloaked_host:
            u.host = u.cloaked_host
        elif u.realhost:
            u.host = u.realhost

        # Something changed, so send a CHGHOST hook
        if old_host != u.host:
            self.call_hooks([target, 'CHGHOST', {'target': target, 'newhost': u.host}])

    def handle_metadata(self, source, command, args):
        """Handles various user metadata for ngIRCd (cloaked host, account name, etc.)"""
        # <- :ngircd.midnight.local METADATA jlu5 cloakhost :hidden-3a2a739e.ngircd.midnight.local
        target = self._get_UID(args[0])

        if target not in self.users:
            log.warning("(%s) Ignoring METADATA to missing user %r?", self.name, target)
            return

        datatype = args[1]
        u = self.users[target]

        if datatype == 'cloakhost':  # Set cloaked host
            u.cloaked_host = args[-1]
            self._check_cloak_change(target)

        elif datatype == 'host':  # Host changing. This actually sets the "real host" that ngIRCd stores
            u.realhost = args[-1]
            self._check_cloak_change(target)

        elif datatype == 'user':  # Ident changing
            u.ident = args[-1]
            self.call_hooks([target, 'CHGIDENT', {'target': target, 'newident': args[-1]}])

        elif datatype == 'info':  # Realname changing
            u.realname = args[-1]
            self.call_hooks([target, 'CHGNAME', {'target': target, 'newgecos': args[-1]}])

        elif datatype == 'accountname':  # Services account
            self.call_hooks([target, 'CLIENT_SERVICES_LOGIN', {'text': args[-1]}])

    def handle_nick(self, source, command, args):
        """
        Handles the NICK command, used for server introductions and nick changes.
        """
        if len(args) >= 2:
            # User introduction:
            # <- :ngircd.midnight.local NICK jlu5 1 ~jlu5 localhost 1 +io :realname
            nick = args[0]
            assert source in self.servers, "Server %r tried to introduce nick %r but isn't in the servers index?" % (source, nick)
            self._check_nick_collision(nick)

            ident = args[2]
            host = args[3]
            uid = self._uidgen.next_uid(prefix=nick)
            realname = args[-1]

            ts = int(time.time())
            self.users[uid] = User(self, nick, ts, uid, source, ident=ident, host=host,
                                   realname=realname, realhost=host)
            parsedmodes = self.parse_modes(uid, [args[5]])
            self.apply_modes(uid, parsedmodes)

            # Add the nick to the list of users on its server; this is used for SQUIT tracking
            self.servers[source].users.add(uid)

            # Check away status and cloaked host changes
            self._check_umode_away_change(uid)
            self._check_cloak_change(uid)

            return {'uid': uid, 'ts': ts, 'nick': nick, 'realhost': host, 'host': host, 'ident': ident,
                    'parse_as': 'UID', 'ip': '0.0.0.0'}
        else:
            # Nick changes:
            # <- :jlu5 NICK :jlu5_
            oldnick = self.users[source].nick
            newnick = self.users[source].nick = args[0]
            return {'newnick': newnick, 'oldnick': oldnick}

    def handle_njoin(self, source, command, args):
        # <- :ngircd.midnight.local NJOIN #test :tester,@%jlu5

        channel = args[0]
        chandata = self._channels[channel].deepcopy()
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
            self._channels[channel].users.add(user)

        return {'channel': channel, 'users': namelist, 'modes': [], 'channeldata': chandata}

    def handle_pass(self, source, command, args):
        """
        Handles phase one of the ngIRCd login process (password auth and version info).
        """
        # PASS is step one of server introduction, and is used to send the server info and password.
        # <- :ngircd.midnight.local PASS xyzpassword 0210-IRC+ ngIRCd|24~3-gbc728f92:CHLMSXZ PZ
        recvpass = args[0]
        if recvpass != self.serverdata['recvpass']:
            raise ProtocolError("RECVPASS from uplink does not match configuration!")

        if 'IRC+' not in args[1]:
            raise ProtocolError("Linking to non-ngIRCd server using this protocol module is not supported")

    def handle_ping(self, source, command, args):
        """
        Handles incoming PINGs (and implicit end of burst).
        """
        self._send_with_prefix(self.sid, 'PONG %s :%s' % (self._expandPUID(self.sid), args[-1]), queue=False)

        if not self.servers[source].has_eob:
            # Treat the first PING we receive as end of burst.
            self.servers[source].has_eob = True

            if source == self.uplink:
                self.connected.set()

            # Return the endburst hook.
            return {'parse_as': 'ENDBURST'}

    def handle_server(self, source, command, args):
        """
        Handles the SERVER command.
        """
        # <- :ngircd.midnight.local SERVER ngircd.midnight.local 1 :ngIRCd dev server
        servername = args[0].lower()
        serverdesc = args[-1]

        # The uplink should be set to None for the uplink; otherwise, set it equal to the sender server.
        self.servers[servername] = Server(self, source if source != servername else None, servername, desc=serverdesc)

        if self.uplink is None:
            self.uplink = servername
            log.debug('(%s) Got %s as uplink', self.name, servername)
        else:
            # Only send the SERVER hook if this isn't the initial connection.
            return {'name': servername, 'sid': None, 'text': serverdesc}

Class = NgIRCdProtocol
