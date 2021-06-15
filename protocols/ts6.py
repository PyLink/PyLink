"""
ts6.py: PyLink protocol module for TS6-based IRCds (charybdis, elemental-ircd).
"""

import re
import time

from pylinkirc import conf, utils
from pylinkirc.classes import *
from pylinkirc.log import log
from pylinkirc.protocols.ts6_common import TS6BaseProtocol

__all__ = ['TS6Protocol']


class TS6Protocol(TS6BaseProtocol):

    SUPPORTED_IRCDS = ('charybdis', 'elemental', 'chatircd', 'ratbox')
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._ircd = self.serverdata.get('ircd', 'elemental' if self.serverdata.get('use_elemental_modes')
                                                             else 'charybdis')
        self._ircd = self._ircd.lower()
        if self._ircd not in self.SUPPORTED_IRCDS:
            log.warning("(%s) Unsupported IRCd %r; falling back to 'charybdis' instead", self.name, self._ircd)
            self._ircd = 'charybdis'

        self._can_chghost = False
        if self._ircd in ('charybdis', 'elemental', 'chatircd'):
            # Charybdis and derivatives allow slashes in hosts. Ratbox does not.
            self.protocol_caps |= {'slash-in-hosts'}
            self._can_chghost = True

        self.casemapping = 'rfc1459'
        self.hook_map = {'SJOIN': 'JOIN', 'TB': 'TOPIC', 'TMODE': 'MODE', 'BMASK': 'MODE',
                         'EUID': 'UID', 'RSFNC': 'SVSNICK', 'ETB': 'TOPIC',
                         # ENCAP LOGIN is used on burst for EUID-less servers
                         'LOGIN': 'CLIENT_SERVICES_LOGIN'}

        self.required_caps = {'TB', 'ENCAP', 'QS', 'CHW'}

    ### OUTGOING COMMANDS

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

        uid = self.uidgen[server].next_uid()

        # EUID:
        # parameters: nickname, hopcount, nickTS, umodes, username,
        # visible hostname, IP address, UID, real hostname, account name, gecos
        ts = ts or int(time.time())
        realname = realname or conf.conf['pylink']['realname']
        raw_modes = self.join_modes(modes)
        u = self.users[uid] = User(self, nick, ts, uid, server, ident=ident, host=host,
                                   realname=realname, realhost=realhost or host, ip=ip,
                                   manipulatable=manipulatable, opertype=opertype)

        self.apply_modes(uid, modes)
        self.servers[server].users.add(uid)

        if 'EUID' in self._caps:
            # charybdis-style EUID
            self._send_with_prefix(server, "EUID {nick} {hopcount} {ts} {modes} {ident} {host} {ip} {uid} "
                                           "{realhost} * :{realname}".format(ts=ts, host=host,
                                           nick=nick, ident=ident, uid=uid,
                                           modes=raw_modes, ip=ip, realname=realname,
                                           realhost=realhost or host,
                                           hopcount=self.servers[server].hopcount))
        else:
            # Basic ratbox UID
            self._send_with_prefix(server, "UID {nick} {hopcount} {ts} {modes} {ident} {host} {ip} {uid} "
                                           ":{realname}".format(ts=ts, host=host,
                                           nick=nick, ident=ident, uid=uid,
                                           modes=raw_modes, ip=ip, realname=realname,
                                           hopcount=self.servers[server].hopcount))

            if realhost:
                # If real host is specified, send it using ENCAP REALHOST
                self._send_with_prefix(uid, "ENCAP * REALHOST %s" % realhost)

        return u

    def spawn_server(self, name, sid=None, uplink=None, desc=None):
        """
        Spawns a server off a PyLink server. desc (server description)
        defaults to the one in the config. uplink defaults to the main PyLink
        server, and sid (the server ID) is automatically generated if not
        given.
        """
        desc = desc or self.serverdata.get('serverdesc') or conf.conf['pylink']['serverdesc']
        if self.serverdata.get('hidden', False):
            desc = '(H) ' + desc

        return super().spawn_server(name, sid=sid, uplink=uplink, desc=desc)

    def join(self, client, channel):
        """Joins a PyLink client to a channel."""
        # JOIN:
        # parameters: channelTS, channel, '+' (a plus sign)
        if not self.is_internal_client(client):
            log.error('(%s) Error trying to join %r to %r (no such client exists)', self.name, client, channel)
            raise LookupError('No such PyLink client exists.')
        self._send_with_prefix(client, "JOIN {ts} {channel} +".format(ts=self._channels[channel].ts, channel=channel))
        self._channels[channel].users.add(client)
        self.users[client].channels.add(channel)

    def oper_notice(self, source, text):
        """
        Send a message to all opers.
        """
        if self.is_internal_server(source):
            # Charybdis TS6 only allows OPERWALL from users
            source = self.pseudoclient.uid
        self._send_with_prefix(source, 'OPERWALL :%s' % text)

    def sjoin(self, server, channel, users, ts=None, modes=set()):
        """Sends an SJOIN for a group of users to a channel.

        The sender should always be a Server ID (SID). TS is optional, and defaults
        to the one we've stored in the channel state if not given.
        <users> is a list of (prefix mode, UID) pairs:

        Example uses:
            sjoin('100', '#test', [('', '100AAABBC'), ('o', 100AAABBB'), ('v', '100AAADDD')])
            sjoin(self.sid, '#test', [('o', self.pseudoclient.uid)])
        """
        # https://github.com/grawity/irc-docs/blob/master/server/ts6.txt#L821
        # parameters: channelTS, channel, simple modes, opt. mode parameters..., nicklist

        # Broadcasts a channel creation or bursts a channel.

        # The nicklist consists of users joining the channel, with status prefixes for
        # their status ('@+', '@', '+' or ''), for example:
        # '@+1JJAAAAAB +2JJAAAA4C 1JJAAAADS'. All users must be behind the source server
        # so it is not possible to use this message to force users to join a channel.
        server = server or self.sid
        assert users, "sjoin: No users sent?"
        log.debug('(%s) sjoin: got %r for users', self.name, users)
        if not server:
            raise LookupError('No such PyLink client exists.')

        modes = set(modes or self._channels[channel].modes)
        orig_ts = self._channels[channel].ts
        ts = ts or orig_ts

        # Get all the ban modes in a separate list. These are bursted using a separate BMASK
        # command.
        banmodes = {k: [] for k in self.cmodes['*A']}
        regularmodes = []
        log.debug('(%s) Unfiltered SJOIN modes: %s', self.name, modes)
        for mode in modes:
            modechar = mode[0][-1]
            if modechar in self.cmodes['*A']:
                # Mode character is one of 'beIq'
                if (modechar, mode[1]) in self._channels[channel].modes:
                    # Don't reset modes that are already set.
                    continue

                banmodes[modechar].append(mode[1])
            else:
                regularmodes.append(mode)
        log.debug('(%s) Filtered SJOIN modes to be regular modes: %s, banmodes: %s', self.name, regularmodes, banmodes)

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
                    pr = self.prefixmodes.get(prefix)
                    if pr:
                        prefixchars += pr
                        changedmodes.add(('+%s' % prefix, user))
                namelist.append(prefixchars+user)
                uids.append(user)
                try:
                    self.users[user].channels.add(channel)
                except KeyError:  # Not initialized yet?
                    log.debug("(%s) sjoin: KeyError trying to add %r to %r's channel list?", self.name, channel, user)
            users = users[12:]
            namelist = ' '.join(namelist)
            self._send_with_prefix(server, "SJOIN {ts} {channel} {modes} :{users}".format(
                    ts=ts, users=namelist, channel=channel,
                    modes=self.join_modes(regularmodes)))
            self._channels[channel].users.update(uids)

        # Now, burst bans.
        # <- :42X BMASK 1424222769 #dev b :*!test@*.isp.net *!badident@*
        for bmode, bans in banmodes.items():
            # Max 15-3 = 12 bans per line to prevent cut off. (TS6 allows a max of 15 parameters per
            # line)
            if bans:
                log.debug('(%s) sjoin: bursting mode %s with bans %s, ts:%s', self.name, bmode, bans, ts)
                msgprefix = ':{sid} BMASK {ts} {channel} {bmode} :'.format(sid=server, ts=ts,
                                                                          channel=channel, bmode=bmode)
                # Actually, we cut off at 17 arguments/line, since the prefix and command name don't count.
                for msg in utils.wrap_arguments(msgprefix, bans, self.S2S_BUFSIZE, max_args_per_line=17):
                    self.send(msg)

        self.updateTS(server, channel, ts, changedmodes)

    def mode(self, numeric, target, modes, ts=None):
        """Sends mode changes from a PyLink client/server."""
        # c <- :0UYAAAAAA TMODE 0 #a +o 0T4AAAAAC
        # u <- :0UYAAAAAA MODE 0UYAAAAAA :-Facdefklnou

        if (not self.is_internal_client(numeric)) and \
                (not self.is_internal_server(numeric)):
            raise LookupError('No such PyLink client/server exists.')

        self.apply_modes(target, modes)
        modes = list(modes)

        if self.is_channel(target):
            ts = ts or self._channels[target].ts
            # TMODE:
            # parameters: channelTS, channel, cmode changes, opt. cmode parameters...

            # On output, at most ten cmode parameters should be sent; if there are more,
            # multiple TMODE messages should be sent.
            msgprefix = ':%s TMODE %s %s ' % (numeric, ts, target)
            bufsize = self.S2S_BUFSIZE - len(msgprefix)

            for modestr in self.wrap_modes(modes, bufsize, max_modes_per_msg=10):
                self.send(msgprefix + modestr)
        else:
            joinedmodes = self.join_modes(modes)
            self._send_with_prefix(numeric, 'MODE %s %s' % (target, joinedmodes))

    def topic_burst(self, numeric, target, text):
        """Sends a topic change from a PyLink server. This is usually used on burst."""
        if not self.is_internal_server(numeric):
            raise LookupError('No such PyLink server exists.')
        # TB
        # capab: TB
        # source: server
        # propagation: broadcast
        # parameters: channel, topicTS, opt. topic setter, topic
        ts = self._channels[target].ts
        servername = self.servers[numeric].name
        self._send_with_prefix(numeric, 'TB %s %s %s :%s' % (target, ts, servername, text))
        self._channels[target].topic = text
        self._channels[target].topicset = True

    def invite(self, numeric, target, channel):
        """Sends an INVITE from a PyLink client.."""
        if not self.is_internal_client(numeric):
            raise LookupError('No such PyLink client exists.')
        self._send_with_prefix(numeric, 'INVITE %s %s %s' % (target, channel, self._channels[channel].ts))

    def knock(self, numeric, target, text):
        """Sends a KNOCK from a PyLink client."""
        if 'KNOCK' not in self._caps:
            log.debug('(%s) knock: Dropping KNOCK to %r since the IRCd '
                      'doesn\'t support it.', self.name, target)
            return
        if not self.is_internal_client(numeric):
            raise LookupError('No such PyLink client exists.')
        # No text value is supported here; drop it.
        self._send_with_prefix(numeric, 'KNOCK %s' % target)

    def set_server_ban(self, source, duration, user='*', host='*', reason='User banned'):
        """
        Sets a server ban.
        """
        # source: user
        # parameters: target server mask, duration, user mask, host mask, reason
        assert not (user == host == '*'), "Refusing to set ridiculous ban on *@*"

        if not source in self.users:
            log.debug('(%s) Forcing KLINE sender to %s as TS6 does not allow KLINEs from servers', self.name, self.pseudoclient.uid)
            source = self.pseudoclient.uid

        self._send_with_prefix(source, 'ENCAP * KLINE %s %s %s :%s' % (duration, user, host, reason))

    def update_client(self, target, field, text):
        """Updates the hostname of any connected client."""
        field = field.upper()
        if field == 'HOST' and self._can_chghost:
            self.users[target].host = text
            self._send_with_prefix(self.sid, 'CHGHOST %s :%s' % (target, text))
            if not self.is_internal_client(target):
                # If the target isn't one of our clients, send hook payload
                # for other plugins to listen to.
                self.call_hooks([self.sid, 'CHGHOST',
                                   {'target': target, 'newhost': text}])
        else:
            raise NotImplementedError("Changing field %r of a client is "
                                      "unsupported by this IRCd." % field)

    ### Core / handlers

    def post_connect(self):
        """Initializes a connection to a server."""
        ts = self.start_ts

        f = self.send

        # Base TS6 mode set from ratbox.
        self.cmodes.update({'sslonly': 'S', 'noknock': 'p',
                            '*A': 'beI',
                            '*B': 'k',
                            '*C': 'l',
                            '*D': 'imnpstrS'})

        # https://github.com/grawity/irc-docs/blob/master/server/ts6.txt#L80
        if self._ircd in ('charybdis', 'elemental', 'chatircd'):
            self.cmodes.update({
                'quiet': 'q', 'redirect': 'f', 'freetarget': 'F',
                'joinflood': 'j', 'largebanlist': 'L', 'permanent': 'P',
                'noforwards': 'Q', 'stripcolor': 'c', 'allowinvite':
                'g', 'opmoderated': 'z', 'noctcp': 'C',
                # charybdis modes provided by extensions
                'operonly': 'O', 'adminonly': 'A', 'sslonly': 'S',
                'nonotice': 'T',
                '*A': 'beIq', '*B': 'k', '*C': 'lfj', '*D': 'mnprstFLPQcgzCOAST'
            })
            self.umodes.update({
                'deaf': 'D', 'servprotect': 'S', 'admin': 'a',
                'invisible': 'i', 'oper': 'o', 'wallops': 'w',
                'snomask': 's', 'noforward': 'Q', 'regdeaf': 'R',
                'callerid': 'g', 'operwall': 'z', 'locops': 'l',
                'cloak': 'x', 'override': 'p', 'ssl': 'Z',
                '*A': '', '*B': '', '*C': '', '*D': 'DSaiowsQRgzlxpZ'
            })

            # Charybdis extbans
            self.extbans_matching = {'ban_all_registered': '$a', 'ban_inchannel': '$c:', 'ban_account': '$a:',
                                     'ban_all_opers': '$o', 'ban_realname': '$r:', 'ban_server': '$s:',
                                     'ban_banshare': '$j:', 'ban_extgecos': '$x:', 'ban_all_ssl': '$z'}
        elif self._ircd == 'ratbox':
            self.umodes.update({
                'callerid': 'g', 'admin': 'a', 'sno_botfloods': 'b',
                'sno_clientconnections': 'c', 'sno_extclientconnections': 'C', 'sno_debug': 'd',
                'sno_fullauthblock': 'f', 'sno_skill': 'k', 'locops': 'l', 'sno_rejectedclients': 'r',
                'snomask': 's', 'sno_badclientconnections': 'u', 'sno_serverconnects': 'x',
                'sno_stats': 'y', 'operwall': 'z', 'sno_operspy': 'Z', 'deaf': 'D', 'servprotect': 'S',
                '*A': '', '*B': '', '*C': '', '*D': 'igoabcCdfklrsuwxyzZD'
            })

        # TODO: make these more flexible...
        if self.serverdata.get('use_owner'):
            self.cmodes['owner'] = 'y'
            self.prefixmodes['y'] = '~'
        if self.serverdata.get('use_admin'):
            self.cmodes['admin'] = 'a'
            self.prefixmodes['a'] = '!' if self._ircd != 'chatircd' else '&'
        if self.serverdata.get('use_halfop'):
            self.cmodes['halfop'] = 'h'
            self.prefixmodes['h'] = '%'

        # Toggles support of shadowircd/elemental-ircd specific channel modes:
        # +T (no notice), +u (hidden ban list), +E (no kicks), +J (blocks kickrejoin),
        # +K (no repeat messages), +d (no nick changes), and user modes:
        # +B (bot), +C (blocks CTCP), +V (no invites), +I (hides channel list)
        if self._ircd == 'elemental':
            elemental_cmodes = {'hiddenbans': 'u', 'nokick': 'E',
                                'kicknorejoin': 'J', 'repeat': 'K', 'nonick': 'd',
                                'blockcaps': 'G'}
            self.cmodes.update(elemental_cmodes)
            self.cmodes['*D'] += ''.join(elemental_cmodes.values())

            elemental_umodes = {'noctcp': 'C', 'bot': 'B', 'noinvite': 'V', 'hidechans': 'I'}
            self.umodes.update(elemental_umodes)
            self.umodes['*D'] += ''.join(elemental_umodes.values())

        elif self._ircd == 'chatircd':
            chatircd_cmodes = {'netadminonly': 'N'}
            self.cmodes.update(chatircd_cmodes)
            self.cmodes['*D'] += ''.join(chatircd_cmodes.values())

            chatircd_umodes = {'netadmin': 'n', 'bot': 'B', 'sslonlymsg': 't'}
            self.umodes.update(chatircd_umodes)
            self.umodes['*D'] += ''.join(chatircd_umodes.values())

        # Add definitions for all the inverted versions of the extbans.
        if self.extbans_matching:
            for k, v in self.extbans_matching.copy().items():
                if k == 'ban_all_registered':
                    newk = 'ban_unregistered'
                else:
                    newk = k.replace('_all_', '_').replace('ban_', 'ban_not_')
                self.extbans_matching[newk] = '$~' + v[1:]

        # https://github.com/grawity/irc-docs/blob/master/server/ts6.txt#L55
        f('PASS %s TS 6 %s' % (self.serverdata["sendpass"], self.sid))

        # We request the following capabilities:

        # QS: SQUIT doesn't send recursive quits for each users; required
        # by charybdis (Source: https://github.com/grawity/irc-docs/blob/master/server/ts-capab.txt)
        # ENCAP: message encapsulation for certain commands
        # EX: Support for ban exemptions (+e)
        # IE: Support for invite exemptions (+e)
        # CHW: Allow sending messages to @#channel and the like.
        # KNOCK: support for /knock
        # SAVE: support for SAVE (forces user to UID in nick collision)
        # SERVICES: adds mode +r (only registered users can join a channel)
        # TB: topic burst command; we send this in topic_burst
        # EUID: extended UID command, which includes real hostname + account data info,
        #       and allows sending CHGHOST without ENCAP.
        # RSFNC: states that we support RSFNC (forced nick changed attempts). XXX: With atheme services,
        #        does this actually do anything?
        # EOPMOD: supports ETB (extended TOPIC burst) and =#channel messages for opmoderated +z
        # KLN: supports remote KLINEs
        f('CAPAB :QS ENCAP EX CHW IE KNOCK SAVE SERVICES TB EUID RSFNC EOPMOD SAVETS_100 KLN')

        sdesc = self.serverdata.get('serverdesc') or conf.conf['pylink']['serverdesc']
        if self.serverdata.get('hidden', False):
            sdesc = '(H) ' + sdesc
        f('SERVER %s 0 :%s' % (self.serverdata["hostname"], sdesc))

        # Finally, end all the initialization with a PING - that's Charybdis'
        # way of saying end-of-burst :)
        self._ping_uplink()

    def handle_pass(self, numeric, command, args):
        """
        Handles the PASS command, used to send the server's SID and negotiate
        passwords on connect.
        """
        # <- PASS $somepassword TS 6 :42X

        if args[0] != self.serverdata['recvpass']:
            # Check if recvpass is correct
            raise ProtocolError('Recvpass from uplink server %r does not match configuration!' % numeric)

        if args[1] != 'TS' and args[2] != '6':
            raise ProtocolError("Remote protocol version is too old! Is this even TS6?")

        numeric = args[-1]
        log.debug('(%s) Found uplink SID as %r', self.name, numeric)

        # Server name and SID are sent in different messages, so we fill this
        # with dummy information until we get the actual sid.
        self.servers[numeric] = Server(self, None, '')
        self.uplink = numeric

    def handle_capab(self, numeric, command, args):
        """
        Handles the CAPAB command, used for TS6 capability negotiation.
        """
        # We only get a list of keywords here. Charybdis obviously assumes that
        # we know what modes it supports (indeed, this is a standard list).
        # <- CAPAB :BAN CHW CLUSTER ENCAP EOPMOD EUID EX IE KLN KNOCK MLOCK QS RSFNC SAVE SERVICES TB UNKLN
        self._caps = caps = args[0].split()

        for required_cap in self.required_caps:
            if required_cap not in caps:
                raise ProtocolError('%s not found in TS6 capabilities list; this is required! (got %r)' % (required_cap, caps))

        if 'EX' in caps:
            self.cmodes['banexception'] = 'e'
        if 'IE' in caps:
            self.cmodes['invex'] = 'I'
        if 'SERVICES' in caps:
            self.cmodes['regonly'] = 'r'

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
            destination = self.sid
        if self.is_internal_server(destination):
            self._send_with_prefix(destination, 'PONG %s %s' % (destination, source), queue=False)

            if not self.servers[source].has_eob:
                # TS6 endburst is just sending a PING to the other server.
                # https://github.com/charybdis-ircd/charybdis/blob/dc336d1/modules/core/m_server.c#L484-L485
                self.servers[source].has_eob = True

                if source == self.uplink:
                    log.debug('(%s) self.connected set!', self.name)
                    self.connected.set()

                # Return the endburst hook.
                return {'parse_as': 'ENDBURST'}

    def handle_sjoin(self, servernumeric, command, args):
        """Handles incoming SJOIN commands."""
        # parameters: channelTS, channel, simple modes, opt. mode parameters..., nicklist
        # <- :0UY SJOIN 1451041566 #channel +nt :@0UYAAAAAB
        channel = args[1]
        chandata = self._channels[channel].deepcopy()
        userlist = args[-1].split()

        modestring = args[2:-1] or args[2]
        parsedmodes = self.parse_modes(channel, modestring)
        namelist = []

        # Keep track of other modes that are added due to prefix modes being joined too.
        changedmodes = set(parsedmodes)

        log.debug('(%s) handle_sjoin: got userlist %r for %r', self.name, userlist, channel)
        for userpair in userlist:
            # charybdis sends this in the form "@+UID1, +UID2, UID3, @UID4"
            r = re.search(r'([^\d]*)(.*)', userpair)
            user = r.group(2)
            modeprefix = r.group(1) or ''
            finalprefix = ''
            assert user, 'Failed to get the UID from %r; our regex needs updating?' % userpair
            log.debug('(%s) handle_sjoin: got modeprefix %r for user %r', self.name, modeprefix, user)

            # Don't crash when we get an invalid UID.
            if user not in self.users:
                log.debug('(%s) handle_sjoin: tried to introduce user %s not in our user list, ignoring...',
                          self.name, user)
                continue

            for m in modeprefix:
                # Iterate over the mapping of prefix chars to prefixes, and
                # find the characters that match.
                for char, prefix in self.prefixmodes.items():
                    if m == prefix:
                        finalprefix += char
            namelist.append(user)
            self.users[user].channels.add(channel)

            # Only save mode changes if the remote has lower TS than us.
            changedmodes |= {('+%s' % mode, user) for mode in finalprefix}
            self._channels[channel].users.add(user)

        # Statekeeping with timestamps
        their_ts = int(args[0])
        our_ts = self._channels[channel].ts
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
            oldchans = self.users[numeric].channels.copy()
            log.debug('(%s) Got /join 0 from %r, channel list is %r',
                      self.name, numeric, oldchans)
            for channel in oldchans:
                self._channels[channel].users.discard(numeric)
                self.users[numeric].channels.discard(channel)
            return {'channels': oldchans, 'text': 'Left all channels.', 'parse_as': 'PART'}
        else:
            channel = args[1]
            self.updateTS(numeric, channel, ts)

            self.users[numeric].channels.add(channel)
            self._channels[channel].users.add(numeric)

        # We send users and modes here because SJOIN and JOIN both use one hook,
        # for simplicity's sake (with plugins).
        return {'channel': channel, 'users': [numeric], 'modes':
                self._channels[channel].modes, 'ts': ts}

    def handle_euid(self, numeric, command, args):
        """Handles incoming EUID commands (user introduction)."""
        # <- :42X EUID jlu5 1 1437505322 +ailoswz ~jlu5 127.0.0.1 127.0.0.1 42XAAAAAB * * :realname
        nick = args[0]
        self._check_nick_collision(nick)
        ts, modes, ident, host, ip, uid, realhost, accountname, realname = args[2:11]
        ts = int(ts)
        if realhost == '*':
            realhost = host

        log.debug('(%s) handle_euid got args: nick=%s ts=%s uid=%s ident=%s '
                  'host=%s realname=%s realhost=%s ip=%s', self.name, nick, ts, uid,
                  ident, host, realname, realhost, ip)
        assert ts != 0, "Bad TS 0 for user %s" % uid

        if ip == '0':  # IP was invalid; something used for services.
            ip = '0.0.0.0'

        self.users[uid] = User(self, nick, ts, uid, numeric, ident, host, realname, realhost, ip)

        parsedmodes = self.parse_modes(uid, [modes])
        log.debug('Applying modes %s for %s', parsedmodes, uid)
        self.apply_modes(uid, parsedmodes)
        self.servers[numeric].users.add(uid)

        # Call the OPERED UP hook if +o is being added to the mode list.
        self._check_oper_status_change(uid, parsedmodes)

        # Set the accountname if present
        if accountname != "*":
            self.call_hooks([uid, 'CLIENT_SERVICES_LOGIN', {'text': accountname}])

        # charybdis and derivatives have a usermode (+Z) to mark SSL connections
        # ratbox doesn't appear to have this
        has_ssl = self.users[uid].ssl = ('+%s' % self.umodes.get('ssl'), None) in parsedmodes

        return {'uid': uid, 'ts': ts, 'nick': nick, 'realhost': realhost, 'host': host, 'ident': ident, 'ip': ip, 'secure': has_ssl}

    def handle_uid(self, numeric, command, args):
        """Handles legacy user introductions (UID)."""
        # tl;dr We want to convert the following UID parameters:
        #    nickname, hopcount, nickTS, umodes, username, visible hostname, IP address, UID, gecos
        # to EUID parameters when parsing:
        #    nickname, hopcount, nickTS, umodes, username, visible hostname, IP address, UID,
        #    real hostname, account name, gecos

        euid_args = args[:]

        # Insert a * to denote that the user is not logged in.
        euid_args.insert(8, '*')

        # Copy the visible hostname to the real hostname, as this data isn't sent yet.
        euid_args.insert(8, args[5])

        return self.handle_euid(numeric, command, euid_args)

    def handle_server(self, numeric, command, args):
        """
        Handles 1) incoming legacy (no SID) server introductions,
        2) Sending server data in initial connection.
        """
        if numeric == self.uplink and not self.servers[numeric].name:
            # <- SERVER charybdis.midnight.vpn 1 :charybdis test server
            sname = args[0].lower()

            log.debug('(%s) Found uplink server name as %r', self.name, sname)
            self.servers[numeric].name = sname
            self.servers[numeric].desc = args[-1]

            # According to the TS6 protocol documentation, we should send SVINFO
            # when we get our uplink's SERVER command.
            self.send('SVINFO 6 6 0 :%s' % int(time.time()))

            return

        # <- :services.int SERVER a.bc 2 :(H) [jlu5] a
        return super().handle_server(numeric, command, args)

    def handle_tmode(self, numeric, command, args):
        """Handles incoming TMODE commands (channel mode change)."""
        # <- :42XAAAAAB TMODE 1437450768 #test -c+lkC 3 agte4
        # <- :0UYAAAAAD TMODE 0 #a +h 0UYAAAAAD
        channel = args[1]
        oldobj = self._channels[channel].deepcopy()
        modes = args[2:]
        changedmodes = self.parse_modes(channel, modes)
        self.apply_modes(channel, changedmodes)
        ts = int(args[0])
        return {'target': channel, 'modes': changedmodes, 'ts': ts,
                'channeldata': oldobj}

    def handle_tb(self, numeric, command, args):
        """Handles incoming topic burst (TB) commands."""
        # <- :42X TB #chat 1467427448 jlu5!~jlu5@127.0.0.1 :test
        channel = args[0]
        ts = args[1]
        setter = args[2]
        topic = args[-1]
        self._channels[channel].topic = topic
        self._channels[channel].topicset = True
        return {'channel': channel, 'setter': setter, 'ts': ts, 'text': topic}

    def handle_etb(self, numeric, command, args):
        """Handles extended topic burst (ETB)."""
        # <- :00AAAAAAC ETB 0 #test 1470021157 jlu5 :test | abcd
        # Same as TB, with extra TS and extensions arguments.
        channel = args[1]
        ts = args[2]
        setter = args[3]
        topic = args[-1]
        self._channels[channel].topic = topic
        self._channels[channel].topicset = True
        return {'channel': channel, 'setter': setter, 'ts': ts, 'text': topic}

    def handle_chghost(self, numeric, command, args):
        """Handles incoming CHGHOST commands."""
        target = self._get_UID(args[0])
        self.users[target].host = newhost = args[1]
        return {'target': target, 'newhost': newhost}

    def handle_bmask(self, numeric, command, args):
        """Handles incoming BMASK commands (ban propagation on burst)."""
        # <- :42X BMASK 1424222769 #dev b :*!test@*.isp.net *!badident@*
        # This is used for propagating bans, not TMODE!
        channel = args[1]
        mode = args[2]
        ts = int(args[0])
        modes = []
        for ban in args[-1].split():
            modes.append(('+%s' % mode, ban))
        self.apply_modes(channel, modes)
        return {'target': channel, 'modes': modes, 'ts': ts}

    def handle_472(self, numeric, command, args):
        """Handles the incoming 472 numeric.

        472 is sent to us when one of our clients tries to set a mode the uplink
        server doesn't support. In this case, we'll raise a warning to alert
        the administrator that certain extensions should be loaded for the best
        compatibility.
        """
        # <- :charybdis.midnight.vpn 472 jlu5|devel O :is an unknown mode char to me
        badmode = args[1]
        reason = args[-1]
        setter = args[0]
        charlist = {'A': 'chm_adminonly', 'O': 'chm_operonly', 'S': 'chm_sslonly',
                    'T': 'chm_nonotice'}
        if badmode in charlist:
            log.warning('(%s) User %r attempted to set channel mode %r, but the '
                        'extension providing it isn\'t loaded! To prevent possible'
                        ' desyncs, try adding the line "loadmodule "extensions/%s.so";" to '
                        'your IRCd configuration.', self.name, setter, badmode,
                        charlist[badmode])

    def handle_su(self, numeric, command, args):
        """
        Handles SU, which is used for setting login information.
        """
        # <- :00A ENCAP * SU 42XAAAAAC :jlu5
        # <- :00A ENCAP * SU 42XAAAAAC
        try:
            account = args[1]  # Account name is being set
        except IndexError:
            account = ''  # No account name means a logout

        uid = args[0]
        self.call_hooks([uid, 'CLIENT_SERVICES_LOGIN', {'text': account}])

    def handle_rsfnc(self, numeric, command, args):
        """
        Handles RSFNC, used for forced nick change attempts.
        """
        # <- :00A ENCAP somenet.relay RSFNC 801AAAAAB Guest75038 1468299643 :1468299675
        return {'target': args[0], 'newnick': args[1]}

    def handle_realhost(self, uid, command, args):
        """Handles real host propagation."""
        log.debug('(%s) Got REALHOST %s for %s', self.name, args[0], uid)
        self.users[uid].realhost = args[0]

    def handle_login(self, uid, command, args):
        """Handles login propagation on burst."""
        self.users[uid].services_account = args[0]
        return {'text': args[0]}

Class = TS6Protocol
