"""
nefarious.py: Nefarious IRCu protocol module for PyLink.
"""

import sys
import os
import base64
from ipaddress import ip_address

# Import hacks to access utils and classes...
curdir = os.path.dirname(__file__)
sys.path += [curdir, os.path.dirname(curdir)]

import utils
from log import log
from classes import *

def p10b64encode(num, length=2):
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

    def next_sid(self):
        """
        Returns the next available SID.
        """
        if self.currentnum > self.maxnum:
            raise ProtocolError("Ran out of valid SIDs! Check your 'sidrange' setting and try again.")
        sid = p10b64encode(self.currentnum)

        self.currentnum += 1
        return sid

class P10Protocol(Protocol):

    def __init__(self, irc):
        super().__init__(irc)

        # Dictionary of UID generators (one for each server) that the protocol module will fill in.
        self.uidgen = {}

        # SID generator for P10.
        self.sidgen = P10SIDGenerator(irc)

        self.hook_map = {'END_OF_BURST': 'ENDBURST', 'OPMODE': 'MODE'}

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

    ### COMMANDS

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

        # Encode IPs when sending
        if ip_address(ip).version == 4:
            # Thanks to Jobe @ evilnet for the tips here! -GL
            ip = b'\x00\x00' + socket.inet_aton(ip)
            b64ip = base64.b64encode(ip, b'[]')[2:].decode()
        else:  # TODO: propagate IPv6 address, but only if uplink supports it
            b64ip = 'AAAAAA'

        self._send(server, "N {nick} 1 {ts} {ident} {host} {modes} {ip} {uid} "
                   ":{realname}".format(ts=ts, host=host, nick=nick, ident=ident, uid=uid,
                                        modes=raw_modes, ip=b64ip, realname=realname,
                                        realhost=realhost))
        return u

    def join(self, client, channel):
        """Joins a PyLink client to a channel."""
        # <- ABAAB J #test3 1460744371
        channel = utils.toLower(self.irc, channel)
        ts = self.irc.channels[channel].ts

        if not self.irc.isInternalClient(client):
            raise LookupError('No such PyLink client exists.')

        if not self.irc.channels[channel].users:
            # Empty channels should be created with the CREATE command.
            self._send(client, "C {channel} {ts}".format(ts=ts, channel=channel))
        else:
            self._send(client, "J {channel} {ts}".format(ts=ts, channel=channel))

        self.irc.channels[channel].users.add(client)
        self.irc.users[client].channels.add(channel)

    def kick(self, numeric, channel, target, reason=None):
        """Sends kicks from a PyLink client/server."""

        if (not self.irc.isInternalClient(numeric)) and \
                (not self.irc.isInternalServer(numeric)):
            raise LookupError('No such PyLink client/server exists.')

        channel = utils.toLower(self.irc, channel)
        if not reason:
            reason = 'No reason given'

        self._send(numeric, 'K %s %s :%s' % (channel, target, reason))

        # We can pretend the target left by its own will; all we really care about
        # is that the target gets removed from the channel userlist, and calling
        # handle_part() does that just fine.
        self.handle_part(target, 'KICK', [channel])

    def kill(self, numeric, target, reason):
        """Sends a kill from a PyLink client/server."""
        # <- ABAAA D AyAAA :nefarious.midnight.vpn!GL (test)

        if (not self.irc.isInternalClient(numeric)) and \
                (not self.irc.isInternalServer(numeric)):
            raise LookupError('No such PyLink client/server exists.')

        self._send(numeric, 'D %s :Killed (%s)' % (target, reason))
        self.removeClient(target)

    def message(self, numeric, target, text):
        """Sends a PRIVMSG from a PyLink client."""
        if not self.irc.isInternalClient(numeric):
            raise LookupError('No such PyLink client exists.')

        self._send(numeric, 'P %s :%s' % (target, text))

    def mode(self, numeric, target, modes, ts=None):
        """Sends mode changes from a PyLink client/server."""
        # <- ABAAA M GL -w
        # <- ABAAA M #test +v ABAAB 1460747615

        if (not self.irc.isInternalClient(numeric)) and \
                (not self.irc.isInternalServer(numeric)):
            raise LookupError('No such PyLink client/server exists.')

        utils.applyModes(self.irc, target, modes)
        modes = list(modes)

        # According to the P10 specification:
        # https://github.com/evilnet/nefarious2/blob/master/doc/p10.txt#L29
        # One line can have a max of 15 parameters. Excluding the target and the first part of the
        # modestring, this means we can send a max of 13 modes with arguments per line.
        if utils.isChannel(target):
            # Channel mode changes have a trailing TS. User mode changes do not.
            cobj = self.irc.channels[utils.toLower(self.irc, target)]
            ts = ts or cobj.ts
            send_ts = True
        else:
            send_ts = False

        while modes[:12]:
            joinedmodes = utils.joinModes([m for m in modes[:12]])
            modes = modes[12:]
            self._send(numeric, 'M %s %s%s' % (target, joinedmodes, ' %s' % ts if send_ts else ''))

    def nick(self, numeric, newnick):
        """Changes the nick of a PyLink client."""
        # <- ABAAA N GL_ 1460753763
        if not self.irc.isInternalClient(numeric):
            raise LookupError('No such PyLink client exists.')

        self._send(numeric, 'NICK %s %s' % (newnick, int(time.time())))
        self.irc.users[numeric].nick = newnick

    def notice(self, numeric, target, text):
        """Sends a NOTICE from a PyLink client."""
        if not self.irc.isInternalClient(numeric):
            raise LookupError('No such PyLink client exists.')

        self._send(numeric, 'O %s :%s' % (target, text))

    def part(self, client, channel, reason=None):
        """Sends a part from a PyLink client."""
        channel = utils.toLower(self.irc, channel)

        if not self.irc.isInternalClient(client):
            raise LookupError('No such PyLink client exists.')

        msg = "L %s" % channel
        if reason:
            msg += " :%s" % reason
        self._send(client, msg)
        self.handle_part(client, 'PART', [channel])

    def ping(self, source=None, target=None):
        """Sends a PING to a target server. Periodic PINGs are sent to our uplink
        automatically by the Irc() internals; plugins shouldn't have to use this."""
        source = source or self.irc.sid
        if source is None:
            return
        if target is not None:
            self._send(source, 'G %s %s' % (source, target))
        else:
            self._send(source, 'G %s' % source)

    def quit(self, numeric, reason):
        """Quits a PyLink client."""
        if self.irc.isInternalClient(numeric):
            self._send(numeric, "Q :%s" % reason)
            self.removeClient(numeric)
        else:
            raise LookupError("No such PyLink client exists.")

    ### HANDLERS

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
        self.irc.sid = sid = p10b64encode(self.irc.serverdata["sid"])
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

        # If the sender isn't in numeric format, try to convert it automatically.
        sender_sid = self._getSid(sender)
        sender_uid = self._getUid(sender)
        if sender_sid in self.irc.servers:
            # Sender is a server (converting from name to SID gave a valid result).
            sender = sender_sid
        elif sender_uid in self.irc.users:
            # Sender is a user (converting from name to UID gave a valid result).
            sender = sender_uid
        else:
            # No sender prefix; treat as coming from uplink IRCd.
            sender = self.irc.uplink
            args.insert(0, sender)

        command_token = args[1].upper()
        args = args[2:]

        log.debug('(%s) Found message sender as %s', self.irc.name, sender)

        try:
            # Convert the token given into a regular command, if present.
            command = self._getCommand(command_token)
            log.debug('(%s) Translating token %s to command %s', self.irc.name, command_token, command)

            func = getattr(self, 'handle_'+command.lower())

        except AttributeError:  # Unhandled command, ignore
            return

        else:  # Send a hook with the hook arguments given by the handler function.
            parsed_args = func(sender, command, args)
            if parsed_args is not None:
                return [sender, command, parsed_args]

    def handle_server(self, source, command, args):
        """Handles incoming server introductions."""
        # <- SERVER nefarious.midnight.vpn 1 1460673022 1460673239 J10 ABP]] +h6 :Nefarious2 test server
        servername = args[0].lower()
        sid = args[5][:2]
        sdesc = args[-1]
        self.irc.servers[sid] = IrcServer(source, servername, desc=sdesc)

        if self.irc.uplink is None:
            # If we haven't already found our uplink, this is probably it.
            self.irc.uplink = sid

        return {'name': servername, 'sid': sid, 'text': sdesc}

    def handle_nick(self, source, command, args):
        """Handles the NICK command, used for user introductions and nick changes."""
        if len(args) > 2:
            # <- AB N GL 1 1460673049 ~gl nefarious.midnight.vpn +iw B]AAAB ABAAA :realname

            nick = args[0]
            ts, ident, host = args[2:5]

            # XXX: Is realhost ever sent?
            realhost = host

            # Thanks to Jobe @ evilnet for the code on what to do here. :) -GL
            ip = args[-3]

            if '_' in ip:  # IPv6
                s = ''
                # P10-encoded IPv6 addresses are formed with chunks, where each 16-bit
                # portion of the address (each part between :'s) is encoded as 3 B64 chars.
                # A single :: is translated into an underscore (_).
                # https://github.com/evilnet/nefarious2/blob/master/doc/p10.txt#L723
                # Example: 1:2::3 -> AABAAC_AAD
                for b64chunk in re.findall('([A-Z]{3}|_)', ip):
                    if b64chunk == '_':
                        s += ':'
                    else:
                        ipchunk = base64.b64decode('A' + b64chunk, '[]')[1:]
                        for char in ipchunk:
                            s += str(char)
                        s += ':'

                ip = s.rstrip(':')

            else:  # IPv4
                # Pad the characters with two \x00's (represented in P10 B64 as AA)
                ip = 'AA' + ip
                # Decode it via Base64, dropping the initial padding characters.
                ip = base64.b64decode(ip, altchars='[]')[2:]
                # Convert the IP to a string.
                ip = socket.inet_ntoa(ip)

            uid = args[-2]
            realname = args[-1]

            log.debug('(%s) handle_nick got args: nick=%s ts=%s uid=%s ident=%s '
                      'host=%s realname=%s realhost=%s ip=%s', self.irc.name, nick, ts, uid,
                      ident, host, realname, realhost, ip)

            self.irc.users[uid] = IrcUser(nick, ts, uid, ident, host, realname, realhost, ip)
            self.irc.servers[source].users.add(uid)

            # https://github.com/evilnet/nefarious2/blob/master/doc/p10.txt#L708
            # Mode list is optional, and can be detected if the 6th argument starts with a +.
            # This list can last until the 3rd LAST argument in the line, should there be mode
            # parameters attached.
            if args[5].startswith('+'):
                modes = args[5:-3]
                parsedmodes = utils.parseModes(self.irc, uid, modes)
                utils.applyModes(self.irc, uid, parsedmodes)

            # Call the OPERED UP hook if +o is being added to the mode list.
            if ('+o', None) in parsedmodes:
                self.irc.callHooks([uid, 'CLIENT_OPERED', {'text': 'IRC Operator'}])

            # Set the accountname if present
            #if accountname != "*":
            #    self.irc.callHooks([uid, 'CLIENT_SERVICES_LOGIN', {'text': accountname}])

            return {'uid': uid, 'ts': ts, 'nick': nick, 'realhost': realhost, 'host': host, 'ident': ident, 'ip': ip}

        else:
            # <- ABAAA N GL_ 1460753763
            oldnick = self.irc.users[numeric].nick
            newnick = self.irc.users[numeric].nick = args[0]
            return {'newnick': newnick, 'oldnick': oldnick, 'ts': int(args[1])}

    def handle_ping(self, source, command, args):
        """Handles incoming PING requests."""
        # Snippet from Jobe @ evilnet, thanks! AFAIK, the P10 docs are out of date and don't
        # show the right PING/PONG syntax used by nefarious.
        # <- IA G !1460745823.89510 Channels.CollectiveIRC.Net 1460745823.89510
        # -> X3 Z Channels.CollectiveIRC.Net 1460745823.89510 0 1460745823.089840
        # Arguments of a PONG: our server hostname, the original TS of PING,
        #                      difference between PING and PONG in seconds, the current TS.
        # Why is this the way it is? I don't know... -GL

        target = args[1]
        sid = self._getSid(target)
        orig_pingtime = args[0][1:]  # Strip the !, used to denote a TS instead of a server name.

        currtime = time.time()
        timediff = int(time.time() - float(orig_pingtime))

        if self.irc.isInternalServer(sid):
            # Only respond if the target server is ours. No forwarding is needed because
            # no IRCds can ever connect behind us...
            self._send(self.irc.sid, 'Z %s %s %s %s' % (target, orig_pingtime, timediff, currtime))

    def handle_pong(self, source, command, args):
        """Handles incoming PONGs."""
        # <- AB Z AB :Ay
        if source == self.irc.uplink:
            self.irc.lastping = time.time()

    def handle_burst(self, source, command, args):
        """Handles the BURST command, used for bursting channels on link.

        This is equivalent to SJOIN on most IRCds."""
        # Oh no, we have to figure out which parameter is which...
        # <- AB B #test 1460742014 ABAAB,ABAAA:o
        # <- AB B #services 1460742014 ABAAA:o
        # <- AB B #test 1460742014 +tnlk 10 testkey ABAAB,ABAAA:o :%*!*@bad.host
        # <- AB B #test 1460742014 +tnl 10 ABAAB,ABAAA:o :%*!*@other.bad.host *!*@bad.host
        # <- AB B #test2 1460743539 +l 10 ABAAA:vo :%*!*@bad.host
        # <- AB B #test 1460747615 ABAAA:o :% ~ *!*@test.host
        # 1 <channel>
        # 2 <timestamp>
        # 3+ [<modes> [<mode extra parameters>]] [<users>] [<bans>]
        channel = utils.toLower(self.irc, args[0])
        userlist = args[-1].split()
        their_ts = int(args[1])
        our_ts = self.irc.channels[channel].ts

        self.updateTS(channel, their_ts)

        bans = []
        if args[-1].startswith('%'):
            # Ban lists start with a %. However, if one argument is "~",
            # Parse everything after it as an exempt (+e).
            exempts = False
            for host in args[-1][1:].split(' '):
                if not host:
                    # Space between % and ~ ignore.
                    continue
                elif host == '~':
                    exempts = True
                    continue

                if exempts:
                    bans.append(('+e', host))
                else:
                    bans.append(('+b', host))

            # Remove this argument from the args list.
            args = args[:-1]

        userlist = args[-1].split(',')

        # Then, we can make the modestring just encompass all the text until the end of the string.
        # If no modes are given, this will simply be empty.
        modestring = args[2:-1]
        if modestring:
            parsedmodes = utils.parseModes(self.irc, channel, modestring)
        else:
            parsedmodes = []

        # Add the ban list to the list of modes to process.
        parsedmodes.extend(bans)

        if parsedmodes:
            utils.applyModes(self.irc, channel, parsedmodes)

        namelist = []
        log.debug('(%s) handle_sjoin: got userlist %r for %r', self.irc.name, userlist, channel)
        for userpair in userlist:
            # This is given in the form UID1,UID2:prefixes
            try:
                user, prefixes = userpair.split(':')
            except ValueError:
                user = userpair
                prefixes = ''
            log.debug('(%s) handle_burst: got mode prefixes %r for user %r', self.irc.name, prefixes, user)

            # Don't crash when we get an invalid UID.
            if user not in self.irc.users:
                log.warning('(%s) handle_burst: tried to introduce user %s not in our user list, ignoring...',
                            self.irc.name, user)
                continue

            namelist.append(user)

            self.irc.users[user].channels.add(channel)

            if their_ts <= our_ts:
                utils.applyModes(self.irc, channel, [('+%s' % mode, user) for mode in prefixes])

            self.irc.channels[channel].users.add(user)
        return {'channel': channel, 'users': namelist, 'modes': parsedmodes, 'ts': their_ts}

    def handle_join(self, source, command, args):
        """Handles incoming JOINs and channel creations."""
        # <- ABAAA C #test3 1460744371
        # <- ABAAB J #test3 1460744371
        # <- ABAAB J #test3
        try:
            # TS is optional
            ts = int(args[1])
        except IndexError:
            ts = None

        if args[0] == '0' and command == 'JOIN':
            # /join 0; part the user from all channels
            oldchans = self.irc.users[numeric].channels.copy()
            log.debug('(%s) Got /join 0 from %r, channel list is %r',
                      self.irc.name, numeric, oldchans)
            for channel in oldchans:
                self.irc.channels[channel].users.discard(source)
                self.irc.users[source].channels.discard(channel)
            return {'channels': oldchans, 'text': 'Left all channels.', 'parse_as': 'PART'}
        else:
            channel = utils.toLower(self.irc, args[0])
            if ts:  # Only update TS if one was sent.
                self.updateTS(channel, ts)

        return {'channel': channel, 'users': [source], 'modes':
                self.irc.channels[channel].modes, 'ts': ts or int(time.time())}

    handle_create = handle_join

    def handle_privmsg(self, source, command, args):
        """Handles incoming PRIVMSG/NOTICE."""
        # <- ABAAA P AyAAA :privmsg text
        # <- ABAAA O AyAAA :notice text
        target = args[0]

        # We use lowercase channels internally, but uppercase UIDs.
        if utils.isChannel(target):
            target = utils.toLower(self.irc, target)
        return {'target': target, 'text': args[1]}

    handle_notice = handle_privmsg

    def handle_end_of_burst(self, source, command, args):
        """Handles end of burst from our uplink."""
        # Send EOB acknowledgement; this is required by the P10 specification,
        # and needed if we want to be able to receive channel messages, etc.
        self._send(self.irc.sid, 'EA')
        return {}

    def handle_mode(self, source, command, args):
        """Handles mode changes."""
        # <- ABAAA M GL -w
        # <- ABAAA M #test +v ABAAB 1460747615
        # <- ABAAA OM #test +h ABAAA
        target = args[0]
        if utils.isChannel(target):
            target = utils.toLower(self.irc, target)

        modestrings = args[1:]
        changedmodes = utils.parseModes(self.irc, target, modestrings)
        utils.applyModes(self.irc, target, changedmodes)

        # Call the CLIENT_OPERED hook if +o is being set.
        if ('+o', None) in changedmodes and target in self.irc.users:
            self.irc.callHooks([target, 'CLIENT_OPERED', {'text': 'IRC Operator'}])

        return {'target': target, 'modes': changedmodes}
    # OPMODE is like SAMODE on other IRCds, and it follows the same modesetting syntax.
    handle_opmode = handle_mode

    def handle_part(self, source, command, args):
        """Handles user parts."""
        # <- ABAAA L #test,#test2
        # <- ABAAA L #test :test

        channels = utils.toLower(self.irc, args[0]).split(',')
        for channel in channels:
            # We should only get PART commands for channels that exist, right??
            self.irc.channels[channel].removeuser(source)

            try:
                self.irc.users[source].channels.discard(channel)
            except KeyError:
                log.debug("(%s) handle_part: KeyError trying to remove %r from %r's channel list?",
                          self.irc.name, channel, source)
            try:
                reason = args[1]
            except IndexError:
                reason = ''

            # Clear empty non-permanent channels.
            if not self.irc.channels[channel].users:
                del self.irc.channels[channel]

        return {'channels': channels, 'text': reason}

    def handle_kick(self, source, command, args):
        """Handles incoming KICKs."""
        # <- ABAAA K #TEST AyAAA :PyLink-devel
        channel = utils.toLower(self.irc, args[0])
        kicked = args[1]

        self.handle_part(kicked, 'KICK', [channel, args[2]])
        return {'channel': channel, 'target': kicked, 'text': args[2]}

    def handle_quit(self, numeric, command, args):
        """Handles incoming QUITs."""
        # <- ABAAB Q :Killed (GL_ (bangbang))
        self.removeClient(numeric)
        return {'text': args[0]}

    def handle_kill(self, numeric, command, args):
        """Handles incoming KILLs."""
        # <- ABAAA D AyAAA :nefarious.midnight.vpn!GL (test)
        killed = args[0]
        if killed in self.irc.users:
            self.removeClient(killed)
        return {'target': killed, 'text': args[1], 'userdata': self.irc.users.get(killed)}

    def handle_squit(self, numeric, command, args):
        """Handles incoming SQUITs."""
        # <- ABAAE SQ nefarious.midnight.vpn 0 :test

        split_server = self._getSid(args[0])

        affected_users = []
        log.debug('(%s) Splitting server %s (reason: %s)', self.irc.name, split_server, args[-1])

        if split_server not in self.irc.servers:
            log.warning("(%s) Tried to split a server (%s) that didn't exist!", self.irc.name, split_server)
            return

        # Prevent RuntimeError: dictionary changed size during iteration
        old_servers = self.irc.servers.copy()
        # Cycle through our list of servers. If any server's uplink is the one that is being SQUIT,
        # remove them and all their users too.
        for sid, data in old_servers.items():
            if data.uplink == split_server:
                log.debug('Server %s also hosts server %s, removing those users too...', split_server, sid)
                # Recursively run SQUIT on any other hubs this server may have been connected to.
                args = self.handle_squit(sid, 'SQUIT', [sid, "0",
                                         "PyLink: Automatically splitting leaf servers of %s" % sid])
                affected_users += args['users']

        for user in self.irc.servers[split_server].users.copy():
            affected_users.append(user)
            log.debug('Removing client %s (%s)', user, self.irc.users[user].nick)
            self.removeClient(user)

        sname = self.irc.servers[split_server].name
        del self.irc.servers[split_server]
        log.debug('(%s) Netsplit affected users: %s', self.irc.name, affected_users)

        return {'target': split_server, 'users': affected_users, 'name': sname}

Class = P10Protocol
