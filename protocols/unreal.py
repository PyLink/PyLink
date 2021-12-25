"""
unreal.py: UnrealIRCd 4.x-5.x protocol module for PyLink.
"""

import codecs
import re
import socket
import time

from pylinkirc import conf, utils
from pylinkirc.classes import *
from pylinkirc.log import log
from pylinkirc.protocols.ts6_common import TS6BaseProtocol

__all__ = ['UnrealProtocol']


SJOIN_PREFIXES = {'q': '*', 'a': '~', 'o': '@', 'h': '%', 'v': '+', 'b': '&', 'e': '"', 'I': "'"}

class UnrealProtocol(TS6BaseProtocol):
    # I'm not sure what the real limit is, but the text posted at
    # https://github.com/jlu5/PyLink/issues/378 suggests 427 characters.
    # https://github.com/unrealircd/unrealircd/blob/4cad9cb/src/modules/m_server.c#L1260 may
    # also help. (but why BUFSIZE-*80*?) -jlu5
    S2S_BUFSIZE = 427
    _KNOWN_CMODES = {'ban': 'b',
              'banexception': 'e',
              'blockcolor': 'c',
              'censor': 'G',
              'delayjoin': 'D',
              'flood_unreal': 'f',
              'invex': 'I',
              'inviteonly': 'i',
              'issecure': 'Z',
              'key': 'k',
              'limit': 'l',
              'moderated': 'm',
              'noctcp': 'C',
              'noextmsg': 'n',
              'noinvite': 'V',
              'nokick': 'Q',
              'noknock': 'K',
              'nonick': 'N',
              'nonotice': 'T',
              'op': 'o',
              'operonly': 'O',
              'permanent': 'P',
              'private': 'p',
              'registered': 'r',
              'regmoderated': 'M',
              'regonly': 'R',
              'secret': 's',
              'sslonly': 'z',
              'stripcolor': 'S',
              'topiclock': 't',
              'voice': 'v'}
    _KNOWN_UMODES = {'bot': 'B',
              'censor': 'G',
              'cloak': 'x',
              'deaf': 'd',
              'filter': 'G',
              'hidechans': 'p',
              'hideidle': 'I',
              'hideoper': 'H',
              'invisible': 'i',
              'noctcp': 'T',
              'protected': 'q',
              'regdeaf': 'R',
              'registered': 'r',
              'sslonlymsg': 'Z',
              'servprotect': 'S',
              'showwhois': 'W',
              'snomask': 's',
              'ssl': 'z',
              'vhost': 't',
              'wallops': 'w'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.protocol_caps |= {'slash-in-nicks', 'underscore-in-hosts', 'slash-in-hosts'}
        # Set our case mapping (rfc1459 maps "\" and "|" together, for example)
        self.casemapping = 'ascii'

        # Unreal protocol version
        self.proto_ver = 4203
        self.min_proto_ver = 4000

        self.hook_map = {'UMODE2': 'MODE', 'SVSKILL': 'KILL', 'SVSMODE': 'MODE',
                         'SVS2MODE': 'MODE', 'SJOIN': 'JOIN', 'SETHOST': 'CHGHOST',
                         'SETIDENT': 'CHGIDENT', 'SETNAME': 'CHGNAME',
                         'EOS': 'ENDBURST'}

        self.caps = []
        self.prefixmodes = {'q': '~', 'a': '&', 'o': '@', 'h': '%', 'v': '+'}

        self.needed_caps = ["VL", "SID", "CHANMODES", "NOQUIT", "SJ3", "NICKIP", "UMODE2", "SJOIN"]

        # Command aliases to handlers defined in parent modules
        self.handle_svskill = self.handle_kill
        self.topic_burst = self.topic

    ### OUTGOING COMMAND FUNCTIONS
    def spawn_client(self, nick, ident='null', host='null', realhost=None, modes=set(),
            server=None, ip='0.0.0.0', realname=None, ts=None, opertype='IRC Operator',
            manipulatable=False):
        """
        Spawns a new client with the given options.

        Note: No nick collision / valid nickname checks are done here; it is
        up to plugins to make sure they don't introduce anything invalid.
        """
        server = server or self.sid
        if not self.is_internal_server(server):
            raise ValueError('Server %r is not a PyLink server!' % server)

        # Unreal 4.0 uses TS6-style UIDs. They don't start from AAAAAA like other IRCd's
        # do, but that doesn't matter to us...
        uid = self.uidgen[server].next_uid()

        ts = ts or int(time.time())
        realname = realname or conf.conf['pylink']['realname']
        realhost = realhost or host

        # Add +xt so that vHost cloaking always works.
        modes = set(modes)  # Ensure type safety
        modes |= {('+x', None), ('+t', None)}

        raw_modes = self.join_modes(modes)
        u = self.users[uid] = User(self,  nick, ts, uid, server, ident=ident, host=host, realname=realname,
            realhost=realhost, ip=ip, manipulatable=manipulatable, opertype=opertype)
        self.apply_modes(uid, modes)
        self.servers[server].users.add(uid)

        # UnrealIRCd requires encoding the IP by first packing it into a binary format,
        # and then encoding the binary with Base64.
        if ip == '0.0.0.0':  # Dummy IP (for services, etc.) use a single *.
            encoded_ip = '*'
        else:
            try:  # Try encoding as IPv4 first.
                binary_ip = socket.inet_pton(socket.AF_INET, ip)
            except OSError:
                try:  # That failed, try IPv6 next.
                    binary_ip = socket.inet_pton(socket.AF_INET6, ip)
                except OSError:
                    raise ValueError("Invalid IPv4 or IPv6 address %r." % ip)

            # Encode in Base64.
            encoded_ip = codecs.encode(binary_ip, "base64")
            # Now, strip the trailing \n and decode into a string again.
            encoded_ip = encoded_ip.strip().decode()

        # <- :001 UID jlu5 0 1441306929 jlu5 localhost 0018S7901 0 +iowx * midnight-1C620195 fwAAAQ== :realname
        self._send_with_prefix(server, "UID {nick} {hopcount} {ts} {ident} {realhost} {uid} 0 {modes} "
                               "{host} * {ip} :{realname}".format(ts=ts, host=host,
                               nick=nick, ident=ident, uid=uid,
                               modes=raw_modes, realname=realname,
                               realhost=realhost, ip=encoded_ip,
                               hopcount=self.servers[server].hopcount))

        return u

    def join(self, client, channel):
        """Joins a PyLink client to a channel."""
        if not self.is_internal_client(client):
            raise LookupError('No such PyLink client exists.')

        # Forward this on to SJOIN, as using JOIN in Unreal S2S seems to cause TS corruption bugs.
        # This seems to be what Unreal itself does anyways.
        if channel not in self.channels:
            prefix = 'o'  # Create new channels with the first joiner as op
        else:
            prefix = ''
        self.sjoin(self.sid, channel, [(prefix, client)])

    def sjoin(self, server, channel, users, ts=None, modes=set()):
        """Sends an SJOIN for a group of users to a channel.

        The sender should always be a server (SID). TS is optional, and defaults
        to the one we've stored in the channel state if not given.
        <users> is a list of (prefix mode, UID) pairs:

        Example uses:
            sjoin('100', '#test', [('', '100AAABBC'), ('o', 100AAABBB'), ('v', '100AAADDD')])
            sjoin(self.sid, '#test', [('o', self.pseudoclient.uid)])
        """
        # <- :001 SJOIN 1444361345 #test :*@+1JJAAAAAB %2JJAAAA4C 1JJAAAADS
        server = server or self.sid
        assert users, "sjoin: No users sent?"
        if not server:
            raise LookupError('No such PyLink server exists.')

        changedmodes = set(modes or self._channels[channel].modes)
        orig_ts = self._channels[channel].ts
        ts = ts or orig_ts
        uids = []
        itemlist = []

        for userpair in users:
            assert len(userpair) == 2, "Incorrect format of userpair: %r" % userpair
            prefixes, user = userpair

            # Unreal uses slightly different prefixes in SJOIN. +q is * instead of ~,
            # and +a is ~ instead of &.
            # &, ", and ' are used for bursting bans.
            prefixchars = ''.join([SJOIN_PREFIXES.get(prefix, '') for prefix in prefixes])

            if prefixchars:
                changedmodes |= {('+%s' % prefix, user) for prefix in prefixes}

            itemlist.append(prefixchars+user)
            uids.append(user)

            try:
                self.users[user].channels.add(channel)
            except KeyError:  # Not initialized yet?
                log.debug("(%s) sjoin: KeyError trying to add %r to %r's channel list?", self.name, channel, user)

        # Track simple modes separately.
        simplemodes = set()
        for modepair in modes:
            if modepair[0][-1] in self.cmodes['*A']:
                # Bans, exempts, invex get expanded to forms like "&*!*@some.host" in SJOIN.

                if (modepair[0][-1], modepair[1]) in self._channels[channel].modes:
                    # Mode is already set; skip it.
                    continue

                sjoin_prefix = SJOIN_PREFIXES.get(modepair[0][-1])
                if sjoin_prefix:
                    itemlist.append(sjoin_prefix+modepair[1])
            else:
                simplemodes.add(modepair)

        # Store the part of the SJOIN that we may reuse due to line wrapping (i.e. the sjoin
        # "prefix")
        sjoin_prefix = ":{sid} SJOIN {ts} {channel}".format(sid=server, ts=ts, channel=channel)

        # Modes are optional; add them if they exist
        if modes:
            sjoin_prefix += " %s" % self.join_modes(simplemodes)

        sjoin_prefix += " :"
        # Wrap arguments to the max supported S2S line length to prevent cutoff
        # (https://github.com/jlu5/PyLink/issues/378)
        for line in utils.wrap_arguments(sjoin_prefix, itemlist, self.S2S_BUFSIZE):
            self.send(line)

        self._channels[channel].users.update(uids)

        self.updateTS(server, channel, ts, changedmodes)

    def _ping_uplink(self):
        """Sends a PING to the uplink."""
        if self.sid and self.uplink:
            self._send_with_prefix(self.sid, 'PING %s %s' % (self.get_friendly_name(self.sid), self.get_friendly_name(self.uplink)))

    def mode(self, numeric, target, modes, ts=None):
        """
        Sends mode changes from a PyLink client/server. The mode list should be
        a list of (mode, arg) tuples, i.e. the format of utils.parse_modes() output.
        """
        # <- :unreal.midnight.vpn MODE #test +ntCo jlu5 1444361345

        if (not self.is_internal_client(numeric)) and \
                (not self.is_internal_server(numeric)):
            raise LookupError('No such PyLink client/server exists.')

        self.apply_modes(target, modes)

        if self.is_channel(target):
            modes = list(modes)  # Needed for indexing

            # Make sure we expand any PUIDs when sending outgoing modes...
            for idx, mode in enumerate(modes):
                if mode[0][-1] in self.prefixmodes:
                    log.debug('(%s) mode: expanding PUID of mode %s', self.name, str(mode))
                    modes[idx] = (mode[0], self._expandPUID(mode[1]))

            # The MODE command is used for channel mode changes only
            ts = ts or self._channels[target].ts

            # 7 characters for "MODE", the space between MODE and the target, the space between the
            # target and mode list, and the space between the mode list and TS.
            bufsize = self.S2S_BUFSIZE - 7

            # Subtract the length of the TS and channel arguments
            bufsize -= len(str(ts))
            bufsize -= len(target)

            # Subtract the prefix (":SID " for servers or ":SIDAAAAAA " for servers)
            bufsize -= (5 if self.is_internal_server(numeric) else 11)

            # There is also an (undocumented) 15 args per line limit for MODE. The target, mode
            # characters, and TS take up three args, so we're left with 12 spaces for parameters.
            # Any lines that go over 15 args/line has the potential of corrupting a channel's TS
            # pretty badly, as the last argument gets mangled into a number:
            # * *** Warning! Possible desynch: MODE for channel #test ('+bbbbbbbbbbbb *!*@0.1 *!*@1.1 *!*@2.1 *!*@3.1 *!*@4.1 *!*@5.1 *!*@6.1 *!*@7.1 *!*@8.1 *!*@9.1 *!*@10.1 *!*@11.1') has fishy timestamp (12) (from pylink.local/pylink.local)

            # Thanks to kevin and Jobe for helping me debug this!
            for modestring in self.wrap_modes(modes, bufsize, max_modes_per_msg=12):
                self._send_with_prefix(numeric, 'MODE %s %s %s' % (target, modestring, ts))
        else:
            # For user modes, the only way to set modes (for non-U:Lined servers)
            # is through UMODE2, which sets the modes on the caller.
            # U:Lines can use SVSMODE/SVS2MODE, but I won't expect people to
            # U:Line a PyLink daemon...
            if not self.is_internal_client(target):
                raise ProtocolError('Cannot force mode change on external clients!')

            # XXX: I don't expect usermode changes to ever get cut off, but length
            # checks could be added just to be safe...
            joinedmodes = self.join_modes(modes)
            self._send_with_prefix(target, 'UMODE2 %s' % joinedmodes)

    def oper_notice(self, source, text):
        """
        Send a message to all opers.
        """
        self._send_with_prefix(source, 'GLOBOPS :%s' % text)

    def set_server_ban(self, source, duration, user='*', host='*', reason='User banned'):
        """
        Sets a server ban.
        """
        # Permanent:
        # <- :unreal.midnight.vpn TKL + G ident host.net james!james@localhost 0 1500303745 :no reason
        # Temporary:
        # <- :unreal.midnight.vpn TKL + G * everyone james!james@localhost 1500303702 1500303672 :who needs reasons, do people even read them?
        assert not (user == host == '*'), "Refusing to set ridiculous ban on *@*"

        if source in self.users:
            # GLINEs are always forwarded from the server as far as I can tell.
            real_source = self.get_server(source)
        else:
            real_source = source

        setter = self.get_hostmask(source) if source in self.users else self.get_friendly_name(source)
        currtime = int(time.time())
        self._send_with_prefix(real_source, 'TKL + G %s %s %s %s %s :%s' % (user, host, setter, currtime+duration if duration != 0 else 0, currtime, reason))

    def update_client(self, target, field, text):
        """Updates the ident, host, or realname of any connected client."""
        field = field.upper()

        if field not in ('IDENT', 'HOST', 'REALNAME', 'GECOS'):
            raise NotImplementedError("Changing field %r of a client is "
                                      "unsupported by this protocol." % field)

        if self.is_internal_client(target):
            # It is one of our clients, use SETIDENT/HOST/NAME.
            if field == 'IDENT':
                self.users[target].ident = text
                self._send_with_prefix(target, 'SETIDENT %s' % text)
            elif field == 'HOST':
                self.users[target].host = text
                self._send_with_prefix(target, 'SETHOST %s' % text)
            elif field in ('REALNAME', 'GECOS'):
                self.users[target].realname = text
                self._send_with_prefix(target, 'SETNAME :%s' % text)
        else:
            # It is a client on another server, use CHGIDENT/HOST/NAME.
            if field == 'IDENT':
                self.users[target].ident = text
                self._send_with_prefix(self.sid, 'CHGIDENT %s %s' % (target, text))

                # Send hook payloads for other plugins to listen to.
                self.call_hooks([self.sid, 'CHGIDENT',
                                   {'target': target, 'newident': text}])

            elif field == 'HOST':
                self.users[target].host = text
                self._send_with_prefix(self.sid, 'CHGHOST %s %s' % (target, text))

                self.call_hooks([self.sid, 'CHGHOST',
                                   {'target': target, 'newhost': text}])

            elif field in ('REALNAME', 'GECOS'):
                self.users[target].realname = text
                self._send_with_prefix(self.sid, 'CHGNAME %s :%s' % (target, text))

                self.call_hooks([self.sid, 'CHGNAME',
                                   {'target': target, 'newgecos': text}])

    def kill(self, source, target, reason):
        """Sends a kill from a PyLink client or server."""

        if (not self.is_internal_client(source)) and \
                (not self.is_internal_server(source)):
            raise LookupError('No such PyLink client/server exists.')

        self._send_with_prefix(source, 'KILL %s :%s' % (target, reason))
        self._remove_client(target)

    def knock(self, numeric, target, text):
        """Sends a KNOCK from a PyLink client."""
        # KNOCKs in UnrealIRCd are actually just specially formatted NOTICEs,
        # sent to all ops in a channel.
        # <- :unreal.midnight.vpn NOTICE @#test :[Knock] by jlu5|!jlu5@hidden-1C620195 (test)
        assert self.is_channel(target), "Can only knock on channels!"
        sender = self.get_server(numeric)
        s = '[Knock] by %s (%s)' % (self.get_hostmask(numeric), text)
        self._send_with_prefix(sender, 'NOTICE @%s :%s' % (target, s))

    ### HANDLERS

    def post_connect(self):
        """Initializes a connection to a server."""
        ts = self.start_ts
        self.prefixmodes = {'q': '~', 'a': '&', 'o': '@', 'h': '%', 'v': '+'}

        # Track usages of legacy (Unreal 3.2) nicks.
        self.legacy_uidgen = PUIDGenerator('U32user')

        f = self.send
        host = self.serverdata["hostname"]

        f('PASS :%s' % self.serverdata["sendpass"])
        # https://github.com/unrealircd/unrealircd/blob/2f8cb55e/doc/technical/protoctl.txt
        # We support the following protocol features:
        # SJOIN - supports SJOIN for user introduction
        # SJ3 - extended SJOIN
        # NOQUIT - QUIT messages aren't sent for all users in a netsplit
        # NICKv2 - Extended NICK command, sending MODE and CHGHOST info with it
        # SID - Use UIDs and SIDs (Unreal 4)
        # VL - Sends version string in below SERVER message
        # UMODE2 - used for users setting modes on themselves (one less argument needed)
        # EAUTH - Early auth? (Unreal 4 linking protocol)
        # NICKIP - Extends the NICK command used for introduction (for Unreal 3.2 servers)
        #          to include user IPs.
        # VHP - Sends cloaked hosts of UnrealIRCd 3.2 users as the hostname. This is important
        #       because UnrealIRCd 3.2 only has one vHost field in its NICK command, and not two
        #       like UnrealIRCd 4.0 (cloaked host + displayed host). Without VHP, cloaking does
        #       not work for any UnrealIRCd 3.2 users.
        # ESVID - Supports account names in services stamps instead of just the signon time.
        #         AFAIK this doesn't actually affect services' behaviour?
        # EXTSWHOIS - support multiple SWHOIS lines (purely informational for us)
        f('PROTOCTL SJOIN SJ3 NOQUIT NICKv2 VL UMODE2 PROTOCTL NICKIP EAUTH=%s SID=%s VHP ESVID EXTSWHOIS' % (self.serverdata["hostname"], self.sid))
        sdesc = self.serverdata.get('serverdesc') or conf.conf['pylink']['serverdesc']
        f('SERVER %s 1 U%s-h6e-%s :%s' % (host, self.proto_ver, self.sid, sdesc))

        self._send_with_prefix(self.sid, 'EOS')

        # Extban definitions
        self.extbans_acting = {'quiet': '~q:',
                               'ban_nonick': '~n:',
                               'ban_nojoins': '~j:',
                               'filter': '~T:block:',
                               'filter_censor': '~T:censor:',
                               'msgbypass_external': '~m:external:',
                               'msgbypass_censor': '~m:censor:',
                               'msgbypass_moderated': '~m:moderated:',
                               # These two sort of map to InspIRCd +e S: and +e T:
                               'ban_stripcolor': '~m:color:',
                               'ban_nonotice': '~m:notice:',
                               'timedban_unreal': '~t:'}
        self.extbans_matching = {'ban_account': '~a:',
                                 'ban_inchannel': '~c:',
                                 'ban_opertype': '~O:',
                                 'ban_realname': '~r:',
                                 'ban_account_legacy': '~R:',
                                 'ban_certfp': '~S:'}

    def handle_eos(self, numeric, command, args):
        """EOS is used to denote end of burst."""
        self.servers[numeric].has_eob = True
        if numeric == self.uplink:
            self.connected.set()
        return {}

    def handle_uid(self, numeric, command, args):
        # <- :001 UID jlu5 0 1441306929 jlu5 localhost 0018S7901 0 +iowx * midnight-1C620195 fwAAAQ== :realname
        # <- :001 UID jlu5| 0 1441389007 jlu5 10.120.0.6 001ZO8F03 0 +iwx * 391A9CB9.26A16454.D9847B69.IP CngABg== :realname
        # arguments: nick, hopcount?, ts, ident, real-host, UID, services account (0 if none), modes,
        #            displayed host, cloaked (+x) host, base64-encoded IP, and realname
        nick = args[0]
        self._check_nick_collision(nick)
        ts, ident, realhost, uid, accountname, modestring, host = args[2:9]
        ts = int(ts)

        if host == '*':
            # A single * means that there is no displayed/virtual host, and
            # that it's the same as the real host
            host = args[9]

        # Decode UnrealIRCd's IPs, which are stored in base64-encoded network structure
        raw_ip = args[10].encode()  # codecs.decode only takes bytes, not str
        if raw_ip == b'*':  # Dummy IP (for services, etc.)
            ip = '0.0.0.0'
        else:
            # First, decode the Base64 string into a packed binary IP address.
            ip = codecs.decode(raw_ip, "base64")

            try:  # IPv4 address.
                ip = socket.inet_ntop(socket.AF_INET, ip)
            except ValueError:  # IPv6 address.
                ip = socket.inet_ntop(socket.AF_INET6, ip)
                # HACK: make sure a leading ":" in the IPv6 address (e.g. ::1)
                # doesn't cause it to be misinterpreted as the last argument
                # in a line, should it be mirrored to other networks.
                if ip.startswith(':'):
                    ip = '0' + ip

        realname = args[-1]

        self.users[uid] = User(self, nick, ts, uid, numeric, ident, host, realname, realhost, ip)
        self.servers[numeric].users.add(uid)

        # Handle user modes
        parsedmodes = self.parse_modes(uid, [modestring])
        self.apply_modes(uid, parsedmodes)

        # The cloaked (+x) host is completely separate from the displayed host
        # and real host in that it is ONLY shown if the user is +x (cloak mode
        # enabled) but NOT +t (vHost set).
        self.users[uid].cloaked_host = args[9]

        self._check_oper_status_change(uid, parsedmodes)

        if ('+x', None) not in parsedmodes:
            # If +x is not set, update to use the person's real host.
            self.users[uid].host = realhost

        # Set the account name if present: if this is a number, set it to the user nick.
        if ('+r', None) in parsedmodes and accountname.isdigit():
            accountname = nick

        # Track SSL/TLS status
        has_ssl = self.users[uid].ssl = ('+z', None) in parsedmodes

        if not accountname.isdigit():
            self.call_hooks([uid, 'CLIENT_SERVICES_LOGIN', {'text': accountname}])

        # parse_as is used here to prevent legacy user introduction from being confused
        # with a nick change.
        return {'uid': uid, 'ts': ts, 'nick': nick, 'realhost': realhost, 'host': host,
                'ident': ident, 'ip': ip, 'parse_as': 'UID', 'secure': has_ssl}

    def handle_pass(self, numeric, command, args):
        # <- PASS :abcdefg
        if args[0] != self.serverdata['recvpass']:
            raise ProtocolError("RECVPASS from uplink does not match configuration!")

    def handle_ping(self, numeric, command, args):
        if numeric == self.uplink:
            self.send('PONG %s :%s' % (self.serverdata['hostname'], args[-1]), queue=False)

    def handle_server(self, numeric, command, args):
        """Handles the SERVER command, which is used for both authentication and
        introducing legacy (non-SID) servers."""
        # <- SERVER unreal.midnight.vpn 1 :U3999-Fhin6OoEM UnrealIRCd test server
        sname = args[0]
        if self.uplink not in self.servers:  # We're doing authentication
            for cap in self.needed_caps:
                if cap not in self.caps:
                    raise ProtocolError("Not all required capabilities were met "
                                        "by the remote server. Your version of UnrealIRCd "
                                        "is probably too old! (Got: %s, needed: %s)" %
                                        (sorted(self.caps), sorted(self.needed_caps)))

            sdesc = args[-1].split(" ", 1)
            # Get our protocol version. I really don't know why the version and the server
            # description aren't two arguments instead of one... -jlu5
            vline = sdesc[0].split('-', 1)
            sdesc = " ".join(sdesc[1:])

            try:
                protover = int(vline[0].strip('U'))
            except ValueError:
                raise ProtocolError("Protocol version too old! (needs at least %s "
                                    "(Unreal 4.x), got something invalid; "
                                    "is VL being sent?)" % self.min_proto_ver)

            if protover < self.min_proto_ver:
                raise ProtocolError("Protocol version too old! (needs at least %s "
                                    "(Unreal 4.x), got %s)" % (self.min_proto_ver, protover))
            self.servers[numeric] = Server(self, None, sname, desc=sdesc)

            # Prior to 4203, Unreal did not send PROTOCTL USERMODES (see handle_protoctl() )
            if protover < 4203:
                self.umodes.update(self._KNOWN_UMODES)
                self.umodes['*D'] = ''.join(self._KNOWN_UMODES.values())
        else:
            # Legacy (non-SID) servers can still be introduced using the SERVER command.
            # <- :services.int SERVER a.bc 2 :(H) [jlu5] a
            return super().handle_server(numeric, command, args)

    def handle_protoctl(self, numeric, command, args):
        """Handles protocol negotiation."""
        # Make a list of all our capability names.
        self.caps += [arg.split('=')[0] for arg in args]

        # Unreal 4.0.x:
        # <- PROTOCTL NOQUIT NICKv2 SJOIN SJOIN2 UMODE2 VL SJ3 TKLEXT TKLEXT2 NICKIP ESVID
        # <- PROTOCTL CHANMODES=beI,k,l,psmntirzMQNRTOVKDdGPZSCc NICKCHARS= SID=001 MLOCK TS=1441314501 EXTSWHOIS
        # Unreal 4.2.x:
        # <- PROTOCTL NOQUIT NICKv2 SJOIN SJOIN2 UMODE2 VL SJ3 TKLEXT TKLEXT2 NICKIP ESVID SJSBY
        # <- PROTOCTL CHANMODES=beI,kLf,l,psmntirzMQNRTOVKDdGPZSCc USERMODES=iowrsxzdHtIDZRqpWGTSB BOOTED=1574014839 PREFIX=(qaohv)~&@%+ NICKCHARS= SID=001 MLOCK TS=1574020869 EXTSWHOIS
        # Unreal 5.0.0-rc1:
        # <- PROTOCTL NOQUIT NICKv2 SJOIN SJOIN2 UMODE2 VL SJ3 TKLEXT TKLEXT2 NICKIP ESVID SJSBY MTAGS
        # <- PROTOCTL CHANMODES=beI,kLf,lH,psmntirzMQNRTOVKDdGPZSCc USERMODES=iowrsxzdHtIDZRqpWGTSB BOOTED=1574020755 PREFIX=(qaohv)~&@%+ SID=001 MLOCK TS=1574020823 EXTSWHOIS
        # <- PROTOCTL NICKCHARS= CHANNELCHARS=utf8
        for cap in args:
            if cap.startswith('SID'):
                self.uplink = cap.split('=', 1)[1]
            elif cap.startswith('CHANMODES'):
                # Parse all the supported channel modes.
                supported_cmodes = cap.split('=', 1)[1]
                self.cmodes['*A'], self.cmodes['*B'], self.cmodes['*C'], self.cmodes['*D'] = supported_cmodes.split(',')
                for namedmode, modechar in self._KNOWN_CMODES.items():
                    if modechar in supported_cmodes:
                        self.cmodes[namedmode] = modechar
            elif cap.startswith('USERMODES'):  # Only for protover >= 4203
                self.umodes['*D'] = supported_umodes = cap.split('=', 1)[1]
                for namedmode, modechar in self._KNOWN_UMODES.items():
                    if modechar in supported_umodes:
                        self.umodes[namedmode] = modechar

        # Add in the supported prefix modes.
        self.cmodes.update({'halfop': 'h', 'admin': 'a', 'owner': 'q',
                            'op': 'o', 'voice': 'v'})

    def handle_join(self, numeric, command, args):
        """Handles the UnrealIRCd JOIN command."""
        # <- :jlu5 JOIN #pylink,#test
        if args[0] == '0':
            # /join 0; part the user from all channels
            oldchans = self.users[numeric].channels.copy()
            log.debug('(%s) Got /join 0 from %r, channel list is %r',
                      self.name, numeric, oldchans)
            for ch in oldchans:
                self._channels[ch].users.discard(numeric)
                self.users[numeric].channels.discard(ch)
            return {'channels': oldchans, 'text': 'Left all channels.', 'parse_as': 'PART'}

        else:
            for channel in args[0].split(','):
                c = self._channels[channel]
                self.users[numeric].channels.add(channel)
                self._channels[channel].users.add(numeric)
                # Call hooks manually, because one JOIN command in UnrealIRCd can
                # have multiple channels...
                self.call_hooks([numeric, command, {'channel': channel, 'users': [numeric], 'modes':
                                                       c.modes, 'ts': c.ts}])

    def handle_sjoin(self, numeric, command, args):
        """Handles the UnrealIRCd SJOIN command."""
        # <- :001 SJOIN 1444361345 #test :001AAAAAA @001AAAAAB +001AAAAAC
        # <- :001 SJOIN 1483250129 #services +nt :+001OR9V02 @*~001DH6901 &*!*@test "*!*@blah.blah '*!*@yes.no
        channel = args[1]
        chandata = self._channels[channel].deepcopy()
        userlist = args[-1].split()

        namelist = []
        log.debug('(%s) handle_sjoin: got userlist %r for %r', self.name, userlist, channel)

        modestring = ''

        # FIXME: Implement edge-case mode conflict handling as documented here:
        # https://www.unrealircd.org/files/docs/technical/serverprotocol.html#S5_1

        changedmodes = set()
        parsedmodes = []
        try:
            if args[2].startswith('+'):
                modestring = args[2:-1] or args[2]
                # Strip extra spaces between the mode argument and the user list, if
                # there are any. XXX: report this as a bug in unreal's s2s protocol?
                modestring = [m for m in modestring if m]
                parsedmodes = self.parse_modes(channel, modestring)
                changedmodes = set(parsedmodes)
        except IndexError:
            pass

        for userpair in userlist:
            # &, ", and ' entries are used for bursting bans:
            # https://www.unrealircd.org/files/docs/technical/serverprotocol.html#S5_1
            if userpair.startswith("&"):
                changedmodes.add(('+b', userpair[1:]))
            elif userpair.startswith('"'):
                changedmodes.add(('+e', userpair[1:]))
            elif userpair.startswith("'"):
                changedmodes.add(('+I', userpair[1:]))
            else:
                # Note: don't be too zealous in matching here or we'll break with nicks
                # like "[abcd]".
                r = re.search(r'([~*@%+]*)(.*)', userpair)
                user = r.group(2)

                if not user:
                    # Userpair with no user? Ignore. XXX: find out how this is even possible...
                    # <- :002 SJOIN 1486361658 #idlerpg :@
                    continue

                user = self._get_UID(user)  # Normalize nicks to UIDs for Unreal 3.2 links
                if user not in self.users:
                    # Work around a potential race when sending kills on join
                    log.debug("(%s) Ignoring user %s in SJOIN to %s, they don't exist anymore", self.name, user, channel)
                    continue

                # Unreal uses slightly different prefixes in SJOIN. +q is * instead of ~,
                # and +a is ~ instead of &.
                modeprefix = (r.group(1) or '').replace("~", "&").replace("*", "~")
                finalprefix = ''

                log.debug('(%s) handle_sjoin: got modeprefix %r for user %r', self.name, modeprefix, user)
                for m in modeprefix:
                    # Iterate over the mapping of prefix chars to prefixes, and
                    # find the characters that match.
                    for char, prefix in self.prefixmodes.items():
                        if m == prefix:
                            finalprefix += char
                namelist.append(user)
                self.users[user].channels.add(channel)

                # Only merge the remote's prefix modes if their TS is smaller or equal to ours.
                changedmodes |= {('+%s' % mode, user) for mode in finalprefix}

                self._channels[channel].users.add(user)

        our_ts = self._channels[channel].ts
        their_ts = int(args[0])
        self.updateTS(numeric, channel, their_ts, changedmodes)

        return {'channel': channel, 'users': namelist, 'modes': parsedmodes,
                'ts': their_ts, 'channeldata': chandata}

    def handle_nick(self, numeric, command, args):
        """Handles NICK changes, and legacy NICK introductions from pre-4.0 servers."""
        if len(args) > 2:
            # Handle legacy NICK introduction here.
            # I don't want to rewrite all the user introduction stuff, so I'll just reorder the arguments
            # so that handle_uid can handle this instead.
            # But since legacy nicks don't have any UIDs attached, we'll have to store the users
            # internally using pseudo UIDs. In other words, we need to convert from this:
            #   <- NICK Global 3 1456843578 services novernet.com services.novernet.com 0 +ioS * :Global Noticer
            #   & nick hopcount timestamp username hostname server service-identifier-token :realname
            #   With NICKIP and VHP enabled:
            #   <- NICK legacy32 2 1470699865 jlu5 localhost unreal32.midnight.vpn jlu5 +iowx hidden-1C620195 AAAAAAAAAAAAAAAAAAAAAQ== :realname
            # to this:
            #   <- :001 UID jlu5 0 1441306929 jlu5 localhost 0018S7901 0 +iowx * hidden-1C620195 fwAAAQ== :realname
            log.debug('(%s) got legacy NICK args: %s', self.name, ' '.join(args))

            new_args = args[:]  # Clone the old args list
            servername = new_args[5].lower()  # Get the name of the users' server.

            # Fake a UID and put it where it belongs in the new-style UID command. These take the
            # NICK@COUNTER, where COUNTER is an int starting at 0 and incremented every time a new
            # user joins.
            fake_uid = self.legacy_uidgen.next_uid(prefix=args[0])
            new_args[5] = fake_uid

            # This adds a dummy cloaked host (equal the real host) to put the displayed host in the
            # right position. As long as the VHP capability is respected, this will propagate +x cloaked
            # hosts from UnrealIRCd 3.2 users. Otherwise, +x host cloaking won't work!
            new_args.insert(-2, args[4])

            log.debug('(%s) translating legacy NICK args to: %s', self.name, ' '.join(new_args))

            return self.handle_uid(servername, 'UID_LEGACY', new_args)
        else:
            # Normal NICK change, just let ts6_common handle it.
            # :70MAAAAAA NICK jlu5-devel 1434744242
            return super().handle_nick(numeric, command, args)

    def handle_mode(self, numeric, command, args):
        # <- :unreal.midnight.vpn MODE #test +bb test!*@* *!*@bad.net
        # <- :unreal.midnight.vpn MODE #test +q jlu5 1444361345
        # <- :unreal.midnight.vpn MODE #test +ntCo jlu5 1444361345
        # <- :unreal.midnight.vpn MODE #test +mntClfo 5 [10t]:5  jlu5 1444361345
        # <- :jlu5 MODE #services +v jlu5

        # This seems pretty relatively inconsistent - why do some commands have a TS at the end while others don't?
        # Answer: the first syntax (MODE sent by SERVER) is used for channel bursts - according to Unreal 3.2 docs,
        # the last argument should be interpreted as a timestamp ONLY if it is a number and the sender is a server.
        # Ban bursting does not give any TS, nor do normal users setting modes. SAMODE is special though, it will
        # send 0 as a TS argument (which should be ignored unless breaking the internal channel TS is desired).

        # Also, we need to get rid of that extra space following the +f argument. :|
        if self.is_channel(args[0]):
            channel = args[0]
            oldobj = self._channels[channel].deepcopy()

            modes = [arg for arg in args[1:] if arg]  # normalize whitespace
            parsedmodes = self.parse_modes(channel, modes)

            if parsedmodes:
                if parsedmodes[0][0] == '+&':
                    # UnrealIRCd uses a & virtual mode to denote mode bounces, meaning that an
                    # attempt to set modes by us was rejected for some reason (usually due to
                    # timestamps). Drop the mode change to prevent mode floods.
                    log.debug("(%s) Received mode bounce %s in channel %s! Our TS: %s",
                              self.name, modes, channel, self._channels[channel].ts)
                    return

                self.apply_modes(channel, parsedmodes)

            if numeric in self.servers and args[-1].isdigit():
                # Sender is a server AND last arg is number. Perform TS updates.
                their_ts = int(args[-1])
                if their_ts > 0:
                    self.updateTS(numeric, channel, their_ts)
            return {'target': channel, 'modes': parsedmodes, 'channeldata': oldobj}
        else:
            # User mode change
            target = self._get_UID(args[0])
            return self._handle_umode(target, self.parse_modes(target, args[1:]))

    def _check_cloak_change(self, uid, parsedmodes):
        """
        Checks whether +x/-x was set in the mode query, and changes the
        hostname of the user given to or from their cloaked host if True.
        """

        userobj = self.users[uid]
        final_modes = userobj.modes
        oldhost = userobj.host

        if (('+x', None) in parsedmodes and ('t', None) not in final_modes) \
                or (('-t', None) in parsedmodes and ('x', None) in final_modes):
            # If either:
            #    1) +x is being set, and the user does NOT have +t.
            #    2) -t is being set, but the user has +x set already.
            # We should update the user's host to their cloaked host and send
            # out a hook payload saying that the host has changed.
            newhost = userobj.host = userobj.cloaked_host
        elif ('-x', None) in parsedmodes or ('-t', None) in parsedmodes:
            # Otherwise, if either:
            #    1) -x is being set.
            #    2) -t is being set, but the person doesn't have +x set already.
            #       (the case where the person DOES have +x is handled above)
            # Restore the person's host to the uncloaked real host.
            newhost = userobj.host = userobj.realhost
        else:
            # Nothing changed, just return.
            return

        if newhost != oldhost:
            # Only send a payload if the old and new hosts are different.
            self.call_hooks([uid, 'SETHOST',
                               {'target': uid, 'newhost': newhost}])

    def handle_svsmode(self, numeric, command, args):
        """Handles SVSMODE, used by services for setting user modes on others."""
        # <- :source SVSMODE target +usermodes
        target = self._get_UID(args[0])

        return self._handle_umode(target, self.parse_modes(target, args[1:]))

    def handle_svs2mode(self, sender, command, args):
        """
        Handles SVS2MODE, which sets services login information on the given target.
        """
        # In a nutshell: check for the +d argument: if it's an integer, ignore
        # it and set the user's account name to their nick. Otherwise, treat the
        # parameter as the new account name (this is known as logging in AS some account,
        # which is supported by atheme and Anope 2.x).

        # Logging in (with account info, atheme):
        # <- :NickServ SVS2MODE jlu5 +rd jlu5

        # Logging in (without account info, anope 2.0?):
        # <- :NickServ SVS2MODE 001WCO6YK +r

        # Logging in (without account info, anope 1.8):
        # Note: ignore the timestamp.
        # <- :services.abc.net SVS2MODE jlu5 +rd 1470696723

        # Logging out (atheme):
        # <- :NickServ SVS2MODE jlu5 -r+d 0

        # Logging out (anope 1.8):
        # <- :services.abc.net SVS2MODE jlu5 -r+d 1

        # Logging out (anope 2.0):
        # <- :NickServ SVS2MODE 009EWLA03 -r

        # Logging in to account from a different nick (atheme):
        # Note: no +r is being set.
        # <- :NickServ SVS2MODE somenick +d jlu5

        # Logging in to account from a different nick (anope):
        # <- :NickServ SVS2MODE 001SALZ01 +d jlu5
        # <- :NickServ SVS2MODE 001SALZ01 +r

        target = self._get_UID(args[0])
        parsedmodes = self.parse_modes(target, args[1:])

        if ('+r', None) in parsedmodes:
            # Umode +r is being set (log in)
            try:
                # Try to get the account name (mode argument for +d)
                account = args[2]
            except IndexError:
                # If one doesn't exist, make it the same as the nick, but only if the account name
                # wasn't set already.
                if not self.users[target].services_account:
                    account = self.get_friendly_name(target)
                else:
                    return
            else:
                if account.isdigit():
                    # If the +d argument is a number, ignore it and set the account name to the nick.
                    account = self.get_friendly_name(target)

        elif ('-r', None) in parsedmodes:
            # Umode -r being set.

            if not self.users[target].services_account:
                # User already has no account; ignore.
                return

            account = ''
        elif ('+d', None) in parsedmodes:
            # Nick identification status wasn't changed, but services account was.
            account = args[2]
            if account == '0':  # +d 0 means logout
                account = ''
        else:
            return

        self.call_hooks([target, 'CLIENT_SERVICES_LOGIN', {'text': account}])
        # The internal mode +d used for services stamps clashes with the DEAF mode, so don't parse it as
        # an actual mode mode parsing.
        return self._handle_umode(target, [mode for mode in parsedmodes if mode[0][-1] != 'd'])

    def _handle_umode(self, target, parsedmodes):
        """Internal helper function to parse umode changes."""
        if not parsedmodes:
            return

        self.apply_modes(target, parsedmodes)

        self._check_oper_status_change(target, parsedmodes)
        self._check_cloak_change(target, parsedmodes)

        return {'target': target, 'modes': parsedmodes}

    def handle_umode2(self, source, command, args):
        """Handles UMODE2, used to set user modes on oneself."""
        # <- :jlu5 UMODE2 +W
        target = self._get_UID(source)
        return self._handle_umode(target, self.parse_modes(target, args))

    def handle_topic(self, numeric, command, args):
        """Handles the TOPIC command."""
        # <- jlu5 TOPIC #services jlu5 1444699395 :weeee
        # <- TOPIC #services devel.relay 1452399682 :test
        channel = args[0]
        topic = args[-1]
        setter = args[1]
        ts = args[2]

        oldtopic = self._channels[channel].topic
        self._channels[channel].topic = topic
        self._channels[channel].topicset = True

        return {'channel': channel, 'setter': setter, 'ts': ts, 'text': topic,
                'oldtopic': oldtopic}

    def handle_setident(self, numeric, command, args):
        """Handles SETIDENT, used for self ident changes."""
        # <- :70MAAAAAB SETIDENT test
        self.users[numeric].ident = newident = args[0]
        return {'target': numeric, 'newident': newident}

    def handle_sethost(self, numeric, command, args):
        """Handles CHGHOST, used for self hostname changes."""
        # <- :70MAAAAAB SETIDENT some.host
        self.users[numeric].host = newhost = args[0]

        # When SETHOST or CHGHOST is used, modes +xt are implicitly set on the
        # target.
        self.apply_modes(numeric, [('+x', None), ('+t', None)])

        return {'target': numeric, 'newhost': newhost}

    def handle_setname(self, numeric, command, args):
        """Handles SETNAME, used for self real name/gecos changes."""
        # <- :70MAAAAAB SETNAME :afdsafasf
        self.users[numeric].realname = newgecos = args[0]
        return {'target': numeric, 'newgecos': newgecos}

    def handle_chgident(self, source, command, args):
        """Handles CHGIDENT, used for denoting ident changes."""
        # <- :jlu5 CHGIDENT jlu5 test
        target = self._get_UID(args[0])

        # Bounce attempts to change fields of protected PyLink clients
        if self.is_internal_client(target):
            log.warning("(%s) Bouncing attempt from %s to change ident of PyLink client %s",
                        self.name, self.get_friendly_name(source), self.get_friendly_name(target))
            self.update_client(target, 'IDENT', self.users[target].ident)
            return

        self.users[target].ident = newident = args[1]
        return {'target': target, 'newident': newident}

    def handle_chghost(self, source, command, args):
        """Handles CHGHOST, used for denoting hostname changes."""
        # <- :jlu5 CHGHOST jlu5 some.host
        target = self._get_UID(args[0])
        # Bounce attempts to change fields of protected PyLink clients
        if self.is_internal_client(target):
            log.warning("(%s) Bouncing attempt from %s to change host of PyLink client %s",
                        self.name, self.get_friendly_name(source), self.get_friendly_name(target))
            self.update_client(target, 'HOST', self.users[target].host)
            return

        self.users[target].host = newhost = args[1]

        # When SETHOST or CHGHOST is used, modes +xt are implicitly set on the
        # target.
        self.apply_modes(target, [('+x', None), ('+t', None)])

        return {'target': target, 'newhost': newhost}

    def handle_chgname(self, source, command, args):
        """Handles CHGNAME, used for denoting real name/gecos changes."""
        # <- :jlu5 CHGNAME jlu5 :afdsafasf
        target = self._get_UID(args[0])
        # Bounce attempts to change fields of protected PyLink clients
        if self.is_internal_client(target):
            log.warning("(%s) Bouncing attempt from %s to change gecos of PyLink client %s",
                        self.name, self.get_friendly_name(source), self.get_friendly_name(target))
            self.update_client(target, 'REALNAME', self.users[target].realname)
            return

        self.users[target].realname = newgecos = args[1]
        return {'target': target, 'newgecos': newgecos}

    def handle_tsctl(self, source, command, args):
        """Handles /TSCTL alltime requests."""
        # <- :jlu5 TSCTL alltime

        if args[0] == 'alltime':
            self._send_with_prefix(self.sid, 'NOTICE %s :*** Server=%s time()=%d' % (source, self.hostname(), time.time()))

Class = UnrealProtocol
