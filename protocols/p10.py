"""
p10.py: P10 protocol module for PyLink, supporting Nefarious IRCu and others.
"""

import base64
import socket
import string
import struct
import time
from ipaddress import ip_address

from pylinkirc import conf, structures, utils
from pylinkirc.classes import *
from pylinkirc.log import log
from pylinkirc.protocols.ircs2s_common import *

__all__ = ['P10Protocol']


class P10UIDGenerator(UIDGenerator):
    """Implements a P10 UID Generator."""

    def __init__(self, sid):
        uidchars = string.ascii_uppercase + string.ascii_lowercase + string.digits + '[]'
        length = 3
        super().__init__(uidchars, length, sid)

def p10b64encode(num, length=2):
    """
    Encodes a given numeric using P10 Base64 numeric nicks, as documented at
    https://github.com/evilnet/nefarious2/blob/a29b63144/doc/p10.txt#L69-L92
    """
    # Pack the given number as an unsigned int.
    sidbytes = struct.pack('>I', num)[1:]
    sid = base64.b64encode(sidbytes, b'[]')[-length:]
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

GLINE_MAX_EXPIRE = 604800

class P10Protocol(IRCS2SProtocol):
    COMMAND_TOKENS = {
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
        'WH': 'WALLHOPS',
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Dictionary of UID generators (one for each server).
        self.uidgen = structures.KeyedDefaultdict(P10UIDGenerator)

        # SID generator for P10.
        self.sidgen = P10SIDGenerator(self)

        self.hook_map = {'END_OF_BURST': 'ENDBURST', 'OPMODE': 'MODE',
                         'CLEARMODE': 'MODE', 'BURST': 'JOIN',
                         'WALLCHOPS': 'NOTICE', 'WALLHOPS': 'NOTICE',
                         'WALLVOICES': 'NOTICE'}

        self.protocol_caps |= {'slash-in-hosts', 'underscore-in-hosts',
                               'has-statusmsg'}

        # OPMODE is like SAMODE on other IRCds, and it follows the same modesetting syntax.
        self.handle_opmode = self.handle_mode

    def _send_with_prefix(self, source, text, **kwargs):
        self.send("%s %s" % (source, text), **kwargs)

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
        # Many thanks to Jobe @ evilnet for the code on what to do here. :) -jlu5

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
    def encode_p10_ipv6(ip):
        """Encodes a P10 IPv6 address."""
        # This method is documented briefly at https://github.com/evilnet/nefarious2/blob/47c8bea/doc/p10.txt#L723
        # Basically, each address chunk is encoded into a 3-length word, with :: replaced by _
        # e.g. '1:2::3' -> AABAAC_AAD
        #      '::1' -> AAA_AAB
        ipbits = []
        for ipbit in ip.split(':'):
            if not ipbit:
                # split() creates an empty string between the two colons in "::" if it exists
                # Use this to our advantage here.
                ipbits.append('_')
            else:
                ipbit = int(ipbit, base=16)
                ipbits.append(p10b64encode(ipbit, length=3))

        encoded_ip = ''.join(ipbits)
        if encoded_ip.startswith('_'):  # Special case for ::1, as "__AAA" is probably invalid
            encoded_ip = 'AAA' + encoded_ip
        return encoded_ip

    ### COMMANDS

    def spawn_client(self, nick, ident='null', host='null', realhost=None, modes=set(),
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

        server = server or self.sid
        if not self.is_internal_server(server):
            raise ValueError('Server %r is not a PyLink server!' % server)

        # Create an UIDGenerator instance for every SID, so that each gets
        # distinct values.
        uid = self.uidgen.setdefault(server, P10UIDGenerator(server)).next_uid()

        # Fill in all the values we need
        ts = ts or int(time.time())
        realname = realname or conf.conf['pylink']['realname']
        realhost = realhost or host
        raw_modes = self.join_modes(modes)

        # Initialize an User instance
        u = self.users[uid] = User(self, nick, ts, uid, server, ident=ident, host=host, realname=realname,
                                   realhost=realhost, ip=ip, manipulatable=manipulatable, opertype=opertype)

        # Fill in modes and add it to our users index
        self.apply_modes(uid, modes)
        self.servers[server].users.add(uid)

        # Encode IPs when sending
        if ip_address(ip).version == 4:
            # Thanks to Jobe for the tips here!
            ip = b'\x00\x00' + socket.inet_aton(ip)
            b64ip = base64.b64encode(ip, b'[]')[2:].decode()
        else:  # Propagate IPv6 address, but only if uplink supports it
            if '6' in self._flags:
                b64ip = self.encode_p10_ipv6(ip)
            else:
                b64ip = 'AAAAAA'

        self._send_with_prefix(server, "N {nick} {hopcount} {ts} {ident} {host} {modes} {ip} {uid} "
                                       ":{realname}".format(ts=ts, host=host, nick=nick, ident=ident, uid=uid,
                                                            modes=raw_modes, ip=b64ip, realname=realname,
                                                            realhost=realhost, hopcount=self.servers[server].hopcount))
        return u

    def away(self, source, text):
        """Sends an AWAY message from a PyLink client. <text> can be an empty string
        to unset AWAY status."""
        if not self.is_internal_client(source):
            raise LookupError('No such PyLink client exists.')

        if text:
            self._send_with_prefix(source, 'A :%s' % text)
        else:
            self._send_with_prefix(source, 'A')
        self.users[source].away = text

    def invite(self, numeric, target, channel):
        """Sends INVITEs from a PyLink client."""
        # Note: we have to send a nick as the target, not a UID.
        # <- ABAAA I PyLink-devel #services 1460948992

        if not self.is_internal_client(numeric):
            raise LookupError('No such PyLink client exists.')

        nick = self.users[target].nick

        self._send_with_prefix(numeric, 'I %s %s %s' % (nick, channel, self._channels[channel].ts))

    def join(self, client, channel):
        """Joins a PyLink client to a channel."""
        # <- ABAAB J #test3 1460744371
        ts = self._channels[channel].ts

        if not self.is_internal_client(client):
            raise LookupError('No such PyLink client exists.')

        if not self._channels[channel].users:
            # Empty channels should be created with the CREATE command.
            self._send_with_prefix(client, "C {channel} {ts}".format(ts=ts, channel=channel))
        else:
            self._send_with_prefix(client, "J {channel} {ts}".format(ts=ts, channel=channel))

        self._channels[channel].users.add(client)
        self.users[client].channels.add(channel)

    def kick(self, numeric, channel, target, reason=None):
        """Sends kicks from a PyLink client/server."""

        if (not self.is_internal_client(numeric)) and \
                (not self.is_internal_server(numeric)):
            raise LookupError('No such PyLink client/server exists.')

        if not reason:
            reason = 'No reason given'

        cobj = self._channels[channel]
        # Prevent kick bounces by sending our kick through the server if
        # the sender isn't op.
        if numeric not in self.servers and (not cobj.is_halfop_plus(numeric)):
            reason = '(%s) %s' % (self.get_friendly_name(numeric), reason)
            numeric = self.get_server(numeric)

        self._send_with_prefix(numeric, 'K %s %s :%s' % (channel, target, reason))

        # We can pretend the target left by its own will; all we really care about
        # is that the target gets removed from the channel userlist, and calling
        # handle_part() does that just fine.
        self.handle_part(target, 'KICK', [channel])

        if self.is_internal_client(target):
            # Send PART in response to acknowledge the KICK, per
            # https://github.com/evilnet/nefarious2/blob/ed12d64/doc/p10.txt#L611-L616
            self._send_with_prefix(target, 'L %s :%s' % (channel, reason))

    def kill(self, numeric, target, reason):
        """Sends a kill from a PyLink client/server."""
        # <- ABAAA D AyAAA :nefarious.midnight.vpn!jlu5 (test)

        if (not self.is_internal_client(numeric)) and \
                (not self.is_internal_server(numeric)):
            raise LookupError('No such PyLink client/server exists.')

        self._send_with_prefix(numeric, 'D %s :Killed (%s)' % (target, reason))
        self._remove_client(target)

    def knock(self, source, target, text):
        """KNOCK wrapper for P10: notifies chanops that someone wants to join
        the channel."""
        prefix = '%' if 'h' in self.prefixmodes else '@'
        self.notice(self.pseudoclient.uid, prefix + target,
                    "Knock from %s: %s" % (self.get_friendly_name(source), text))

    def message(self, source, target, text, _notice=False):
        """Sends a PRIVMSG from a PyLink client or server."""
        if (not self.is_internal_client(source)) and \
                (not self.is_internal_server(source)):
            raise LookupError('No such PyLink client/server exists.')

        token = 'O' if _notice else 'P'
        stripped_target = target.lstrip(''.join(self.prefixmodes.values()))
        if self.is_channel(stripped_target):
            msgprefixes = target.split('#', 1)[0]
            # Note: Only NOTICEs to @#channel are actually supported by P10 via
            # WALLCHOPS/WALLHOPS/WALLVOICES. For us it's better to convert
            # PRIVMSGs to these notices instead of dropping them.

            # WALL* commands use this syntax:
            # <- ABAAA WC #magichouse :@ test
            # <- ABAAA WH #magichouse :% test
            # <- ABAAA WV #magichouse :+ test
            # An oddity with the protocol mandates that we send the target prefix
            # in the message. As a side effect, the @/%/+ is actually added to the
            # final text the client sees.
            # This does however make parsing slightly easier.
            if '@' in msgprefixes:
                token = 'WC'
                text = '@ ' + text
            elif '%' in msgprefixes:
                token = 'WH'
                text = '% ' + text
            elif '+' in msgprefixes:
                token = 'WV'
                text = '+ ' + text
            target = stripped_target

        self._send_with_prefix(source, '%s %s :%s' % (token, target, text))

    def notice(self, source, target, text):
        """Sends a NOTICE from a PyLink client or server."""
        self.message(source, target, text, _notice=True)

    def mode(self, numeric, target, modes, ts=None):
        """Sends mode changes from a PyLink client/server."""
        # <- ABAAA M jlu5 -w
        # <- ABAAA M #test +v ABAAB 1460747615

        if (not self.is_internal_client(numeric)) and \
                (not self.is_internal_server(numeric)):
            raise LookupError('No such PyLink client/server exists.')

        modes = list(modes)

        # According to the P10 specification:
        # https://github.com/evilnet/nefarious2/blob/4e2dcb1/doc/p10.txt#L146
        # One line can have a max of 15 parameters. Excluding the target and the first part of the
        # modestring, this means we can send a max of 13 modes with arguments per line.
        is_cmode = self.is_channel(target)
        if is_cmode:
            # Channel mode changes have a trailing TS. User mode changes do not.
            cobj = self._channels[target]
            ts = ts or cobj.ts

            # Prevent mode bounces by sending our mode through the server if
            # the sender isn't op.
            if (numeric not in self.servers) and (not cobj.is_halfop_plus(numeric)):
                numeric = self.get_server(numeric)

            # Wrap modes: start with max bufsize and subtract the lengths of the source, target,
            # mode command, and whitespace.
            bufsize = self.S2S_BUFSIZE - len(numeric) - 4 - len(target) - len(str(ts))

            real_target = target
        else:
            assert target in self.users, "Unknown mode target %s" % target
            # P10 uses nicks in user MODE targets, NOT UIDs. ~jlu5
            real_target = self.users[target].nick

        self.apply_modes(target, modes)

        while modes[:12]:
            joinedmodes = self.join_modes([m for m in modes[:12]])
            if is_cmode:
                for wrapped_modes in self.wrap_modes(modes[:12], bufsize):
                    self._send_with_prefix(numeric, 'M %s %s %s' % (real_target, wrapped_modes, ts))
            else:
                self._send_with_prefix(numeric, 'M %s %s' % (real_target, joinedmodes))
            modes = modes[12:]

    def nick(self, numeric, newnick):
        """Changes the nick of a PyLink client."""
        # <- ABAAA N jlu5_ 1460753763
        if not self.is_internal_client(numeric):
            raise LookupError('No such PyLink client exists.')

        self._send_with_prefix(numeric, 'N %s %s' % (newnick, int(time.time())))
        self.users[numeric].nick = newnick

        # Update the NICK TS.
        self.users[numeric].ts = int(time.time())

    def numeric(self, source, numeric, target, text):
        """Sends raw numerics from a server to a remote client. This is used for WHOIS
        replies."""
        # <- AB 311 AyAAA jlu5 ~jlu5 nefarious.midnight.vpn * :realname
        self._send_with_prefix(source, '%s %s %s' % (numeric, target, text))

    def oper_notice(self, source, text):
        """
        Send a message to all opers.
        """
        self._send_with_prefix(source, 'WA :%s' % text)

    def part(self, client, channel, reason=None):
        """Sends a part from a PyLink client."""

        if not self.is_internal_client(client):
            raise LookupError('No such PyLink client exists.')

        msg = "L %s" % channel
        if reason:
            msg += " :%s" % reason
        self._send_with_prefix(client, msg)
        self.handle_part(client, 'PART', [channel])

    def _ping_uplink(self):
        """Sends a PING to the uplink."""
        if self.sid:
            self._send_with_prefix(self.sid, 'G %s' % self.sid)

    def quit(self, numeric, reason):
        """Quits a PyLink client."""
        if self.is_internal_client(numeric):
            self._send_with_prefix(numeric, "Q :%s" % reason)
            self._remove_client(numeric)
        else:
            raise LookupError("No such PyLink client exists.")

    def set_server_ban(self, source, duration, user='*', host='*', reason='User banned'):
        """
        Sets a server ban.
        """
        assert not (user == host == '*'), "Refusing to set ridiculous ban on *@*"

        # https://github.com/evilnet/nefarious2/blob/master/doc/p10.txt#L535
        # <- ABAAA jlu5 * +test@test.host 30 1500300185 1500300215 :haha, you're banned now!!!!1
        currtime = int(time.time())

        if duration == 0 or duration > GLINE_MAX_EXPIRE:
            # IRCu and Nefarious set 7 weeks (604800 secs) as the max GLINE length - look for the
            # GLINE_MAX_EXPIRE definition
            log.debug('(%s) Lowering GLINE duration on %s@%s from %s to %s', self.name, user, host, duration, GLINE_MAX_EXPIRE)
            duration = GLINE_MAX_EXPIRE

        self._send_with_prefix(source, 'GL * +%s@%s %s %s %s :%s' % (user, host, duration, currtime, currtime+duration, reason))

    def sjoin(self, server, channel, users, ts=None, modes=set()):
        """Sends an SJOIN for a group of users to a channel.

        The sender should always be a Server ID (SID). TS is optional, and defaults
        to the one we've stored in the channel state if not given.
        <users> is a list of (prefix mode, UID) pairs:

        Example uses:
            sjoin('100', '#test', [('', '100AAABBC'), ('o', 100AAABBB'), ('v', '100AAADDD')])
            sjoin(self.sid, '#test', [('o', self.pseudoclient.uid)])
        """
        # <- AB B #test 1460742014 +tnl 10 ABAAB,ABAAA:o :%*!*@other.bad.host ~ *!*@bad.host
        server = server or self.sid

        assert users, "sjoin: No users sent?"
        log.debug('(%s) sjoin: got %r for users', self.name, users)
        if not server:
            raise LookupError('No such PyLink client exists.')

        # Only send non-list modes in the modes argument BURST. Bans and exempts are formatted differently:
        # <- AB B #test 1460742014 +tnl 10 ABAAB,ABAAA:o :%*!*@other.bad.host *!*@bad.host
        # <- AB B #test2 1460743539 +l 10 ABAAA:vo :%*!*@bad.host
        # <- AB B #test 1460747615 ABAAA:o :% ~ *!*@test.host
        modes = modes or self._channels[channel].modes
        orig_ts = self._channels[channel].ts
        ts = ts or orig_ts

        bans = []
        exempts = []
        regularmodes = []
        for mode in modes:
            modechar = mode[0][-1]
            # Store bans and exempts in separate lists for processing, but don't reset bans that have already been set.
            if modechar in self.cmodes['*A']:
                if (modechar, mode[1]) not in self._channels[channel].modes:
                    if modechar == 'b':
                        bans.append(mode[1])
                    elif modechar == 'e':
                        exempts.append(mode[1])
            else:
                regularmodes.append(mode)

        log.debug('(%s) sjoin: bans: %s, exempts: %s, other modes: %s', self.name, bans, exempts, regularmodes)

        changedmodes = set(modes)
        changedusers = []
        namelist = []

        # This is annoying because we have to sort our users by access before sending...
        # Joins should look like: A0AAB,A0AAC,ABAAA:v,ABAAB:o,ABAAD,ACAAA:ov
        users = sorted(users, key=self.access_sort)

        msgprefix = '{sid} B {channel} {ts} '.format(sid=server, channel=channel, ts=ts)
        if regularmodes:
            msgprefix += '%s ' % self.join_modes(regularmodes)

        last_prefixes = ''
        for userpair in users:
            # We take <users> as a list of (prefixmodes, uid) pairs.
            assert len(userpair) == 2, "Incorrect format of userpair: %r" % userpair
            prefixes, user = userpair

            # Keep track of all the users and modes that are added. namelist is used
            # to track what we actually send to the IRCd.
            changedusers.append(user)
            log.debug('(%s) sjoin: adding %s:%s to namelist', self.name, user, prefixes)

            if prefixes and prefixes != last_prefixes:
                namelist.append('%s:%s' % (user, prefixes))
            else:
                namelist.append(user)

            last_prefixes = prefixes
            if prefixes:
                for prefix in prefixes:
                    changedmodes.add(('+%s' % prefix, user))

            self.users[user].channels.add(channel)
        else:
            if namelist:
                log.debug('(%s) sjoin: got %r for namelist', self.name, namelist)

                # Flip the (prefixmodes, user) pairs in users, and save it as a dict for easy lookup
                # later of what modes each target user should have.
                names_dict = {uid: prefixes for prefixes, uid in users}

                # Wrap all users and send them to prevent cutoff. Subtract 4 off the maximum
                # buf size to account for user prefix data that may be re-added (e.g. ":ohv")
                for linenum, wrapped_msg in \
                        enumerate(utils.wrap_arguments(msgprefix, namelist, self.S2S_BUFSIZE-1-len(self.prefixmodes),
                                                      separator=',')):
                    if linenum:  # Implies "if linenum > 0"
                        # XXX: Ugh, this postprocessing sucks, but we have to make sure that mode prefixes are accounted
                        # for in the burst.
                        wrapped_args = self.parse_args(wrapped_msg.split(" "))
                        wrapped_namelist = wrapped_args[-1].split(',')
                        log.debug('(%s) sjoin: wrapped args: %s (post-wrap fixing)', self.name,
                                  wrapped_args)

                        # If the first UID was supposed to have a prefix mode attached, re-add it here
                        first_uid = wrapped_namelist[0]

                        first_prefix = names_dict.get(first_uid, '')
                        log.debug('(%s) sjoin: prefixes for first user %s: %s (post-wrap fixing)', self.name,
                                  first_uid, first_prefix)

                        if (':' not in first_uid) and first_prefix:
                            log.debug('(%s) sjoin: re-adding prefix %s to user %s (post-wrap fixing)', self.name,
                                      first_uid, first_prefix)
                            wrapped_namelist[0] += ':%s' % prefixes
                            wrapped_msg = ' '.join(wrapped_args[:-1])
                            wrapped_msg += ' '
                            wrapped_msg += ','.join(wrapped_namelist)

                    self.send(wrapped_msg)

        self._channels[channel].users.update(changedusers)

        # Technically we can send bans together with the above user introductions, but
        # it's easier to line wrap them separately.
        if bans or exempts:
            msgprefix += ':%'  # Ban string starts with a % if there is anything
            if bans:
                for wrapped_msg in utils.wrap_arguments(msgprefix, bans, self.S2S_BUFSIZE):
                    self.send(wrapped_msg)
            if exempts:
                # Now add exempts, which are separated from the ban list by a single argument "~".
                msgprefix += ' ~ '
                for wrapped_msg in utils.wrap_arguments(msgprefix, exempts, self.S2S_BUFSIZE):
                    self.send(wrapped_msg)

        self.updateTS(server, channel, ts, changedmodes)

    def spawn_server(self, name, sid=None, uplink=None, desc=None):
        """
        Spawns a server off a PyLink server. desc (server description)
        defaults to the one in the config. uplink defaults to the main PyLink
        server, and sid (the server ID) is automatically generated if not
        given.
        """
        # <- SERVER nefarious.midnight.vpn 1 1460673022 1460673239 J10 ABP]] +h6 :Nefarious2 test server
        uplink = uplink or self.sid
        name = name.lower()
        desc = desc or self.serverdata.get('serverdesc') or conf.conf['pylink']['serverdesc']

        if sid is None:  # No sid given; generate one!
            sid = self.sidgen.next_sid()

        assert len(sid) == 2, "Incorrect SID length"
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
        self._send_with_prefix(uplink, 'SERVER %s %s %s %s P10 %s]]] +h6 :%s' % \
                   (name, self.servers[sid].hopcount, self.start_ts, int(time.time()), sid, desc))

        return sid

    def squit(self, source, target, text='No reason given'):
        """SQUITs a PyLink server."""
        # <- ABAAE SQ nefarious.midnight.vpn 0 :test

        targetname = self.servers[target].name

        self._send_with_prefix(source, 'SQ %s 0 :%s' % (targetname, text))
        self.handle_squit(source, 'SQUIT', [target, text])

    def topic(self, source, target, text):
        """Sends a TOPIC change from a PyLink client or server."""
        # <- ABAAA T #test jlu5!~jlu5@nefarious.midnight.vpn 1460852591 1460855795 :blah
        # First timestamp is channel creation time, second is current time,
        if (not self.is_internal_client(source)) and (not self.is_internal_server(source)):
            raise LookupError('No such PyLink client/server exists.')

        if source in self.users:  # Expand the nick!user@host if the sender is a user
            sendername = self.get_hostmask(source)
        else:
            # For servers, just show the server name.
            sendername = self.get_friendly_name(source)

        creationts = self._channels[target].ts

        self._send_with_prefix(source, 'T %s %s %s %s :%s' % (target, sendername, creationts,
                   int(time.time()), text))
        self._channels[target].topic = text
        self._channels[target].topicset = True
    topic_burst = topic

    def update_client(self, target, field, text):
        """Updates the ident or host of any connected client."""
        uobj = self.users[target]

        ircd = self.serverdata.get('ircd', self.serverdata.get('p10_ircd', 'nefarious')).lower()

        if self.is_internal_client(target):
            # Host changing via SETHOST is only supported on nefarious and snircd.
            if ircd not in ('nefarious', 'snircd'):
                raise NotImplementedError("Host changing for internal clients (via SETHOST) is only "
                                          "available on nefarious and snircd, and we're using p10_ircd=%r" % ircd)

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
                raise NotImplementedError("Changing field %r of a client is "
                                          "unsupported by this protocol." % field)
        elif field == 'HOST':
            # Host changing via FAKE is only supported on nefarious.
            if ircd != 'nefarious':
                raise NotImplementedError("vHost changing for non-PyLink clients (via FAKE) is "
                                          "only available on nefarious, and we're using p10_ircd=%r" % ircd)

            # Use FAKE (FA) for external clients.
            self._send_with_prefix(self.sid, 'FA %s %s' % (target, text))

            # Save the host change as a user mode (this is what P10 does on bursts),
            # so further host checks work.
            self.apply_modes(target, [('+f', text)])
            self.mode(self.sid, target, [('+x', None)])
        else:
            raise NotImplementedError("Changing field %r of a client is "
                                      "unsupported by this protocol." % field)

        # P10 cloaks aren't as simple as just replacing the displayed host with the one we're
        # sending. Check for cloak changes properly.
        # Note: we don't need to send any hooks here, _check_cloak_change does that for us.
        self._check_cloak_change(target)

    ### HANDLERS

    def handle_events(self, data):
        """
        Events handler for the P10 protocol. This is mostly the same as RFC1459, with extra handling
        for the fact that P10 does not send source numerics prefixed with a ":".
        """
        # After the initial PASS & SERVER message, every following message should be prefixed
        if self.uplink and not data.startswith(":"):
            data = ':' + data
        return super().handle_events(data)

    def post_connect(self):
        """Initializes a connection to a server."""
        ts = self.start_ts

        self.send("PASS :%s" % self.serverdata["sendpass"])

        # {7S} *** SERVER

        # 1 <name of new server>
        # 2 <hops>
        # 3 <boot TS>
        # 4 <link TS>
        # 5 <protocol>
        # 6 <numeric of new server><max client numeric>
        # 7 <flags> <-- Mark ourselves as a service with IPv6 support (+s & +6) -jlu5
        # -1 <description of new server>

        name = self.serverdata["hostname"]

        # Encode our SID using P10 Base64.
        self.sid = sid = p10b64encode(self.serverdata["sid"])

        desc = self.serverdata.get('serverdesc') or conf.conf['pylink']['serverdesc']

        self._flags = []

        # Enumerate modes, from https://github.com/evilnet/nefarious2/blob/master/doc/modes.txt
        p10_ircd = self.serverdata.get('p10_ircd', 'nefarious').lower()
        if p10_ircd == 'nefarious':
            cmodes = {'delayjoin': 'D', 'registered': 'R', 'key': 'k', 'banexception': 'e',
                      'redirect': 'L', 'oplevel_apass': 'A', 'oplevel_upass': 'U',
                      'adminonly': 'a', 'operonly': 'O', 'regmoderated': 'M', 'nonotice': 'N',
                      'permanent': 'z', 'hidequits': 'Q', 'noctcp': 'C', 'noamsg': 'T', 'blockcolor': 'c',
                      'stripcolor': 'S', 'had_delayjoin': 'd', 'regonly': 'r',
                      '*A': 'be', '*B': 'AUk', '*C': 'Ll', '*D': 'psmtinrDRaOMNzQCTcSd'}
            self.umodes.update({'servprotect': 'k', 'sno_debug': 'g', 'cloak': 'x', 'privdeaf': 'D',
                                    'hidechans': 'n', 'deaf_commonchan': 'q', 'bot': 'B', 'deaf': 'd',
                                    'hideoper': 'H', 'hideidle': 'I', 'regdeaf': 'R', 'showwhois': 'W',
                                    'admin': 'a', 'override': 'X', 'noforward': 'L', 'ssl': 'z',
                                    'registered': 'r', 'cloak_sethost': 'h', 'cloak_fakehost': 'f',
                                    'cloak_hashedhost': 'C', 'cloak_hashedip': 'c', 'locop': 'O',
                                    '*A': '', '*B': '', '*C': 'fCcrh', '*D': 'oOiwskgxnqBdDHIRWaXLz'})
            # Nefarious supports extbans as documented at
            # https://github.com/evilnet/nefarious2/blob/master/doc/extendedbans.txt
            self.extbans_matching.update({
                'ban_account': '~a:',
                'ban_inchannel': '~c:',
                'ban_realname': '~r:',
                'ban_mark': '~m:',
                'ban_unregistered_mark': '~M:',
                'ban_banshare': '~j:'
            })
            self.extbans_acting.update({
                'quiet': '~q:',
                'ban_nonick': '~n:'
            })
        elif p10_ircd == 'snircd':
            # snircd has +u instead of +Q for hidequits, and fewer chanel modes.
            cmodes = {'oplevel_apass': 'A', 'oplevel_upass': 'U', 'delayjoin': 'D', 'regonly': 'r',
                      'had_delayjoin': 'd', 'hidequits': 'u', 'regmoderated': 'M', 'blockcolor': 'c',
                      'noctcp': 'C', 'nonotice': 'N', 'noamsg': 'T',
                      '*A': 'b', '*B': 'AUk', '*C': 'l', '*D': 'imnpstrDducCMNT'}
            # From https://www.quakenet.org/help/general/what-user-modes-are-available-on-quakenet
            # plus my own testing.
            self.umodes.update({'servprotect': 'k', 'sno_debug': 'g', 'cloak': 'x',
                                    'hidechans': 'n', 'deaf': 'd', 'hideidle': 'I', 'regdeaf': 'R',
                                    'override': 'X', 'registered': 'r', 'cloak_sethost': 'h', 'locop': 'O',
                                    '*A': '', '*B': '', '*C': 'h', '*D': 'imnpstrkgxndIRXO'})
        elif p10_ircd == 'ircu':
            # ircu proper has even fewer modes.
            cmodes = {'oplevel_apass': 'A', 'oplevel_upass': 'U', 'delayjoin': 'D', 'regonly': 'r',
                      'had_delayjoin': 'd', 'blockcolor': 'c', 'noctcp': 'C', 'registered': 'R',
                      '*A': 'b', '*B': 'AUk', '*C': 'l', '*D': 'imnpstrDdRcC'}
            self.umodes.update({'servprotect': 'k', 'sno_debug': 'g', 'cloak': 'x',
                                    'deaf': 'd', 'registered': 'r', 'locop': 'O',
                                    '*A': '', '*B': '', '*C': '', '*D': 'imnpstrkgxdO'})

        if self.serverdata.get('use_halfop'):
            cmodes['halfop'] = 'h'
            self.prefixmodes['h'] = '%'
        self.cmodes.update(cmodes)

        self.send('SERVER %s 1 %s %s J10 %s]]] +s6 :%s' % (name, ts, ts, sid, desc))
        self._send_with_prefix(sid, "EB")

    def handle_server(self, source, command, args):
        """Handles incoming server introductions."""
        # <- SERVER nefarious.midnight.vpn 1 1460673022 1460673239 J10 ABP]] +h6 :Nefarious2 test server
        servername = args[0].lower()
        sid = args[5][:2]
        sdesc = args[-1]
        self.servers[sid] = Server(self, source, servername, desc=sdesc)
        self._flags = list(args[6])[1:]

        if self.uplink is None:
            # If we haven't already found our uplink, this is probably it.
            self.uplink = sid

        return {'name': servername, 'sid': sid, 'text': sdesc}

    def handle_nick(self, source, command, args):
        """Handles the NICK command, used for user introductions and nick changes."""
        if len(args) > 2:
            # <- AB N jlu5 1 1460673049 ~jlu5 nefarious.midnight.vpn +iw B]AAAB ABAAA :realname

            nick = args[0]
            self._check_nick_collision(nick)
            ts, ident, host = args[2:5]
            ts = int(ts)
            realhost = host
            ip = args[-3]
            ip = self.decode_p10_ip(ip)
            uid = args[-2]
            realname = args[-1]

            log.debug('(%s) handle_nick got args: nick=%s ts=%s uid=%s ident=%s '
                      'host=%s realname=%s realhost=%s ip=%s', self.name, nick, ts, uid,
                      ident, host, realname, realhost, ip)

            uobj = self.users[uid] = User(self, nick, ts, uid, source, ident, host, realname, realhost, ip)
            uobj.ssl = False
            self.servers[source].users.add(uid)

            # https://github.com/evilnet/nefarious2/blob/master/doc/p10.txt#L708
            # Mode list is optional, and can be detected if the 6th argument starts with a +.
            # This list can last until the 3rd LAST argument in the line, should there be mode
            # parameters attached.
            if args[5].startswith('+'):
                modes = args[5:-3]
                parsedmodes = self.parse_modes(uid, modes)
                self.apply_modes(uid, parsedmodes)

                for modepair in parsedmodes:
                    if modepair[0][-1] == 'r':
                        # Parse account registrations, sent as usermode "+r accountname:TS"
                        accountname = modepair[1].split(':', 1)[0]
                        self.call_hooks([uid, 'CLIENT_SERVICES_LOGIN', {'text': accountname}])

                    elif modepair[0][-1] == self.umodes.get('ssl'):  # track SSL status where available
                        uobj.ssl = True

                # Call the OPERED UP hook if +o is being added to the mode list.
                self._check_oper_status_change(uid, parsedmodes)

            self._check_cloak_change(uid)

            return {'uid': uid, 'ts': ts, 'nick': nick, 'realhost': realhost, 'host': host, 'ident': ident, 'ip': ip, 'parse_as': 'UID', 'secure': uobj.ssl}

        else:
            # <- ABAAA N jlu5_ 1460753763
            oldnick = self.users[source].nick
            newnick = self.users[source].nick = args[0]

            self.users[source].ts = ts = int(args[1])

            # Update the nick TS.
            return {'newnick': newnick, 'oldnick': oldnick, 'ts': ts}

    def _check_cloak_change(self, uid):
        """Checks for cloak changes (ident and host) on the given UID."""
        uobj = self.users[uid]
        ident = uobj.ident

        modes = dict(uobj.modes)
        log.debug('(%s) _check_cloak_change: modes of %s are %s', self.name, uid, modes)

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
            elif uobj.services_account and self.serverdata.get('use_account_cloaks'):
                # The user is registered. However, if account cloaks are enabled, we have to figure
                # out their new cloaked host. There can be oper cloaks and user cloaks, each with
                # a different suffix. Account cloaks take the format of <accountname>.<suffix>.
                # e.g. someone logged in as "person1" might get cloak "person1.users.somenet.org"
                #      someone opered and logged in as "person2" might get cloak "person.opers.somenet.org"
                # This is a lot of extra configuration on the services' side, but there's nothing else
                # we can do about it.
                if self.serverdata.get('use_oper_account_cloaks') and 'o' in modes:
                    try:
                        # These errors should be fatal.
                        suffix = self.serverdata['oper_cloak_suffix']
                    except KeyError:
                        raise ProtocolError("(%s) use_oper_account_cloaks was enabled, but "
                                            "oper_cloak_suffix was not defined!" % self.name)
                else:
                    try:
                        suffix = self.serverdata['cloak_suffix']
                    except KeyError:
                        raise ProtocolError("(%s) use_account_cloaks was enabled, but "
                                            "cloak_suffix was not defined!" % self.name)

                accountname = uobj.services_account
                newhost = "%s.%s" % (accountname, suffix)

            elif 'C' in modes and self.serverdata.get('use_hashed_cloaks'):
                # +C propagates hashed IP cloaks, similar to UnrealIRCd. (thank god we don't
                # need to generate these ourselves)
                newhost = modes['C']
            else:
                # No cloaking mechanism matched, fall back to the real host.
                newhost = uobj.realhost

        # Propagate a hostname update to plugins, but only if the changed host is different.
        if newhost != uobj.host:
             self.call_hooks([uid, 'CHGHOST', {'target': uid, 'newhost': newhost}])
        if ident != uobj.ident:
             self.call_hooks([uid, 'CHGIDENT', {'target': uid, 'newident': ident}])
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
        # Why is this the way it is? I don't know... -jlu5

        target = args[1]
        sid = self._get_SID(target)
        orig_pingtime = args[0][1:]  # Strip the !, used to denote a TS instead of a server name.

        currtime = time.time()
        timediff = int(time.time() - float(orig_pingtime))

        if self.is_internal_server(sid):
            # Only respond if the target server is ours. No forwarding is needed because
            # no IRCds can ever connect behind us...
            self._send_with_prefix(self.sid, 'Z %s %s %s %s' % (target, orig_pingtime, timediff, currtime), queue=False)

    def handle_pass(self, source, command, args):
        """Handles authentication with our uplink."""
        # <- PASS :testpass
        if args[0] != self.serverdata['recvpass']:
            raise ProtocolError("RECVPASS from uplink does not match configuration!")

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

        channel = args[0]
        chandata = self._channels[channel].deepcopy()

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
            parsedmodes = self.parse_modes(channel, modestring)
        else:
            parsedmodes = []

        changedmodes = set(parsedmodes + bans)

        namelist = []
        prefixes = ''
        userlist = args[-1].split(',')
        log.debug('(%s) handle_burst: got userlist %r for %r', self.name, userlist, channel)

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
                log.debug('(%s) handle_burst: got mode prefixes %r for user %r', self.name, prefixes, user)

                # Don't crash when we get an invalid UID.
                if user not in self.users:
                    log.warning('(%s) handle_burst: tried to introduce user %s not in our user list, ignoring...',
                                self.name, user)
                    continue

                namelist.append(user)

                self.users[user].channels.add(channel)

                # Only save mode changes if the remote has lower TS than us.
                changedmodes |= {('+%s' % mode, user) for mode in prefixes}

                self._channels[channel].users.add(user)

        # Statekeeping with timestamps
        their_ts = int(args[1])
        our_ts = self._channels[channel].ts
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
            oldchans = self.users[source].channels.copy()
            log.debug('(%s) Got /join 0 from %r, channel list is %r',
                      self.name, source, oldchans)

            for channel in oldchans:
                self._channels[channel].users.discard(source)
                self.users[source].channels.discard(channel)

            return {'channels': oldchans, 'text': 'Left all channels.', 'parse_as': 'PART'}
        else:
            channel = args[0]
            if ts:  # Only update TS if one was sent.
                self.updateTS(source, channel, ts)

            self.users[source].channels.add(channel)
            self._channels[channel].users.add(source)

        return {'channel': channel, 'users': [source], 'modes':
                self._channels[channel].modes, 'ts': ts or int(time.time())}
    handle_create = handle_join

    def handle_end_of_burst(self, source, command, args):
        """Handles end of burst from servers."""

        # Send EOB acknowledgement; this is required by the P10 specification,
        # and needed if we want to be able to receive channel messages, etc.
        if source == self.uplink:
            self._send_with_prefix(self.sid, 'EA')
            self.connected.set()

        self.servers[source].has_eob = True
        return {}

    def handle_kick(self, source, command, args):
        """Handles incoming KICKs."""
        # <- ABAAA K #TEST AyAAA :PyLink-devel
        channel = args[0]
        kicked = args[1]

        self.handle_part(kicked, 'KICK', [channel, args[2]])

        # Send PART in response to acknowledge the KICK, per
        # https://github.com/evilnet/nefarious2/blob/ed12d64/doc/p10.txt#L611-L616
        self._send_with_prefix(kicked, 'L %s :%s' % (channel, args[2]))

        return {'channel': channel, 'target': kicked, 'text': args[2]}

    def handle_topic(self, source, command, args):
        """Handles TOPIC changes."""
        # <- ABAAA T #test jlu5!~jlu5@nefarious.midnight.vpn 1460852591 1460855795 :blah
        channel = args[0]
        topic = args[-1]

        oldtopic = self._channels[channel].topic
        self._channels[channel].topic = topic
        self._channels[channel].topicset = True

        return {'channel': channel, 'setter': args[1], 'text': topic,
                'oldtopic': oldtopic}

    def handle_clearmode(self, numeric, command, args):
        """Handles CLEARMODE, which is used to clear a channel's modes."""
        # <- ABAAA CM #test ovpsmikbl
        channel = args[0]
        modes = args[1]

        # Enumerate a list of our existing modes, including prefix modes.
        existing = list(self._channels[channel].modes)
        for pmode, userlist in self._channels[channel].prefixmodes.items():
            # Expand the prefix modes lists to individual ('o', 'UID') mode pairs.
            modechar = self.cmodes.get(pmode)
            existing += [(modechar, user) for user in userlist]

        # Back up the channel state.
        oldobj = self._channels[channel].deepcopy()

        changedmodes = []

        # Iterate over all the modes we have for this channel.
        for modepair in existing:
            modechar, data = modepair

            # Check if each mode matches any that we're unsetting.
            if modechar in modes:
                if modechar in (self.cmodes['*A']+self.cmodes['*B']+''.join(self.prefixmodes.keys())):
                    # Mode is a list mode, prefix mode, or one that always takes a parameter when unsetting.
                    changedmodes.append(('-%s' % modechar, data))
                else:
                    # Mode does not take an argument when unsetting.
                    changedmodes.append(('-%s' % modechar, None))

        self.apply_modes(channel, changedmodes)
        return {'target': channel, 'modes': changedmodes, 'channeldata': oldobj}

    def handle_account(self, numeric, command, args):
        """Handles services account changes."""
        # ACCOUNT has two possible syntaxes in P10, one with extended accounts
        # and one without.

        target = args[0]

        if self.serverdata.get('use_extended_accounts'):
            # Registration: <- AA AC ABAAA R jlu5 1459019072
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
            elif len(args[1]) > 1:
                log.warning('(%s) Got subcommand %r for %s in ACCOUNT message, is use_extended_accounts set correctly?',
                            self.name, args[1], target)
                return
            else:
                return

        else:
            # ircu or nefarious with F:EXTENDED_ACCOUNTS = FALSE
            # 1 <target user numeric>
            # 2 <account name>
            # 3 [<account timestamp>]
            accountname = args[1]

        # Call this manually because we need the UID to be the sender.
        self.call_hooks([target, 'CLIENT_SERVICES_LOGIN', {'text': accountname}])

        # Check for any cloak changes now.
        self._check_cloak_change(target)

    def handle_fake(self, numeric, command, args):
        """Handles incoming FAKE hostmask changes."""
        target = args[0]
        text = args[1]

        # Assume a usermode +f change, and then update the cloak checking.
        self.apply_modes(target, [('+f', text)])

        self._check_cloak_change(target)
        # We don't need to send any hooks here, _check_cloak_change does that for us.

    def handle_svsnick(self, source, command, args):
        """Handles SVSNICK (forced nickname change attempts)."""
        # From Nefarious docs at https://github.com/evilnet/nefarious2/blob/7bd3ac4/doc/p10.txt#L1057
        # {7SN} *** SVSNICK (non undernet)

        # 1 <target numeric>
        # 2 <new nick>
        return {'target': args[0], 'newnick': args[1]}

    def handle_wallchops(self, source, command, args):
        """Handles WALLCHOPS/WALLHOPS/WALLVOICES, the equivalent of @#channel
        messages and the like on P10."""
        # <- ABAAA WC #magichouse :@ test
        # <- ABAAA WH #magichouse :% test
        # <- ABAAA WV #magichouse :+ test
        prefix, text = args[-1].split(' ', 1)
        return {'target': prefix+args[0], 'text': text}
    handle_wallhops = handle_wallvoices = handle_wallchops

Class = P10Protocol
