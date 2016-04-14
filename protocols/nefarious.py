"""
p10.py: P10 protocol module for PyLink, targetting Nefarious 2.
"""

import sys
import os

# Import hacks to access utils and classes...
curdir = os.path.dirname(__file__)
sys.path += [curdir, os.path.dirname(curdir)]

import utils
from log import log
from classes import *

class P10SIDGenerator():
    def __init__(self, irc):
        self.irc = irc
        try:
            query = irc.serverdata["sidrange"]
        except (KeyError, ValueError):
            raise RuntimeError('(%s) "sidrange" is missing from your server configuration block!' % irc.name)

        try:
            # Query is taken in the format MINNUM-MAXNUM, so we need
            # to get the actual number values out of that.
            self.minnum, self.maxnum = map(int, query.split('-', 1))
        except ValueError:
            raise RuntimeError('(%s) Invalid sidrange %r' % (irc.name, query))
        else:
            # Initialize a counter for the last numeric we've used.
            self.currentnum = self.minnum

    @staticmethod
    def encode(num, length=2):
        """
        Encodes a given numeric using P10 Base64 numeric nicks, as documented at
        https://github.com/evilnet/nefarious2/blob/a29b63144/doc/p10.txt#L69-L92
        """
        c = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789[]'
        s = ''
        # To accomplish this encoding, we divide the given value into a series of places. Much like
        # a number can be divided into hundreds, tens, and digits (e.g. 128 is 1, 2, and 8), the
        # places here add up to the value given. In the case of P10 Base64, each place can represent
        # 0 to 63. divmod() is used to get the quotient and remainder of a division operation. When
        # used on the input number and the length of our allowed characters list, the output becomes
        # the values of (the next highest base, the current base).
        places = divmod(num, len(c))
        print('places:', places)
        while places[0] >= len(c):
            # If the base one higher than ours is greater than the largest value each base can
            # represent, repeat the divmod process on that value,also keeping track of the
            # remaining values we've calculated already.
            places = divmod(places[0], len(c)) + places[1:]
            print('places:', places)

        # Expand the place values we've got to the characters list now.
        chars = [c[place] for place in places]
        s = ''.join(chars)
        # Pad up to the required string length using the first character in our list (A).
        return s.rjust(length, c[0])

    def next_sid(self):
        """
        Returns the next available SID.
        """
        if self.currentnum > self.maxnum:
            raise ProtocolError("Ran out of valid SIDs! Check your 'sidrange' setting and try again.")
        sid = self.encodeSID(self.currentnum)

        self.currentnum += 1
        return sid

