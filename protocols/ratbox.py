import time

from pylinkirc import utils, conf
from pylinkirc.log import log
from pylinkirc.classes import *
from pylinkirc.protocols.ts6 import *

class RatboxProtocol(TS6Protocol):

    def __init__(self, irc):
        super().__init__(irc)
        # Don't require EUID for Ratbox
        self.required_caps.discard('EUID')

        self.hook_map['LOGIN'] = 'CLIENT_SERVICES_LOGIN'
        self.protocol_caps -= {'slash-in-hosts'}

    def connect(self):
        """Initializes a connection to a server."""
        super().connect()

        # Note: +r, +e, and +I support will be negotiated on link
        self.irc.cmodes = {'op': 'o', 'secret': 's', 'private': 'p', 'noextmsg': 'n', 'moderated': 'm',
                       'inviteonly': 'i', 'topiclock': 't', 'limit': 'l', 'ban': 'b', 'voice': 'v',
                       'key': 'k', 'sslonly': 'S', 'noknock': 'p',
                       '*A': 'beI',
                       '*B': 'k',
                       '*C': 'l',
                       '*D': 'imnpstrS'}

        self.irc.umodes = {
            'invisible': 'i', 'callerid': 'g', 'oper': 'o', 'admin': 'a', 'sno_botfloods': 'b',
            'sno_clientconnections': 'c', 'sno_extclientconnections': 'C', 'sno_debug': 'd',
            'sno_fullauthblock': 'f', 'sno_skill': 'k', 'locops': 'l',
            'sno_rejectedclients': 'r', 'snomask': 's', 'sno_badclientconnections': 'u',
            'wallops': 'w', 'sno_serverconnects': 'x', 'sno_stats': 'y',
            'operwall': 'z', 'sno_operspy': 'Z', 'deaf': 'D', 'servprotect': 'S',
            # Now, map all the ABCD type modes:
            '*A': '', '*B': '', '*C': '', '*D': 'igoabcCdfklrsuwxyzZD'
        }

    def spawnClient(self, nick, ident='null', host='null', realhost=None, modes=set(),
            server=None, ip='0.0.0.0', realname=None, ts=None, opertype=None,
            manipulatable=False):
        """
        Spawns a new client with the given options.

        Note: No nick collision / valid nickname checks are done here; it is
        up to plugins to make sure they don't introduce anything invalid.
        """

        # parameters: nickname, hopcount, nickTS, umodes, username, visible hostname, IP address,
        # UID, gecos

        server = server or self.irc.sid
        if not self.irc.isInternalServer(server):
            raise ValueError('Server %r is not a PyLink server!' % server)

        uid = self.uidgen[server].next_uid()

        ts = ts or int(time.time())
        realname = realname or conf.conf['bot']['realname']
        raw_modes = self.irc.joinModes(modes)

        orig_realhost = realhost
        realhost = realhost or host

        u = self.irc.users[uid] = IrcUser(nick, ts, uid, server, ident=ident, host=host, realname=realname,
            realhost=realhost, ip=ip, manipulatable=manipulatable)
        self.irc.applyModes(uid, modes)
        self.irc.servers[server].users.add(uid)
        self._send(server, "UID {nick} 1 {ts} {modes} {ident} {host} {ip} {uid} "
                   ":{realname}".format(ts=ts, host=host,
                    nick=nick, ident=ident, uid=uid,
                   modes=raw_modes, ip=ip, realname=realname))

        if orig_realhost:
            # If real host is specified, send it using ENCAP REALHOST
            self._send(uid, "ENCAP * REALHOST %s" % orig_realhost)

        return u

    def updateClient(self, target, field, text):
        """updateClient() stub for ratbox."""
        raise NotImplementedError("User data changing is not supported on ircd-ratbox.")

    def handle_realhost(self, uid, command, args):
        """Handles real host propagation."""
        log.debug('(%s) Got REALHOST %s for %s', args[0], uid)
        self.irc.users[uid].realhost = args[0]

    def handle_login(self, uid, command, args):
        """Handles login propagation on burst."""
        self.irc.users[uid].services_account = args[0]
        return {'text': args[0]}

Class = RatboxProtocol
