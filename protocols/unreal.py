"""
unreal.py: UnrealIRCd 4.0 protocol module for PyLink.
"""

import time
import sys
import os
import codecs
import socket
import re

from pylinkirc import utils
from pylinkirc.classes import *
from pylinkirc.log import log
from pylinkirc.protocols.ts6_common import *

class UnrealProtocol(TS6BaseProtocol):
    def __init__(self, irc):
        super().__init__(irc)
        # Set our case mapping (rfc1459 maps "\" and "|" together, for example)
        self.casemapping = 'ascii'
        self.proto_ver = 4000
        self.min_proto_ver = 4000
        self.hook_map = {'UMODE2': 'MODE', 'SVSKILL': 'KILL', 'SVSMODE': 'MODE',
                         'SVS2MODE': 'MODE', 'SJOIN': 'JOIN', 'SETHOST': 'CHGHOST',
                         'SETIDENT': 'CHGIDENT', 'SETNAME': 'CHGNAME',
                         'EOS': 'ENDBURST'}

        self.caps = []
        self.irc.prefixmodes = {'q': '~', 'a': '&', 'o': '@', 'h': '%', 'v': '+'}

        self.needed_caps = ["VL", "SID", "CHANMODES", "NOQUIT", "SJ3", "NICKIP", "UMODE2"]

        # Some command aliases
        self.handle_svskill = self.handle_kill

    def _expandPUID(self, uid):
        """
        Returns the outgoing nick for the given UID. For PUIDs (used to store UID-less
        3.2 users), this will change the PUID given to the actual user's nick,
        so that that the older IRCds can understand it.
        """
        if uid in self.irc.users and '@' in uid:
            # UID exists and has a @ in it, meaning it's a PUID (orignick@counter style).
            # Return this user's nick accordingly.
            nick = self.irc.users[uid].nick
            log.debug('(%s) Mangling target PUID %s to nick %s', self.irc.name, uid, nick)
            return nick
        return uid

    ### OUTGOING COMMAND FUNCTIONS
    def spawnClient(self, nick, ident='null', host='null', realhost=None, modes=set(),
            server=None, ip='0.0.0.0', realname=None, ts=None, opertype='IRC Operator',
            manipulatable=False):
        """
        Spawns a new client with the given options.

        Note: No nick collision / valid nickname checks are done here; it is
        up to plugins to make sure they don't introduce anything invalid.
        """
        server = server or self.irc.sid
        if not self.irc.isInternalServer(server):
            raise ValueError('Server %r is not a PyLink server!' % server)

        # Unreal 4.0 uses TS6-style UIDs. They don't start from AAAAAA like other IRCd's
        # do, but that doesn't matter to us...
        uid = self.uidgen[server].next_uid()

        ts = ts or int(time.time())
        realname = realname or self.irc.botdata['realname']
        realhost = realhost or host

        # Add +xt so that vHost cloaking always works.
        modes = set(modes)  # Ensure type safety
        modes |= {('+x', None), ('+t', None)}

        raw_modes = self.irc.joinModes(modes)
        u = self.irc.users[uid] = IrcUser(nick, ts, uid, ident=ident, host=host, realname=realname,
            realhost=realhost, ip=ip, manipulatable=manipulatable, opertype=opertype)
        self.irc.applyModes(uid, modes)
        self.irc.servers[server].users.add(uid)

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

        # <- :001 UID GL 0 1441306929 gl localhost 0018S7901 0 +iowx * midnight-1C620195 fwAAAQ== :realname
        self._send(server, "UID {nick} 0 {ts} {ident} {realhost} {uid} 0 {modes} "
                           "{host} * {ip} :{realname}".format(ts=ts, host=host,
                                nick=nick, ident=ident, uid=uid,
                                modes=raw_modes, realname=realname,
                                realhost=realhost, ip=encoded_ip))

        return u

    def join(self, client, channel):
        """Joins a PyLink client to a channel."""
        channel = self.irc.toLower(channel)
        if not self.irc.isInternalClient(client):
            raise LookupError('No such PyLink client exists.')
        self._send(client, "JOIN %s" % channel)
        self.irc.channels[channel].users.add(client)
        self.irc.users[client].channels.add(channel)

    def sjoin(self, server, channel, users, ts=None, modes=set()):
        """Sends an SJOIN for a group of users to a channel.

        The sender should always be a server (SID). TS is optional, and defaults
        to the one we've stored in the channel state if not given.
        <users> is a list of (prefix mode, UID) pairs:

        Example uses:
            sjoin('100', '#test', [('', '100AAABBC'), ('o', 100AAABBB'), ('v', '100AAADDD')])
            sjoin(self.irc.sid, '#test', [('o', self.irc.pseudoclient.uid)])

        Note that for UnrealIRCd, no mode data is sent in an SJOIN command, only
        The channel name, TS, and user list.
        """
        # <- :001 SJOIN 1444361345 #test :001DJ1O02
        # The nicklist consists of users joining the channel, with status prefixes for
        # their status ('@+', '@', '+' or ''), for example:
        # '@+1JJAAAAAB +2JJAAAA4C 1JJAAAADS'.
        channel = self.irc.toLower(channel)
        server = server or self.irc.sid
        assert users, "sjoin: No users sent?"
        if not server:
            raise LookupError('No such PyLink server exists.')

        changedmodes = set(modes or self.irc.channels[channel].modes)
        orig_ts = self.irc.channels[channel].ts
        ts = ts or orig_ts
        uids = []
        namelist = []

        for userpair in users:
            assert len(userpair) == 2, "Incorrect format of userpair: %r" % userpair
            prefixes, user = userpair

            # Unreal uses slightly different prefixes in SJOIN. +q is * instead of ~,
            # and +a is ~ instead of &.
            # &, ", and ' are used for bursting bans.
            sjoin_prefixes = {'q': '*', 'a': '~', 'o': '@', 'h': '%', 'v': '+'}
            prefixchars = ''.join([sjoin_prefixes.get(prefix, '') for prefix in prefixes])

            if prefixchars:
                changedmodes |= {('+%s' % prefix, user) for prefix in prefixes}

            namelist.append(prefixchars+user)
            uids.append(user)

            try:
                self.irc.users[user].channels.add(channel)
            except KeyError:  # Not initialized yet?
                log.debug("(%s) sjoin: KeyError trying to add %r to %r's channel list?", self.irc.name, channel, user)

        namelist = ' '.join(namelist)

        self._send(server, "SJOIN {ts} {channel} :{users}".format(
                   ts=ts, users=namelist, channel=channel))

        # Burst modes separately. No really, this is what I see UnrealIRCd do! It sends
        # JOINs on burst and then MODE!
        if modes:
            self.mode(server, channel, modes, ts=ts)

        self.irc.channels[channel].users.update(uids)

        self.updateTS(server, channel, ts, changedmodes)

    def ping(self, source=None, target=None):
        """Sends a PING to a target server. Periodic PINGs are sent to our uplink
        automatically by the Irc() internals; plugins shouldn't have to use this."""
        source = source or self.irc.sid
        target = target or self.irc.uplink
        if not (target is None or source is None):
            self._send(source, 'PING %s %s' % (self.irc.servers[source].name, self.irc.servers[target].name))

    def mode(self, numeric, target, modes, ts=None):
        """
        Sends mode changes from a PyLink client/server. The mode list should be
        a list of (mode, arg) tuples, i.e. the format of utils.parseModes() output.
        """
        # <- :unreal.midnight.vpn MODE #test +ntCo GL 1444361345

        if (not self.irc.isInternalClient(numeric)) and \
                (not self.irc.isInternalServer(numeric)):
            raise LookupError('No such PyLink client/server exists.')

        self.irc.applyModes(target, modes)
        joinedmodes = self.irc.joinModes(modes)
        if utils.isChannel(target):
            # The MODE command is used for channel mode changes only
            ts = ts or self.irc.channels[self.irc.toLower(target)].ts
            self._send(numeric, 'MODE %s %s %s' % (target, joinedmodes, ts))
        else:
            # For user modes, the only way to set modes (for non-U:Lined servers)
            # is through UMODE2, which sets the modes on the caller.
            # U:Lines can use SVSMODE/SVS2MODE, but I won't expect people to
            # U:Line a PyLink daemon...
            if not self.irc.isInternalClient(target):
                raise ProtocolError('Cannot force mode change on external clients!')
            self._send(target, 'UMODE2 %s' % joinedmodes)

    def topicBurst(self, numeric, target, text):
        """Sends a TOPIC change from a PyLink server."""
        if not self.irc.isInternalServer(numeric):
            raise LookupError('No such PyLink server exists.')
        self._send(numeric, 'TOPIC %s :%s' % (target, text))
        self.irc.channels[target].topic = text
        self.irc.channels[target].topicset = True

    def updateClient(self, target, field, text):
        """Updates the ident, host, or realname of any connected client."""
        field = field.upper()

        if field not in ('IDENT', 'HOST', 'REALNAME', 'GECOS'):
            raise NotImplementedError("Changing field %r of a client is "
                                      "unsupported by this protocol." % field)

        if self.irc.isInternalClient(target):
            # It is one of our clients, use SETIDENT/HOST/NAME.
            if field == 'IDENT':
                self.irc.users[target].ident = text
                self._send(target, 'SETIDENT %s' % text)
            elif field == 'HOST':
                self.irc.users[target].host = text
                self._send(target, 'SETHOST %s' % text)
            elif field in ('REALNAME', 'GECOS'):
                self.irc.users[target].realname = text
                self._send(target, 'SETNAME :%s' % text)
        else:
            # It is a client on another server, use CHGIDENT/HOST/NAME.
            if field == 'IDENT':
                self.irc.users[target].ident = text
                self._send(self.irc.sid, 'CHGIDENT %s %s' % (target, text))

                # Send hook payloads for other plugins to listen to.
                self.irc.callHooks([self.irc.sid, 'CHGIDENT',
                                   {'target': target, 'newident': text}])

            elif field == 'HOST':
                self.irc.users[target].host = text
                self._send(self.irc.sid, 'CHGHOST %s %s' % (target, text))

                self.irc.callHooks([self.irc.sid, 'CHGHOST',
                                   {'target': target, 'newhost': text}])

            elif field in ('REALNAME', 'GECOS'):
                self.irc.users[target].realname = text
                self._send(self.irc.sid, 'CHGNAME %s :%s' % (target, text))

                self.irc.callHooks([self.irc.sid, 'CHGNAME',
                                   {'target': target, 'newgecos': text}])

    def invite(self, numeric, target, channel):
        """Sends an INVITE from a PyLink client.."""
        if not self.irc.isInternalClient(numeric):
            raise LookupError('No such PyLink client exists.')
        self._send(numeric, 'INVITE %s %s' % (target, channel))

    def knock(self, numeric, target, text):
        """Sends a KNOCK from a PyLink client."""
        # KNOCKs in UnrealIRCd are actually just specially formatted NOTICEs,
        # sent to all ops in a channel.
        # <- :unreal.midnight.vpn NOTICE @#test :[Knock] by GL|!gl@hidden-1C620195 (test)
        assert utils.isChannel(target), "Can only knock on channels!"
        sender = self.irc.getServer(numeric)
        s = '[Knock] by %s (%s)' % (self.irc.getHostmask(numeric), text)
        self._send(sender, 'NOTICE @%s :%s' % (target, s))

    ### HANDLERS

    def connect(self):
        """Initializes a connection to a server."""
        ts = self.irc.start_ts
        self.irc.prefixmodes = {'q': '~', 'a': '&', 'o': '@', 'h': '%', 'v': '+'}

        # Track usages of legacy (Unreal 3.2) nicks.
        self.legacy_uidgen = utils.PUIDGenerator('U32user')

        self.irc.umodes.update({'deaf': 'd', 'invisible': 'i', 'hidechans': 'p',
                                'protected': 'q', 'registered': 'r',
                                'snomask': 's', 'vhost': 't', 'wallops': 'w',
                                'bot': 'B', 'cloak': 'x', 'ssl': 'z',
                                'filter': 'G', 'hideoper': 'H', 'hideidle': 'I',
                                'regdeaf': 'R', 'servprotect': 'S',
                                'noctcp': 'T', 'showwhois': 'W',
                                '*A': '', '*B': '', '*C': '', '*D': 'dipqrstwBxzGHIRSTW'})

        f = self.irc.send
        host = self.irc.serverdata["hostname"]

        f('PASS :%s' % self.irc.serverdata["sendpass"])
        # https://github.com/unrealircd/unrealircd/blob/2f8cb55e/doc/technical/protoctl.txt
        # We support the following protocol features:
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
        f('PROTOCTL SJ3 NOQUIT NICKv2 VL UMODE2 PROTOCTL NICKIP EAUTH=%s SID=%s VHP ESVID' % (self.irc.serverdata["hostname"], self.irc.sid))
        sdesc = self.irc.serverdata.get('serverdesc') or self.irc.botdata['serverdesc']
        f('SERVER %s 1 U%s-h6e-%s :%s' % (host, self.proto_ver, self.irc.sid, sdesc))
        f('NETINFO 1 %s %s * 0 0 0 :%s' % (self.irc.start_ts, self.proto_ver, self.irc.serverdata.get("netname", self.irc.name)))
        self._send(self.irc.sid, 'EOS')

    def handle_eos(self, numeric, command, args):
        """EOS is used to denote end of burst."""
        return {}

    def handle_uid(self, numeric, command, args):
        # <- :001 UID GL 0 1441306929 gl localhost 0018S7901 0 +iowx * midnight-1C620195 fwAAAQ== :realname
        # <- :001 UID GL| 0 1441389007 gl 10.120.0.6 001ZO8F03 0 +iwx * 391A9CB9.26A16454.D9847B69.IP CngABg== :realname
        # arguments: nick, hopcount?, ts, ident, real-host, UID, services account (0 if none), modes,
        #            displayed host, cloaked (+x) host, base64-encoded IP, and realname
        nick = args[0]
        ts, ident, realhost, uid, accountname, modestring, host = args[2:9]

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

        self.irc.users[uid] = IrcUser(nick, ts, uid, ident, host, realname, realhost, ip)
        self.irc.servers[numeric].users.add(uid)

        # Handle user modes
        parsedmodes = self.irc.parseModes(uid, [modestring])
        self.irc.applyModes(uid, parsedmodes)

        # The cloaked (+x) host is completely separate from the displayed host
        # and real host in that it is ONLY shown if the user is +x (cloak mode
        # enabled) but NOT +t (vHost set).
        self.irc.users[uid].cloaked_host = args[9]

        if ('+o', None) in parsedmodes:
            # If +o being set, call the CLIENT_OPERED internal hook.
            self.irc.callHooks([uid, 'CLIENT_OPERED', {'text': 'IRC Operator'}])

        if ('+x', None) not in parsedmodes:
            # If +x is not set, update to use the person's real host.
            self.irc.users[uid].host = realhost

        # Set the account name if present: if this is a number, set it to the user nick.
        if ('+r', None) in parsedmodes and accountname.isdigit():
            accountname = nick

        if not accountname.isdigit():
            self.irc.callHooks([uid, 'CLIENT_SERVICES_LOGIN', {'text': accountname}])

        return {'uid': uid, 'ts': ts, 'nick': nick, 'realhost': realhost, 'host': host, 'ident': ident, 'ip': ip}

    def handle_pass(self, numeric, command, args):
        # <- PASS :abcdefg
        if args[0] != self.irc.serverdata['recvpass']:
            raise ProtocolError("Error: RECVPASS from uplink does not match configuration!")

    def handle_ping(self, numeric, command, args):
        if numeric == self.irc.uplink:
            self.irc.send('PONG %s :%s' % (self.irc.serverdata['hostname'], args[-1]))

    def handle_pong(self, source, command, args):
        log.debug('(%s) Ping received from %s for %s.', self.irc.name, source, args[-1])
        if source in (self.irc.uplink, self.irc.servers[self.irc.uplink].name) and args[-1] == self.irc.serverdata['hostname']:
            log.debug('(%s) Set self.irc.lastping.', self.irc.name)
            self.irc.lastping = time.time()

    def handle_server(self, numeric, command, args):
        """Handles the SERVER command, which is used for both authentication and
        introducing legacy (non-SID) servers."""
        # <- SERVER unreal.midnight.vpn 1 :U3999-Fhin6OoEM UnrealIRCd test server
        sname = args[0]
        if numeric == self.irc.uplink and not self.irc.connected.is_set():  # We're doing authentication
            for cap in self.needed_caps:
                if cap not in self.caps:
                    raise ProtocolError("Not all required capabilities were met "
                                        "by the remote server. Your version of UnrealIRCd "
                                        "is probably too old! (Got: %s, needed: %s)" %
                                        (sorted(self.caps), sorted(self.needed_caps)))

            sdesc = args[-1].split(" ", 1)
            # Get our protocol version. I really don't know why the version and the server
            # description aren't two arguments instead of one... -GLolol
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
            self.irc.servers[numeric] = IrcServer(None, sname, desc=sdesc)

            # Set irc.connected to True, meaning that protocol negotiation passed.
            log.debug('(%s) self.irc.connected set!', self.irc.name)
            self.irc.connected.set()
        else:
            # Legacy (non-SID) servers can still be introduced using the SERVER command.
            # <- :services.int SERVER a.bc 2 :(H) [GL] a
            servername = args[0].lower()
            sdesc = args[-1]
            self.irc.servers[servername] = IrcServer(numeric, servername, desc=sdesc)
            return {'name': servername, 'sid': None, 'text': sdesc}

    def handle_sid(self, numeric, command, args):
        """Handles the SID command, used for introducing remote servers by our uplink."""
        # <- SID services.int 2 00A :Shaltúre IRC Services
        sname = args[0].lower()
        sid = args[2]
        sdesc = args[-1]
        self.irc.servers[sid] = IrcServer(numeric, sname, desc=sdesc)
        return {'name': sname, 'sid': sid, 'text': sdesc}

    def handle_squit(self, numeric, command, args):
        """Handles the SQUIT command."""
        # <- SQUIT services.int :Read error
        # Convert the server name to a SID...
        args[0] = self._getSid(args[0])
        # Then, use the SQUIT handler in TS6BaseProtocol as usual.
        return super().handle_squit(numeric, 'SQUIT', args)

    def handle_protoctl(self, numeric, command, args):
        """Handles protocol negotiation."""

        cmodes = {'noknock': 'K', 'limit': 'l', 'registered': 'r', 'flood_unreal': 'f',
                  'censor': 'G', 'noextmsg': 'n', 'invex': 'I', 'permanent': 'P',
                  'sslonly': 'z', 'operonly': 'O', 'moderated': 'm', 'blockcolor': 'c',
                  'regmoderated': 'M', 'noctcp': 'C', 'secret': 's', 'ban': 'b',
                  'nokick': 'Q', 'private': 'p', 'stripcolor': 'S', 'key': 'k',
                  'op': 'o', 'voice': 'v', 'regonly': 'R', 'noinvite': 'V',
                  'banexception': 'e', 'nonick': 'N', 'issecure': 'Z', 'topiclock': 't',
                  'nonotice': 'T', 'delayjoin': 'D', 'inviteonly': 'i'}

        # Make a list of all our capability names.
        self.caps += [arg.split('=')[0] for arg in args]

        # <- PROTOCTL NOQUIT NICKv2 SJOIN SJOIN2 UMODE2 VL SJ3 TKLEXT TKLEXT2 NICKIP ESVID
        # <- PROTOCTL CHANMODES=beI,k,l,psmntirzMQNRTOVKDdGPZSCc NICKCHARS= SID=001 MLOCK TS=1441314501 EXTSWHOIS
        for cap in args:
            if cap.startswith('SID'):
                self.irc.uplink = cap.split('=', 1)[1]
            elif cap.startswith('CHANMODES'):
                # Parse all the supported channel modes.
                supported_cmodes = cap.split('=', 1)[1]
                self.irc.cmodes['*A'], self.irc.cmodes['*B'], self.irc.cmodes['*C'], self.irc.cmodes['*D'] = supported_cmodes.split(',')
                for namedmode, modechar in cmodes.items():
                    if modechar in supported_cmodes:
                        self.irc.cmodes[namedmode] = modechar
                self.irc.cmodes['*B'] += 'f'  # Add +f to the list too, dunno why it isn't there.

        # Add in the supported prefix modes.
        self.irc.cmodes.update({'halfop': 'h', 'admin': 'a', 'owner': 'q',
                                'op': 'o', 'voice': 'v'})

    def handle_privmsg(self, source, command, args):
        # Convert nicks to UIDs, where they exist.
        target = self._getUid(args[0])
        # We use lowercase channels internally, but uppercase UIDs.
        if utils.isChannel(target):
            target = self.irc.toLower(target)
        return {'target': target, 'text': args[1]}
    handle_notice = handle_privmsg

    def handle_join(self, numeric, command, args):
        """Handles the UnrealIRCd JOIN command."""
        # <- :GL JOIN #pylink,#test
        if args[0] == '0':
            # /join 0; part the user from all channels
            oldchans = self.irc.users[numeric].channels.copy()
            log.debug('(%s) Got /join 0 from %r, channel list is %r',
                      self.irc.name, numeric, oldchans)
            for ch in oldchans:
                self.irc.channels[ch].users.discard(numeric)
                self.irc.users[numeric].channels.discard(ch)
            return {'channels': oldchans, 'text': 'Left all channels.', 'parse_as': 'PART'}

        else:
            for channel in args[0].split(','):
                # Normalize channel case.
                channel = self.irc.toLower(channel)

                c = self.irc.channels[channel]

                self.irc.users[numeric].channels.add(channel)
                self.irc.channels[channel].users.add(numeric)
                # Call hooks manually, because one JOIN command in UnrealIRCd can
                # have multiple channels...
                self.irc.callHooks([numeric, command, {'channel': channel, 'users': [numeric], 'modes':
                                                       c.modes, 'ts': c.ts}])

    def handle_sjoin(self, numeric, command, args):
        """Handles the UnrealIRCd SJOIN command."""
        # <- :001 SJOIN 1444361345 #test :001DJ1O02
        # memberlist should be a list of UIDs with their channel status prefixes, as
        # in ":001AAAAAA @001AAAAAB +001AAAAAC".
        # Interestingly, no modes are ever sent in this command as far as I've seen.
        channel = self.irc.toLower(args[1])
        chandata = self.irc.channels[channel].deepcopy()
        userlist = args[-1].split()

        namelist = []
        log.debug('(%s) handle_sjoin: got userlist %r for %r', self.irc.name, userlist, channel)

        # Keep track of other modes that are added due to prefix modes being joined too.
        changedmodes = set(self.irc.channels[channel].modes)

        for userpair in userlist:
            if userpair.startswith("&\"'"):  # TODO: handle ban bursts too
                # &, ", and ' entries are used for bursting bans:
                # https://www.unrealircd.org/files/docs/technical/serverprotocol.html#S5_1
                break
            r = re.search(r'([^\w]*)(.*)', userpair)
            user = r.group(2)
            # Unreal uses slightly different prefixes in SJOIN. +q is * instead of ~,
            # and +a is ~ instead of &.
            modeprefix = (r.group(1) or '').replace("~", "&").replace("*", "~")
            finalprefix = ''
            assert user, 'Failed to get the UID from %r; our regex needs updating?' % userpair
            log.debug('(%s) handle_sjoin: got modeprefix %r for user %r', self.irc.name, modeprefix, user)
            for m in modeprefix:
                # Iterate over the mapping of prefix chars to prefixes, and
                # find the characters that match.
                for char, prefix in self.irc.prefixmodes.items():
                    if m == prefix:
                        finalprefix += char
            namelist.append(user)
            self.irc.users[user].channels.add(channel)

            # Only merge the remote's prefix modes if their TS is smaller or equal to ours.
            changedmodes |= {('+%s' % mode, user) for mode in finalprefix}

            self.irc.channels[channel].users.add(user)

        our_ts = self.irc.channels[channel].ts
        their_ts = int(args[0])
        self.updateTS(numeric, channel, their_ts, changedmodes)

        return {'channel': channel, 'users': namelist, 'modes': self.irc.channels[channel].modes,
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
            #   <- NICK GL32 2 1470699865 gl localhost unreal32.midnight.vpn GL +iowx hidden-1C620195 AAAAAAAAAAAAAAAAAAAAAQ== :realname
            # to this:
            #   <- :001 UID GL 0 1441306929 gl localhost 0018S7901 0 +iowx * hidden-1C620195 fwAAAQ== :realname
            log.debug('(%s) got legacy NICK args: %s', self.irc.name, ' '.join(args))

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

            log.debug('(%s) translating legacy NICK args to: %s', self.irc.name, ' '.join(new_args))

            return self.handle_uid(servername, 'UID_LEGACY', new_args)
        else:
            # Normal NICK change, just let ts6_common handle it.
            # :70MAAAAAA NICK GL-devel 1434744242
            return super().handle_nick(numeric, command, args)

    def handle_mode(self, numeric, command, args):
        # <- :unreal.midnight.vpn MODE #test +bb test!*@* *!*@bad.net
        # <- :unreal.midnight.vpn MODE #test +q GL 1444361345
        # <- :unreal.midnight.vpn MODE #test +ntCo GL 1444361345
        # <- :unreal.midnight.vpn MODE #test +mntClfo 5 [10t]:5  GL 1444361345
        # <- :GL MODE #services +v GL

        # This seems pretty relatively inconsistent - why do some commands have a TS at the end while others don't?
        # Answer: the first syntax (MODE sent by SERVER) is used for channel bursts - according to Unreal 3.2 docs,
        # the last argument should be interpreted as a timestamp ONLY if it is a number and the sender is a server.
        # Ban bursting does not give any TS, nor do normal users setting modes. SAMODE is special though, it will
        # send 0 as a TS argument (which should be ignored unless breaking the internal channel TS is desired).

        # Also, we need to get rid of that extra space following the +f argument. :|
        if utils.isChannel(args[0]):
            channel = self.irc.toLower(args[0])
            oldobj = self.irc.channels[channel].deepcopy()

            modes = list(filter(None, args[1:]))  # normalize whitespace
            parsedmodes = self.irc.parseModes(channel, modes)

            if parsedmodes:
                if parsedmodes[0][0] == '+&':
                    # UnrealIRCd uses a & virtual mode to denote mode bounces, meaning that an
                    # attempt to set modes by us was rejected for some reason (usually due to
                    # timestamps). Drop the mode change to prevent mode floods.
                    log.debug("(%s) Received mode bounce %s in channel %s! Our TS: %s",
                              self.irc.name, modes, channel, self.irc.channels[channel].ts)
                    return

                self.irc.applyModes(channel, parsedmodes)

            if numeric in self.irc.servers and args[-1].isdigit():
                # Sender is a server AND last arg is number. Perform TS updates.
                their_ts = int(args[-1])
                if their_ts > 0:
                    self.updateTS(numeric, channel, their_ts)
            return {'target': channel, 'modes': parsedmodes, 'channeldata': oldobj}
        else:
            log.warning("(%s) received MODE for non-channel target: %r",
                        self.irc.name, args)
            raise NotImplementedError

    def checkCloakChange(self, uid, parsedmodes):
        """
        Checks whether +x/-x was set in the mode query, and changes the
        hostname of the user given to or from their cloaked host if True.
        """

        userobj = self.irc.users[uid]
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
            self.irc.callHooks([uid, 'SETHOST',
                               {'target': uid, 'newhost': newhost}])

    def handle_svsmode(self, numeric, command, args):
        """Handles SVSMODE, used by services for setting user modes on others."""
        # <- :source SVSMODE target +usermodes
        target = self._getUid(args[0])
        modes = args[1:]

        parsedmodes = self.irc.parseModes(target, modes)
        self.irc.applyModes(target, parsedmodes)

        # If +x/-x is being set, update cloaked host info.
        self.checkCloakChange(target, parsedmodes)

        return {'target': target, 'modes': parsedmodes}

    def handle_svs2mode(self, sender, command, args):
        """
        Handles SVS2MODE, which sets services login information on the given target.
        """
        # Once again this syntax is inconsistent and poorly documented. +d sets a
        # "services stamp" that some services packages use as an account name field,
        # while others simply use for tracking the login time? In a nutshell: check
        # for the +d argument: if it's an integer, ignore it and set accountname to
        # the user's nick. Otherwise, treat the parameter as a nick.

        # Logging in (with account info, atheme):
        # <- :NickServ SVS2MODE GL +rd GL

        # Logging in (without account info, anope 2.0?):
        # <- :NickServ SVS2MODE 001WCO6YK +r

        # Logging in (without account info, anope 1.8):
        # Note: ignore the timestamp.
        # <- :services.abc.net SVS2MODE GLolol +rd 1470696723

        # Logging out (atheme):
        # <- :NickServ SVS2MODE GL -r+d 0

        # Logging out (anope 1.8):
        # <- :services.abc.net SVS2MODE GLolol -r+d 1

        # Logging out (anope 2.0):
        # <- :NickServ SVS2MODE 009EWLA03 -r

        # Logging in to account from a different nick (atheme):
        # Note: no +r is being set.
        # <- :NickServ SVS2MODE somenick +d GL

        # Logging in to account from a different nick (anope):
        # <- :NickServ SVS2MODE 001SALZ01 +d GL
        # <- :NickServ SVS2MODE 001SALZ01 +r

        target = self._getUid(args[0])
        parsedmodes = self.irc.parseModes(target, args[1:])

        if ('+r', None) in parsedmodes:
            # Umode +r is being set (log in)
            try:
                # Try to get the account name (mode argument for +d)
                account = args[2]
            except IndexError:
                # If one doesn't exist, make it the same as the nick, but only if the account name
                # wasn't set already.
                if not self.irc.users[target].services_account:
                    account = self.irc.getFriendlyName(target)
                else:
                    return
            else:
                if account.isdigit():
                    # If the +d argument is a number, ignore it and set the account name to the nick.
                    account = self.irc.getFriendlyName(target)

        elif ('-r', None) in parsedmodes:
            # Umode -r being set.

            if not self.irc.users[target].services_account:
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

        self.irc.callHooks([target, 'CLIENT_SERVICES_LOGIN', {'text': account}])

    def handle_umode2(self, numeric, command, args):
        """Handles UMODE2, used to set user modes on oneself."""
        # <- :GL UMODE2 +W
        parsedmodes = self.irc.parseModes(numeric, args)
        self.irc.applyModes(numeric, parsedmodes)

        if ('+o', None) in parsedmodes:
            # If +o being set, call the CLIENT_OPERED internal hook.
            self.irc.callHooks([numeric, 'CLIENT_OPERED', {'text': 'IRC Operator'}])

        self.checkCloakChange(numeric, parsedmodes)

        return {'target': numeric, 'modes': parsedmodes}

    def handle_topic(self, numeric, command, args):
        """Handles the TOPIC command."""
        # <- GL TOPIC #services GL 1444699395 :weeee
        # <- TOPIC #services devel.relay 1452399682 :test
        channel = self.irc.toLower(args[0])
        topic = args[-1]
        setter = args[1]
        ts = args[2]

        oldtopic = self.irc.channels[channel].topic
        self.irc.channels[channel].topic = topic
        self.irc.channels[channel].topicset = True

        return {'channel': channel, 'setter': setter, 'ts': ts, 'text': topic,
                'oldtopic': oldtopic}

    def handle_setident(self, numeric, command, args):
        """Handles SETIDENT, used for self ident changes."""
        # <- :70MAAAAAB SETIDENT test
        self.irc.users[numeric].ident = newident = args[0]
        return {'target': numeric, 'newident': newident}

    def handle_sethost(self, numeric, command, args):
        """Handles CHGHOST, used for self hostname changes."""
        # <- :70MAAAAAB SETIDENT some.host
        self.irc.users[numeric].host = newhost = args[0]

        # When SETHOST or CHGHOST is used, modes +xt are implicitly set on the
        # target.
        self.irc.applyModes(numeric, [('+x', None), ('+t', None)])

        return {'target': numeric, 'newhost': newhost}

    def handle_setname(self, numeric, command, args):
        """Handles SETNAME, used for self real name/gecos changes."""
        # <- :70MAAAAAB SETNAME :afdsafasf
        self.irc.users[numeric].realname = newgecos = args[0]
        return {'target': numeric, 'newgecos': newgecos}

    def handle_chgident(self, numeric, command, args):
        """Handles CHGIDENT, used for denoting ident changes."""
        # <- :GL CHGIDENT GL test
        target = self._getUid(args[0])
        self.irc.users[target].ident = newident = args[1]
        return {'target': target, 'newident': newident}

    def handle_chghost(self, numeric, command, args):
        """Handles CHGHOST, used for denoting hostname changes."""
        # <- :GL CHGHOST GL some.host
        target = self._getUid(args[0])
        self.irc.users[target].host = newhost = args[1]

        # When SETHOST or CHGHOST is used, modes +xt are implicitly set on the
        # target.
        self.irc.applyModes(target, [('+x', None), ('+t', None)])

        return {'target': target, 'newhost': newhost}

    def handle_chgname(self, numeric, command, args):
        """Handles CHGNAME, used for denoting real name/gecos changes."""
        # <- :GL CHGNAME GL :afdsafasf
        target = self._getUid(args[0])
        self.irc.users[target].realname = newgecos = args[1]
        return {'target': target, 'newgecos': newgecos}

    def handle_invite(self, numeric, command, args):
        """Handles incoming INVITEs."""
        # <- :GL INVITE PyLink-devel :#a
        target = self._getUid(args[0])
        channel = self.irc.toLower(args[1])
        # We don't actually need to process this; it's just something plugins/hooks can use
        return {'target': target, 'channel': channel}

    def handle_kill(self, numeric, command, args):
        """Handles incoming KILLs."""
        # <- :GL| KILL GLolol :hidden-1C620195!GL| (test)
        # Use ts6_common's handle_kill, but coerse UIDs to nicks first.

        new_args = [self._getUid(args[0])]
        new_args.extend(args[1:])

        return super().handle_kill(numeric, command, new_args)

    def handle_tsctl(self, source, command, args):
        """Handles /TSCTL alltime requests."""
        # <- :GL TSCTL alltime

        if args[0] == 'alltime':
            # XXX: We override notice() here because that abstraction doesn't allow messages from servers.
            self._send(self.irc.sid, 'NOTICE %s :*** Server=%s time()=%d' % (source, self.irc.hostname(), time.time()))

Class = UnrealProtocol