class P10Protocol(Protocol):

    def __init__(self, irc):
        super().__init__(irc)

        # Dictionary of UID generators (one for each server) that the protocol module will fill in.
        self.uidgen = {}

        # SID generator for P10.
        self.sidgen = P10SIDGenerator(irc)

    def _send(self, source, text):
        self.irc.send("%s %s" % (source, text))

    @staticmethod
    def _getCommand(token):
        """Returns the command name for the given token."""
        tokens = {
            'AC': 'ACCOUNT',
            'AD': 'ADMIN',
            'LL': 'ASLL',
            'A': 'AWAY',
            'B': 'BURST',
            'CAP': 'CAP',
            'CM': 'CLEARMODE',
            'CLOSE': 'CLOSE',
            'CN': 'CNOTICE',
            'CO': 'CONNECT',
            'CP': 'CPRIVMSG',
            'C': 'CREATE',
            'DE': 'DESTRUCT',
            'DS': 'DESYNCH',
            'DIE': 'DIE',
            'DNS': 'DNS',
            'EB': 'END_OF_BURST',
            'EA': 'EOB_ACK',
            'Y': 'ERROR',
            'GET': 'GET',
            'GL': 'GLINE',
            'HASH': 'HASH',
            'HELP': 'HELP',
            'F': 'INFO',
            'I': 'INVITE',
            'ISON': 'ISON',
            'J': 'JOIN',
            'JU': 'JUPE',
            'K': 'KICK',
            'D': 'KILL',
            'LI': 'LINKS',
            'LIST': 'LIST',
            'LU': 'LUSERS',
            'MAP': 'MAP',
            'M': 'MODE',
            'MO': 'MOTD',
            'E': 'NAMES',
            'N': 'NICK',
            'O': 'NOTICE',
            'OPER': 'OPER',
            'OM': 'OPMODE',
            'L': 'PART',
            'PA': 'PASS',
            'G': 'PING',
            'Z': 'PONG',
            'POST': 'POST',
            'P': 'PRIVMSG',
            'PRIVS': 'PRIVS',
            'PROTO': 'PROTO',
            'Q': 'QUIT',
            'REHASH': 'REHASH',
            'RESET': 'RESET',
            'RESTART': 'RESTART',
            'RI': 'RPING',
            'RO': 'RPONG',
            'S': 'SERVER',
            'SERVSET': 'SERVLIST',
            'SERVSET': 'SERVSET',
            'SET': 'SET',
            'SE': 'SETTIME',
            'U': 'SILENCE',
            'SQUERY': 'SQUERY',
            'SQ': 'SQUIT',
            'R': 'STATS',
            'TI': 'TIME',
            'T': 'TOPIC',
            'TR': 'TRACE',
            'UP': 'UPING',
            'USER': 'USER',
            'USERHOST': 'USERHOST',
            'USERIP': 'USERIP',
            'V': 'VERSION',
            'WC': 'WALLCHOPS',
            'WA': 'WALLOPS',
            'WU': 'WALLUSERS',
            'WV': 'WALLVOICES',
            'H': 'WHO',
            'W': 'WHOIS',
            'X': 'WHOWAS',
            'XQ': 'XQUERY',
            'XR': 'XREPLY',
            'SN': 'SVSNICK',
            'SJ': 'SVSJOIN',
            'SH': 'SETHOST'
        }
        # If the token isn't in the list, return it raw.
        return tokens.get(token, token)

    def spawnClient(self, nick, ident='null', host='null', realhost=None, modes=set(),
            server=None, ip='0.0.0.0', realname=None, ts=None, opertype='IRC Operator',
            manipulatable=False):
        # {7N} *** NICK
        # 1 <nickname>
        # 2 <hops>
        # 3 <TS>
        # 4 <userid> <-- a.k.a ident
        # 5 <host>
        # 6 [<+modes>]
        # 7+ [<mode parameters>]
        # -3 <base64 IP>
        # -2 <numeric>
        # -1 <fullname>

        server = server or self.irc.sid
        if not self.irc.isInternalServer(server):
            raise ValueError('Server %r is not a PyLink server!' % server)

        # Create an UIDGenerator instance for every SID, so that each gets
        # distinct values.
        uid = self.uidgen.setdefault(server, utils.P10UIDGenerator(server)).next_uid()

        # Fill in all the values we need
        ts = ts or int(time.time())
        realname = realname or self.irc.botdata['realname']
        realhost = realhost or host
        raw_modes = utils.joinModes(modes)

        # Initialize an IrcUser instance
        u = self.irc.users[uid] = IrcUser(nick, ts, uid, ident=ident, host=host, realname=realname,
                                          realhost=realhost, ip=ip, manipulatable=manipulatable,
                                          opertype=opertype)

        # Fill in modes and add it to our users index
        utils.applyModes(self.irc, uid, modes)
        self.irc.servers[server].users.add(uid)
        # TODO: send IPs
        self._send(server, "N {nick} 1 {ts} {ident} {host} {modes} AAAAAA {uid} "
                   ":{realname}".format(ts=ts, host=host, nick=nick, ident=ident, uid=uid,
                                        modes=raw_modes, ip=ip, realname=realname,
                                        realhost=realhost))
        return u

    def join(self, client, channel):
        pass

    def ping(*args):
        pass

    def connect(self):
        """Initializes a connection to a server."""
        ts = self.irc.start_ts

        self.irc.send("PASS :%s" % self.irc.serverdata["sendpass"])

        # {7S} *** SERVER

        # 1 <name of new server>
        # 2 <hops>
        # 3 <boot TS>
        # 4 <link TS>
        # 5 <protocol>
        # 6 <numeric of new server><max client numeric>
        # 7 <flags> <-- Mark ourselves as a service with IPv6 support (+s & +6) -GLolol
        # -1 <description of new server>

        name = self.irc.serverdata["hostname"]

        # HACK: Encode our SID everywhere, and replace it in the IrcServer index.
        old_sid = self.irc.sid
        self.irc.sid = sid = self.sidgen.encode(self.irc.serverdata["sid"])
        self.irc.servers[sid] = self.irc.servers[old_sid]
        del self.irc.servers[old_sid]

        desc = self.irc.serverdata.get('serverdesc') or self.irc.botdata['serverdesc']

        self.irc.send('SERVER %s 1 %s %s J10 %s]]] +s6 :%s' % (name, ts, ts, sid, desc))
        self._send(sid, "EB")
        self.irc.connected.set()

    def handle_events(self, data):
        """
        Event handler for the P10 protocol.

        This passes most commands to the various handle_ABCD() functions defined elsewhere in the
        protocol modules, coersing various sender prefixes from nicks and server names to P10
        "numeric nicks", whenever possible.

        Commands sent without an explicit sender prefix are treated as originating from the uplink
        server.
        """
        data = data.split(" ")
        args = self.parseArgs(data)

        sender = args[0]
        if sender.startswith(':'):
            # From https://github.com/evilnet/nefarious2/blob/a29b63144/doc/p10.txt#L140:
            # if source begins with a colon, it (except for the colon) is the name. otherwise, it is
            # a numeric. a P10 implementation must only send lines with a numeric source prefix.
            sender = sender[1:]

        command_token = args[1].upper()

        # If the sender isn't in numeric format, try to convert it automatically.
        sender_sid = self._getSid(sender)
        sender_uid = self._getUid(sender)
        if sender_sid in self.irc.servers:
            # Sender is a server (converting from name to SID gave a valid result).
            sender = sender_server
        elif sender_uid in self.irc.users:
            # Sender is a user (converting from name to UID gave a valid result).
            sender = self._getUid(sender)
        else:
            # No sender prefix; treat as coming from uplink IRCd.
            sender = self.irc.uplink

        args = args[2:]

        try:
            # Convert the token given into a regular command, if present.
            command = self._getCommand(command_token)

            func = getattr(self, 'handle_'+command.lower())

        except AttributeError:  # Unhandled command, ignore
            return

        else:  # Send a hook with the hook arguments given by the handler function.
            parsed_args = func(numeric, command, args)
            if parsed_args is not None:
                return [numeric, command, parsed_args]

Class = P10Protocol
