"""
ts6_common.py: Common base protocol class with functions shared by the UnrealIRCd, InspIRCd, and TS6 protocol modules.
"""

import string
import time

from pylinkirc import conf, structures
from pylinkirc.classes import *
from pylinkirc.log import log
from pylinkirc.protocols.ircs2s_common import *

__all__ = ['TS6BaseProtocol']


class TS6SIDGenerator():
    """
    TS6 SID Generator. <query> is a 3 character string with any combination of
    uppercase letters, digits, and #'s. it must contain at least one #,
    which are used by the generator as a wildcard. On every next_sid() call,
    the first available wildcard character (from the right) will be
    incremented to generate the next SID.

    When there are no more available SIDs left (SIDs are not reused, only
    incremented), RuntimeError is raised.

    Example queries:
        "1#A" would give: 10A, 11A, 12A ... 19A, 1AA, 1BA ... 1ZA (36 total results)
        "#BQ" would give: 0BQ, 1BQ, 2BQ ... 9BQ (10 total results)
        "6##" would give: 600, 601, 602, ... 60Y, 60Z, 610, 611, ... 6ZZ (1296 total results)
    """

    def __init__(self, irc):
        self.irc = irc
        try:
            self.query = query = list(irc.serverdata["sidrange"])
        except KeyError:
            raise RuntimeError('(%s) "sidrange" is missing from your server configuration block!' % irc.name)

        self.iters = self.query.copy()
        self.output = self.query.copy()
        self.allowedchars = {}
        qlen = len(query)

        assert qlen == 3, 'Incorrect length for a SID (must be 3, got %s)' % qlen
        assert '#' in query, "Must be at least one wildcard (#) in query"

        for idx, char in enumerate(query):
            # Iterate over each character in the query string we got, along
            # with its index in the string.
            assert char in (string.digits+string.ascii_uppercase+"#"), \
                "Invalid character %r found." % char
            if char == '#':
                if idx == 0:  # The first char be only digits
                    self.allowedchars[idx] = string.digits
                else:
                    self.allowedchars[idx] = string.digits+string.ascii_uppercase
                self.iters[idx] = iter(self.allowedchars[idx])
                self.output[idx] = self.allowedchars[idx][0]
                next(self.iters[idx])

    def increment(self, pos=2):
        """
        Increments the SID generator to the next available SID.
        """
        if pos < 0:
            # Oh no, we've wrapped back to the start!
            raise RuntimeError('No more available SIDs!')
        it = self.iters[pos]
        try:
            self.output[pos] = next(it)
        except TypeError:  # This position is not an iterator, but a string.
            self.increment(pos-1)
        except StopIteration:
            self.output[pos] = self.allowedchars[pos][0]
            self.iters[pos] = iter(self.allowedchars[pos])
            next(self.iters[pos])
            self.increment(pos-1)

    def next_sid(self):
        """
        Returns the next unused TS6 SID for the server.
        """
        while ''.join(self.output) in self.irc.servers:
            # Increment until the SID we have doesn't already exist.
            self.increment()
        sid = ''.join(self.output)
        return sid

class TS6UIDGenerator(UIDGenerator):
     """Implements an incremental TS6 UID Generator."""

     def __init__(self, sid):
         # TS6 UIDs are 6 characters in length (9 including the SID).
         # They go from ABCDEFGHIJKLMNOPQRSTUVWXYZ -> 0123456789 -> wrap around:
         # e.g. AAAAAA, AAAAAB ..., AAAAA8, AAAAA9, AAAABA, etc.
         uidchars = string.ascii_uppercase + string.digits
         length = 6
         super().__init__(uidchars, length, sid)

