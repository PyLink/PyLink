"""
inspircd.py: InspIRCd 2.0, 3.x protocol module for PyLink.
"""

import threading
import time

from pylinkirc import conf
from pylinkirc.classes import *
from pylinkirc.log import log
from pylinkirc.protocols.ts6_common import TS6BaseProtocol

__all__ = ['InspIRCdProtocol']


class InspIRCdProtocol(TS6BaseProtocol):

    S2S_BUFSIZE = 0  # InspIRCd allows infinitely long S2S messages, so set bufsize to infinite
    SUPPORTED_IRCDS = ['insp20', 'insp3']
    DEFAULT_IRCD = SUPPORTED_IRCDS[1]

    MAX_PROTO_VER = 1205  # anything above this warns (not officially supported)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.protocol_caps |= {'slash-in-nicks', 'slash-in-hosts', 'underscore-in-hosts'}

        # This is only the default value - on InspIRCd 3 it will be negotiated on connect in CAPAB CAPABILITIES
        self.casemapping = 'rfc1459'

        # Raw commands sent from servers vary from protocol to protocol. Here, we map
        # non-standard names to our hook handlers, so command handlers' outputs
        # are called with the right hooks.
        self.hook_map = {'FJOIN': 'JOIN', 'RSQUIT': 'SQUIT', 'FMODE': 'MODE',
                         'FTOPIC': 'TOPIC', 'OPERTYPE': 'MODE', 'FHOST': 'CHGHOST',
                         'FIDENT': 'CHGIDENT', 'FNAME': 'CHGNAME', 'SVSTOPIC': 'TOPIC',
                         'SAKICK': 'KICK', 'IJOIN': 'JOIN'}

        ircd_target = self.serverdata.get('target_version', self.DEFAULT_IRCD).lower()
        if ircd_target == 'insp20':
            self.proto_ver = 1202
        elif ircd_target == 'insp3':
            self.proto_ver = 1205
        else:
            raise ProtocolError("Unsupported target_version %r: supported values include %s" % (ircd_target, self.SUPPORTED_IRCDS))
        log.debug('(%s) inspircd: using protocol version %s for target_version %r', self.name, self.proto_ver, ircd_target)

        # Track prefix mode levels on InspIRCd 3
        self._prefix_levels = {}

        # Track the modules supported by the uplink.
        self._modsupport = set()

        # Settable by plugins (e.g. relay) as needed, used to work around +j being triggered
        # by bursting users.
        self._endburst_delay = 0

    ### Outgoing commands

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

        ts = ts or int(time.time())
        realname = realname or conf.conf['pylink']['realname']
        realhost = realhost or host
        raw_modes = self.join_modes(modes)
        u = self.users[uid] = User(self, nick, ts, uid, server, ident=ident, host=host,
                                   realname=realname, realhost=realhost, ip=ip,
                                   manipulatable=manipulatable, opertype=opertype)

        self.apply_modes(uid, modes)
        self.servers[server].users.add(uid)

        self._send_with_prefix(server, "UID {uid} {ts} {nick} {realhost} {host} {ident} {ip}"
                               " {ts} {modes} + :{realname}".format(ts=ts, host=host,
                               nick=nick, ident=ident, uid=uid,
                               modes=raw_modes, ip=ip, realname=realname,
                               realhost=realhost))
        if ('o', None) in modes or ('+o', None) in modes:
            self._oper_up(uid, opertype)
        return u

    def join(self, client, channel):
        """Joins a PyLink client to a channel."""
        # InspIRCd doesn't distinguish between burst joins and regular joins,
        # so what we're actually doing here is sending FJOIN from the server,
        # on behalf of the clients that are joining.

        server = self.get_server(client)
        if not self.is_internal_server(server):
            log.error('(%s) Error trying to join %r to %r (no such client exists)', self.name, client, channel)
            raise LookupError('No such PyLink client exists.')

        # Strip out list-modes, they shouldn't be ever sent in FJOIN.
        modes = [m for m in self._channels[channel].modes if m[0] not in self.cmodes['*A']]
        self._send_with_prefix(server, "FJOIN {channel} {ts} {modes} :,{uid}".format(
                ts=self._channels[channel].ts, uid=client, channel=channel,
                modes=self.join_modes(modes)))
        self._channels[channel].users.add(client)
        self.users[client].channels.add(channel)

    def sjoin(self, server, channel, users, ts=None, modes=set()):
        """Sends an SJOIN for a group of users to a channel.

        The sender should always be a Server ID (SID). TS is optional, and defaults
        to the one we've stored in the channel state if not given.
        <users> is a list of (prefix mode, UID) pairs:

        Example uses:
            sjoin('100', '#test', [('', '100AAABBC'), ('qo', 100AAABBB'), ('h', '100AAADDD')])
            sjoin(self.sid, '#test', [('o', self.pseudoclient.uid)])
        """
        server = server or self.sid
        assert users, "sjoin: No users sent?"
        log.debug('(%s) sjoin: got %r for users', self.name, users)

        if not server:
            raise LookupError('No such PyLink client exists.')

        # Strip out list-modes, they shouldn't ever be sent in FJOIN (protocol rules).
        modes = modes or self._channels[channel].modes
        orig_ts = self._channels[channel].ts
        ts = ts or orig_ts

        banmodes = []
        regularmodes = []
        for mode in modes:
            modechar = mode[0][-1]
            if modechar in self.cmodes['*A']:
                # Track bans separately (they are sent as a normal FMODE instead of in FJOIN.
                # However, don't reset bans that have already been set.
                if (modechar, mode[1]) not in self._channels[channel].modes:
                    banmodes.append(mode)
            else:
                regularmodes.append(mode)

        uids = []
        changedmodes = set(modes)
        namelist = []

        # We take <users> as a list of (prefixmodes, uid) pairs.
        for userpair in users:
            assert len(userpair) == 2, "Incorrect format of userpair: %r" % userpair
            prefixes, user = userpair
            namelist.append(','.join(userpair))
            uids.append(user)
            for m in prefixes:
                changedmodes.add(('+%s' % m, user))
            try:
                self.users[user].channels.add(channel)
            except KeyError:  # Not initialized yet?
                log.debug("(%s) sjoin: KeyError trying to add %r to %r's channel list?", self.name, channel, user)

        namelist = ' '.join(namelist)
        self._send_with_prefix(server, "FJOIN {channel} {ts} {modes} :{users}".format(
                ts=ts, users=namelist, channel=channel,
                modes=self.join_modes(modes)))
        self._channels[channel].users.update(uids)

        if banmodes:
            # Burst ban modes if there are any.
            # <- :1ML FMODE #test 1461201525 +bb *!*@bad.user *!*@rly.bad.user
            self._send_with_prefix(server, "FMODE {channel} {ts} {modes} ".format(
                ts=ts, channel=channel, modes=self.join_modes(banmodes)))

        self.updateTS(server, channel, ts, changedmodes)

    def _oper_up(self, target, opertype=None):
        """Opers a client up (internal function specific to InspIRCd).

        This should be called whenever user mode +o is set on anyone, because
        InspIRCd requires a special command (OPERTYPE) to be sent in order to
        recognize ANY non-burst oper ups.

        Plugins don't have to call this function themselves, but they can
        set the opertype attribute of an User object (in self.users),
        and the change will be reflected here."""
        userobj = self.users[target]
        try:
            otype = opertype or userobj.opertype or 'IRC Operator'
        except AttributeError:
            log.debug('(%s) opertype field for %s (%s) isn\'t filled yet!',
                      self.name, target, userobj.nick)
            # whatever, this is non-standard anyways.
            otype = 'IRC Operator'
        assert otype, "Tried to send an empty OPERTYPE!"
        log.debug('(%s) Sending OPERTYPE from %s to oper them up.',
                  self.name, target)
        userobj.opertype = otype

        # InspIRCd 2.x uses _ in OPERTYPE to denote spaces, while InspIRCd 3.x does not.
        # This is one of the few things not fixed by 2.0/3.0 link compat, so here's a workaround
        if self.remote_proto_ver < 1205:
            otype = otype.replace(" ", "_")
        else:
            otype = ':' + otype

        self._send_with_prefix(target, 'OPERTYPE %s' % otype)

    def mode(self, numeric, target, modes, ts=None):
        """Sends mode changes from a PyLink client/server."""
        # -> :9PYAAAAAA FMODE #pylink 1433653951 +os 9PYAAAAAA
        # -> :9PYAAAAAA MODE 9PYAAAAAA -i+w

        if (not self.is_internal_client(numeric)) and \
                (not self.is_internal_server(numeric)):
            raise LookupError('No such PyLink client/server exists.')

        if ('+o', None) in modes and not self.is_channel(target):
            # https://github.com/inspircd/inspircd/blob/master/src/modules/m_spanningtree/opertype.cpp#L26-L28
            # Servers need a special command to set umode +o on people.
            self._oper_up(target)

        self.apply_modes(target, modes)
        joinedmodes = self.join_modes(modes)

        if self.is_channel(target):
            ts = ts or self._channels[target].ts
            self._send_with_prefix(numeric, 'FMODE %s %s %s' % (target, ts, joinedmodes))
        else:
            self._send_with_prefix(numeric, 'MODE %s %s' % (target, joinedmodes))

    def kill(self, numeric, target, reason):
        """Sends a kill from a PyLink client/server."""
        if (not self.is_internal_client(numeric)) and \
                (not self.is_internal_server(numeric)):
            raise LookupError('No such PyLink client/server exists.')

        # InspIRCd will show the raw kill message sent from our server as the quit message.
        # So, make the kill look actually like a kill instead of someone quitting with
        # an arbitrary message.
        if numeric in self.servers:
            sourcenick = self.servers[numeric].name
        else:
            sourcenick = self.users[numeric].nick

        self._send_with_prefix(numeric, 'KILL %s :Killed (%s (%s))' % (target, sourcenick, reason))

        self._remove_client(target)

    def topic(self, source, target, text):
        """Sends a topic change from a PyLink client."""
        if not self.is_internal_client(source):
            raise LookupError('No such PyLink client exists.')

        if self.proto_ver >= 1205:
            self._send_with_prefix(source, 'FTOPIC %s %s %s :%s' % (target, self._channels[target].ts, int(time.time()), text))
        else:
            return super().topic(source, target, text)

    def topic_burst(self, source, target, text):
        """Sends a topic change from a PyLink server. This is usually used on burst."""
        if not self.is_internal_server(source):
            raise LookupError('No such PyLink server exists.')

        topic_ts = int(time.time())
        servername = self.servers[source].name

        if self.proto_ver >= 1205:
            self._send_with_prefix(source, 'FTOPIC %s %s %s %s :%s' % (target, self._channels[target].ts, topic_ts, servername, text))
        else:
            self._send_with_prefix(source, 'FTOPIC %s %s %s :%s' % (target, topic_ts, servername, text))

        self._channels[target].topic = text
        self._channels[target].topicset = True

    def knock(self, numeric, target, text):
        """Sends a KNOCK from a PyLink client."""
        if not self.is_internal_client(numeric):
            raise LookupError('No such PyLink client exists.')
        self._send_with_prefix(numeric, 'ENCAP * KNOCK %s :%s' % (target, text))

    def update_client(self, target, field, text):
        """Updates the ident, host, or realname of any connected client."""
        field = field.upper()

        if field not in ('IDENT', 'HOST', 'REALNAME', 'GECOS'):
            raise NotImplementedError("Changing field %r of a client is "
                                      "unsupported by this protocol." % field)

        if self.is_internal_client(target):
            # It is one of our clients, use FIDENT/HOST/NAME.
            if field == 'IDENT':
                self.users[target].ident = text
                self._send_with_prefix(target, 'FIDENT %s' % text)
            elif field == 'HOST':
                self.users[target].host = text
                self._send_with_prefix(target, 'FHOST %s' % text)
            elif field in ('REALNAME', 'GECOS'):
                self.users[target].realname = text
                self._send_with_prefix(target, 'FNAME :%s' % text)
        else:
            # It is a client on another server, use CHGIDENT/HOST/NAME.
            if field == 'IDENT':
                if 'm_chgident.so' not in self._modsupport:
                    raise NotImplementedError('Cannot change idents as m_chgident.so is not loaded')

                self.users[target].ident = text
                self._send_with_prefix(self.sid, 'CHGIDENT %s %s' % (target, text))

                # Send hook payloads for other plugins to listen to.
                self.call_hooks([self.sid, 'CHGIDENT',
                                   {'target': target, 'newident': text}])
            elif field == 'HOST':
                if 'm_chghost.so' not in self._modsupport:
                    raise NotImplementedError('Cannot change hosts as m_chghost.so is not loaded')

                self.users[target].host = text
                self._send_with_prefix(self.sid, 'CHGHOST %s %s' % (target, text))

                self.call_hooks([self.sid, 'CHGHOST',
                                   {'target': target, 'newhost': text}])

            elif field in ('REALNAME', 'GECOS'):
                if 'm_chgname.so' not in self._modsupport:
                    raise NotImplementedError('Cannot change real names as m_chgname.so is not loaded')

                self.users[target].realname = text
                self._send_with_prefix(self.sid, 'CHGNAME %s :%s' % (target, text))

                self.call_hooks([self.sid, 'CHGNAME',
                                   {'target': target, 'newgecos': text}])
    def oper_notice(self, source, text):
        """
        Send a message to all opers.
        """
        # <- :70M SNONOTICE G :From jlu5: aaaaaa
        self._send_with_prefix(self.sid, 'SNONOTICE G :From %s: %s' % (self.get_friendly_name(source), text))

    def numeric(self, source, numeric, target, text):
        """Sends raw numerics from a server to a remote client."""
        # InspIRCd 2.0 syntax (undocumented):
        # Essentially what this does is push the raw numeric text after the first ":" towards the
        # given user.
        # <- :70M PUSH 0ALAAAAAA ::midnight.vpn 422 PyLink-devel :Message of the day file is missing.

        # InspIRCd 3 uses a new NUM command in this format:
        # -> NUM <numeric source sid> <target uuid> <numeric ID> <params>
        if self.proto_ver >= 1205:
            self._send('NUM %s %s %s %s' % (source, target, numeric, text))
        else:
            self._send_with_prefix(self.sid, 'PUSH %s ::%s %s %s %s' % (target, source, numeric, target, text))

    def invite(self, source, target, channel):
        """Sends an INVITE from a PyLink client."""
        if not self.is_internal_client(source):
            raise LookupError('No such PyLink client exists.')

        if self.proto_ver >= 1205:  # insp3
            # Note: insp3 supports optionally sending an invite expiration (after the TS argument),
            # but we don't use / expose that feature yet.
            self._send_with_prefix(source, 'INVITE %s %s %d' % (target, channel, self._channels[channel].ts))
        else:  # insp2
            self._send_with_prefix(source, 'INVITE %s %s' % (target, channel))

    def away(self, source, text):
        """Sends an AWAY message from a PyLink client. <text> can be an empty string
        to unset AWAY status."""
        if text:
            self._send_with_prefix(source, 'AWAY %s :%s' % (int(time.time()), text))
        else:
            self._send_with_prefix(source, 'AWAY')
        self.users[source].away = text

    def spawn_server(self, name, sid=None, uplink=None, desc=None):
        """
        Spawns a server off a PyLink server. desc (server description)
        defaults to the one in the config. uplink defaults to the main PyLink
        server, and sid (the server ID) is automatically generated if not
        given.

        Endburst delay can be tweaked by setting the _endburst_delay variable
        to a positive value before calling spawn_server(). This can be used to
        prevent PyLink bursts from filling up snomasks and triggering InspIRCd +j.
        """
        # -> :0AL SERVER test.server * 1 0AM :some silly pseudoserver
        uplink = uplink or self.sid
        name = name.lower()

        # "desc" defaults to the configured server description.
        desc = desc or self.serverdata.get('serverdesc') or conf.conf['pylink']['serverdesc']

        if sid is None:  # No sid given; generate one!
            sid = self.sidgen.next_sid()

        assert len(sid) == 3, "Incorrect SID length"
        if sid in self.servers:
            raise ValueError('A server with SID %r already exists!' % sid)

        for server in self.servers.values():
            if name == server.name:
                raise ValueError('A server named %r already exists!' % name)

        if not self.is_internal_server(uplink):
            raise ValueError('Server %r is not a PyLink server!' % uplink)

        if not self.is_server_name(name):
            raise ValueError('Invalid server name %r' % name)

        self.servers[sid] = Server(self, uplink, name, internal=True, desc=desc)
        if self.proto_ver >= 1205:
            # <- :3IN SERVER services.abc.local 0SV :Some server
            self._send_with_prefix(uplink, 'SERVER %s %s :%s' % (name, sid, desc))
        else:
            # <- :00A SERVER test.server * 1 00C :test
            self._send_with_prefix(uplink, 'SERVER %s * %s %s :%s' % (name, self.servers[sid].hopcount, sid, desc))

        # Endburst delay clutter

        def endburstf():
            # Delay ENDBURST by X seconds if requested.
            if self._aborted.wait(self._endburst_delay):
                # We managed to catch the abort flag before sending ENDBURST, so break
                log.debug('(%s) stopping endburstf() for %s as aborted was set', self.name, sid)
                return
            self._send_with_prefix(sid, 'ENDBURST')

        if self._endburst_delay:
            t = threading.Thread(target=endburstf, name="protocols/inspircd delayed ENDBURST thread for %s@%s" % (sid, self.name))
            t.daemon = True
            t.start()
        else:  # Else, send burst immediately
            self._send_with_prefix(sid, 'ENDBURST')
        return sid

    def set_server_ban(self, source, duration, user='*', host='*', reason='User banned'):
        """
        Sets a server ban.
        """
        # <- :70M ADDLINE G *@10.9.8.7 midnight.local 1433704565 0 :gib reason pls kthx

        assert not (user == host == '*'), "Refusing to set ridiculous ban on *@*"

        # Per https://wiki.inspircd.org/InspIRCd_Spanning_Tree_1.2/ADDLINE, the setter argument can
        # be a max of 64 characters
        self._send_with_prefix(source, 'ADDLINE G %s@%s %s %s %s :%s' % (user, host, self.get_friendly_name(source)[:64],
                                                                         int(time.time()), duration, reason))

    ### Core / command handlers

    def _post_disconnect(self):
        super()._post_disconnect()
        log.debug('(%s) _post_disconnect: clearing _modsupport entries. Last: %s', self.name, self._modsupport)
        self._modsupport.clear()

    def post_connect(self):
        """Initializes a connection to a server."""
        ts = self.start_ts

        f = self.send
        f('CAPAB START %s' % self.proto_ver)
        f('CAPAB CAPABILITIES :PROTOCOL=%s' % self.proto_ver)
        f('CAPAB END')

        host = self.serverdata["hostname"]
        f('SERVER {host} {Pass} 0 {sid} :{sdesc}'.format(host=host,
          Pass=self.serverdata["sendpass"], sid=self.sid,
          sdesc=self.serverdata.get('serverdesc') or conf.conf['pylink']['serverdesc']))

        self._send_with_prefix(self.sid, 'BURST %s' % ts)

        # InspIRCd sends VERSION data on link, instead of when requested by a client.
        if self.proto_ver >= 1205:
            verstr = self.version()
            for version_type in {'version', 'rawversion'}:
                self._send_with_prefix(self.sid, 'SINFO %s :%s' % (version_type, verstr.split(' ', 1)[0]))
            self._send_with_prefix(self.sid, 'SINFO fullversion :%s' % verstr)
        else:
            self._send_with_prefix(self.sid, 'VERSION :%s' % self.version())
        self._send_with_prefix(self.sid, 'ENDBURST')

        # Extban definitions
        self.extbans_acting = {'quiet': 'm:', 'ban_nonick': 'N:', 'ban_blockcolor': 'c:',
                               'ban_partmsgs': 'p:', 'ban_invites': 'A:', 'ban_blockcaps': 'B:',
                               'ban_noctcp': 'C:', 'ban_nokicks': 'Q:', 'ban_stripcolor': 'S:',
                               'ban_nonotice': 'T:'}
        self.extbans_matching = {'ban_inchannel': 'j:', 'ban_realname': 'r:', 'ban_server': 's:',
                                 'ban_certfp': 'z:', 'ban_opertype': 'O:', 'ban_account': 'R:',
                                 # Note: InspIRCd /helpop refers to this as an acting extban, but
                                 # it actually behaves as a matching one...
                                 'ban_unregistered_matching': 'U:'}

    def handle_capab(self, source, command, args):
        """
        Handles the CAPAB command, used for capability negotiation with our
        uplink.
        """
        # 5 CAPAB subcommands are usually sent on connect (excluding START and END):
        #   CAPAB MODULES, MODSUPPORT, CHANMODES, USERMODES, and CAPABILITIES
        # We check just about everything except MODULES

        if args[0] == 'START':
            # Check the protocol version
            # insp20:
            # <- CAPAB START 1202
            # insp3:
            # <- CAPAB START 1205
            self.remote_proto_ver = protocol_version = int(args[1])

            log.debug("(%s) handle_capab: got remote protocol version %s", self.name, protocol_version)
            if protocol_version < self.proto_ver:
                raise ProtocolError("Remote protocol version is too old! "
                                    "At least %s is needed. (got %s)" %
                                    (self.proto_ver, protocol_version))
            elif protocol_version > self.MAX_PROTO_VER:
                log.warning("(%s) PyLink support for InspIRCd > 3.x is experimental, "
                            "and should not be relied upon for anything important.",
                            self.name)
            elif protocol_version >= 1205 > self.proto_ver:
                log.warning("(%s) PyLink 3.0 introduces native support for InspIRCd 3. "
                            "You should enable this by setting the 'target_version' option in your "
                            "InspIRCd server block to 'insp3'. Otherwise, some features will not "
                            "work correctly!", self.name)
                log.warning("(%s) Falling back to InspIRCd 2.0 (compatibility) mode.", self.name)

            if self.proto_ver >= 1205:
                # Clear mode lists, they will be negotiated during burst
                self.cmodes = {'*A': '', '*B': '', '*C': '', '*D': ''}
                self.umodes = {'*A': '', '*B': '', '*C': '', '*D': ''}
                self.prefixmodes.clear()

        if args[0] in {'CHANMODES', 'USERMODES'}:
            # insp20:
            # <- CAPAB CHANMODES :admin=&a allowinvite=A autoop=w ban=b
            #    banexception=e blockcolor=c c_registered=r exemptchanops=X
            #    filter=g flood=f halfop=%h history=H invex=I inviteonly=i
            #    joinflood=j key=k kicknorejoin=J limit=l moderated=m nickflood=F
            #    noctcp=C noextmsg=n nokick=Q noknock=K nonick=N nonotice=T
            #    official-join=!Y op=@o operonly=O opmoderated=U owner=~q
            #    permanent=P private=p redirect=L reginvite=R regmoderated=M
            #    secret=s sslonly=z stripcolor=S topiclock=t voice=+v
            # <- CAPAB USERMODES :bot=B callerid=g cloak=x deaf_commonchan=c
            #    helpop=h hidechans=I hideoper=H invisible=i oper=o regdeaf=R
            #    servprotect=k showwhois=W snomask=s u_registered=r u_stripcolor=S
            #    wallops=w

            # insp3:
            # <- CAPAB CHANMODES :list:autoop=w list:ban=b list:banexception=e list:filter=g list:invex=I
            #    list:namebase=Z param-set:anticaps=B param-set:flood=f param-set:joinflood=j param-set:kicknorejoin=J
            #    param-set:limit=l param-set:nickflood=F param-set:redirect=L param:key=k prefix:10000:voice=+v
            #    prefix:20000:halfop=%h prefix:30000:op=@o prefix:40000:admin=&a prefix:50000:founder=~q
            #    prefix:9000000:official-join=!Y simple:allowinvite=A simple:auditorium=u simple:blockcolor=c
            #    simple:c_registered=r simple:censor=G simple:inviteonly=i simple:moderated=m simple:noctcp=C
            #    simple:noextmsg=n simple:nokick=Q simple:noknock=K simple:nonick=N simple:nonotice=T
            #    simple:operonly=O simple:permanent=P simple:private=p simple:reginvite=R simple:regmoderated=M
            #    simple:secret=s simple:sslonly=z simple:stripcolor=S simple:topiclock=t
            # <- CAPAB USERMODES :param-set:snomask=s simple:antiredirect=L simple:bot=B simple:callerid=g simple:cloak=x
            #    simple:deaf_commonchan=c simple:helpop=h simple:hidechans=I simple:hideoper=H simple:invisible=i
            #    simple:oper=o simple:regdeaf=R simple:u_censor=G simple:u_registered=r simple:u_stripcolor=S
            #    simple:wallops=w

            mydict = self.cmodes if args[0] == 'CHANMODES' else self.umodes

            # Named modes are essential for a cross-protocol IRC service. We
            # can use InspIRCd as a model here and assign a similar mode map to
            # our cmodes list.
            for modepair in args[-1].split():
                name, char = modepair.rsplit('=', 1)

                if self.proto_ver >= 1205:
                    # Detect mode types from the mode type tag
                    parts = name.split(':')
                    modetype = parts[0]
                    name = parts[-1]

                    # Modes are divided into A, B, C, and D classes
                    # See http://www.irc.org/tech_docs/005.html
                    if modetype == 'simple':       # No parameter
                        mydict['*D'] += char
                    elif modetype == 'param-set':  # Only parameter when setting (e.g. cmode +l)
                        mydict['*C'] += char
                    elif modetype == 'param':      # Always has parameter (e.g. cmode +k)
                        mydict['*B'] += char
                    elif modetype == 'list':       # List modes like ban, except, invex, ...
                        mydict['*A'] += char
                    elif modetype == 'prefix':     # prefix:30000:op=@o
                        if args[0] != 'CHANMODES':  # This should never happen...
                            log.warning("(%s) Possible desync? Got a prefix type modepair %r but not for channel modes", self.name, modepair)
                        else:
                            # We don't do anything with prefix levels yet, let's just store them for future use
                            self._prefix_levels[name] = int(parts[1])

                            # Map mode names to their prefixes
                            self.prefixmodes[char[-1]] = char[0]

                # Strip c_, u_ prefixes to be consistent with other protocols.
                if name.startswith(('c_', 'u_')):
                    name = name[2:]

                if name == 'reginvite':  # Reginvite? That's an odd name.
                    name = 'regonly'

                if name == 'antiredirect':  # User mode +L
                    name = 'noforward'

                if name == 'founder':  # Channel mode +q
                    # Founder, owner; same thing. m_customprefix allows you to name it anything you like,
                    # but PyLink uses the latter in its definitions
                    name = 'owner'

                if name in ('repeat', 'kicknorejoin'):
                    # Suffix modes using inspircd-specific arguments so that it can
                    # be safely relayed.
                    name += '_insp'

                # Add the mode char to our table
                mydict[name] = char[-1]

        elif args[0] == 'CAPABILITIES':
            # insp20:
            # <- CAPAB CAPABILITIES :NICKMAX=21 CHANMAX=64 MAXMODES=20
            # IDENTMAX=11 MAXQUIT=255 MAXTOPIC=307 MAXKICK=255 MAXGECOS=128
            # MAXAWAY=200 IP6SUPPORT=1 PROTOCOL=1202 PREFIX=(Yqaohv)!~&@%+
            # CHANMODES=IXbegw,k,FHJLfjl,ACKMNOPQRSTUcimnprstz
            # USERMODES=,,s,BHIRSWcghikorwx GLOBOPS=1 SVSPART=1

            # insp3:
            # CAPAB CAPABILITIES :NICKMAX=30 CHANMAX=64 MAXMODES=20 IDENTMAX=10 MAXQUIT=255 MAXTOPIC=307
            # MAXKICK=255 MAXREAL=128 MAXAWAY=200 MAXHOST=64 CHALLENGE=xxxxxxxxx CASEMAPPING=ascii GLOBOPS=1

            # First, turn the arguments into a dict
            caps = self.parse_isupport(args[-1])
            log.debug("(%s) handle_capab: capabilities list is %s", self.name, caps)

            # Store the max nick and channel lengths
            if 'NICKMAX' in caps:
                self.maxnicklen = int(caps['NICKMAX'])
            if 'CHANMAX' in caps:
                self.maxchanlen = int(caps['CHANMAX'])
            # Casemapping - this is only sent in InspIRCd 3.x
            if 'CASEMAPPING' in caps:
                self.casemapping = caps['CASEMAPPING']
                log.debug('(%s) handle_capab: updated casemapping to %s', self.name, self.casemapping)

            # InspIRCd 2 only: mode & prefix definitions are sent as CAPAB CAPABILITIES CHANMODES/USERMODES/PREFIX
            if self.proto_ver < 1205:
                if 'CHANMODES' in caps:
                    self.cmodes['*A'], self.cmodes['*B'], self.cmodes['*C'], self.cmodes['*D'] \
                        = caps['CHANMODES'].split(',')
                if 'USERMODES' in caps:
                    self.umodes['*A'], self.umodes['*B'], self.umodes['*C'], self.umodes['*D'] \
                        = caps['USERMODES'].split(',')
                if 'PREFIX' in caps:
                    # Separate the prefixes field (e.g. "(Yqaohv)!~&@%+") into a
                    # dict mapping mode characters to mode prefixes.
                    self.prefixmodes = self.parse_isupport_prefixes(caps['PREFIX'])
                    log.debug('(%s) handle_capab: self.prefixmodes set to %r', self.name,
                              self.prefixmodes)

        elif args[0] == 'MODSUPPORT':
            # <- CAPAB MODSUPPORT :m_alltime.so m_check.so m_chghost.so m_chgident.so m_chgname.so m_fullversion.so m_gecosban.so m_knock.so m_muteban.so m_nicklock.so m_nopartmsg.so m_opmoderated.so m_sajoin.so m_sanick.so m_sapart.so m_serverban.so m_services_account.so m_showwhois.so m_silence.so m_swhois.so m_uninvite.so m_watch.so
            self._modsupport |= set(args[-1].split())

    def handle_kick(self, source, command, args):
        """Handles incoming KICKs."""
        # InspIRCD 3 adds membership IDs to KICK messages when forwarding across servers
        # <- :3INAAAAAA KICK #endlessvoid 3INAAAAAA :test (local)
        # <- :3INAAAAAA KICK #endlessvoid 7PYAAAAAA 0 :test (remote)
        if self.proto_ver >= 1205 and len(args) > 3:
            del args[2]

        return super().handle_kick(source, command, args)

    def handle_ping(self, source, command, args):
        """Handles incoming PING commands, so we don't time out."""
        # InspIRCd 2:
        # <- :70M PING 70M 0AL
        # -> :0AL PONG 0AL 70M

        # InspIRCd 3:
        # <- :3IN PING 808
        # -> :808 PONG 3IN
        if len(args) >= 2:
            self._send_with_prefix(args[1], 'PONG %s %s' % (args[1], source), queue=False)
        else:
            self._send_with_prefix(args[0], 'PONG %s' % source, queue=False)

    def handle_fjoin(self, servernumeric, command, args):
        """Handles incoming FJOIN commands (InspIRCd equivalent of JOIN/SJOIN)."""
        # insp2:
        # <- :70M FJOIN #chat 1423790411 +AFPfjnt 6:5 7:5 9:5 :o,1SRAABIT4 v,1IOAAF53R <...>
        # insp3:
        # <- :3IN FJOIN #test 1556842195 +nt :o,3INAAAAAA:4
        channel = args[0]
        chandata = self._channels[channel].deepcopy()
        # InspIRCd sends each channel's users in the form of 'modeprefix(es),UID'
        userlist = args[-1].split()

        modestring = args[2:-1] or args[2]
        parsedmodes = self.parse_modes(channel, modestring)
        namelist = []

        # Keep track of other modes that are added due to prefix modes being joined too.
        changedmodes = set(parsedmodes)

        for user in userlist:
            modeprefix, user = user.split(',', 1)

            if self.proto_ver >= 1205:
                # XXX: we don't handle membership IDs yet
                user = user.split(':', 1)[0]

            # Don't crash when we get an invalid UID.
            if user not in self.users:
                log.debug('(%s) handle_fjoin: tried to introduce user %s not in our user list, ignoring...',
                          self.name, user)
                continue

            namelist.append(user)
            self.users[user].channels.add(channel)

            # Only save mode changes if the remote has lower TS than us.
            changedmodes |= {('+%s' % mode, user) for mode in modeprefix}

            self._channels[channel].users.add(user)

        # Statekeeping with timestamps. Note: some service packages (Anope 1.8) send a trailing
        # 'd' after the timestamp, which we should strip out to prevent int() from erroring.
        # This is technically valid in InspIRCd S2S because atoi() ignores non-digit characters,
        # but it's strange behaviour either way...
        # <- :3AX FJOIN #monitor 1485462109d + :,3AXAAAAAK
        their_ts = int(''.join(char for char in args[1] if char.isdigit()))

        our_ts = self._channels[channel].ts
        self.updateTS(servernumeric, channel, their_ts, changedmodes)

        return {'channel': channel, 'users': namelist, 'modes': parsedmodes, 'ts': their_ts,
                'channeldata': chandata}

    def handle_ijoin(self, source, command, args):
        """Handles InspIRCd 3 joins with membership ID."""
        # insp3:
        # EX: regular /join on an existing channel
        # <- :3INAAAAAA IJOIN #valhalla 6

        # EX: /ojoin on an existing channel
        # <- :3INAAAAAA IJOIN #valhalla 7 1559348434 Yo

        # From insp3 source:
        # <- :<uid> IJOIN <chan> <membid> [<ts> [<flags>]]
        #   args idx:      0      1         2     3

        # For now we don't care about the membership ID
        channel = args[0]
        self.users[source].channels.add(channel)
        self._channels[channel].users.add(source)

        # Apply prefix modes if they exist and the TS check passes
        if len(args) >= 4 and int(args[2]) <= self._channels[channel].ts:
            self.apply_modes(source, {('+%s' % mode, source) for mode in args[3]})

        return {'channel': channel, 'users': [source], 'modes':
                self._channels[channel].modes}

    def handle_uid(self, numeric, command, args):
        """Handles incoming UID commands (user introduction)."""
        # :70M UID 70MAAAAAB 1429934638 jlu5 0::1 hidden-7j810p.9mdf.lrek.0000.0000.IP jlu5 0::1 1429934638 +Wioswx +ACGKNOQXacfgklnoqvx :realname
        uid, ts, nick, realhost, host, ident, ip = args[0:7]

        ts = int(ts)

        self._check_nick_collision(nick)
        realname = args[-1]
        self.users[uid] = userobj = User(self, nick, ts, uid, numeric, ident, host, realname, realhost, ip)

        parsedmodes = self.parse_modes(uid, [args[8], args[9]])
        self.apply_modes(uid, parsedmodes)

        self._check_oper_status_change(uid, parsedmodes)

        self.servers[numeric].users.add(uid)
        # InspIRCd sends SSL status in the metadata command, so the info is not known at this point
        return {'uid': uid, 'ts': ts, 'nick': nick, 'realhost': realhost, 'host': host, 'ident': ident, 'ip': ip, 'secure': None}

    def handle_server(self, source, command, args):
        """Handles incoming SERVER commands (introduction of servers)."""

        if self.uplink is None:
            # <- SERVER whatever.net abcdefgh 0 10X :some server description
            servername = args[0].lower()
            source = args[3]

            if args[1] != self.serverdata['recvpass']:
                 # Check if recvpass is correct
                 raise ProtocolError('recvpass from uplink server %s does not match configuration!' % servername)

            sdesc = args[-1]
            self.servers[source] = Server(self, None, servername, desc=sdesc)
            self.uplink = source
            log.debug('(%s) inspircd: found uplink %s', self.name, self.uplink)
            return

        # Other server introductions.
        # insp20:
        # <- :00A SERVER test.server * 1 00C :testing raw message syntax
        # insp3:
        # <- :3IN SERVER services.abc.local 0SV :Some server
        servername = args[0].lower()
        if self.proto_ver >= 1205:
            sid = args[1]  # insp3
        else:
            sid = args[3]  # insp20
        sdesc = args[-1]
        self.servers[sid] = Server(self, source, servername, desc=sdesc)

        return {'name': servername, 'sid': sid, 'text': sdesc}

    def handle_fmode(self, numeric, command, args):
        """Handles the FMODE command, used for channel mode changes."""
        # <- :70MAAAAAA FMODE #chat 1433653462 +hhT 70MAAAAAA 70MAAAAAD
        channel = args[0]
        oldobj = self._channels[channel].deepcopy()
        modes = args[2:]
        changedmodes = self.parse_modes(channel, modes)
        self.apply_modes(channel, changedmodes)
        ts = int(args[1])
        return {'target': channel, 'modes': changedmodes, 'ts': ts,
                'channeldata': oldobj}

    def handle_idle(self, source, command, args):
        """
        Handles the IDLE command, sent between servers in remote WHOIS queries.
        """
        # <- :70MAAAAAA IDLE 1MLAAAAIG
        # -> :1MLAAAAIG IDLE 70MAAAAAA 1433036797 319

        if self.serverdata.get('force_whois_extensions', True):
            return {'target': args[0], 'parse_as': 'WHOIS'}

        # Allow hiding the startup time if set to do so (if both idle and signon time is 0, InspIRCd omits
        # showing this line).
        target = args[0]
        start_time = self.start_ts if (conf.conf['pylink'].get('whois_show_startup_time', True) and
                                       self.get_service_bot(target)) else 0

        # First arg = source, second = signon time, third = idle time
        self._send_with_prefix(target, 'IDLE %s %s 0' % (source, start_time))

    def handle_ftopic(self, source, command, args):
        """Handles incoming topic changes."""
        # insp2 (only used for server senders):
        # <- :70M FTOPIC #channel 1434510754 jlu5!jlu5@escape.the.dreamland.ca :Some channel topic

        # insp3 (used for server AND user senders):
        # <- :3IN FTOPIC #qwerty 1556828864 1556844505 jlu5!jlu5@midnight-umk.of4.0.127.IP :1234abcd
        # <- :3INAAAAAA FTOPIC #qwerty 1556828864 1556844248 :topic text
        #           chan creation time ^          ^ topic set time (the one we want)

        # <- :00A SVSTOPIC #channel 1538402416 SomeUser :test
        channel = args[0]

        if self.proto_ver >= 1205 and command == 'FTOPIC':
            ts = args[2]
            if source in self.users:
                setter = source
            else:
                setter = args[3]
        else:
            ts = args[1]
            setter = args[2]
        ts = int(ts)

        topic = args[-1]
        self._channels[channel].topic = topic
        self._channels[channel].topicset = True
        return {'channel': channel, 'setter': setter, 'ts': ts, 'text': topic}

    # SVSTOPIC is used by InspIRCd module m_topiclock - its arguments are the same as insp2 FTOPIC
    handle_svstopic = handle_ftopic

    def handle_opertype(self, target, command, args):
        """Handles incoming OPERTYPE, which is used to denote an oper up.

        This calls the internal hook CLIENT_OPERED, sets the internal
        opertype of the client, and assumes setting user mode +o on the caller."""
        # This is used by InspIRCd to denote an oper up; there is no MODE
        # command sent for it.
        # <- :70MAAAAAB OPERTYPE Network_Owner
        # Replace escaped _ in opertypes with spaces for InspIRCd 2.0.
        opertype = args[0].replace("_", " ")

        # Set umode +o on the target.
        omode = [('+o', None)]
        self.apply_modes(target, omode)

        # Call the CLIENT_OPERED hook that protocols use. The MODE hook
        # payload is returned below.
        self.call_hooks([target, 'CLIENT_OPERED', {'text': opertype}])
        return {'target': target, 'modes': omode}

    def handle_fident(self, numeric, command, args):
        """Handles FIDENT, used for denoting ident changes."""
        # <- :70MAAAAAB FIDENT test
        self.users[numeric].ident = newident = args[0]
        return {'target': numeric, 'newident': newident}

    def handle_fhost(self, numeric, command, args):
        """Handles FHOST, used for denoting hostname changes."""
        # <- :70MAAAAAB FHOST some.host
        self.users[numeric].host = newhost = args[0]
        return {'target': numeric, 'newhost': newhost}

    def handle_fname(self, numeric, command, args):
        """Handles FNAME, used for denoting real name/gecos changes."""
        # <- :70MAAAAAB FNAME :afdsafasf
        self.users[numeric].realname = newgecos = args[0]
        return {'target': numeric, 'newgecos': newgecos}

    def handle_endburst(self, numeric, command, args):
        """ENDBURST handler; sends a hook with empty contents."""
        self.servers[numeric].has_eob = True
        if numeric == self.uplink:
            self.connected.set()
        return {}

    def handle_away(self, numeric, command, args):
        """Handles incoming AWAY messages."""
        # <- :1MLAAAAIG AWAY 1439371390 :Auto-away
        try:
            ts = args[0]
            self.users[numeric].away = text = args[1]
            return {'text': text, 'ts': ts}
        except IndexError:  # User is unsetting away status
            self.users[numeric].away = ''
            return {'text': ''}

    def handle_rsquit(self, numeric, command, args):
        """
        Handles the RSQUIT command, which is sent by opers to SQUIT remote
        servers.
        """
        # <- :1MLAAAAIG RSQUIT :ayy.lmao
        # <- :1MLAAAAIG RSQUIT ayy.lmao :some reason

        # RSQUIT is sent by opers to SQUIT remote servers. However, it differs from
        # a regular SQUIT in that:
        #    1) It takes a server name instead of a SID,
        #    2) Responses have to be be explicitly sent; i.e. The target server has
        #       to agree with splitting the target, and could ignore such requests
        #       entirely.

        # If we receive such a remote SQUIT, just forward it as a regular
        # SQUIT, in order to be consistent with other IRCds which make SQUITs
        # implicit.
        target = self._get_SID(args[0])
        if self.is_internal_server(target):
            # The target has to be one of our servers in order to work...
            uplink = self.servers[target].uplink
            reason = 'Requested by %s' % self.get_hostmask(numeric)
            self._send_with_prefix(uplink, 'SQUIT %s :%s' % (target, reason))
            return self.handle_squit(numeric, 'SQUIT', [target, reason])
        else:
            log.debug("(%s) Got RSQUIT for '%s', which is either invalid or not "
                      "a server of ours!", self.name, args[0])

    def handle_metadata(self, numeric, command, args):
        """
        Handles the METADATA command, used by servers to send metadata for various objects.
        """
        uid = args[0]

        if args[1] == 'accountname' and uid in self.users:
            # <- :00A METADATA 1MLAAAJET accountname :
            # <- :00A METADATA 1MLAAAJET accountname :tester
            # Sets the services login name of the client.
            self.call_hooks([uid, 'CLIENT_SERVICES_LOGIN', {'text': args[-1]}])

        elif args[1] == 'modules' and numeric == self.uplink:
            # Note: only handle METADATA from our uplink; otherwise leaf servers unloading modules
            # while shutting down will corrupt the state.
            # <- :70M METADATA * modules :-m_chghost.so
            # <- :70M METADATA * modules :+m_chghost.so
            for module in args[-1].split():
                if module.startswith('-'):
                    log.debug('(%s) Removing module %s', self.name, module[1:])
                    self._modsupport.discard(module[1:])
                elif module.startswith('+'):
                    log.debug('(%s) Adding module %s', self.name, module[1:])
                    self._modsupport.add(module[1:])
                else:
                    log.warning('(%s) Got unknown METADATA modules string: %r', self.name, args[-1])
        elif args[1] == 'ssl_cert' and uid in self.users:
            self.users[uid].ssl = True

    def handle_version(self, numeric, command, args):
        """
        Stub VERSION handler (does nothing) to override the one in ts6_common.
        """

    def handle_sakick(self, source, command, args):
        """Handles forced kicks (SAKICK)."""
        # <- :1MLAAAAAD ENCAP 0AL SAKICK #test 0ALAAAAAB :test
        # ENCAP -> SAKICK args: ['#test', '0ALAAAAAB', 'test']

        target = args[1]
        channel = args[0]
        try:
            reason = args[2]
        except IndexError:
            # Kick reason is optional, strange...
            reason = self.get_friendly_name(source)

        if not self.is_internal_client(target):
            log.warning("(%s) Got SAKICK for client that not one of ours: %s", self.name, target)
            return
        else:
            # Like RSQUIT, SAKICK requires that the receiving server acknowledge that a kick has
            # happened. This comes from the server hosting the target client.
            server = self.get_server(target)

        self.kick(server, channel, target, reason)
        return {'channel': channel, 'target': target, 'text': reason}

    def handle_alltime(self, source, command, args):
        """Handles /ALLTIME requests."""
        # -> :9PYAAAAAA ENCAP * ALLTIME
        # <- :70M PUSH 0ALAAAAAC ::midnight.vpn NOTICE PyLink-devel :System time is 2016-08-13 02:23:06 (1471054986) on midnight.vpn

        # XXX: We override notice() here because that abstraction doesn't allow messages from servers.
        timestring = '%s (%s)' % (time.strftime('%Y-%m-%d %H:%M:%S'), int(time.time()))
        self._send_with_prefix(self.sid, 'NOTICE %s :System time is %s on %s' % (source, timestring, self.hostname()))

Class = InspIRCdProtocol
