"""
ratbox.py: ircd-ratbox protocol module for PyLink.
"""

import time

from pylinkirc import utils, conf
from pylinkirc.log import log
from pylinkirc.classes import *
from pylinkirc.protocols.ts6 import *

class RatboxProtocol(TS6Protocol):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Don't require EUID for Ratbox
        self.required_caps.discard('EUID')

        self.hook_map['LOGIN'] = 'CLIENT_SERVICES_LOGIN'
        self.protocol_caps -= {'slash-in-hosts'}

    def post_connect(self):
        """Initializes a connection to a server."""

        super().post_connect()

        # Note: +r, +e, and +I support will be negotiated on link
        self.cmodes = {'op': 'o', 'secret': 's', 'private': 'p', 'noextmsg': 'n', 'moderated': 'm',
                       'inviteonly': 'i', 'topiclock': 't', 'limit': 'l', 'ban': 'b', 'voice': 'v',
                       'key': 'k', 'sslonly': 'S', 'noknock': 'p',
                       '*A': 'beI',
                       '*B': 'k',
                       '*C': 'l',
                       '*D': 'imnpstrS'}

        self.umodes = {
            'invisible': 'i', 'callerid': 'g', 'oper': 'o', 'admin': 'a', 'sno_botfloods': 'b',
            'sno_clientconnections': 'c', 'sno_extclientconnections': 'C', 'sno_debug': 'd',
            'sno_fullauthblock': 'f', 'sno_skill': 'k', 'locops': 'l',
            'sno_rejectedclients': 'r', 'snomask': 's', 'sno_badclientconnections': 'u',
            'wallops': 'w', 'sno_serverconnects': 'x', 'sno_stats': 'y',
            'operwall': 'z', 'sno_operspy': 'Z', 'deaf': 'D', 'servprotect': 'S',
            # Now, map all the ABCD type modes:
            '*A': '', '*B': '', '*C': '', '*D': 'igoabcCdfklrsuwxyzZD'
        }

        self.extbans_matching.clear()

    def spawn_client(self, nick, ident='null', host='null', realhost=None, modes=set(),
            server=None, ip='0.0.0.0', realname=None, ts=None, opertype=None,
            manipulatable=False):
        """
        Spawns a new client with the given options.

        Note: No nick collision / valid nickname checks are done here; it is
        up to plugins to make sure they don't introduce anything invalid.
        """

        # parameters: nickname, hopcount, nickTS, umodes, username, visible hostname, IP address,
        # UID, gecos

        server = server or self.sid
        if not self.is_internal_server(server):
            raise ValueError('Server %r is not a PyLink server!' % server)

        uid = self.uidgen[server].next_uid()

        ts = ts or int(time.time())
        realname = realname or conf.conf['bot']['realname']
        raw_modes = self.join_modes(modes)

        orig_realhost = realhost
        realhost = realhost or host

        u = self.users[uid] = User(self, nick, ts, uid, server, ident=ident, host=host, realname=realname,
            realhost=realhost, ip=ip, manipulatable=manipulatable)
        self.apply_modes(uid, modes)
        self.servers[server].users.add(uid)

        self._send_with_prefix(server, "UID {nick} 1 {ts} {modes} {ident} {host} {ip} {uid} "
                               ":{realname}".format(ts=ts, host=host,
                               nick=nick, ident=ident, uid=uid,
                               modes=raw_modes, ip=ip, realname=realname))

        if orig_realhost:
            # If real host is specified, send it using ENCAP REALHOST
            self._send_with_prefix(uid, "ENCAP * REALHOST %s" % orig_realhost)

        return u

    def update_client(self, target, field, text):
        """update_client() stub for ratbox."""
        raise NotImplementedError("User data changing is not supported on ircd-ratbox.")

Class = RatboxProtocol
