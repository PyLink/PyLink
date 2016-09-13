"""
nefarious.py: Nefarious IRCu protocol module for PyLink.
"""

import base64
import struct
from ipaddress import ip_address
import time

from pylinkirc import utils, structures
from pylinkirc.classes import *
from pylinkirc.log import log
from pylinkirc.protocols.ircs2s_common import *

class P10UIDGenerator(utils.IncrementalUIDGenerator):
     """Implements an incremental P10 UID Generator."""

     def __init__(self, sid):
         self.allowedchars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789[]'
         self.length = 3
         super().__init__(sid)

def p10b64encode(num, length=2):
    """
    Encodes a given numeric using P10 Base64 numeric nicks, as documented at
    https://github.com/evilnet/nefarious2/blob/a29b63144/doc/p10.txt#L69-L92
    """
    # Pack the given number as an unsigned int.
    sidbytes = struct.pack('>I', num)[1:]
    sid = base64.b64encode(sidbytes, b'[]')[-2:]
    return sid.decode()  # Return a string, not bytes.

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

class P10Protocol(IRCS2SProtocol):

    def __init__(self, irc):
        super().__init__(irc)

        # Dictionary of UID generators (one for each server).
        self.uidgen = structures.KeyedDefaultdict(P10UIDGenerator)

        # SID generator for P10.
        self.sidgen = P10SIDGenerator(irc)

        self.hook_map = {'END_OF_BURST': 'ENDBURST', 'OPMODE': 'MODE', 'CLEARMODE': 'MODE', 'BURST': 'JOIN'}

    def _send(self, source, text):
        self.irc.send("%s %s" % (source, text))

    @staticmethod
    def access_sort(key):
        """
        Sorts (prefixmode, UID) keys based on the prefix modes given.
        """
        prefixes, user = key
        # Add the prefixes given for each userpair, giving each one a set value. This ensures
        # that 'ohv' > 'oh' > 'ov' > 'o' > 'hv' > 'h' > 'v' > ''
        accesses = {'o': 100, 'h': 10, 'v': 1}

        num = 0
        for prefix in prefixes:
            num += accesses.get(prefix, 0)

        return num

    @staticmethod
    def decode_p10_ip(ip):
        """Decodes a P10 IP."""
        # Many thanks to Jobe @ evilnet for the code on what to do here. :) -GL

        if len(ip) == 6:  # IPv4
            # Pad the characters with two \x00's (represented in P10 B64 as AA)
            ip = 'AA' + ip

            # Decode it via Base64, dropping the initial padding characters.
            ip = base64.b64decode(ip, altchars='[]')[2:]

            # Convert the IP to a string.
            return socket.inet_ntoa(ip)

        elif len(ip) <= 24 or '_' in ip:  # IPv6
            s = ''
            # P10-encoded IPv6 addresses are formed with chunks, where each 16-bit
            # portion of the address (each part between :'s) is encoded as 3 B64 chars.
            # A single :: is translated into an underscore (_).
            # https://github.com/evilnet/nefarious2/blob/master/doc/p10.txt#L723
            # Example: 1:2::3 -> AABAAC_AAD

            # Treat the part before and after the _ as two separate pieces (head and tail).
            head = ip
            tail = ''
            byteshead = b''
            bytestail = b''

            if '_' in ip:
                head, tail = ip.split('_')

            # Each B64-encoded section is 3 characters long. Split them up and
            # iterate.
            for section in range(0, len(head), 3):
                byteshead += base64.b64decode('A' + head[section:section+3], '[]')[1:]
            for section in range(0, len(tail), 3):
                bytestail += base64.b64decode('A' + tail[section:section+3], '[]')[1:]

            ipbytes = byteshead

            # Figure out how many 0's the center _ actually represents.
            # Subtract 16 (the amount of chunks in a v6 address) by
            # the length of the head and tail sections.
            pad = 16 - len(byteshead) - len(bytestail)
            ipbytes += (b'\x00' * pad)  # Pad with zeros.
            ipbytes += bytestail

            ip = socket.inet_ntop(socket.AF_INET6, ipbytes)
            if ip.startswith(':'):
                # HACK: prevent ::1 from being treated as end-of-line
                # when sending to other IRCds.
                ip = '0' + ip
            return ip

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
            'SH': 'SETHOST',
            'FA': 'FAKE'
        }
        # If the token isn't in the list, return it raw.
        return tokens.get(token, token)

    ### COMMANDS

    def spawnClient(self, nick, ident='null', host='null', realhost=None, modes=set(),
            server=None, ip='0.0.0.0', realname=None, ts=None, opertype='IRC Operator',
            manipulatable=False):
        """
        Spawns a new client with the given options.

        Note: No nick collision / valid nickname checks are done here; it is
        up to plugins to make sure they don't introduce anything invalid.
        """
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
        uid = self.uidgen.setdefault(server, P10UIDGenerator(server)).next_uid()

        # Fill in all the values we need
        ts = ts or int(time.time())
        realname = realname or self.irc.botdata['realname']
        realhost = realhost or host
        raw_modes = self.irc.joinModes(modes)

        # Initialize an IrcUser instance
        u = self.irc.users[uid] = IrcUser(nick, ts, uid, ident=ident, host=host, realname=realname,
                                          realhost=realhost, ip=ip, manipulatable=manipulatable,
                                          opertype=opertype)

        # Fill in modes and add it to our users index
        self.irc.applyModes(uid, modes)
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

    def away(self, source, text):
        """Sends an AWAY message from a PyLink client. <text> can be an empty string
        to unset AWAY status."""
        if not self.irc.isInternalClient(source):
            raise LookupError('No such PyLink client exists.')

        if text:
            self._send(source, 'A :%s' % text)
        else:
            self._send(source, 'A')
        self.irc.users[source].away = text

    def invite(self, numeric, target, channel):
        """Sends INVITEs from a PyLink client."""
        # Note: we have to send a nick as the target, not a UID.
        # <- ABAAA I PyLink-devel #services 1460948992

        if not self.irc.isInternalClient(numeric):
            raise LookupError('No such PyLink client exists.')

        nick = self.irc.users[target].nick

        self._send(numeric, 'I %s %s %s' % (nick, channel, self.irc.channels[channel].ts))

    def join(self, client, channel):
        """Joins a PyLink client to a channel."""
        # <- ABAAB J #test3 1460744371
        channel = self.irc.toLower(channel)
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

        channel = self.irc.toLower(channel)
        if not reason:
            reason = 'No reason given'

        cobj = self.irc.channels[channel]
        # HACK: prevent kick bounces by sending our kick through the server if
        # the sender isn't op.
        if numeric not in self.irc.servers and (not cobj.isOp(numeric)) and (not cobj.isHalfop(numeric)):
            reason = '(%s) %s' % (self.irc.getFriendlyName(numeric), reason)
            numeric = self.irc.getServer(numeric)

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

    def knock(self, numeric, target, text):
        raise NotImplementedError('KNOCK is not supported on P10.')

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

        modes = list(modes)

        # According to the P10 specification:
        # https://github.com/evilnet/nefarious2/blob/master/doc/p10.txt#L29
        # One line can have a max of 15 parameters. Excluding the target and the first part of the
        # modestring, this means we can send a max of 13 modes with arguments per line.
        if utils.isChannel(target):
            # Channel mode changes have a trailing TS. User mode changes do not.
            cobj = self.irc.channels[self.irc.toLower(target)]
            ts = ts or cobj.ts
            send_ts = True

            # HACK: prevent mode bounces by sending our mode through the server if
            # the sender isn't op.
            if numeric not in self.irc.servers and (not cobj.isOp(numeric)) and (not cobj.isHalfop(numeric)):
                numeric = self.irc.getServer(numeric)

            real_target = target
        else:
            assert target in self.irc.users, "Unknown mode target %s" % target
            # P10 uses nicks in user MODE targets, NOT UIDs. ~GL
            real_target = self.irc.users[target].nick
            send_ts = False

        self.irc.applyModes(target, modes)

        while modes[:12]:
            joinedmodes = self.irc.joinModes([m for m in modes[:12]])
            modes = modes[12:]
            self._send(numeric, 'M %s %s%s' % (real_target, joinedmodes, ' %s' % ts if send_ts else ''))

    def nick(self, numeric, newnick):
        """Changes the nick of a PyLink client."""
        # <- ABAAA N GL_ 1460753763
        if not self.irc.isInternalClient(numeric):
            raise LookupError('No such PyLink client exists.')

        self._send(numeric, 'N %s %s' % (newnick, int(time.time())))
        self.irc.users[numeric].nick = newnick

        # Update the NICK TS.
        self.irc.users[numeric].ts = int(time.time())

    def numeric(self, source, numeric, target, text):
        """Sends raw numerics from a server to a remote client. This is used for WHOIS
        replies."""
        # <- AB 311 AyAAA GL ~gl nefarious.midnight.vpn * :realname
        self._send(source, '%s %s %s' % (numeric, target, text))

    def notice(self, numeric, target, text):
        """Sends a NOTICE from a PyLink client."""
        if not self.irc.isInternalClient(numeric):
            raise LookupError('No such PyLink client exists.')

        self._send(numeric, 'O %s :%s' % (target, text))

    def part(self, client, channel, reason=None):
        """Sends a part from a PyLink client."""
        channel = self.irc.toLower(channel)

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

    def sjoin(self, server, channel, users, ts=None, modes=set()):
        """Sends an SJOIN for a group of users to a channel.

        The sender should always be a Server ID (SID). TS is optional, and defaults
        to the one we've stored in the channel state if not given.
        <users> is a list of (prefix mode, UID) pairs:

        Example uses:
            sjoin('100', '#test', [('', '100AAABBC'), ('o', 100AAABBB'), ('v', '100AAADDD')])
            sjoin(self.irc.sid, '#test', [('o', self.irc.pseudoclient.uid)])
        """
        # <- AB B #test 1460742014 +tnl 10 ABAAB,ABAAA:o :%*!*@other.bad.host ~ *!*@bad.host
        channel = self.irc.toLower(channel)
        server = server or self.irc.sid

        assert users, "sjoin: No users sent?"
        log.debug('(%s) sjoin: got %r for users', self.irc.name, users)
        if not server:
            raise LookupError('No such PyLink client exists.')

        # Only send non-list modes in the modes argument BURST. Bans and exempts are formatted differently:
        # <- AB B #test 1460742014 +tnl 10 ABAAB,ABAAA:o :%*!*@other.bad.host *!*@bad.host
        # <- AB B #test2 1460743539 +l 10 ABAAA:vo :%*!*@bad.host
        # <- AB B #test 1460747615 ABAAA:o :% ~ *!*@test.host
        modes = modes or self.irc.channels[channel].modes
        orig_ts = self.irc.channels[channel].ts
        ts = ts or orig_ts

        bans = []
        exempts = []
        regularmodes = []
        for mode in modes:
            modechar = mode[0][-1]
            # Store bans and exempts in separate lists for processing, but don't reset bans that have already been set.
            if modechar in self.irc.cmodes['*A']:
                if (modechar, mode[1]) not in self.irc.channels[channel].modes:
                    if modechar == 'b':
                        bans.append(mode[1])
                    elif modechar == 'e':
                        exempts.append(mode[1])
            else:
                regularmodes.append(mode)

        log.debug('(%s) sjoin: bans: %s, exempts: %s, other modes: %s', self.irc.name, bans, exempts, regularmodes)

        changedmodes = set(modes)
        changedusers = []
        namelist = []

        # This is annoying because we have to sort our users by access before sending...
        # Joins should look like: A0AAB,A0AAC,ABAAA:v,ABAAB:o,ABAAD,ACAAA:ov
        users = sorted(users, key=self.access_sort)

        last_prefixes = ''
        for userpair in users:
            # We take <users> as a list of (prefixmodes, uid) pairs.
            assert len(userpair) == 2, "Incorrect format of userpair: %r" % userpair
            prefixes, user = userpair

            # Keep track of all the users and modes that are added. namelist is used
            # to track what we actually send to the IRCd.
            changedusers.append(user)
            log.debug('(%s) sjoin: adding %s:%s to namelist', self.irc.name, user, prefixes)

            if prefixes and prefixes != last_prefixes:
                namelist.append('%s:%s' % (user, prefixes))
            else:
                namelist.append(user)

            last_prefixes = prefixes
            if prefixes:
                for prefix in prefixes:
                    changedmodes.add(('+%s' % prefix, user))

            self.irc.users[user].channels.add(channel)

        namelist = ','.join(namelist)
        log.debug('(%s) sjoin: got %r for namelist', self.irc.name, namelist)

        # Format bans as the last argument if there are any.
        banstring = ''
        if bans or exempts:
            banstring += ' :%'  # Ban string starts with a % if there is anything
            if bans:
                banstring += ' '.join(bans)  # Join all bans, separated by a space
            if exempts:
                # Exempts are separated from the ban list by a single argument "~".
                banstring += ' ~ '
                banstring += ' '.join(exempts)

        if modes:  # Only send modes if there are any.
            self._send(server, "B {channel} {ts} {modes} {users}{banstring}".format(
                       ts=ts, users=namelist, channel=channel,
                       modes=self.irc.joinModes(regularmodes), banstring=banstring))
        else:
            self._send(server, "B {channel} {ts} {users}{banstring}".format(
                       ts=ts, users=namelist, channel=channel, banstring=banstring))

        self.irc.channels[channel].users.update(changedusers)

        self.updateTS(server, channel, ts, changedmodes)

    def spawnServer(self, name, sid=None, uplink=None, desc=None, endburst_delay=0):
        """
        Spawns a server off a PyLink server. desc (server description)
        defaults to the one in the config. uplink defaults to the main PyLink
        server, and sid (the server ID) is automatically generated if not
        given.

        Note: TS6 doesn't use a specific ENDBURST command, so the endburst_delay
        option will be ignored if given.
        """
        # <- SERVER nefarious.midnight.vpn 1 1460673022 1460673239 J10 ABP]] +h6 :Nefarious2 test server
        uplink = uplink or self.irc.sid
        name = name.lower()
        desc = desc or self.irc.serverdata.get('serverdesc') or self.irc.botdata['serverdesc']

        if sid is None:  # No sid given; generate one!
            sid = self.sidgen.next_sid()

        assert len(sid) == 2, "Incorrect SID length"
        if sid in self.irc.servers:
            raise ValueError('A server with SID %r already exists!' % sid)

        for server in self.irc.servers.values():
            if name == server.name:
                raise ValueError('A server named %r already exists!' % name)

        if not self.irc.isInternalServer(uplink):
            raise ValueError('Server %r is not a PyLink server!' % uplink)
        if not utils.isServerName(name):
            raise ValueError('Invalid server name %r' % name)

        self._send(uplink, 'SERVER %s 1 %s %s P10 %s]]] +h6 :%s' % \
                   (name, self.irc.start_ts, int(time.time()), sid, desc))

        self.irc.servers[sid] = IrcServer(uplink, name, internal=True, desc=desc)
        return sid

    def squit(self, source, target, text='No reason given'):
        """SQUITs a PyLink server."""
        # <- ABAAE SQ nefarious.midnight.vpn 0 :test

        targetname = self.irc.servers[target].name

        self._send(source, 'SQ %s 0 :%s' % (targetname, text))
        self.handle_squit(source, 'SQUIT', [target, text])

    def topic(self, numeric, target, text):
        """Sends a TOPIC change from a PyLink client."""
        # <- ABAAA T #test GL!~gl@nefarious.midnight.vpn 1460852591 1460855795 :blah
        # First timestamp is channel creation time, second is current time,

        if not self.irc.isInternalClient(numeric):
            raise LookupError('No such PyLink client exists.')

        sendername = self.irc.getHostmask(numeric)

        creationts = self.irc.channels[target].ts

        self._send(numeric, 'T %s %s %s %s :%s' % (target, sendername, creationts,
                   int(time.time()), text))
        self.irc.channels[target].topic = text
        self.irc.channels[target].topicset = True

    def topicBurst(self, numeric, target, text):
        """Sends a TOPIC change from a PyLink server."""
        # <- AB T #test GL!~gl@nefarious.midnight.vpn 1460852591 1460855795 :blah

        if not self.irc.isInternalServer(numeric):
            raise LookupError('No such PyLink server exists.')

        sendername = self.irc.servers[numeric].name

        creationts = self.irc.channels[target].ts

        self._send(numeric, 'T %s %s %s %s :%s' % (target, sendername, creationts,
                   int(time.time()), text))
        self.irc.channels[target].topic = text
        self.irc.channels[target].topicset = True

    def updateClient(self, target, field, text):
        """Updates the ident or host of any connected client."""
        uobj = self.irc.users[target]

        if self.irc.isInternalClient(target):
            # Use SETHOST (umode +h) for internal clients.
            if field == 'HOST':
                # Set umode +x, and +h with the given vHost as argument.
                # Note: setter of the mode should be the target itself.
                self.mode(target, target, [('+x', None), ('+h', '%s@%s' % (uobj.ident, text))])
            elif field == 'IDENT':
                # HACK: because we can't seem to update the ident only without updating the host,
                # unset +h first before setting the new ident@host.
                self.mode(target, target, [('-h', None)])
                self.mode(target, target, [('+x', None), ('+h', '%s@%s' % (text, uobj.host))])
            else:
                raise NotImplementedError
        elif field == 'HOST':
            # Use FAKE (FA) for external clients.
            self._send(self.irc.sid, 'FA %s %s' % (target, text))

            # Save the host change as a user mode (this is what P10 does on bursts),
            # so further host checks work.
            self.irc.applyModes(target, [('+f', text)])
        else:
            raise NotImplementedError

        # P10 cloaks aren't as simple as just replacing the displayed host with the one we're
        # sending. Check for cloak changes properly.
        # Note: we don't need to send any hooks here, checkCloakChange does that for us.
        self.checkCloakChange(target)

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

        # Encode our SID using P10 Base64.
        self.irc.sid = sid = p10b64encode(self.irc.serverdata["sid"])

        desc = self.irc.serverdata.get('serverdesc') or self.irc.botdata['serverdesc']

        # Enumerate modes, from https://github.com/evilnet/nefarious2/blob/master/doc/modes.txt
        cmodes = {'op': 'o', 'voice': 'v', 'private': 'p', 'secret': 's', 'moderated': 'm',
                  'topiclock': 't', 'inviteonly': 'i', 'noextmsg': 'n', 'regonly': 'r',
                  'delayjoin': 'D', 'registered': 'R', 'key': 'k', 'ban': 'b', 'banexception': 'e',
                  'limit': 'l', 'redirect': 'L', 'oplevel_apass': 'A', 'oplevel_upass': 'U',
                  'adminonly': 'a', 'operonly': 'O', 'regmoderated': 'M', 'nonotice': 'N',
                  'permanent': 'z', 'hidequits': 'Q', 'noctcp': 'C', 'noamsg': 'T', 'blockcolor': 'c',
                  'stripcolor': 'S', 'had_delayjoins': 'd',
                  '*A': 'be', '*B': 'k', '*C': 'Ll', '*D': 'psmtinrDRAUaOMNzQCTcSd'}

        if self.irc.serverdata.get('use_halfop'):
            cmodes['halfop'] = 'h'
            self.irc.prefixmodes['h'] = '%'

        self.irc.cmodes = cmodes

        self.irc.umodes = {'oper': 'o', 'locop': 'O', 'invisible': 'i', 'wallops': 'w',
                           'snomask': 's', 'servprotect': 'k', 'sno_debug': 'g', 'cloak': 'x',
                           'hidechans': 'n', 'deaf_commonchan': 'q', 'bot': 'B', 'deaf': 'D',
                           'hideoper': 'H', 'hideidle': 'I', 'regdeaf': 'R', 'showwhois': 'W',
                           'admin': 'a', 'override': 'X', 'noforward': 'L', 'ssl': 'z',
                           'registered': 'r', 'cloak_sethost': 'h', 'cloak_fakehost': 'f',
                           'cloak_hashedhost': 'C', 'cloak_hashedip': 'c',
                           '*A': '', '*B': '', '*C': 'fCcrh', '*D': 'oOiwskgxnqBDHIRWaXLz'}

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
            realhost = host
            ip = args[-3]
            ip = self.decode_p10_ip(ip)
            uid = args[-2]
            realname = args[-1]

            log.debug('(%s) handle_nick got args: nick=%s ts=%s uid=%s ident=%s '
                      'host=%s realname=%s realhost=%s ip=%s', self.irc.name, nick, ts, uid,
                      ident, host, realname, realhost, ip)

            uobj = self.irc.users[uid] = IrcUser(nick, ts, uid, ident, host, realname, realhost, ip)
            self.irc.servers[source].users.add(uid)

            # https://github.com/evilnet/nefarious2/blob/master/doc/p10.txt#L708
            # Mode list is optional, and can be detected if the 6th argument starts with a +.
            # This list can last until the 3rd LAST argument in the line, should there be mode
            # parameters attached.
            if args[5].startswith('+'):
                modes = args[5:-3]
                parsedmodes = self.irc.parseModes(uid, modes)
                self.irc.applyModes(uid, parsedmodes)

                for modepair in parsedmodes:
                    if modepair[0][-1] == 'r':
                        # Parse account registrations, sent as usermode "+r accountname:TS"
                        accountname = modepair[1].split(':', 1)[0]
                        self.irc.callHooks([uid, 'CLIENT_SERVICES_LOGIN', {'text': accountname}])

                # Call the OPERED UP hook if +o is being added to the mode list.
                if ('+o', None) in parsedmodes:
                    self.irc.callHooks([uid, 'CLIENT_OPERED', {'text': 'IRC Operator'}])

            self.checkCloakChange(uid)

            return {'uid': uid, 'ts': ts, 'nick': nick, 'realhost': realhost, 'host': host, 'ident': ident, 'ip': ip}

        else:
            # <- ABAAA N GL_ 1460753763
            oldnick = self.irc.users[source].nick
            newnick = self.irc.users[source].nick = args[0]

            self.irc.users[source].ts = ts = int(args[1])

            # Update the nick TS.
            return {'newnick': newnick, 'oldnick': oldnick, 'ts': ts}

    def checkCloakChange(self, uid):
        """Checks for cloak changes (ident and host) on the given UID."""
        uobj = self.irc.users[uid]
        ident = uobj.ident

        modes = dict(uobj.modes)
        log.debug('(%s) checkCloakChange: modes of %s are %s', self.irc.name, uid, modes)

        if 'x' not in modes:  # +x isn't set, so cloaking is disabled.
            newhost = uobj.realhost
        else:
            if 'h' in modes:
                # +h is used by SETHOST/spoofhost blocks, or by /sethost when freeform is enabled.
                # It takes the form umode +h ident@some.host, though only the host is
                # actually settable in /sethost.
                ident, newhost = modes['h'].split('@')
            elif 'f' in modes:
                # +f represents another way of setting vHosts, via a command called FAKE.
                # Atheme uses this for vHosts, afaik.
                newhost = modes['f']
            elif uobj.services_account and self.irc.serverdata.get('use_account_cloaks'):
                # The user is registered. However, if account cloaks are enabled, we have to figure
                # out their new cloaked host. There can be oper cloaks and user cloaks, each with
                # a different suffix. Account cloaks take the format of <accountname>.<suffix>.
                # e.g. someone logged in as "person1" might get cloak "person1.users.somenet.org"
                #      someone opered and logged in as "person2" might get cloak "person.opers.somenet.org"
                # This is a lot of extra configuration on the services' side, but there's nothing else
                # we can do about it.
                if self.irc.serverdata.get('use_oper_account_cloaks') and 'o' in modes:
                    try:
                        # These errors should be fatal.
                        suffix = self.irc.serverdata['oper_cloak_suffix']
                    except KeyError:
                        raise ProtocolError("(%s) use_oper_account_cloaks was enabled, but "
                                            "oper_cloak_suffix was not defined!" % self.irc.name)
                else:
                    try:
                        suffix = self.irc.serverdata['cloak_suffix']
                    except KeyError:
                        raise ProtocolError("(%s) use_account_cloaks was enabled, but "
                                            "cloak_suffix was not defined!" % self.irc.name)

                accountname = uobj.services_account
                newhost = "%s.%s" % (accountname, suffix)

            elif 'C' in modes and self.irc.serverdata.get('use_account_cloaks'):
                # +C propagates hashed IP cloaks, similar to UnrealIRCd. (thank god we don't
                # need to generate these ourselves)
                newhost = modes['C']
            else:
                # No cloaking mechanism matched, fall back to the real host.
                newhost = uobj.realhost

        # Propagate a hostname update to plugins, but only if the changed host is different.
        if newhost != uobj.host:
             self.irc.callHooks([uid, 'CHGHOST', {'target': uid, 'newhost': newhost}])
        if ident != uobj.ident:
             self.irc.callHooks([uid, 'CHGIDENT', {'target': uid, 'newident': ident}])
        uobj.host = newhost
        uobj.ident = ident

        return newhost

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

    def handle_pass(self, source, command, args):
        """Handles authentication with our uplink."""
        # <- PASS :testpass
        if args[0] != self.irc.serverdata['recvpass']:
            raise ProtocolError("Error: RECVPASS from uplink does not match configuration!")

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

        if len(args) < 3:
            # No useful data was sent, ignore.
            return

        channel = self.irc.toLower(args[0])
        chandata = self.irc.channels[channel].deepcopy()

        userlist = args[-1].split()

        bans = []
        if args[-1].startswith('%'):
            # Ban lists start with a %. However, if one argument is "~",
            # parse everything after it as an ban exempt (+e).
            exempts = False
            for host in args[-1][1:].split(' '):
                if not host:
                    # Space between % and ~; ignore.
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

        # Then, we can make the modestring just encompass all the text until the end of the string.
        # If no modes are given, this will simply be empty.
        modestring = args[2:-1]
        if modestring:
            parsedmodes = self.irc.parseModes(channel, modestring)
        else:
            parsedmodes = []

        # This list is used to keep track of prefix modes being added to the mode list.
        changedmodes = set(parsedmodes)

        # Also add the the ban list to the list of modes to process internally.
        parsedmodes.extend(bans)
        if parsedmodes:
            self.irc.applyModes(channel, parsedmodes)

        namelist = []
        log.debug('(%s) handle_sjoin: got userlist %r for %r', self.irc.name, userlist, channel)

        prefixes = ''

        userlist = args[-1].split(',')
        if args[-1] != args[1]:  # Make sure the user list is the right argument (not the TS).
            for userpair in userlist:
                # This is given in the form UID1,UID2:prefixes. However, when one userpair is given
                # with a certain prefix, it implicitly applies to all other following UIDs, until
                # another userpair is given with a list of prefix modes. For example,
                # "UID1,UID3:o,UID4,UID5" would assume that UID1 has no prefixes, but that UIDs 3-5
                # all have op.
                try:
                    user, prefixes = userpair.split(':')
                except ValueError:
                    user = userpair
                log.debug('(%s) handle_burst: got mode prefixes %r for user %r', self.irc.name, prefixes, user)

                # Don't crash when we get an invalid UID.
                if user not in self.irc.users:
                    log.warning('(%s) handle_burst: tried to introduce user %s not in our user list, ignoring...',
                                self.irc.name, user)
                    continue

                namelist.append(user)

                self.irc.users[user].channels.add(channel)

                # Only save mode changes if the remote has lower TS than us.
                changedmodes |= {('+%s' % mode, user) for mode in prefixes}

                self.irc.channels[channel].users.add(user)

        # Statekeeping with timestamps
        their_ts = int(args[1])
        our_ts = self.irc.channels[channel].ts
        self.updateTS(source, channel, their_ts, changedmodes)

        return {'channel': channel, 'users': namelist, 'modes': parsedmodes, 'ts': their_ts,
                'channeldata': chandata}

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
            oldchans = self.irc.users[source].channels.copy()
            log.debug('(%s) Got /join 0 from %r, channel list is %r',
                      self.irc.name, source, oldchans)

            for channel in oldchans:
                self.irc.channels[channel].users.discard(source)
                self.irc.users[source].channels.discard(channel)

            return {'channels': oldchans, 'text': 'Left all channels.', 'parse_as': 'PART'}
        else:
            channel = self.irc.toLower(args[0])
            if ts:  # Only update TS if one was sent.
                self.updateTS(source, channel, ts)

            self.irc.users[source].channels.add(channel)
            self.irc.channels[channel].users.add(source)

        return {'channel': channel, 'users': [source], 'modes':
                self.irc.channels[channel].modes, 'ts': ts or int(time.time())}

    handle_create = handle_join

    def handle_privmsg(self, source, command, args):
        """Handles incoming PRIVMSG/NOTICE."""
        # <- ABAAA P AyAAA :privmsg text
        # <- ABAAA O AyAAA :notice text
        target = args[0]

        # We use lower case channels internally, but mixed case UIDs.
        stripped_target = target.lstrip(''.join(self.irc.prefixmodes.values()))
        if utils.isChannel(stripped_target):
            target = self.irc.toLower(target)

        return {'target': target, 'text': args[1]}

    handle_notice = handle_privmsg

    def handle_end_of_burst(self, source, command, args):
        """Handles end of burst from our uplink."""
        # Send EOB acknowledgement; this is required by the P10 specification,
        # and needed if we want to be able to receive channel messages, etc.
        if source == self.irc.uplink:
            self._send(self.irc.sid, 'EA')
            return {}

    def handle_mode(self, source, command, args):
        """Handles mode changes."""
        # <- ABAAA M GL -w
        # <- ABAAA M #test +v ABAAB 1460747615
        # <- ABAAA OM #test +h ABAAA
        target = self._getUid(args[0])
        if utils.isChannel(target):
            target = self.irc.toLower(target)

        modestrings = args[1:]
        changedmodes = self.irc.parseModes(target, modestrings)
        self.irc.applyModes(target, changedmodes)

        # Call the CLIENT_OPERED hook if +o is being set.
        if ('+o', None) in changedmodes and target in self.irc.users:
            self.irc.callHooks([target, 'CLIENT_OPERED', {'text': 'IRC Operator'}])

        if target in self.irc.users:
            # Target was a user. Check for any cloak changes.
            self.checkCloakChange(target)

        return {'target': target, 'modes': changedmodes}
    # OPMODE is like SAMODE on other IRCds, and it follows the same modesetting syntax.
    handle_opmode = handle_mode

    def handle_part(self, source, command, args):
        """Handles user parts."""
        # <- ABAAA L #test,#test2
        # <- ABAAA L #test :test

        channels = self.irc.toLower(args[0]).split(',')
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
        channel = self.irc.toLower(args[0])
        kicked = args[1]

        self.handle_part(kicked, 'KICK', [channel, args[2]])
        return {'channel': channel, 'target': kicked, 'text': args[2]}

    def handle_topic(self, source, command, args):
        """Handles TOPIC changes."""
        # <- ABAAA T #test GL!~gl@nefarious.midnight.vpn 1460852591 1460855795 :blah
        channel = self.irc.toLower(args[0])
        topic = args[-1]

        oldtopic = self.irc.channels[channel].topic
        self.irc.channels[channel].topic = topic
        self.irc.channels[channel].topicset = True

        return {'channel': channel, 'setter': args[1], 'text': topic,
                'oldtopic': oldtopic}

    def handle_invite(self, source, command, args):
        """Handles incoming INVITEs."""
        # From P10 docs:
        # 1 <target nick>
        # 2 <channel>
        # - note that the target is a nickname, not a numeric.
        # <- ABAAA I PyLink-devel #services 1460948992
        target = self._getUid(args[0])
        channel = self.irc.toLower(args[1])

        return {'target': target, 'channel': channel}

    def handle_clearmode(self, numeric, command, args):
        """Handles CLEARMODE, which is used to clear a channel's modes."""
        # <- ABAAA CM #test ovpsmikbl
        channel = self.irc.toLower(args[0])
        modes = args[1]

        # Enumerate a list of our existing modes, including prefix modes.
        existing = list(self.irc.channels[channel].modes)
        for pmode, userlist in self.irc.channels[channel].prefixmodes.items():
            # Expand the prefix modes lists to individual ('o', 'UID') mode pairs.
            modechar = self.irc.cmodes.get(pmode)
            existing += [(modechar, user) for user in userlist]

        # Back up the channel state.
        oldobj = self.irc.channels[channel].deepcopy()

        changedmodes = []

        # Iterate over all the modes we have for this channel.
        for modepair in existing:
            modechar, data = modepair

            # Check if each mode matches any that we're unsetting.
            if modechar in modes:
                if modechar in (self.irc.cmodes['*A']+self.irc.cmodes['*B']+''.join(self.irc.prefixmodes.keys())):
                    # Mode is a list mode, prefix mode, or one that always takes a parameter when unsetting.
                    changedmodes.append(('-%s' % modechar, data))
                else:
                    # Mode does not take an argument when unsetting.
                    changedmodes.append(('-%s' % modechar, None))

        self.irc.applyModes(channel, changedmodes)
        return {'target': channel, 'modes': changedmodes, 'channeldata': oldobj}

    def handle_account(self, numeric, command, args):
        """Handles services account changes."""
        # ACCOUNT has two possible syntaxes in P10, one with extended accounts
        # and one without.

        target = args[0]

        if self.irc.serverdata.get('use_extended_accounts'):
            # Registration: <- AA AC ABAAA R GL 1459019072
            # Logout: <- AA AC ABAAA U

            # 1 <target user numeric>
            # 2 <subcommand>
            # 3+ [<subcommand parameters>]

            # Any other subcommands listed at https://github.com/evilnet/nefarious2/blob/master/doc/p10.txt#L354
            # shouldn't apply to us.

            if args[1] in ('R', 'M'):
                accountname = args[2]
            elif args[1] == 'U':
                accountname = ''  # logout

        else:
            # ircu or nefarious with F:EXTENDED_ACCOUNTS = FALSE
            # 1 <target user numeric>
            # 2 <account name>
            # 3 [<account timestamp>]
            accountname = args[1]

        # Call this manually because we need the UID to be the sender.
        self.irc.callHooks([target, 'CLIENT_SERVICES_LOGIN', {'text': accountname}])

        # Check for any cloak changes now.
        self.checkCloakChange(target)

    def handle_fake(self, numeric, command, args):
        """Handles incoming FAKE hostmask changes."""
        target = args[0]
        text = args[1]

        # Assume a usermode +f change, and then update the cloak checking.
        self.irc.applyModes(target, [('+f', text)])

        self.checkCloakChange(target)
        # We don't need to send any hooks here, checkCloakChange does that for us.

    def handle_svsnick(self, source, command, args):
        """Handles SVSNICK (forced nickname change attempts)."""
        # From Nefarious docs at https://github.com/evilnet/nefarious2/blob/7bd3ac4/doc/p10.txt#L1057
        # {7SN} *** SVSNICK (non undernet)

        # 1 <target numeric>
        # 2 <new nick>
        return {'target': args[0], 'newnick': args[1]}

Class = P10Protocol