class TS6BaseProtocol(IRCS2SProtocol):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Dictionary of UID generators (one for each server).
        self.uidgen = structures.KeyedDefaultdict(TS6UIDGenerator)

        # SID generator for TS6.
        self.sidgen = TS6SIDGenerator(self)

        # Most TS6 variations (unreal, inspircd, charybdis) support this. For
        # pure TS6, we also require the CHW capability which explicitly declares
        # support.
        self.protocol_caps |= {'has-statusmsg'}

    ### OUTGOING COMMANDS

    def kill(self, numeric, target, reason):
        """Sends a kill from a PyLink client/server."""

        if (not self.is_internal_client(numeric)) and \
                (not self.is_internal_server(numeric)):
            raise LookupError('No such PyLink client/server exists.')

        # From TS6 docs:
        # KILL:
        # parameters: target user, path

        # The format of the path parameter is some sort of description of the source of
        # the kill followed by a space and a parenthesized reason. To avoid overflow,
        # it is recommended not to add anything to the path.

        assert target in self.users, "Unknown target %r for kill()!" % target

        if numeric in self.users:
            # Killer was an user. Follow examples of setting the path to be "killer.host!killer.nick".
            userobj = self.users[numeric]
            killpath = '%s!%s' % (userobj.host, userobj.nick)
        elif numeric in self.servers:
            # Sender was a server; killpath is just its name.
            killpath = self.servers[numeric].name
        else:
            # Invalid sender?! This shouldn't happen, but make the killpath our server name anyways.
            log.warning('(%s) Invalid sender %s for kill(); using our server name instead.',
                        self.name, numeric)
            killpath = self.servers[self.sid].name

        self._send_with_prefix(numeric, 'KILL %s :%s (%s)' % (target, killpath, reason))
        self._remove_client(target)

    def nick(self, numeric, newnick):
        """Changes the nick of a PyLink client."""
        if not self.is_internal_client(numeric):
            raise LookupError('No such PyLink client exists.')

        self._send_with_prefix(numeric, 'NICK %s %s' % (newnick, int(time.time())))

        self.users[numeric].nick = newnick

        # Update the NICK TS.
        self.users[numeric].ts = int(time.time())

    def spawn_server(self, name, sid=None, uplink=None, desc=None):
        """
        Spawns a server off a PyLink server. desc (server description)
        defaults to the one in the config. uplink defaults to the main PyLink
        server, and sid (the server ID) is automatically generated if not
        given.
        """
        # -> :0AL SID test.server 1 0XY :some silly pseudoserver
        uplink = uplink or self.sid
        name = name.lower()
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
        self._send_with_prefix(uplink, 'SID %s %s %s :%s' % (name, self.servers[sid].hopcount, sid, desc))
        return sid

    def away(self, source, text):
        """Sends an AWAY message from a PyLink client. <text> can be an empty string
        to unset AWAY status."""
        if text:
            self._send_with_prefix(source, 'AWAY :%s' % text)
        else:
            self._send_with_prefix(source, 'AWAY')
        self.users[source].away = text

    ### HANDLERS

    def handle_knock(self, numeric, command, args):
        """Handles channel KNOCKs."""
        # InspIRCd:
        # <- :70MAAAAAA ENCAP * KNOCK #blah :abcdefg
        # Charybdis:
        # <- :42XAAAAAC KNOCK #endlessvoid
        # UnrealIRCd propagates knocks as a channel notice to all ops, so this handler is not used there.
        channel = args[0]
        try:
            text = args[1]
        except IndexError:
            text = ''
        return {'channel': channel, 'text': text}

    def handle_nick(self, numeric, command, args):
        """Handles incoming NICK changes."""
        # <- :70MAAAAAA NICK jlu5-devel 1434744242
        oldnick = self.users[numeric].nick
        newnick = self.users[numeric].nick = args[0]

        # Update the nick TS.
        self.users[numeric].ts = ts = int(args[1])

        return {'newnick': newnick, 'oldnick': oldnick, 'ts': ts}

    def handle_save(self, numeric, command, args):
        """Handles incoming SAVE messages, used to handle nick collisions."""
        # In this below example, the client Derp_ already exists,
        # and trying to change someone's nick to it will cause a nick
        # collision. On TS6 IRCds, this will simply set the collided user's
        # nick to its UID.

        # <- :70MAAAAAA PRIVMSG 0AL000001 :nickclient PyLink Derp_
        # -> :0AL000001 NICK Derp_ 1433728673
        # <- :70M SAVE 0AL000001 1433728673
        user = args[0]
        oldnick = self.users[user].nick
        self.users[user].nick = user

        # TS6 SAVE sets nick TS to 100. This is hardcoded in InspIRCd and
        # charybdis.
        self.users[user].ts = 100

        return {'target': user, 'ts': 100, 'oldnick': oldnick}

    def handle_server(self, numeric, command, args):
        """Handles the SERVER command, used for introducing older (TS5) servers."""
        # <- :services.int SERVER a.bc 2 :(H) [jlu5] test jupe
        servername = args[0].lower()
        sdesc = args[-1]
        self.servers[servername] = Server(self, numeric, servername, desc=sdesc)
        return {'name': servername, 'sid': None, 'text': sdesc}

    def handle_sid(self, numeric, command, args):
        """Handles the SID command, used for introducing remote servers by our uplink."""
        # <- SID services.int 2 00A :Shaltúre IRC Services
        # parameters: server name, hopcount, sid, server description
        sname = args[0].lower()
        sid = args[2]
        sdesc = args[-1]
        self.servers[sid] = Server(self, numeric, sname, desc=sdesc)
        return {'name': sname, 'sid': sid, 'text': sdesc}

    def handle_svsnick(self, source, command, args):
        """Handles SVSNICK (forced nickname change attempts)."""
        # InspIRCd:
        # <- :00A ENCAP 902 SVSNICK 902AAAAAB Guest53593 :1468299404
        # This is rewritten to SVSNICK with args ['902AAAAAB', 'Guest53593', '1468299404']

        # UnrealIRCd:
        # <- :services.midnight.vpn SVSNICK jlu5 Guest87795 1468303726
        return {'target': self._get_UID(args[0]), 'newnick': args[1]}
