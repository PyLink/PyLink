import time
import sys
import os
import re

from pylinkirc import utils
from pylinkirc.log import log
from pylinkirc.classes import *
from pylinkirc.protocols.ts6 import *

class RatboxProtocol(TS6Protocol):

    def __init__(self, irc):
        super().__init__(irc)
        # Don't require EUID for Ratbox
        self.required_caps.discard('EUID')

    def connect(self):
        """Initializes a connection to a server."""
        super().connect()

        self.irc.cmodes.update({'banexception': 'e', 'invex': 'I'})
        self.irc.cmodes['*A'] += 'eI'

        self.irc.umodes = {
            'invisible': 'i', 'callerid': 'g', 'oper': 'o', 'admin': 'a', 'sno_botwarnings': 'b',
            'sno_clientconnections': 'c', 'sno_extclientconnections': 'C', 'sno_debug': 'd',
            'sno_fullauthblock': 'f', 'sno_skill': 'k', 'sno_locops': 'l',
            'sno_rejectedclients': 'r', 'snomask': 's', 'sno_badclientconnections': 'u',
            'wallops': 'w', 'sno_server_connects': 'x', 'sno_admin_requests': 'y',
            'sno_operwall': 'z', 'sno_operspy': 'Z', 'deaf': 'D',
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
        realname = realname or self.irc.botdata['realname']
        raw_modes = self.irc.joinModes(modes)

        orig_realhost = realhost
        realhost = realhost or host

        u = self.irc.users[uid] = IrcUser(nick, ts, uid, ident=ident, host=host, realname=realname,
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
        raise NotImplementedError

    def handle_realhost(self, uid, command, args):
        """Handles real host propagation."""
        log.debug('(%s) Got REALHOST %s for %s', args[0], uid)
        self.irc.users[uid].realhost = args[0]

Class = RatboxProtocol
