import time
import string
import threading

from pylinkirc import utils, conf
from pylinkirc.log import log
from pylinkirc.classes import Protocol, IrcUser, IrcServer

FALLBACK_REALNAME = 'PyLink Relay Mirror Client'
COMMON_PREFIXMODES = [('h', 'halfop'), ('a', 'admin'), ('q', 'owner'), ('y', 'owner')]

class ClientbotWrapperProtocol(Protocol):
    def __init__(self, irc):
        super().__init__(irc)

        self.has_eob = False

        # Remove conf key checks for those not needed for Clientbot.
        self.conf_keys -= {'recvpass', 'sendpass', 'sid', 'sidrange', 'hostname'}

        # This is just a fallback. Actual casemapping is fetched by handle_005()
        self.casemapping = 'ascii'

        self.caps = {}

        # Initialize counter-based pseudo UID  generators
        self.uidgen = utils.PUIDGenerator('PUID')
        self.sidgen = utils.PUIDGenerator('PSID')

        # Tracks the users sent in a list of /who replies, so that users can be bursted all at once
        # when ENDOFWHO is received.
        self.who_received = set()

        # This stores channel->Timer object mappings for users that we're waiting for a kick
        # acknowledgement for. The timer is set to send a NAMES request to the uplink to prevent
        # things like failed KICK attempts from desyncing plugins like relay.
        self.kick_queue = {}

        # Aliases: 463 (ERR_NOPERMFORHOST), 464 (ERR_PASSWDMISMATCH), and 465 (ERR_YOUREBANNEDCREEP)
        # are essentially all fatal errors for connections.
        self.handle_463 = self.handle_464 = self.handle_465 = self.handle_error

    def _expandPUID(self, uid):
        """
        Returns the real nick for the given PUID.
        """
        if uid in self.irc.users:
            nick = self.irc.users[uid].nick
            log.debug('(%s) Mangling target PUID %s to nick %s', self.irc.name, uid, nick)
            return nick
        return uid

    def connect(self):
        """Initializes a connection to a server."""
        self.has_eob = False
        ts = self.irc.start_ts
        f = self.irc.send

        # Enumerate our own server
        self.irc.sid = self.sidgen.next_sid()

        # Clear states from last connect
        self.who_received.clear()
        self.kick_queue.clear()

        sendpass = self.irc.serverdata.get("sendpass")
        if sendpass:
            f('PASS %s' % sendpass)

        # This is a really gross hack to get the defined NICK/IDENT/HOST/GECOS.
        # But this connection stuff is done before any of the spawnClient stuff in
        # services_support fires.
        self.conf_nick = self.irc.serverdata.get('pylink_nick') or conf.conf["bot"].get("nick", "PyLink")
        f('NICK %s' % (self.conf_nick))
        ident = self.irc.serverdata.get('pylink_ident') or conf.conf["bot"].get("ident", "pylink")
        f('USER %s 8 * :%s' % (ident, # TODO: per net realnames or hostnames aren't implemented yet.
                              conf.conf["bot"].get("realname", "PyLink Clientbot")))

    # Note: clientbot clients are initialized with umode +i by default
    def spawnClient(self, nick, ident='unknown', host='unknown.host', realhost=None, modes={('i', None)},
            server=None, ip='0.0.0.0', realname='', ts=None, opertype=None,
            manipulatable=False):
        """
        STUB: Pretends to spawn a new client with a subset of the given options.
        """

        server = server or self.irc.sid
        uid = self.uidgen.next_uid()

        ts = ts or int(time.time())

        log.debug('(%s) spawnClient stub called, saving nick %s as PUID %s', self.irc.name, nick, uid)
        u = self.irc.users[uid] = IrcUser(nick, ts, uid, ident=ident, host=host, realname=realname,
                                          manipulatable=manipulatable, realhost=realhost, ip=ip)
        self.irc.servers[server].users.add(uid)

        self.irc.applyModes(uid, modes)

        return u

    def spawnServer(self, name, sid=None, uplink=None, desc=None, endburst_delay=0, internal=True):
        """
        STUB: Pretends to spawn a new server with a subset of the given options.
        """
        name = name.lower()
        sid = self.sidgen.next_sid()
        self.irc.servers[sid] = IrcServer(uplink, name, internal=internal)
        return sid

    def away(self, source, text):
        """STUB: sets away messages for clients internally."""
        log.debug('(%s) away: target is %s, internal client? %s', self.irc.name, source, self.irc.isInternalClient(source))

        if self.irc.users[source].away != text:
            if not self.irc.isInternalClient(source):
                log.debug('(%s) away: sending AWAY hook from %s with text %r', self.irc.name, source, text)
                self.irc.callHooks([source, 'AWAY', {'text': text}])

            self.irc.users[source].away = text

    def invite(self, client, target, channel):
        """Invites a user to a channel."""
        self.irc.send('INVITE %s %s' % (self.irc.getFriendlyName(target), channel))

    def join(self, client, channel):
        """STUB: Joins a user to a channel."""
        channel = self.irc.toLower(channel)

        # Only joins for the main PyLink client are actually forwarded. Others are ignored.
        # Note: we do not automatically add our main client to the channel state, as we
        # rely on the /NAMES reply to sync it up properly.
        if self.irc.pseudoclient and client == self.irc.pseudoclient.uid:
            self.irc.send('JOIN %s' % channel)
            # Send a /who request right after
            self.irc.send('WHO %s' % channel)
        else:
            self.irc.channels[channel].users.add(client)
            self.irc.users[client].channels.add(channel)

            log.debug('(%s) join: faking JOIN of client %s/%s to %s', self.irc.name, client,
                      self.irc.getFriendlyName(client), channel)
            self.irc.callHooks([client, 'CLIENTBOT_JOIN', {'channel': channel}])

    def kick(self, source, channel, target, reason=''):
        """Sends channel kicks."""

        log.debug('(%s) kick: checking if target %s (nick: %s) is an internal client? %s',
                  self.irc.name, target, self.irc.getFriendlyName(target),
                  self.irc.isInternalClient(target))
        if self.irc.isInternalClient(target):
            # Target was one of our virtual clients. Just remove them from the state.
            self.handle_part(target, 'KICK', [channel, reason])

            # Send a KICK hook for message formatting.
            self.irc.callHooks([source, 'CLIENTBOT_KICK', {'channel': channel, 'target': target, 'text': reason}])
            return

        self.irc.send('KICK %s %s :<%s> %s' % (channel, self._expandPUID(target),
                      self.irc.getFriendlyName(source), reason))

        # Don't update our state here: wait for the IRCd to send an acknowledgement instead.
        # There is essentially a 3 second wait to do this, as we send NAMES with a delay
        # to resync any users lost due to kicks being blocked, etc.
        if (channel not in self.kick_queue) or (not self.kick_queue[channel][1].is_alive()):
            # However, only do this if there isn't a NAMES request scheduled already.
            t = threading.Timer(3, lambda: self.irc.send('NAMES %s' % channel))
            log.debug('(%s) kick: setting NAMES timer for %s on %s', self.irc.name, target, channel)

            # Store the channel, target UID, and timer object in the internal kick queue.
            self.kick_queue[channel] = ({target}, t)
            t.start()
        else:
            log.debug('(%s) kick: adding %s to kick queue for channel %s', self.irc.name, target, channel)
            self.kick_queue[channel][0].add(target)

    def message(self, source, target, text, notice=False):
        """Sends messages to the target."""
        command = 'NOTICE' if notice else 'PRIVMSG'

        if self.irc.pseudoclient and self.irc.pseudoclient.uid == source:
            self.irc.send('%s %s :%s' % (command, self._expandPUID(target), text))
        else:
            self.irc.callHooks([source, 'CLIENTBOT_MESSAGE', {'target': target, 'is_notice': notice, 'text': text}])

    def nick(self, source, newnick):
        """STUB: Sends NICK changes."""
        if self.irc.pseudoclient and source == self.irc.pseudoclient.uid:
            self.irc.send('NICK :%s' % newnick)
            # No state update here: the IRCd will respond with a NICK acknowledgement if the change succeeds.
        else:
            self.irc.callHooks([source, 'CLIENTBOT_NICK', {'newnick': newnick}])
            self.irc.users[source].nick = newnick

    def notice(self, source, target, text):
        """Sends notices to the target."""
        # Wrap around message(), which does all the text formatting for us.
        self.message(source, target, text, notice=True)

    def ping(self, source=None, target=None):
        """
        Sends PING to the uplink.
        """
        if self.irc.uplink:
            self.irc.send('PING %s' % self.irc.getFriendlyName(self.irc.uplink))

            # Poll WHO periodically to figure out any ident/host/away status changes.
            for channel in self.irc.pseudoclient.channels:
                self.irc.send('WHO %s' % channel)

    def part(self, source, channel, reason=''):
        """STUB: Parts a user from a channel."""
        self.irc.channels[channel].removeuser(source)
        self.irc.users[source].channels.discard(channel)

        # Only parts for the main PyLink client are actually forwarded. Others are ignored.
        if self.irc.pseudoclient and source == self.irc.pseudoclient.uid:
            self.irc.send('PART %s :%s' % (channel, reason))
        else:
            self.irc.callHooks([source, 'CLIENTBOT_PART', {'channel': channel, 'text': reason}])

    def quit(self, source, reason):
        """STUB: Quits a client."""
        userdata = self.irc.users[source]
        self.removeClient(source)
        self.irc.callHooks([source, 'CLIENTBOT_QUIT', {'text': reason, 'userdata': userdata}])

    def sjoin(self, server, channel, users, ts=None, modes=set()):
        """STUB: bursts joins from a server."""
        # This stub only updates the state internally with the users
        # given. modes and TS are currently ignored.
        puids = {u[-1] for u in users}
        for user in puids:
            if self.irc.pseudoclient and self.irc.pseudoclient.uid == user:
                # If the SJOIN affects our main client, forward it as a regular JOIN.
                self.join(user, channel)
            else:
                # Otherwise, track the state for our virtual clients.
                self.irc.users[user].channels.add(channel)

        self.irc.channels[channel].users |= puids
        nicks = {self.irc.getFriendlyName(u) for u in puids}
        self.irc.callHooks([server, 'CLIENTBOT_SJOIN', {'channel': channel, 'nicks': nicks}])

    def squit(self, source, target, text):
        """STUB: SQUITs a server."""
        # What this actually does is just handle the SQUIT internally: i.e.
        # Removing pseudoclients and pseudoservers.
        squit_data = self._squit(source, 'CLIENTBOT_VIRTUAL_SQUIT', [target, text])

        if squit_data.get('nicks'):
            self.irc.callHooks([source, 'CLIENTBOT_SQUIT', squit_data])

    def _stub(self, *args):
        """Stub outgoing command function (does nothing)."""
        return
    kill = mode = topic = topicBurst = knock = numeric = _stub

    def updateClient(self, target, field, text):
        """Updates the known ident, host, or realname of a client."""
        if target not in self.irc.users:
            log.warning("(%s) Unknown target %s for updateClient()", self.irc.name, target)
            return

        u = self.irc.users[target]

        if field == 'IDENT' and u.ident != text:
            u.ident = text
            if not self.irc.isInternalClient(target):
                # We're updating the host of an external client in our state, so send the appropriate
                # hook payloads.
                self.irc.callHooks([self.irc.sid, 'CHGIDENT',
                                   {'target': target, 'newident': text}])
        elif field == 'HOST' and u.host != text:
            u.host = text
            if not self.irc.isInternalClient(target):
                self.irc.callHooks([self.irc.sid, 'CHGHOST',
                                   {'target': target, 'newhost': text}])
        elif field in ('REALNAME', 'GECOS') and u.realname != text:
            u.realname = text
            if not self.irc.isInternalClient(target):
                self.irc.callHooks([self.irc.sid, 'CHGNAME',
                                   {'target': target, 'newgecos': text}])
        else:
            return  # Nothing changed

    def _getUid(self, nick, ident='unknown', host='unknown.host'):
        """
        Fetches the UID for the given nick, creating one if it does not already exist.

        Limited (internal) nick collision checking is done here to prevent Clientbot users from
        being confused with virtual clients, and vice versa."""
        # If this sender isn't known or it is one of our virtual clients, spawn a new one.
        # spawnClient() will take care of any nick collisions caused by new, Clientbot users
        # taking the same nick as one of our virtual clients.
        idsource = self.irc.nickToUid(nick)
        is_internal = self.irc.isInternalClient(idsource)

        if (not idsource) or (is_internal and self.irc.pseudoclient and idsource != self.irc.pseudoclient.uid):
            if idsource:
                log.debug('(%s) Nick-colliding virtual client %s/%s', self.irc.name, idsource, nick)
                self.irc.callHooks([self.irc.sid, 'CLIENTBOT_NICKCOLLIDE', {'target': idsource, 'parse_as': 'SAVE'}])

            idsource = self.spawnClient(nick, ident, host, server=self.irc.uplink, realname=FALLBACK_REALNAME).uid

        return idsource

    def handle_events(self, data):
        """Event handler for the RFC1459/2812 (clientbot) protocol."""
        data = data.split(" ")
        try:
            args = self.parsePrefixedArgs(data)
            sender = args[0]
            command = args[1]
            args = args[2:]

        except IndexError:
            # Raw command without an explicit sender; assume it's being sent by our uplink.
            args = self.parseArgs(data)
            idsource = sender = self.irc.uplink
            command = args[0]
            args = args[1:]
        else:
            # PyLink as a services framework expects UIDs and SIDs for everythiung. Since we connect
            # as a bot here, there's no explicit user introduction, so we're going to generate
            # pseudo-uids and pseudo-sids as we see prefixes.
            if '!' not in sender:
                # Sender is a server name.
                idsource = self._getSid(sender)
                if idsource not in self.irc.servers:
                    idsource = self.spawnServer(sender, internal=False)
            else:
                # Sender is a nick!user@host prefix. Split it into its relevant parts.
                nick, ident, host = utils.splitHostmask(sender)
                idsource = self._getUid(nick, ident, host)

        try:
            func = getattr(self, 'handle_'+command.lower())
        except AttributeError:  # unhandled command
            pass
        else:
            parsed_args = func(idsource, command, args)
            if parsed_args is not None:
                return [idsource, command, parsed_args]

    def handle_001(self, source, command, args):
        """
        Handles 001 / RPL_WELCOME.
        """
        # enumerate our uplink
        self.irc.uplink = source

    def handle_005(self, source, command, args):
        """
        Handles 005 / RPL_ISUPPORT.
        """
        self.caps.update(self.parseCapabilities(args[1:-1]))
        log.debug('(%s) handle_005: self.caps is %s', self.irc.name, self.caps)

        if 'CHANMODES' in self.caps:
            self.irc.cmodes['*A'], self.irc.cmodes['*B'], self.irc.cmodes['*C'], self.irc.cmodes['*D'] = \
                self.caps['CHANMODES'].split(',')
        log.debug('(%s) handle_005: cmodes: %s', self.irc.name, self.irc.cmodes)

        if 'USERMODES' in self.caps:
            self.irc.umodes['*A'], self.irc.umodes['*B'], self.irc.umodes['*C'], self.irc.umodes['*D'] = \
                self.caps['USERMODES'].split(',')
        log.debug('(%s) handle_005: umodes: %s', self.irc.name, self.irc.umodes)

        self.casemapping = self.caps.get('CASEMAPPING', self.casemapping)
        log.debug('(%s) handle_005: casemapping set to %s', self.irc.name, self.casemapping)

        if 'PREFIX' in self.caps:
            self.irc.prefixmodes = prefixmodes = self.parsePrefixes(self.caps['PREFIX'])
            log.debug('(%s) handle_005: prefix modes set to %s', self.irc.name, self.irc.prefixmodes)

            # Autodetect common prefix mode names.
            for char, modename in COMMON_PREFIXMODES:
                # Don't overwrite existing named mode definitions.
                if char in self.irc.prefixmodes and modename not in self.irc.cmodes:
                    self.irc.cmodes[modename] = char
                    log.debug('(%s) handle_005: autodetecting mode %s (%s) as %s', self.irc.name,
                              char, self.irc.prefixmodes[char], modename)

        self.irc.connected.set()

    def handle_376(self, source, command, args):
        """
        Handles end of MOTD numerics, used to start things like autoperform.
        """

        # Run autoperform commands.
        for line in self.irc.serverdata.get("autoperform", []):
            self.irc.send(line)

        # Virtual endburst hook.
        if not self.has_eob:
            self.has_eob = True
            return {'parse_as': 'ENDBURST'}
    handle_422 = handle_376

    def handle_353(self, source, command, args):
        """
        Handles 353 / RPL_NAMREPLY.
        """
        # <- :charybdis.midnight.vpn 353 ice = #test :ice @GL

        # Mark "@"-type channels as secret automatically, per RFC2812.
        channel = self.irc.toLower(args[2])
        if args[1] == '@':
            self.irc.applyModes(channel, [('+s', None)])

        names = set()
        modes = set()
        prefix_to_mode = {v:k for k, v in self.irc.prefixmodes.items()}
        prefixes = ''.join(self.irc.prefixmodes.values())

        for name in args[-1].split():
            nick = name.lstrip(prefixes)

            # Get the PUID for the given nick. If one doesn't exist, spawn
            # a new virtual user. TODO: wait for WHO responses for each nick before
            # spawning in order to get a real ident/host.
            idsource = self._getUid(nick)

            # Queue these virtual users to be joined if they're not already in the channel,
            # or we're waiting for a kick acknowledgment for them.
            if (idsource not in self.irc.channels[channel].users) or (idsource in \
                    self.kick_queue.get(channel, ([],))[0]):
                names.add(idsource)
                self.irc.users[idsource].channels.add(channel)

            # Process prefix modes
            for char in name:
                if char in self.irc.prefixmodes.values():
                    modes.add(('+' + prefix_to_mode[char], idsource))
                else:
                    break

        # Statekeeping: make sure the channel's user list is updated!
        self.irc.channels[channel].users |= names
        self.irc.applyModes(channel, modes)

        log.debug('(%s) handle_353: adding users %s to %s', self.irc.name, names, channel)
        log.debug('(%s) handle_353: adding modes %s to %s', self.irc.name, modes, channel)

        # Unless /WHO has already been received for the given channel, we generally send the hook
        # for JOIN after /who data is received, to enumerate the ident, host, and real names of
        # users.
        if names and hasattr(self.irc.channels[channel], 'who_received'):
            # /WHO *HAS* already been received. Send JOIN hooks here because we use this to keep
            # track of any failed KICK attempts sent by the relay bot.
            log.debug('(%s) handle_353: sending JOIN hook because /WHO was already received for %s',
                      self.irc.name, channel)
            return {'channel': channel, 'users': names, 'modes': self.irc.channels[channel].modes,
                    'parse_as': "JOIN"}

    def handle_352(self, source, command, args):
        """
        Handles 352 / RPL_WHOREPLY.
        """
        # parameter count:               0   1     2       3         4                      5   6  7
        # <- :charybdis.midnight.vpn 352 ice #test ~pylink 127.0.0.1 charybdis.midnight.vpn ice H+ :0 PyLink
        # <- :charybdis.midnight.vpn 352 ice #test ~gl 127.0.0.1 charybdis.midnight.vpn GL H*@ :0 realname
        ident = args[2]
        host = args[3]
        nick = args[5]
        status = args[6]
        # Hopcount and realname field are together. We only care about the latter.
        realname = args[-1].split(' ', 1)[-1]
        uid = self.irc.nickToUid(nick)

        if uid is None:
            log.debug("(%s) Ignoring extraneous /WHO info for %s", self.irc.name, nick)
            return

        self.updateClient(uid, 'IDENT', ident)
        self.updateClient(uid, 'HOST', host)
        self.updateClient(uid, 'GECOS', realname)

        # The status given uses the following letters: <H|G>[*][@|+]
        # H means here (not marked /away)
        # G means away is set (we'll have to fake a message because it's not given)
        # * means IRCop.
        # The rest are prefix modes. Multiple can be given by the IRCd if multiple are set
        log.debug('(%s) handle_352: status string on user %s: %s', self.irc.name, nick, status)
        if status[0] == 'G':
            log.debug('(%s) handle_352: calling away() with argument', self.irc.name)
            self.away(uid, 'Away')
        elif status[0] == 'H':
            log.debug('(%s) handle_352: calling away() without argument', self.irc.name)
            self.away(uid, '')  # Unmark away status
        else:
            log.warning('(%s) handle_352: got wrong string %s for away status', self.irc.name, status[0])

        if '*' in status:  # Track IRCop status
            if not self.irc.isOper(uid, allowAuthed=False):
                # Don't send duplicate oper ups if the target is already oper.
                self.irc.applyModes(uid, [('+o', None)])
                self.irc.callHooks([uid, 'MODE', {'target': uid, 'modes': {('+o', None)}}])
                self.irc.callHooks([uid, 'CLIENT_OPERED', {'text': 'IRC Operator'}])
        elif self.irc.isOper(uid, allowAuthed=False) and not self.irc.isInternalClient(uid):
            # Track deopers
            self.irc.applyModes(uid, [('-o', None)])
            self.irc.callHooks([uid, 'MODE', {'target': uid, 'modes': {('-o', None)}}])

        self.who_received.add(uid)

    def handle_315(self, source, command, args):
        """
        Handles 315 / RPL_ENDOFWHO.
        """
        # <- :charybdis.midnight.vpn 315 ice #test :End of /WHO list.
        # Join all the users in which the last batch of /who requests were received.
        users = self.who_received.copy()
        self.who_received.clear()

        channel = self.irc.toLower(args[1])
        self.irc.channels[channel].who_received = True

        return {'channel': channel, 'users': users, 'modes': self.irc.channels[channel].modes,
                'parse_as': "JOIN"}

    def handle_433(self, source, command, args):
        # <- :millennium.overdrivenetworks.com 433 * ice :Nickname is already in use.
        # HACK: I don't like modifying the config entries raw, but this is difficult because
        # irc.pseudoclient doesn't exist as an attribute until we get run the ENDBURST stuff
        # in service_support (this is mapped to 005 here).
        self.conf_nick += '_'
        self.irc.serverdata['pylink_nick'] = self.conf_nick
        self.irc.send('NICK %s' % self.conf_nick)
    handle_432 = handle_437 = handle_433

    def handle_join(self, source, command, args):
        """
        Handles incoming JOINs.
        """
        # <- :GL|!~GL@127.0.0.1 JOIN #whatever
        channel = self.irc.toLower(args[0])
        self.join(source, channel)

        return {'channel': channel, 'users': [source], 'modes': self.irc.channels[channel].modes}

    def handle_kick(self, source, command, args):
        """
        Handles incoming KICKs.
        """
        # <- :GL!~gl@127.0.0.1 KICK #whatever GL| :xd
        channel = self.irc.toLower(args[0])
        target = self.irc.nickToUid(args[1])

        try:
            reason = args[2]
        except IndexError:
            reason = ''

        if channel in self.kick_queue:
            # Remove this client from the kick queue if present there.
            log.debug('(%s) kick: removing %s from kick queue for channel %s', self.irc.name, target, channel)
            self.kick_queue[channel][0].discard(target)

            if not self.kick_queue[channel][0]:
                log.debug('(%s) kick: cancelling kick timer for channel %s (all kicks accounted for)', self.irc.name, channel)
                # There aren't any kicks that failed to be acknowledged. We can remove the timer now
                self.kick_queue[channel][1].cancel()
                del self.kick_queue[channel]

        self.handle_part(target, 'KICK', [channel, reason])
        return {'channel': channel, 'target': target, 'text': reason}

    def handle_mode(self, source, command, args):
        """Handles MODE changes."""
        # <- :GL!~gl@127.0.0.1 MODE #dev +v ice
        # <- :ice MODE ice :+Zi
        target = args[0]
        if utils.isChannel(target):
            target = self.irc.toLower(target)
            oldobj = self.irc.channels[target].deepcopy()
        else:
            target = self.irc.nickToUid(target)
            oldobj = None
        modes = args[1:]
        changedmodes = self.irc.parseModes(target, modes)
        self.irc.applyModes(target, changedmodes)

        if self.irc.isInternalClient(target):
            log.debug('(%s) Suppressing MODE change hook for internal client %s', self.irc.name, target)
            return
        return {'target': target, 'modes': changedmodes, 'channeldata': oldobj}

    def handle_nick(self, source, command, args):
        """Handles NICK changes."""
        # <- :GL|!~GL@127.0.0.1 NICK :GL_

        if not self.irc.pseudoclient:
            # We haven't properly logged on yet, so any initial NICK should be treated as a forced
            # nick change for US. For example, this clause is used to handle forced nick changes
            # sent by ZNC, when the login nick and the actual IRC nick of the bouncer differ.

            # HACK: change the nick config entry so services_support knows what our main
            # pseudoclient is called.
            oldnick = self.irc.serverdata['pylink_nick']
            self.irc.serverdata['pylink_nick'] = self.conf_nick = args[0]
            log.debug('(%s) Pre-auth FNC: Forcing configured nick to %s from %s', self.irc.name, args[0], oldnick)
            return

        oldnick = self.irc.users[source].nick
        self.irc.users[source].nick = args[0]

        return {'newnick': args[0], 'oldnick': oldnick}

    def handle_part(self, source, command, args):
        """
        Handles incoming PARTs.
        """
        # <- :GL|!~GL@127.0.0.1 PART #whatever
        channels = list(map(self.irc.toLower, args[0].split(',')))
        try:
            reason = args[1]
        except IndexError:
            reason = ''

        for channel in channels:
            self.irc.channels[channel].removeuser(source)
        self.irc.users[source].channels -= set(channels)

        return {'channels': channels, 'text': reason}

    def handle_ping(self, source, command, args):
        """
        Handles incoming PING requests.
        """
        self.irc.send('PONG :%s' % args[0])

    def handle_pong(self, source, command, args):
        """
        Handles incoming PONG.
        """
        if source == self.irc.uplink:
            self.irc.lastping = time.time()

    def handle_privmsg(self, source, command, args):
        """Handles incoming PRIVMSG/NOTICE."""
        # <- :sender PRIVMSG #dev :afasfsa
        # <- :sender NOTICE somenick :afasfsa
        target = args[0]

        # We use lowercase channels internally.
        if utils.isChannel(target):
            target = self.irc.toLower(target)
        else:
            target = self.irc.nickToUid(target)
        if target:
            return {'target': target, 'text': args[1]}

    def handle_quit(self, source, command, args):
        """Handles incoming QUITs."""
        self.quit(source, args[0])
        return {'text': args[0]}

    handle_notice = handle_privmsg

Class = ClientbotWrapperProtocol
