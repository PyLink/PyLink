"""
inspircd.py: InspIRCd 2.x protocol module for PyLink.
"""

import time
import sys
import os
import re
import threading

from pylinkirc import utils
from pylinkirc.classes import *
from pylinkirc.log import log
from pylinkirc.protocols.ts6_common import *

class InspIRCdProtocol(TS6BaseProtocol):
    def __init__(self, irc):
        super().__init__(irc)
        # Set our case mapping (rfc1459 maps "\" and "|" together, for example).
        self.casemapping = 'rfc1459'

        # Raw commands sent from servers vary from protocol to protocol. Here, we map
        # non-standard names to our hook handlers, so command handlers' outputs
        # are called with the right hooks.
        self.hook_map = {'FJOIN': 'JOIN', 'RSQUIT': 'SQUIT', 'FMODE': 'MODE',
                    'FTOPIC': 'TOPIC', 'OPERTYPE': 'MODE', 'FHOST': 'CHGHOST',
                    'FIDENT': 'CHGIDENT', 'FNAME': 'CHGNAME', 'SVSTOPIC': 'TOPIC',
                    'SAKICK': 'KICK'}

        self.min_proto_ver = 1202
        self.proto_ver = 1202
        self.max_proto_ver = 1202  # Anything above should warn (not officially supported)

    ### Outgoing commands

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

        ts = ts or int(time.time())
        realname = realname or self.irc.botdata['realname']
        realhost = realhost or host
        raw_modes = self.irc.joinModes(modes)
        u = self.irc.users[uid] = IrcUser(nick, ts, uid, ident=ident, host=host, realname=realname,
            realhost=realhost, ip=ip, manipulatable=manipulatable, opertype=opertype)

        self.irc.applyModes(uid, modes)
        self.irc.servers[server].users.add(uid)

        self._send(server, "UID {uid} {ts} {nick} {realhost} {host} {ident} {ip}"
                        " {ts} {modes} + :{realname}".format(ts=ts, host=host,
                                                 nick=nick, ident=ident, uid=uid,
                                                 modes=raw_modes, ip=ip, realname=realname,
                                                 realhost=realhost))
        if ('o', None) in modes or ('+o', None) in modes:
            self._operUp(uid, opertype)
        return u

    def join(self, client, channel):
        """Joins a PyLink client to a channel."""
        # InspIRCd doesn't distinguish between burst joins and regular joins,
        # so what we're actually doing here is sending FJOIN from the server,
        # on behalf of the clients that are joining.
        channel = self.irc.toLower(channel)
        server = self.irc.isInternalClient(client)
        if not server:
            log.error('(%s) Error trying to join %r to %r (no such client exists)', self.irc.name, client, channel)
            raise LookupError('No such PyLink client exists.')
        # Strip out list-modes, they shouldn't be ever sent in FJOIN.
        modes = [m for m in self.irc.channels[channel].modes if m[0] not in self.irc.cmodes['*A']]
        self._send(server, "FJOIN {channel} {ts} {modes} :,{uid}".format(
                ts=self.irc.channels[channel].ts, uid=client, channel=channel,
                modes=self.irc.joinModes(modes)))
        self.irc.channels[channel].users.add(client)
        self.irc.users[client].channels.add(channel)

    def sjoin(self, server, channel, users, ts=None, modes=set()):
        """Sends an SJOIN for a group of users to a channel.

        The sender should always be a Server ID (SID). TS is optional, and defaults
        to the one we've stored in the channel state if not given.
        <users> is a list of (prefix mode, UID) pairs:

        Example uses:
            sjoin('100', '#test', [('', '100AAABBC'), ('qo', 100AAABBB'), ('h', '100AAADDD')])
            sjoin(self.irc.sid, '#test', [('o', self.irc.pseudoclient.uid)])
        """
        channel = self.irc.toLower(channel)
        server = server or self.irc.sid
        assert users, "sjoin: No users sent?"
        log.debug('(%s) sjoin: got %r for users', self.irc.name, users)

        if not server:
            raise LookupError('No such PyLink client exists.')

        # Strip out list-modes, they shouldn't ever be sent in FJOIN (protocol rules).
        modes = modes or self.irc.channels[channel].modes
        orig_ts = self.irc.channels[channel].ts
        ts = ts or orig_ts

        banmodes = []
        regularmodes = []
        for mode in modes:
            modechar = mode[0][-1]
            if modechar in self.irc.cmodes['*A']:
                # Track bans separately (they are sent as a normal FMODE instead of in FJOIN.
                # However, don't reset bans that have already been set.
                if (modechar, mode[1]) not in self.irc.channels[channel].modes:
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
                self.irc.users[user].channels.add(channel)
            except KeyError:  # Not initialized yet?
                log.debug("(%s) sjoin: KeyError trying to add %r to %r's channel list?", self.irc.name, channel, user)

        namelist = ' '.join(namelist)
        self._send(server, "FJOIN {channel} {ts} {modes} :{users}".format(
                ts=ts, users=namelist, channel=channel,
                modes=self.irc.joinModes(modes)))
        self.irc.channels[channel].users.update(uids)

        if banmodes:
            # Burst ban modes if there are any.
            # <- :1ML FMODE #test 1461201525 +bb *!*@bad.user *!*@rly.bad.user
            self._send(server, "FMODE {channel} {ts} {modes} ".format(
                ts=ts, channel=channel, modes=self.irc.joinModes(banmodes)))

        self.updateTS(server, channel, ts, changedmodes)

    def _operUp(self, target, opertype=None):
        """Opers a client up (internal function specific to InspIRCd).

        This should be called whenever user mode +o is set on anyone, because
        InspIRCd requires a special command (OPERTYPE) to be sent in order to
        recognize ANY non-burst oper ups.

        Plugins don't have to call this function themselves, but they can
        set the opertype attribute of an IrcUser object (in self.irc.users),
        and the change will be reflected here."""
        userobj = self.irc.users[target]
        try:
            otype = opertype or userobj.opertype or 'IRC Operator'
        except AttributeError:
            log.debug('(%s) opertype field for %s (%s) isn\'t filled yet!',
                      self.irc.name, target, userobj.nick)
            # whatever, this is non-standard anyways.
            otype = 'IRC Operator'
        assert otype, "Tried to send an empty OPERTYPE!"
        log.debug('(%s) Sending OPERTYPE from %s to oper them up.',
                  self.irc.name, target)
        userobj.opertype = otype
        self._send(target, 'OPERTYPE %s' % otype.replace(" ", "_"))

    def mode(self, numeric, target, modes, ts=None):
        """Sends mode changes from a PyLink client/server."""
        # -> :9PYAAAAAA FMODE #pylink 1433653951 +os 9PYAAAAAA
        # -> :9PYAAAAAA MODE 9PYAAAAAA -i+w

        if (not self.irc.isInternalClient(numeric)) and \
                (not self.irc.isInternalServer(numeric)):
            raise LookupError('No such PyLink client/server exists.')

        log.debug('(%s) inspircd._sendModes: received %r for mode list', self.irc.name, modes)
        if ('+o', None) in modes and not utils.isChannel(target):
            # https://github.com/inspircd/inspircd/blob/master/src/modules/m_spanningtree/opertype.cpp#L26-L28
            # Servers need a special command to set umode +o on people.
            self._operUp(target)
        self.irc.applyModes(target, modes)
        joinedmodes = self.irc.joinModes(modes)
        if utils.isChannel(target):
            ts = ts or self.irc.channels[self.irc.toLower(target)].ts
            self._send(numeric, 'FMODE %s %s %s' % (target, ts, joinedmodes))
        else:
            self._send(numeric, 'MODE %s %s' % (target, joinedmodes))

    def kill(self, numeric, target, reason):
        """Sends a kill from a PyLink client/server."""
        if (not self.irc.isInternalClient(numeric)) and \
                (not self.irc.isInternalServer(numeric)):
            raise LookupError('No such PyLink client/server exists.')

        # InspIRCd will show the raw kill message sent from our server as the quit message.
        # So, make the kill look actually like a kill instead of someone quitting with
        # an arbitrary message.
        if numeric in self.irc.servers:
            sourcenick = self.irc.servers[numeric].name
        else:
            sourcenick = self.irc.users[numeric].nick

        self._send(numeric, 'KILL %s :Killed (%s (%s))' % (target, sourcenick, reason))

        # We only need to call removeClient here if the target is one of our
        # clients, since any remote servers will send a QUIT from
        # their target if the command succeeds.
        if self.irc.isInternalClient(target):
            self.removeClient(target)

    def topicBurst(self, numeric, target, text):
        """Sends a topic change from a PyLink server. This is usually used on burst."""
        if not self.irc.isInternalServer(numeric):
            raise LookupError('No such PyLink server exists.')
        ts = int(time.time())
        servername = self.irc.servers[numeric].name
        self._send(numeric, 'FTOPIC %s %s %s :%s' % (target, ts, servername, text))
        self.irc.channels[target].topic = text
        self.irc.channels[target].topicset = True

    def invite(self, numeric, target, channel):
        """Sends an INVITE from a PyLink client.."""
        if not self.irc.isInternalClient(numeric):
            raise LookupError('No such PyLink client exists.')
        self._send(numeric, 'INVITE %s %s' % (target, channel))

    def knock(self, numeric, target, text):
        """Sends a KNOCK from a PyLink client."""
        if not self.irc.isInternalClient(numeric):
            raise LookupError('No such PyLink client exists.')
        self._send(numeric, 'ENCAP * KNOCK %s :%s' % (target, text))

    def updateClient(self, target, field, text):
        """Updates the ident, host, or realname of any connected client."""
        field = field.upper()

        if field not in ('IDENT', 'HOST', 'REALNAME', 'GECOS'):
            raise NotImplementedError("Changing field %r of a client is "
                                      "unsupported by this protocol." % field)

        if self.irc.isInternalClient(target):
            # It is one of our clients, use FIDENT/HOST/NAME.
            if field == 'IDENT':
                self.irc.users[target].ident = text
                self._send(target, 'FIDENT %s' % text)
            elif field == 'HOST':
                self.irc.users[target].host = text
                self._send(target, 'FHOST %s' % text)
            elif field in ('REALNAME', 'GECOS'):
                self.irc.users[target].realname = text
                self._send(target, 'FNAME :%s' % text)
        else:
            # It is a client on another server, use CHGIDENT/HOST/NAME.
            if field == 'IDENT':
                if 'm_chgident.so' not in self.modsupport:
                    log.warning('(%s) Failed to change ident of %s to %r: load m_chgident.so!', self.irc.name, target, text)
                    return

                self.irc.users[target].ident = text
                self._send(self.irc.sid, 'CHGIDENT %s %s' % (target, text))

                # Send hook payloads for other plugins to listen to.
                self.irc.callHooks([self.irc.sid, 'CHGIDENT',
                                   {'target': target, 'newident': text}])
            elif field == 'HOST':
                if 'm_chghost.so' not in self.modsupport:
                    log.warning('(%s) Failed to change host of %s to %r: load m_chghost.so!', self.irc.name, target, text)
                    return

                self.irc.users[target].host = text
                self._send(self.irc.sid, 'CHGHOST %s %s' % (target, text))

                self.irc.callHooks([self.irc.sid, 'CHGHOST',
                                   {'target': target, 'newhost': text}])

            elif field in ('REALNAME', 'GECOS'):
                if 'm_chgname.so' not in self.modsupport:
                    log.warning('(%s) Failed to change real name of %s to %r: load m_chgname.so!', self.irc.name, target, text)
                    return
                self.irc.users[target].realname = text
                self._send(self.irc.sid, 'CHGNAME %s :%s' % (target, text))

                self.irc.callHooks([self.irc.sid, 'CHGNAME',
                                   {'target': target, 'newgecos': text}])

    def ping(self, source=None, target=None):
        """Sends a PING to a target server. Periodic PINGs are sent to our uplink
        automatically by the Irc() internals; plugins shouldn't have to use this."""
        source = source or self.irc.sid
        target = target or self.irc.uplink
        if not (target is None or source is None):
            self._send(source, 'PING %s %s' % (source, target))

    def numeric(self, source, numeric, target, text):
        """Sends raw numerics from a server to a remote client."""
        # InspIRCd 2.0 syntax (undocumented):
        # Essentially what this does is push the raw numeric text after the first ":" towards the
        # given user.
        # <- :70M PUSH 0ALAAAAAA ::midnight.vpn 422 PyLink-devel :Message of the day file is missing.

        # Note: InspIRCd 2.2 uses a new NUM command in this format:
        # :<sid> NUM <numeric source sid> <target uuid> <3 digit number> <params>
        # Take this into consideration if we ever target InspIRCd 2.2, even though m_spanningtree
        # does provide backwards compatibility for commands like this. -GLolol
        self._send(self.irc.sid, 'PUSH %s ::%s %s %s %s' % (target, source, numeric, target, text))

    def away(self, source, text):
        """Sends an AWAY message from a PyLink client. <text> can be an empty string
        to unset AWAY status."""
        if text:
            self._send(source, 'AWAY %s :%s' % (int(time.time()), text))
        else:
            self._send(source, 'AWAY')
        self.irc.users[source].away = text

    def spawnServer(self, name, sid=None, uplink=None, desc=None, endburst_delay=0):
        """
        Spawns a server off a PyLink server. desc (server description)
        defaults to the one in the config. uplink defaults to the main PyLink
        server, and sid (the server ID) is automatically generated if not
        given.

        If endburst_delay is set greater than zero, the sending of ENDBURST
        will be delayed by the amount given. This can be used to prevent
        pseudoserver bursts from triggering IRCd join-flood preventions,
        and prevent connections from filling up the snomasks too much.
        """
        # -> :0AL SERVER test.server * 1 0AM :some silly pseudoserver
        uplink = uplink or self.irc.sid
        name = name.lower()
        # "desc" defaults to the configured server description.
        desc = desc or self.irc.serverdata.get('serverdesc') or self.irc.botdata['serverdesc']
        if sid is None:  # No sid given; generate one!
            sid = self.sidgen.next_sid()
        assert len(sid) == 3, "Incorrect SID length"
        if sid in self.irc.servers:
            raise ValueError('A server with SID %r already exists!' % sid)
        for server in self.irc.servers.values():
            if name == server.name:
                raise ValueError('A server named %r already exists!' % name)
        if not self.irc.isInternalServer(uplink):
            raise ValueError('Server %r is not a PyLink server!' % uplink)
        if not utils.isServerName(name):
            raise ValueError('Invalid server name %r' % name)
        self._send(uplink, 'SERVER %s * 1 %s :%s' % (name, sid, desc))
        self.irc.servers[sid] = IrcServer(uplink, name, internal=True, desc=desc)

        endburstf = lambda: self._send(sid, 'ENDBURST')
        if endburst_delay:
            # Delay ENDBURST by X seconds if requested.
            threading.Timer(endburst_delay, endburstf, ()).start()
        else:  # Else, send burst immediately
            endburstf()
        return sid

    def squit(self, source, target, text='No reason given'):
        """SQUITs a PyLink server."""
        # -> :9PY SQUIT 9PZ :blah, blah
        self._send(source, 'SQUIT %s :%s' % (target, text))
        self.handle_squit(source, 'SQUIT', [target, text])

    ### Core / command handlers

    def connect(self):
        """Initializes a connection to a server."""
        ts = self.irc.start_ts

        # Track the modules supported by the uplink.
        self.modsupport = []

        f = self.irc.send
        f('CAPAB START %s' % self.proto_ver)
        f('CAPAB CAPABILITIES :PROTOCOL=%s' % self.proto_ver)
        f('CAPAB END')

        host = self.irc.serverdata["hostname"]
        f('SERVER {host} {Pass} 0 {sid} :{sdesc}'.format(host=host,
          Pass=self.irc.serverdata["sendpass"], sid=self.irc.sid,
          sdesc=self.irc.serverdata.get('serverdesc') or self.irc.botdata['serverdesc']))

        self._send(self.irc.sid, 'BURST %s' % ts)
        # InspIRCd sends VERSION data on link, instead of whenever requested by a client.
        self._send(self.irc.sid, 'VERSION :%s' % self.irc.version())
        self._send(self.irc.sid, 'ENDBURST')

    def handle_capab(self, source, command, args):
        """
        Handles the CAPAB command, used for capability negotiation with our
        uplink.
        """
        # 6 CAPAB commands are usually sent on connect: CAPAB START, MODULES,
        # MODSUPPORT, CHANMODES, USERMODES, and CAPABILITIES.
        # The only ones of interest to us are CHANMODES, USERMODES,
        # CAPABILITIES, and MODSUPPORT.

        if args[0] == 'CHANMODES':
            # <- CAPAB CHANMODES :admin=&a allowinvite=A autoop=w ban=b
            # banexception=e blockcolor=c c_registered=r exemptchanops=X
            # filter=g flood=f halfop=%h history=H invex=I inviteonly=i
            # joinflood=j key=k kicknorejoin=J limit=l moderated=m nickflood=F
            # noctcp=C noextmsg=n nokick=Q noknock=K nonick=N nonotice=T
            # official-join=!Y op=@o operonly=O opmoderated=U owner=~q
            # permanent=P private=p redirect=L reginvite=R regmoderated=M
            # secret=s sslonly=z stripcolor=S topiclock=t voice=+v

            # Named modes are essential for a cross-protocol IRC service. We
            # can use InspIRCd as a model here and assign a similar mode map to
            # our cmodes list.
            for modepair in args[-1].split():
                name, char = modepair.split('=')

                # Strip c_ prefixes to be consistent with other protocols.
                name = name.lstrip('c_')

                if name == 'reginvite':  # Reginvite? That's a dumb name.
                    name = 'regonly'

                if name == 'founder':  # Channel mode +q
                    # Founder, owner; same thing. m_customprefix allows you to
                    # name it anything you like. The former is config default,
                    # but I personally prefer the latter.
                    name = 'owner'

                # We don't care about mode prefixes; just the mode char.
                self.irc.cmodes[name] = char[-1]


        elif args[0] == 'USERMODES':
            # <- CAPAB USERMODES :bot=B callerid=g cloak=x deaf_commonchan=c
            # helpop=h hidechans=I hideoper=H invisible=i oper=o regdeaf=R
            # servprotect=k showwhois=W snomask=s u_registered=r u_stripcolor=S
            # wallops=w

            # Ditto above.
            for modepair in args[-1].split():
                name, char = modepair.split('=')
                # Strip u_ prefixes to be consistent with other protocols.
                name = name.lstrip('u_')
                self.irc.umodes[name] = char

        elif args[0] == 'CAPABILITIES':
            # <- CAPAB CAPABILITIES :NICKMAX=21 CHANMAX=64 MAXMODES=20
            # IDENTMAX=11 MAXQUIT=255 MAXTOPIC=307 MAXKICK=255 MAXGECOS=128
            # MAXAWAY=200 IP6SUPPORT=1 PROTOCOL=1202 PREFIX=(Yqaohv)!~&@%+
            # CHANMODES=IXbegw,k,FHJLfjl,ACKMNOPQRSTUcimnprstz
            # USERMODES=,,s,BHIRSWcghikorwx GLOBOPS=1 SVSPART=1

            # First, turn the arguments into a dict
            caps = self.parseCapabilities(args[-1])
            log.debug("(%s) capabilities list: %s", self.irc.name, caps)

            # Check the protocol version
            protocol_version = int(caps['PROTOCOL'])

            if protocol_version < self.min_proto_ver:
                raise ProtocolError("Remote protocol version is too old! "
                                    "At least %s (InspIRCd 2.0.x) is "
                                    "needed. (got %s)" % (self.min_proto_ver,
                                                          protocol_version))
            elif protocol_version > self.max_proto_ver:
                log.warning("(%s) PyLink support for InspIRCd 2.2+ is experimental, "
                            "and should not be relied upon for anything major.",
                            self.irc.name)

            # Store the max nick and channel lengths
            self.irc.maxnicklen = int(caps['NICKMAX'])
            self.irc.maxchanlen = int(caps['CHANMAX'])

            # Modes are divided into A, B, C, and D classes
            # See http://www.irc.org/tech_docs/005.html

            # FIXME: Find a neater way to assign/store this.
            self.irc.cmodes['*A'], self.irc.cmodes['*B'], self.irc.cmodes['*C'], self.irc.cmodes['*D'] \
                = caps['CHANMODES'].split(',')
            self.irc.umodes['*A'], self.irc.umodes['*B'], self.irc.umodes['*C'], self.irc.umodes['*D'] \
                = caps['USERMODES'].split(',')

            # Separate the prefixes field (e.g. "(Yqaohv)!~&@%+") into a
            # dict mapping mode characters to mode prefixes.
            self.irc.prefixmodes = self.parsePrefixes(caps['PREFIX'])
            log.debug('(%s) self.irc.prefixmodes set to %r', self.irc.name,
                      self.irc.prefixmodes)

            # Finally, set the irc.connected (protocol negotiation complete)
            # state to True.
            self.irc.connected.set()
        elif args[0] == 'MODSUPPORT':
            # <- CAPAB MODSUPPORT :m_alltime.so m_check.so m_chghost.so m_chgident.so m_chgname.so m_fullversion.so m_gecosban.so m_knock.so m_muteban.so m_nicklock.so m_nopartmsg.so m_opmoderated.so m_sajoin.so m_sanick.so m_sapart.so m_serverban.so m_services_account.so m_showwhois.so m_silence.so m_swhois.so m_uninvite.so m_watch.so
            self.modsupport = args[-1].split()

    def handle_ping(self, source, command, args):
        """Handles incoming PING commands, so we don't time out."""
        # <- :70M PING 70M 0AL
        # -> :0AL PONG 0AL 70M
        if self.irc.isInternalServer(args[1]):
            self._send(args[1], 'PONG %s %s' % (args[1], source))

    def handle_pong(self, source, command, args):
        """Handles incoming PONG commands.

        This is used to keep track of whether the uplink is alive by the Irc()
        internals - a server that fails to reply to our PINGs eventually
        times out and is disconnected."""
        if source == self.irc.uplink and args[1] == self.irc.sid:
            self.irc.lastping = time.time()

    def handle_fjoin(self, servernumeric, command, args):
        """Handles incoming FJOIN commands (InspIRCd equivalent of JOIN/SJOIN)."""
        # :70M FJOIN #chat 1423790411 +AFPfjnt 6:5 7:5 9:5 :o,1SRAABIT4 v,1IOAAF53R <...>
        channel = self.irc.toLower(args[0])
        chandata = self.irc.channels[channel].deepcopy()
        # InspIRCd sends each channel's users in the form of 'modeprefix(es),UID'
        userlist = args[-1].split()

        modestring = args[2:-1] or args[2]
        parsedmodes = self.irc.parseModes(channel, modestring)
        self.irc.applyModes(channel, parsedmodes)
        namelist = []

        # Keep track of other modes that are added due to prefix modes being joined too.
        changedmodes = set(parsedmodes)

        for user in userlist:
            modeprefix, user = user.split(',', 1)

            # Don't crash when we get an invalid UID.
            if user not in self.irc.users:
                log.debug('(%s) handle_fjoin: tried to introduce user %s not in our user list, ignoring...',
                          self.irc.name, user)
                continue

            namelist.append(user)
            self.irc.users[user].channels.add(channel)

            # Only save mode changes if the remote has lower TS than us.
            changedmodes |= {('+%s' % mode, user) for mode in modeprefix}

            self.irc.channels[channel].users.add(user)

        # Statekeeping with timestamps
        their_ts = int(args[1])
        our_ts = self.irc.channels[channel].ts
        self.updateTS(servernumeric, channel, their_ts, changedmodes)

        return {'channel': channel, 'users': namelist, 'modes': parsedmodes, 'ts': their_ts,
                'channeldata': chandata}

    def handle_uid(self, numeric, command, args):
        """Handles incoming UID commands (user introduction)."""
        # :70M UID 70MAAAAAB 1429934638 GL 0::1 hidden-7j810p.9mdf.lrek.0000.0000.IP gl 0::1 1429934638 +Wioswx +ACGKNOQXacfgklnoqvx :realname
        uid, ts, nick, realhost, host, ident, ip = args[0:7]
        realname = args[-1]
        self.irc.users[uid] = userobj = IrcUser(nick, ts, uid, ident, host, realname, realhost, ip)

        parsedmodes = self.irc.parseModes(uid, [args[8], args[9]])
        self.irc.applyModes(uid, parsedmodes)

        if (self.irc.umodes.get('servprotect'), None) in userobj.modes:
            # Services are usually given a "Network Service" WHOIS, so
            # set that as the opertype.
            self.irc.callHooks([uid, 'CLIENT_OPERED', {'text': 'Network Service'}])

        self.irc.servers[numeric].users.add(uid)
        return {'uid': uid, 'ts': ts, 'nick': nick, 'realhost': realhost, 'host': host, 'ident': ident, 'ip': ip}

    def handle_server(self, numeric, command, args):
        """Handles incoming SERVER commands (introduction of servers)."""

        # Initial SERVER command on connect.
        if self.irc.uplink is None:
            # <- SERVER whatever.net abcdefgh 0 10X :some server description
            servername = args[0].lower()
            numeric = args[3]

            if args[1] != self.irc.serverdata['recvpass']:
                 # Check if recvpass is correct
                 raise ProtocolError('Error: recvpass from uplink server %s does not match configuration!' % servername)

            sdesc = args[-1]
            self.irc.servers[numeric] = IrcServer(None, servername, desc=sdesc)
            self.irc.uplink = numeric
            return

        # Other server introductions.
        # <- :00A SERVER test.server * 1 00C :testing raw message syntax
        servername = args[0].lower()
        sid = args[3]
        sdesc = args[-1]
        self.irc.servers[sid] = IrcServer(numeric, servername, desc=sdesc)

        return {'name': servername, 'sid': args[3], 'text': sdesc}

    def handle_fmode(self, numeric, command, args):
        """Handles the FMODE command, used for channel mode changes."""
        # <- :70MAAAAAA FMODE #chat 1433653462 +hhT 70MAAAAAA 70MAAAAAD
        channel = self.irc.toLower(args[0])
        oldobj = self.irc.channels[channel].deepcopy()
        modes = args[2:]
        changedmodes = self.irc.parseModes(channel, modes)
        self.irc.applyModes(channel, changedmodes)
        ts = int(args[1])
        return {'target': channel, 'modes': changedmodes, 'ts': ts,
                'channeldata': oldobj}

    def handle_mode(self, numeric, command, args):
        """Handles incoming user mode changes."""
        # In InspIRCd, MODE is used for setting user modes and
        # FMODE is used for channel modes:
        # <- :70MAAAAAA MODE 70MAAAAAA -i+xc
        target = args[0]
        modestrings = args[1:]
        changedmodes = self.irc.parseModes(target, modestrings)
        self.irc.applyModes(target, changedmodes)
        return {'target': target, 'modes': changedmodes}

    def handle_idle(self, numeric, command, args):
        """
        Handles the IDLE command, sent between servers in remote WHOIS queries.
        """
        # <- :70MAAAAAA IDLE 1MLAAAAIG
        # -> :1MLAAAAIG IDLE 70MAAAAAA 1433036797 319
        sourceuser = numeric
        targetuser = args[0]

        # HACK: make PyLink handle the entire WHOIS request.
        # This works by silently ignoring the idle time request, and sending our WHOIS data as
        # raw numerics instead.
        # The rationale behind this is that PyLink cannot accurately track signon and idle times for
        # things like relay users, without forwarding WHOIS requests between servers in a way the
        # hooks system is really not optimized to do. However, no IDLE response means that no WHOIS
        # data is ever sent back to the calling user, so this workaround is probably the best
        # solution (aside from faking values). -GLolol
        return {'target': args[0], 'parse_as': 'WHOIS'}

    def handle_ftopic(self, numeric, command, args):
        """Handles incoming FTOPIC (sets topic on burst)."""
        # <- :70M FTOPIC #channel 1434510754 GLo|o|!GLolol@escape.the.dreamland.ca :Some channel topic
        channel = self.irc.toLower(args[0])
        ts = args[1]
        setter = args[2]
        topic = args[-1]
        self.irc.channels[channel].topic = topic
        self.irc.channels[channel].topicset = True
        return {'channel': channel, 'setter': setter, 'ts': ts, 'text': topic}

    # SVSTOPIC is used by InspIRCd module m_topiclock - its arguments are the same as FTOPIC
    handle_svstopic = handle_ftopic

    def handle_invite(self, numeric, command, args):
        """Handles incoming INVITEs."""
        # <- :70MAAAAAC INVITE 0ALAAAAAA #blah 0
        target = args[0]
        channel = self.irc.toLower(args[1])
        # We don't actually need to process this; just send the hook so plugins can use it
        return {'target': target, 'channel': channel}

    def handle_knock(self, numeric, command, args):
        """Handles channel KNOCKs."""
        # <- :70MAAAAAA ENCAP * KNOCK #blah :abcdefg
        channel = self.irc.toLower(args[0])
        text = args[1]
        return {'channel': channel, 'text': text}

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
        self.irc.applyModes(target, omode)

        # Call the CLIENT_OPERED hook that protocols use. The MODE hook
        # payload is returned below.
        self.irc.callHooks([target, 'CLIENT_OPERED', {'text': opertype}])
        return {'target': target, 'modes': omode}

    def handle_fident(self, numeric, command, args):
        """Handles FIDENT, used for denoting ident changes."""
        # <- :70MAAAAAB FIDENT test
        self.irc.users[numeric].ident = newident = args[0]
        return {'target': numeric, 'newident': newident}

    def handle_fhost(self, numeric, command, args):
        """Handles FHOST, used for denoting hostname changes."""
        # <- :70MAAAAAB FIDENT some.host
        self.irc.users[numeric].host = newhost = args[0]
        return {'target': numeric, 'newhost': newhost}

    def handle_fname(self, numeric, command, args):
        """Handles FNAME, used for denoting real name/gecos changes."""
        # <- :70MAAAAAB FNAME :afdsafasf
        self.irc.users[numeric].realname = newgecos = args[0]
        return {'target': numeric, 'newgecos': newgecos}

    def handle_endburst(self, numeric, command, args):
        """ENDBURST handler; sends a hook with empty contents."""
        return {}

    def handle_away(self, numeric, command, args):
        """Handles incoming AWAY messages."""
        # <- :1MLAAAAIG AWAY 1439371390 :Auto-away
        try:
            ts = args[0]
            self.irc.users[numeric].away = text = args[1]
            return {'text': text, 'ts': ts}
        except IndexError:  # User is unsetting away status
            self.irc.users[numeric].away = ''
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
        target = self._getSid(args[0])
        if self.irc.isInternalServer(target):
            # The target has to be one of our servers in order to work...
            uplink = self.irc.servers[target].uplink
            reason = 'Requested by %s' % self.irc.getHostmask(numeric)
            self._send(uplink, 'SQUIT %s :%s' % (target, reason))
            return self.handle_squit(numeric, 'SQUIT', [target, reason])
        else:
            log.debug("(%s) Got RSQUIT for '%s', which is either invalid or not "
                      "a server of ours!", self.irc.name, args[0])

    def handle_metadata(self, numeric, command, args):
        """
        Handles the METADATA command, used by servers to send metadata (services
        login name, certfp data, etc.) for clients.
        """
        uid = args[0]

        if args[1] == 'accountname' and uid in self.irc.users:
            # <- :00A METADATA 1MLAAAJET accountname :
            # <- :00A METADATA 1MLAAAJET accountname :tester
            # Sets the services login name of the client.

            self.irc.callHooks([uid, 'CLIENT_SERVICES_LOGIN', {'text': args[-1]}])

    def handle_version(self, numeric, command, args):
        """
        Stub VERSION handler (does nothing) to override the one in ts6_common.
        """
        pass

    def handle_kill(self, source, command, args):
        """Handles incoming KILLs."""
        killed = args[0]
        # Depending on whether the IRCd sends explicit QUIT messages for
        # killed clients, the user may or may not have automatically been
        # removed from our user list.
        # If not, we have to assume that KILL = QUIT and remove them
        # ourselves.
        data = self.irc.users.get(killed)
        if data:
            self.removeClient(killed)
        return {'target': killed, 'text': args[1], 'userdata': data}

    def handle_sakick(self, source, command, args):
        """Handles forced kicks (SAKICK)."""
        # <- :1MLAAAAAD ENCAP 0AL SAKICK #test 0ALAAAAAB :test
        # ENCAP -> SAKICK args: ['#test', '0ALAAAAAB', 'test']

        target = args[1]
        channel = self.irc.toLower(args[0])
        try:
            reason = args[2]
        except IndexError:
            # Kick reason is optional, strange...
            reason = self.irc.getFriendlyName(source)

        if not self.irc.isInternalClient(target):
            log.warning("(%s) Got SAKICK for client that not one of ours: %s", self.irc.name, target)
            return
        else:
            # Like RSQUIT, SAKICK requires that the receiving server acknowledge that a kick has
            # happened. This comes from the server hosting the target client.
            server = self.irc.getServer(target)

        self.kick(server, channel, target, reason)
        return {'channel': channel, 'target': target, 'text': reason}

    def handle_alltime(self, source, command, args):
        """Handles /ALLTIME requests."""
        # -> :9PYAAAAAA ENCAP * ALLTIME
        # <- :70M PUSH 0ALAAAAAC ::midnight.vpn NOTICE PyLink-devel :System time is 2016-08-13 02:23:06 (1471054986) on midnight.vpn

        # XXX: We override notice() here because that abstraction doesn't allow messages from servers.
        timestring = '%s (%s)' % (time.strftime('%Y-%m-%d %H:%M:%S'), int(time.time()))
        self._send(self.irc.sid, 'NOTICE %s :System time is %s on %s' % (source, timestring, self.irc.hostname()))

Class = InspIRCdProtocol
