import time
import string

from pylinkirc import utils, conf
from pylinkirc.log import log
from pylinkirc.classes import Protocol, IrcUser, IrcServer

class ClientbotWrapperProtocol(Protocol):
    def __init__(self, irc):
        super().__init__(irc)

        # FIXME: Grab this from 005 / RPL_ISUPPORT instead of hardcoding.
        self.casemapping = 'ascii'

        self.caps = {}

        # Initialize counter-based pseudo UID  generators
        self.uidgen = utils.PUIDGenerator('PUID')
        self.sidgen = utils.PUIDGenerator('PSID')

    def _expandPUID(self, uid):
        """
        Returns the real nick for the given PUID.
        """
        if uid in self.irc.users:
            nick = self.irc.users[uid].nick
            log.debug('(%s) Mangling target PUID %s to nick %s', self.irc.name, uid, nick)
            return nick
        return uid

    def _formatText(self, source, text):
        """
        Formats text with the given sender as a prefix.
        """
        if self.irc.pseudoclient and source == self.irc.pseudoclient.uid:
            return text
        else:
            # TODO: configurable formatting
            return '<%s> %s' % (self.irc.getFriendlyName(source), text)

    def connect(self):
        """Initializes a connection to a server."""
        ts = self.irc.start_ts
        f = self.irc.send

        # TODO: fetch channel/user/prefix modes from RPL_ISUPPORT.
        #self.irc.prefixmodes = {'q': '~', 'a': '&', 'o': '@', 'h': '%', 'v': '+'}

        # HACK: Replace the SID from the config options with our own.
        old_sid = self.irc.sid
        self.irc.sid = sid = self.sidgen.next_uid()
        self.irc.servers[sid] = self.irc.servers[old_sid]
        del self.irc.servers[old_sid]

        sendpass = self.irc.serverdata.get("sendpass")
        if sendpass:
            f('PASS %s' % sendpass)

        # This is a really gross hack to get the defined NICK/IDENT/HOST/GECOS.
        # But this connection stuff is done before any of the spawnClient stuff in
        # services_support fires.
        f('NICK %s' % (self.irc.serverdata.get('pylink_nick') or conf.conf["bot"].get("nick", "PyLink")))
        ident = self.irc.serverdata.get('pylink_ident') or conf.conf["bot"].get("ident", "pylink")
        f('USER %s %s 0.0.0.0 %s' % (ident, ident,
                                     # TODO: per net realnames or hostnames aren't implemented yet.
                                     conf.conf["bot"].get("realname", "PyLink Clientbot")))

    def spawnClient(self, nick, ident='null', host='null', realhost=None, modes=set(),
            server=None, ip='0.0.0.0', realname=None, ts=None, opertype=None,
            manipulatable=False):
        """
        STUB: Pretends to spawn a new client with a subset of the given options.
        """

        server = server or self.irc.sid
        uid = self.uidgen.next_uid()

        ts = ts or int(time.time())
        realname = realname or ''
        log.debug('(%s) spawnClient stub called, saving nick %s as PUID %s', self.irc.name, nick, uid)
        u = self.irc.users[uid] = IrcUser(nick, ts, uid, ident=ident, host=host, realname=realname)
        log.debug('(%s) self.irc.users: %s', self.irc.name, self.irc.users)
        self.irc.servers[server].users.add(uid)
        return u

    def spawnServer(self, name, sid=None, uplink=None, desc=None, endburst_delay=0):
        """
        STUB: Pretends to spawn a new server with a subset of the given options.
        """
        name = name.lower()
        sid = self.sidgen.next_sid()
        self.irc.servers[sid] = IrcServer(uplink, name)
        return sid

    def join(self, client, channel):
        """STUB: Joins a user to a channel."""
        channel = self.irc.toLower(channel)

        self.irc.channels[channel].users.add(client)
        self.irc.users[client].channels.add(channel)

        # Only joins for the main PyLink client are actually forwarded. Others are ignored.
        if self.irc.pseudoclient and client == self.irc.pseudoclient.uid:
            self.irc.send('JOIN %s' % channel)
        else:
            log.debug('(%s) join: faking JOIN of client %s/%s to %s', self.irc.name, client,
                      self.irc.getFriendlyName(client), channel)

    def kick(self, source, channel, target, reason=''):
        """Sends channel kicks."""
        # TODO: handle kick failures and send rejoin hooks for the target
        reason = self._formatText(source, reason)
        self.irc.send('KICK %s %s :%s' % (channel, self._expandPUID(target), reason))
        self.part(target, channel, reason=reason)

    def message(self, source, target, text, notice=False):
        """Sends messages to the target."""
        command = 'NOTICE' if notice else 'PRIVMSG'
        target = self._expandPUID(target)

        self.irc.send('%s %s :%s' % (command, target, self._formatText(source, text)))

    def nick(self, source, newnick):
        """STUB: Sends NICK changes."""
        if source == irc.pseudoclient.uid:
            self.irc.send('NICK :%s' % (channel, self._expandPUID(target), reason))
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

    def part(self, source, channel, reason=''):
        """STUB: Parts a user from a channel."""
        self.irc.channels[channel].removeuser(source)
        self.irc.users[source].channels.discard(channel)

        # Only parts for the main PyLink client are actually forwarded. Others are ignored.
        if self.irc.pseudoclient and source == self.irc.pseudoclient.uid:
            self.irc.send('PART %s :%s' % (channel, reason))

    def quit(self, source, reason):
        """STUB: Quits a client."""
        self.removeClient(source)

    def sjoin(self, server, channel, users, ts=None, modes=set()):
        """STUB: bursts joins from a server."""
        puids = {u[-1] for u in users}
        for user in puids:
            self.irc.users[user].channels.add(channel)

        self.irc.channels[channel].users |= puids

    def squit(self, source, target, text):
        self._squit(source, target, text)

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
            log.debug('(%s) handle_events: sender is %s', self.irc.name, sender)
            if '!' not in sender:
                # Sender is a server name.
                idsource = self._getSid(sender)
                if idsource not in self.irc.servers:
                    idsource = self.spawnServer(sender)
            else:
                # Sender is a nick!user@host prefix. Split it into its relevant parts.
                nick, ident, host = utils.splitHostmask(sender)
                idsource = self.irc.nickToUid(nick)
                if not idsource:
                    idsource = self.spawnClient(nick, ident, host, server=self.irc.uplink).uid
            log.debug('(%s) handle_events: idsource is %s', self.irc.name, idsource)

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
        # TODO: capability negotiation happens here
        if not self.irc.connected.is_set():
            self.irc.connected.set()
            return {'parse_as': 'ENDBURST'}

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
        for name in args[-1].split():
            # TODO: process prefix modes instead of just stripping them
            name = name.lstrip(string.punctuation)

            # Get the PUID for the given nick. If one doesn't exist, spawn
            # a new virtual user. TODO: wait for WHO responses for each nick before
            # spawning in order to get a real ident/host.
            idsource = self.irc.nickToUid(name) or self.spawnClient(name, server=self.irc.uplink).uid

            # Queue these virtual users to be joined if they're not already in the channel.
            if idsource not in self.irc.channels[channel].users:
                names.add(idsource)
                self.irc.users[idsource].channels.add(channel)

        # Statekeeping: make sure the channel's user list is updated!
        self.irc.channels[channel].users |= names

        log.debug('(%s) handle_353: adding users %s to %s', self.irc.name, names, channel)

        return {'channel': channel, 'users': names, 'modes': self.irc.channels[channel].modes,
                'parse_as': "JOIN"}

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

        self.part(target, channel, reason)
        return {'channel': channel, 'target': target, 'text': reason}

    def handle_nick(self, source, command, args):
        # <- :GL|!~GL@127.0.0.1 NICK :GL_
        oldnick = self.irc.users[source].nick
        self.nick(source, args[0])
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
            self.part(source, channel, reason)

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
            target = self._getUid(target)
        return {'target': target, 'text': args[1]}

    def handle_quit(self, source, command, args):
        """Handles incoming QUITs."""
        self.quit(source, args[0])
        return {'text': args[0]}

    handle_notice = handle_privmsg

Class = ClientbotWrapperProtocol
