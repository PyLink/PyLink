import time

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

        if client == self.irc.pseudoclient.uid:
            self.irc.send('JOIN %s' % channel)
        else:
            log.debug('(%s) join: faking JOIN of client %s/%s to %s', self.irc.name, client,
                      self.irc.getFriendlyName(client), channel)

    def ping(self, source=None, target=None):
        if self.irc.uplink:
            self.irc.send('PING %s' % self.irc.getFriendlyName(self.irc.uplink))

    def handle_events(self, data):
        """Event handler for the RFC1459 (clientbot) protocol.
        """
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


Class = ClientbotWrapperProtocol
