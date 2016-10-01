"""
ts6.py: PyLink protocol module for TS6-based IRCds (charybdis, elemental-ircd).
"""

import time
import sys
import os
import re

from pylinkirc import utils
from pylinkirc.classes import *
from pylinkirc.log import log
from pylinkirc.protocols.ts6_common import *

class TS6Protocol(TS6BaseProtocol):
    def __init__(self, irc):
        super().__init__(irc)
        self.casemapping = 'rfc1459'
        self.hook_map = {'SJOIN': 'JOIN', 'TB': 'TOPIC', 'TMODE': 'MODE', 'BMASK': 'MODE',
                         'EUID': 'UID', 'RSFNC': 'SVSNICK', 'ETB': 'TOPIC'}

        # Track whether we've received end-of-burst from the uplink.
        self.has_eob = False

    ### OUTGOING COMMANDS

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

        uid = self.uidgen[server].next_uid()

        # EUID:
        # parameters: nickname, hopcount, nickTS, umodes, username,
        # visible hostname, IP address, UID, real hostname, account name, gecos
        ts = ts or int(time.time())
        realname = realname or self.irc.botdata['realname']
        realhost = realhost or host
        raw_modes = self.irc.joinModes(modes)
        u = self.irc.users[uid] = IrcUser(nick, ts, uid, ident=ident, host=host, realname=realname,
            realhost=realhost, ip=ip, manipulatable=manipulatable, opertype=opertype)

        self.irc.applyModes(uid, modes)
        self.irc.servers[server].users.add(uid)

        self._send(server, "EUID {nick} 1 {ts} {modes} {ident} {host} {ip} {uid} "
                "{realhost} * :{realname}".format(ts=ts, host=host,
                nick=nick, ident=ident, uid=uid,
                modes=raw_modes, ip=ip, realname=realname,
                realhost=realhost))

        return u

    def join(self, client, channel):
        """Joins a PyLink client to a channel."""
        channel = self.irc.toLower(channel)
        # JOIN:
        # parameters: channelTS, channel, '+' (a plus sign)
        if not self.irc.isInternalClient(client):
            log.error('(%s) Error trying to join %r to %r (no such client exists)', self.irc.name, client, channel)
            raise LookupError('No such PyLink client exists.')
        self._send(client, "JOIN {ts} {channel} +".format(ts=self.irc.channels[channel].ts, channel=channel))
        self.irc.channels[channel].users.add(client)
        self.irc.users[client].channels.add(channel)

    def sjoin(self, server, channel, users, ts=None, modes=set()):
        """Sends an SJOIN for a group of users to a channel.

        The sender should always be a Server ID (SID). TS is optional, and defaults
        to the one we've stored in the channel state if not given.
        <users> is a list of (prefix mode, UID) pairs:

        Example uses:
            sjoin('100', '#test', [('', '100AAABBC'), ('o', 100AAABBB'), ('v', '100AAADDD')])
            sjoin(self.irc.sid, '#test', [('o', self.irc.pseudoclient.uid)])
        """
        # https://github.com/grawity/irc-docs/blob/master/server/ts6.txt#L821
        # parameters: channelTS, channel, simple modes, opt. mode parameters..., nicklist

        # Broadcasts a channel creation or bursts a channel.

        # The nicklist consists of users joining the channel, with status prefixes for
        # their status ('@+', '@', '+' or ''), for example:
        # '@+1JJAAAAAB +2JJAAAA4C 1JJAAAADS'. All users must be behind the source server
        # so it is not possible to use this message to force users to join a channel.
        channel = self.irc.toLower(channel)
        server = server or self.irc.sid
        assert users, "sjoin: No users sent?"
        log.debug('(%s) sjoin: got %r for users', self.irc.name, users)
        if not server:
            raise LookupError('No such PyLink client exists.')

        modes = set(modes or self.irc.channels[channel].modes)
        orig_ts = self.irc.channels[channel].ts
        ts = ts or orig_ts

        # Get all the ban modes in a separate list. These are bursted using a separate BMASK
        # command.
        banmodes = {k: set() for k in self.irc.cmodes['*A']}
        regularmodes = []
        log.debug('(%s) Unfiltered SJOIN modes: %s', self.irc.name, modes)
        for mode in modes:
            modechar = mode[0][-1]
            if modechar in self.irc.cmodes['*A']:
                # Mode character is one of 'beIq'
                banmodes[modechar].add(mode[1])
            else:
                regularmodes.append(mode)
        log.debug('(%s) Filtered SJOIN modes to be regular modes: %s, banmodes: %s', self.irc.name, regularmodes, banmodes)

        changedmodes = modes
        while users[:12]:
            uids = []
            namelist = []
            # We take <users> as a list of (prefixmodes, uid) pairs.
            for userpair in users[:12]:
                assert len(userpair) == 2, "Incorrect format of userpair: %r" % userpair
                prefixes, user = userpair
                prefixchars = ''
                for prefix in prefixes:
                    pr = self.irc.prefixmodes.get(prefix)
                    if pr:
                        prefixchars += pr
                        changedmodes.add(('+%s' % prefix, user))
                namelist.append(prefixchars+user)
                uids.append(user)
                try:
                    self.irc.users[user].channels.add(channel)
                except KeyError:  # Not initialized yet?
                    log.debug("(%s) sjoin: KeyError trying to add %r to %r's channel list?", self.irc.name, channel, user)
            users = users[12:]
            namelist = ' '.join(namelist)
            self._send(server, "SJOIN {ts} {channel} {modes} :{users}".format(
                    ts=ts, users=namelist, channel=channel,
                    modes=self.irc.joinModes(regularmodes)))
            self.irc.channels[channel].users.update(uids)

        # Now, burst bans.
        # <- :42X BMASK 1424222769 #dev b :*!test@*.isp.net *!badident@*
        for bmode, bans in banmodes.items():
            # Max 15-3 = 12 bans per line to prevent cut off. (TS6 allows a max of 15 parameters per
            # line)
            if bans:
                log.debug('(%s) sjoin: bursting mode %s with bans %s, ts:%s', self.irc.name, bmode, bans, ts)
                bans = list(bans)  # Convert into list for splicing
                while bans[:12]:
                    self._send(server, "BMASK {ts} {channel} {bmode} :{bans}".format(ts=ts,
                               channel=channel, bmode=bmode, bans=' '.join(bans[:12])))
                    bans = bans[12:]

        self.updateTS(server, channel, ts, changedmodes)

    def mode(self, numeric, target, modes, ts=None):
        """Sends mode changes from a PyLink client/server."""
        # c <- :0UYAAAAAA TMODE 0 #a +o 0T4AAAAAC
        # u <- :0UYAAAAAA MODE 0UYAAAAAA :-Facdefklnou

        if (not self.irc.isInternalClient(numeric)) and \
                (not self.irc.isInternalServer(numeric)):
            raise LookupError('No such PyLink client/server exists.')

        self.irc.applyModes(target, modes)
        modes = list(modes)

        if utils.isChannel(target):
            ts = ts or self.irc.channels[self.irc.toLower(target)].ts
            # TMODE:
            # parameters: channelTS, channel, cmode changes, opt. cmode parameters...

            # On output, at most ten cmode parameters should be sent; if there are more,
            # multiple TMODE messages should be sent.
            while modes[:10]:
                # Seriously, though. If you send more than 10 mode parameters in
                # a line, charybdis will silently REJECT the entire command!
                joinedmodes = self.irc.joinModes([m for m in modes[:10] if m[0] not in self.irc.cmodes['*A']])
                modes = modes[10:]
                self._send(numeric, 'TMODE %s %s %s' % (ts, target, joinedmodes))
        else:
            joinedmodes = self.irc.joinModes(modes)
            self._send(numeric, 'MODE %s %s' % (target, joinedmodes))

    def topicBurst(self, numeric, target, text):
        """Sends a topic change from a PyLink server. This is usually used on burst."""
        if not self.irc.isInternalServer(numeric):
            raise LookupError('No such PyLink server exists.')
        # TB
        # capab: TB
        # source: server
        # propagation: broadcast
        # parameters: channel, topicTS, opt. topic setter, topic
        ts = self.irc.channels[target].ts
        servername = self.irc.servers[numeric].name
        self._send(numeric, 'TB %s %s %s :%s' % (target, ts, servername, text))
        self.irc.channels[target].topic = text
        self.irc.channels[target].topicset = True

    def invite(self, numeric, target, channel):
        """Sends an INVITE from a PyLink client.."""
        if not self.irc.isInternalClient(numeric):
            raise LookupError('No such PyLink client exists.')
        self._send(numeric, 'INVITE %s %s %s' % (target, channel, self.irc.channels[channel].ts))

    def knock(self, numeric, target, text):
        """Sends a KNOCK from a PyLink client."""
        if 'KNOCK' not in self.irc.caps:
            log.debug('(%s) knock: Dropping KNOCK to %r since the IRCd '
                      'doesn\'t support it.', self.irc.name, target)
            return
        if not self.irc.isInternalClient(numeric):
            raise LookupError('No such PyLink client exists.')
        # No text value is supported here; drop it.
        self._send(numeric, 'KNOCK %s' % target)

    def updateClient(self, target, field, text):
        """Updates the hostname of any connected client."""
        field = field.upper()
        if field == 'HOST':
            self.irc.users[target].host = text
            self._send(self.irc.sid, 'CHGHOST %s :%s' % (target, text))
            if not self.irc.isInternalClient(target):
                # If the target isn't one of our clients, send hook payload
                # for other plugins to listen to.
                self.irc.callHooks([self.irc.sid, 'CHGHOST',
                                   {'target': target, 'newhost': text}])
        else:
            raise NotImplementedError("Changing field %r of a client is "
                                      "unsupported by this protocol." % field)

    def ping(self, source=None, target=None):
        """Sends a PING to a target server. Periodic PINGs are sent to our uplink
        automatically by the Irc() internals; plugins shouldn't have to use this."""
        source = source or self.irc.sid
        if source is None:
            return
        if target is not None:
            self._send(source, 'PING %s %s' % (source, target))
        else:
            self._send(source, 'PING %s' % source)

    ### Core / handlers

    def connect(self):
        """Initializes a connection to a server."""
        ts = self.irc.start_ts
        self.has_eob = False

        f = self.irc.send

        # https://github.com/grawity/irc-docs/blob/master/server/ts6.txt#L80
        chary_cmodes = { # TS6 generic modes (note that +p is noknock instead of private):
                        'op': 'o', 'voice': 'v', 'ban': 'b', 'key': 'k', 'limit':
                        'l', 'moderated': 'm', 'noextmsg': 'n', 'noknock': 'p',
                        'secret': 's', 'topiclock': 't', 'inviteonly': 'i',
                         # charybdis-specific modes:
                        'quiet': 'q', 'redirect': 'f', 'freetarget': 'F',
                        'joinflood': 'j', 'largebanlist': 'L', 'permanent': 'P',
                        'noforwards': 'Q', 'stripcolor': 'c', 'allowinvite':
                        'g', 'opmoderated': 'z', 'noctcp': 'C',
                         # charybdis-specific modes provided by EXTENSIONS
                        'operonly': 'O', 'adminonly': 'A', 'sslonly': 'S',
                        'nonotice': 'T',
                         # Now, map all the ABCD type modes:
                        '*A': 'beIq', '*B': 'k', '*C': 'lfj', '*D': 'mnprstFLPQcgzCOAST'}

        if self.irc.serverdata.get('use_owner'):
            chary_cmodes['owner'] = 'y'
            self.irc.prefixmodes['y'] = '~'
        if self.irc.serverdata.get('use_admin'):
            chary_cmodes['admin'] = 'a'
            self.irc.prefixmodes['a'] = '!'
        if self.irc.serverdata.get('use_halfop'):
            chary_cmodes['halfop'] = 'h'
            self.irc.prefixmodes['h'] = '%'

        self.irc.cmodes = chary_cmodes

        # Define supported user modes
        chary_umodes = {'deaf': 'D', 'servprotect': 'S', 'admin': 'a',
                        'invisible': 'i', 'oper': 'o', 'wallops': 'w',
                        'snomask': 's', 'noforward': 'Q', 'regdeaf': 'R',
                        'callerid': 'g', 'operwall': 'z', 'locops': 'l',
                        'cloak': 'x', 'override': 'p',
                        # Now, map all the ABCD type modes:
                        '*A': '', '*B': '', '*C': '', '*D': 'DSaiowsQRgzlxp'}
        self.irc.umodes = chary_umodes

        # Toggles support of shadowircd/elemental-ircd specific channel modes:
        # +T (no notice), +u (hidden ban list), +E (no kicks), +J (blocks kickrejoin),
        # +K (no repeat messages), +d (no nick changes), and user modes:
        # +B (bot), +C (blocks CTCP), +D (deaf), +V (no invites), +I (hides channel list)
        if self.irc.serverdata.get('use_elemental_modes'):
            elemental_cmodes = {'hiddenbans': 'u', 'nokick': 'E',
                                'kicknorejoin': 'J', 'repeat': 'K', 'nonick': 'd',
                                'blockcaps': 'G'}
            self.irc.cmodes.update(elemental_cmodes)
            self.irc.cmodes['*D'] += ''.join(elemental_cmodes.values())

            elemental_umodes = {'noctcp': 'C', 'deaf': 'D', 'bot': 'B', 'noinvite': 'V',
                                'hidechans': 'I'}
            self.irc.umodes.update(elemental_umodes)
            self.irc.umodes['*D'] += ''.join(elemental_umodes.values())

        # https://github.com/grawity/irc-docs/blob/master/server/ts6.txt#L55
        f('PASS %s TS 6 %s' % (self.irc.serverdata["sendpass"], self.irc.sid))

        # We request the following capabilities (for charybdis):

        # QS: SQUIT doesn't send recursive quits for each users; required
        # by charybdis (Source: https://github.com/grawity/irc-docs/blob/master/server/ts-capab.txt)
        # ENCAP: message encapsulation for certain commands
        # EX: Support for ban exemptions (+e)
        # IE: Support for invite exemptions (+e)
        # CHW: Allow sending messages to @#channel and the like.
        # KNOCK: support for /knock
        # SAVE: support for SAVE (forces user to UID in nick collision)
        # SERVICES: adds mode +r (only registered users can join a channel)
        # TB: topic burst command; we send this in topicBurst
        # EUID: extended UID command, which includes real hostname + account data info,
        #       and allows sending CHGHOST without ENCAP.
        # RSFNC: states that we support RSFNC (forced nick changed attempts). XXX: With atheme services,
        #        does this actually do anything?
        # EOPMOD: supports ETB (extended TOPIC burst) and =#channel messages for opmoderated +z
        f('CAPAB :QS ENCAP EX CHW IE KNOCK SAVE SERVICES TB EUID RSFNC EOPMOD')

        f('SERVER %s 0 :%s' % (self.irc.serverdata["hostname"],
                               self.irc.serverdata.get('serverdesc') or self.irc.botdata['serverdesc']))

        # Finally, end all the initialization with a PING - that's Charybdis'
        # way of saying end-of-burst :)
        self.ping()

    def handle_pass(self, numeric, command, args):
        """
        Handles the PASS command, used to send the server's SID and negotiate
        passwords on connect.
        """
        # <- PASS $somepassword TS 6 :42X

        if args[0] != self.irc.serverdata['recvpass']:
            # Check if recvpass is correct
            raise ProtocolError('Recvpass from uplink server %s does not match configuration!' % servername)

        if args[1] != 'TS' and args[2] != '6':
            raise ProtocolError("Remote protocol version is too old! Is this even TS6?")

        numeric = args[-1]
        log.debug('(%s) Found uplink SID as %r', self.irc.name, numeric)

        # Server name and SID are sent in different messages, so we fill this
        # with dummy information until we get the actual sid.
        self.irc.servers[numeric] = IrcServer(None, '')
        self.irc.uplink = numeric

    def handle_capab(self, numeric, command, args):
        """
        Handles the CAPAB command, used for TS6 capability negotiation.
        """
        # We only get a list of keywords here. Charybdis obviously assumes that
        # we know what modes it supports (indeed, this is a standard list).
        # <- CAPAB :BAN CHW CLUSTER ENCAP EOPMOD EUID EX IE KLN KNOCK MLOCK QS RSFNC SAVE SERVICES TB UNKLN
        self.irc.caps = caps = args[0].split()

        for required_cap in ('EUID', 'SAVE', 'TB', 'ENCAP', 'QS', 'CHW'):
            if required_cap not in caps:
                raise ProtocolError('%s not found in TS6 capabilities list; this is required! (got %r)' % (required_cap, caps))

        if 'EX' in caps:
            self.irc.cmodes['banexception'] = 'e'
        if 'IE' in caps:
            self.irc.cmodes['invex'] = 'I'
        if 'SERVICES' in caps:
            self.irc.cmodes['regonly'] = 'r'

        log.debug('(%s) self.irc.connected set!', self.irc.name)
        self.irc.connected.set()

    def handle_ping(self, source, command, args):
        """Handles incoming PING commands."""
        # PING:
        # source: any
        # parameters: origin, opt. destination server
        # PONG:
        # source: server
        # parameters: origin, destination

        # Sends a PING to the destination server, which will reply with a PONG. If the
        # destination server parameter is not present, the server receiving the message
        # must reply.
        try:
            destination = args[1]
        except IndexError:
            destination = self.irc.sid
        if self.irc.isInternalServer(destination):
            self._send(destination, 'PONG %s %s' % (destination, source))

            if destination == self.irc.sid and not self.has_eob:
                # Charybdis' idea of endburst is just sending a PING. No, really!
                # https://github.com/charybdis-ircd/charybdis/blob/dc336d1/modules/core/m_server.c#L484-L485
                self.has_eob = True

                # Return the endburst hook.
                return {'parse_as': 'ENDBURST'}


    def handle_pong(self, source, command, args):
        """Handles incoming PONG commands."""
        if source == self.irc.uplink:
            self.irc.lastping = time.time()

    def handle_sjoin(self, servernumeric, command, args):
        """Handles incoming SJOIN commands."""
        # parameters: channelTS, channel, simple modes, opt. mode parameters..., nicklist
        # <- :0UY SJOIN 1451041566 #channel +nt :@0UYAAAAAB
        channel = self.irc.toLower(args[1])
        chandata = self.irc.channels[channel].deepcopy()
        userlist = args[-1].split()

        modestring = args[2:-1] or args[2]
        parsedmodes = self.irc.parseModes(channel, modestring)
        namelist = []

        # Keep track of other modes that are added due to prefix modes being joined too.
        changedmodes = set(parsedmodes)

        log.debug('(%s) handle_sjoin: got userlist %r for %r', self.irc.name, userlist, channel)
        for userpair in userlist:
            # charybdis sends this in the form "@+UID1, +UID2, UID3, @UID4"
            r = re.search(r'([^\d]*)(.*)', userpair)
            user = r.group(2)
            modeprefix = r.group(1) or ''
            finalprefix = ''
            assert user, 'Failed to get the UID from %r; our regex needs updating?' % userpair
            log.debug('(%s) handle_sjoin: got modeprefix %r for user %r', self.irc.name, modeprefix, user)

            # Don't crash when we get an invalid UID.
            if user not in self.irc.users:
                log.debug('(%s) handle_sjoin: tried to introduce user %s not in our user list, ignoring...',
                          self.irc.name, user)
                continue

            for m in modeprefix:
                # Iterate over the mapping of prefix chars to prefixes, and
                # find the characters that match.
                for char, prefix in self.irc.prefixmodes.items():
                    if m == prefix:
                        finalprefix += char
            namelist.append(user)
            self.irc.users[user].channels.add(channel)

            # Only save mode changes if the remote has lower TS than us.
            changedmodes |= {('+%s' % mode, user) for mode in finalprefix}
            self.irc.channels[channel].users.add(user)

        # Statekeeping with timestamps
        their_ts = int(args[0])
        our_ts = self.irc.channels[channel].ts
        self.updateTS(servernumeric, channel, their_ts, changedmodes)

        return {'channel': channel, 'users': namelist, 'modes': parsedmodes, 'ts': their_ts,
                'channeldata': chandata}

    def handle_join(self, numeric, command, args):
        """Handles incoming channel JOINs."""
        # parameters: channelTS, channel, '+' (a plus sign)
        # <- :0UYAAAAAF JOIN 0 #channel +
        ts = int(args[0])
        if args[0] == '0':
            # /join 0; part the user from all channels
            oldchans = self.irc.users[numeric].channels.copy()
            log.debug('(%s) Got /join 0 from %r, channel list is %r',
                      self.irc.name, numeric, oldchans)
            for channel in oldchans:
                self.irc.channels[channel].users.discard(numeric)
                self.irc.users[numeric].channels.discard(channel)
            return {'channels': oldchans, 'text': 'Left all channels.', 'parse_as': 'PART'}
        else:
            channel = self.irc.toLower(args[1])
            self.updateTS(numeric, channel, ts)

            self.irc.users[numeric].channels.add(channel)
            self.irc.channels[channel].users.add(numeric)

        # We send users and modes here because SJOIN and JOIN both use one hook,
        # for simplicity's sake (with plugins).
        return {'channel': channel, 'users': [numeric], 'modes':
                self.irc.channels[channel].modes, 'ts': ts}

    def handle_euid(self, numeric, command, args):
        """Handles incoming EUID commands (user introduction)."""
        # <- :42X EUID GL 1 1437505322 +ailoswz ~gl 127.0.0.1 127.0.0.1 42XAAAAAB * * :realname
        nick = args[0]
        ts, modes, ident, host, ip, uid, realhost, accountname, realname = args[2:11]
        if realhost == '*':
            realhost = None

        log.debug('(%s) handle_euid got args: nick=%s ts=%s uid=%s ident=%s '
                  'host=%s realname=%s realhost=%s ip=%s', self.irc.name, nick, ts, uid,
                  ident, host, realname, realhost, ip)
        assert ts != 0, "Bad TS 0 for user %s" % uid

        if ip == '0':  # IP was invalid; something used for services.
            ip = '0.0.0.0'

        self.irc.users[uid] = IrcUser(nick, ts, uid, ident, host, realname, realhost, ip)

        parsedmodes = self.irc.parseModes(uid, [modes])
        log.debug('Applying modes %s for %s', parsedmodes, uid)
        self.irc.applyModes(uid, parsedmodes)
        self.irc.servers[numeric].users.add(uid)

        # Call the OPERED UP hook if +o is being added to the mode list.
        if ('+o', None) in parsedmodes:
            otype = 'Server Administrator' if ('+a', None) in parsedmodes else 'IRC Operator'
            self.irc.callHooks([uid, 'CLIENT_OPERED', {'text': otype}])

        # Set the accountname if present
        if accountname != "*":
            self.irc.callHooks([uid, 'CLIENT_SERVICES_LOGIN', {'text': accountname}])

        return {'uid': uid, 'ts': ts, 'nick': nick, 'realhost': realhost, 'host': host, 'ident': ident, 'ip': ip}

    def handle_uid(self, numeric, command, args):
        raise ProtocolError("Servers should use EUID instead of UID to send users! "
                            "This IS a required capability after all...")

    def handle_sid(self, numeric, command, args):
        """Handles incoming server introductions."""
        # parameters: server name, hopcount, sid, server description
        servername = args[0].lower()
        sid = args[2]
        sdesc = args[-1]
        self.irc.servers[sid] = IrcServer(numeric, servername, desc=sdesc)
        return {'name': servername, 'sid': sid, 'text': sdesc}

    def handle_server(self, numeric, command, args):
        """
        Handles 1) incoming legacy (no SID) server introductions,
        2) Sending server data in initial connection.
        """
        if numeric == self.irc.uplink and not self.irc.servers[numeric].name:
            # <- SERVER charybdis.midnight.vpn 1 :charybdis test server
            sname = args[0].lower()

            log.debug('(%s) Found uplink server name as %r', self.irc.name, sname)
            self.irc.servers[numeric].name = sname
            self.irc.servers[numeric].desc = args[-1]

            # According to the TS6 protocol documentation, we should send SVINFO
            # when we get our uplink's SERVER command.
            self.irc.send('SVINFO 6 6 0 :%s' % int(time.time()))

            return

        # <- :services.int SERVER a.bc 2 :(H) [GL] a
        servername = args[0].lower()
        sdesc = args[-1]
        self.irc.servers[servername] = IrcServer(numeric, servername, desc=sdesc)
        return {'name': servername, 'sid': None, 'text': sdesc}

    def handle_tmode(self, numeric, command, args):
        """Handles incoming TMODE commands (channel mode change)."""
        # <- :42XAAAAAB TMODE 1437450768 #test -c+lkC 3 agte4
        # <- :0UYAAAAAD TMODE 0 #a +h 0UYAAAAAD
        channel = self.irc.toLower(args[1])
        oldobj = self.irc.channels[channel].deepcopy()
        modes = args[2:]
        changedmodes = self.irc.parseModes(channel, modes)
        self.irc.applyModes(channel, changedmodes)
        ts = int(args[0])
        return {'target': channel, 'modes': changedmodes, 'ts': ts,
                'channeldata': oldobj}

    def handle_mode(self, numeric, command, args):
        """Handles incoming user mode changes."""
        # <- :70MAAAAAA MODE 70MAAAAAA -i+xc
        target = args[0]
        modestrings = args[1:]
        changedmodes = self.irc.parseModes(target, modestrings)
        self.irc.applyModes(target, changedmodes)
        # Call the OPERED UP hook if +o is being set.
        if ('+o', None) in changedmodes:
            otype = 'Server Administrator' if ('a', None) in self.irc.users[target].modes else 'IRC Operator'
            self.irc.callHooks([target, 'CLIENT_OPERED', {'text': otype}])
        return {'target': target, 'modes': changedmodes}

    def handle_tb(self, numeric, command, args):
        """Handles incoming topic burst (TB) commands."""
        # <- :42X TB #chat 1467427448 GL!~gl@127.0.0.1 :test
        channel = self.irc.toLower(args[0])
        ts = args[1]
        setter = args[2]
        topic = args[-1]
        self.irc.channels[channel].topic = topic
        self.irc.channels[channel].topicset = True
        return {'channel': channel, 'setter': setter, 'ts': ts, 'text': topic}

    def handle_etb(self, numeric, command, args):
        """Handles extended topic burst (ETB)."""
        # <- :00AAAAAAC ETB 0 #test 1470021157 GL :test | abcd
        # Same as TB, with extra TS and extensions arguments.
        channel = self.irc.toLower(args[1])
        ts = args[2]
        setter = args[3]
        topic = args[-1]
        self.irc.channels[channel].topic = topic
        self.irc.channels[channel].topicset = True
        return {'channel': channel, 'setter': setter, 'ts': ts, 'text': topic}

    def handle_invite(self, numeric, command, args):
        """Handles incoming INVITEs."""
        # <- :70MAAAAAC INVITE 0ALAAAAAA #blah 12345
        target = args[0]
        channel = self.irc.toLower(args[1])
        try:
            ts = args[3]
        except IndexError:
            ts = int(time.time())
        # We don't actually need to process this; it's just something plugins/hooks can use
        return {'target': target, 'channel': channel, 'ts': ts}

    def handle_chghost(self, numeric, command, args):
        """Handles incoming CHGHOST commands."""
        target = self._getUid(args[0])
        self.irc.users[target].host = newhost = args[1]
        return {'target': target, 'newhost': newhost}

    def handle_bmask(self, numeric, command, args):
        """Handles incoming BMASK commands (ban propagation on burst)."""
        # <- :42X BMASK 1424222769 #dev b :*!test@*.isp.net *!badident@*
        # This is used for propagating bans, not TMODE!
        channel = self.irc.toLower(args[1])
        mode = args[2]
        ts = int(args[0])
        modes = []
        for ban in args[-1].split():
            modes.append(('+%s' % mode, ban))
        self.irc.applyModes(channel, modes)
        return {'target': channel, 'modes': modes, 'ts': ts}

    def handle_472(self, numeric, command, args):
        """Handles the incoming 472 numeric.

        472 is sent to us when one of our clients tries to set a mode the uplink
        server doesn't support. In this case, we'll raise a warning to alert
        the administrator that certain extensions should be loaded for the best
        compatibility.
        """
        # <- :charybdis.midnight.vpn 472 GL|devel O :is an unknown mode char to me
        badmode = args[1]
        reason = args[-1]
        setter = args[0]
        charlist = {'A': 'chm_adminonly', 'O': 'chm_operonly', 'S': 'chm_sslonly',
                    'T': 'chm_nonotice'}
        if badmode in charlist:
            log.warning('(%s) User %r attempted to set channel mode %r, but the '
                        'extension providing it isn\'t loaded! To prevent possible'
                        ' desyncs, try adding the line "loadmodule "extensions/%s.so";" to '
                        'your IRCd configuration.', self.irc.name, setter, badmode,
                        charlist[badmode])

    def handle_su(self, numeric, command, args):
        """
        Handles SU, which is used for setting login information.
        """
        # <- :00A ENCAP * SU 42XAAAAAC :GLolol
        # <- :00A ENCAP * SU 42XAAAAAC
        try:
            account = args[1]  # Account name is being set
        except IndexError:
            account = ''  # No account name means a logout

        uid = args[0]
        self.irc.callHooks([uid, 'CLIENT_SERVICES_LOGIN', {'text': account}])

    def handle_rsfnc(self, numeric, command, args):
        """
        Handles RSFNC, used for forced nick change attempts.
        """
        # <- :00A ENCAP somenet.relay RSFNC 801AAAAAB Guest75038 1468299643 :1468299675
        return {'target': args[0], 'newnick': args[1]}

Class = TS6Protocol
