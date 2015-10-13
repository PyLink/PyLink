import time
import sys
import os
import time
import ipaddress
import re

curdir = os.path.dirname(__file__)
sys.path += [curdir, os.path.dirname(curdir)]
import utils
from log import log
from classes import *
from ts6_common import TS6BaseProtocol

class UnrealProtocol(TS6BaseProtocol):
    def __init__(self, irc):
        super(UnrealProtocol, self).__init__(irc)
        # Set our case mapping (rfc1459 maps "\" and "|" together, for example".
        self.casemapping = 'ascii'
        self.proto_ver = 3999
        self.min_proto_ver = 3999
        self.hook_map = {'UMODE2': 'MODE'}
        self.uidgen = {}

        self.caps = {}
        self._unrealCmodes = {'l': 'limit', 'c': 'blockcolor', 'G': 'censor',
                         'D': 'delayjoin', 'n': 'noextmsg', 's': 'secret',
                         'T': 'nonotice', 'z': 'sslonly', 'b': 'ban', 'V': 'noinvite',
                         'Z': 'issecure', 'r': 'registered', 'N': 'nonick',
                         'e': 'banexception', 'R': 'regonly', 'M': 'regmoderated',
                         'p': 'private', 'Q': 'nokick', 'P': 'permanent', 'k': 'key',
                         'C': 'noctcp', 'O': 'operonly', 'S': 'stripcolor',
                         'm': 'moderated', 'K': 'noknock', 'o': 'op', 'v': 'voice',
                         'I': 'invex', 't': 'topiclock', 'f': 'flood_unreal'}
        self._neededCaps = ["VL", "SID", "CHANMODES", "NOQUIT", "SJ3"]

    ### OUTGOING COMMAND FUNCTIONS
    def spawnClient(self, nick, ident='null', host='null', realhost=None, modes=set(),
            server=None, ip='0.0.0.0', realname=None, ts=None, opertype=None,
            manipulatable=True):
        """Spawns a client with nick <nick> on the given IRC connection.

        Note: No nick collision / valid nickname checks are done here; it is
        up to plugins to make sure they don't introduce anything invalid."""
        server = server or self.irc.sid
        if not utils.isInternalServer(self.irc, server):
            raise ValueError('Server %r is not a PyLink internal PseudoServer!' % server)
        # Unreal 3.4 uses TS6-style UIDs. They don't start from AAAAAA like other IRCd's
        # do, but we can do that fine...
        uid = self.uidgen.setdefault(server, utils.TS6UIDGenerator(server)).next_uid()
        ts = ts or int(time.time())
        realname = realname or self.irc.botdata['realname']
        realhost = realhost or host
        raw_modes = utils.joinModes(modes)
        u = self.irc.users[uid] = IrcUser(nick, ts, uid, ident=ident, host=host, realname=realname,
            realhost=realhost, ip=ip)
        utils.applyModes(self.irc, uid, modes)
        self.irc.servers[server].users.add(uid)
        # <- :001 UID GL 0 1441306929 gl localhost 0018S7901 0 +iowx * midnight-1C620195 fwAAAQ== :realname
        self._send(server, "UID {nick} 0 {ts} {ident} {realhost} {uid} 0 {modes} "
                           "* {host} * :{realname}".format(ts=ts, host=host,
                                nick=nick, ident=ident, uid=uid,
                                modes=raw_modes, realname=realname,
                                realhost=realhost))
        return u

    def joinClient(self, client, channel):
        pass

    def pingServer(self, source=None, target=None):
        """Sends a PING to a target server. Periodic PINGs are sent to our uplink
        automatically by the Irc() internals; plugins shouldn't have to use this."""
        source = source or self.irc.sid
        target = target or self.irc.uplink
        if not (target is None or source is None):
            self._send(source, 'PING %s %s' % (self.irc.servers[source].name, self.irc.servers[target].name))

    ### HANDLERS

    def connect(self):
        """Initializes a connection to a server."""
        ts = self.irc.start_ts
        self.irc.prefixmodes = {'q': '~', 'a': '&', 'o': '@', 'h': '%', 'v': '+'}
        ### XXX: fill out self.irc.umodes

        f = self.irc.send
        host = self.irc.serverdata["hostname"]
        f('PASS :%s' % self.irc.serverdata["sendpass"])
        # https://github.com/unrealself.ircd/unrealself.ircd/blob/2f8cb55e/doc/technical/protoctl.txt
        # We support the following protocol features:
        # SJ3 - extended SJOIN
        # NOQUIT - QUIT messages aren't sent for all users in a netsplit
        # NICKv2 - Extended NICK command, sending MODE and CHGHOST info with it
        # SID - Use UIDs and SIDs (unreal 3.4)
        # VL - Sends version string in below SERVER message
        # UMODE2 - used for users setting modes on themselves (one less argument needed)
        # EAUTH - Early auth? (Unreal 3.4 linking protocol)
        # ~~NICKIP - sends the IP in the NICK/UID command~~ Doesn't work with SID/UID support
        f('PROTOCTL SJ3 NOQUIT NICKv2 VL UMODE2 PROTOCTL EAUTH=%s SID=%s' % (self.irc.serverdata["hostname"], self.irc.sid))
        sdesc = self.irc.serverdata.get('serverdesc') or self.irc.botdata['serverdesc']
        f('SERVER %s 1 U%s-h6e-%s :%s' % (host, self.proto_ver, self.irc.sid, sdesc))
        f('NETINFO 1 %s %s * 0 0 0 :%s' % (self.irc.start_ts, self.proto_ver, self.irc.serverdata.get("netname", self.irc.name)))
        self._send(self.irc.sid, 'EOS')

    def handle_uid(self, numeric, command, args):
        # <- :001 UID GL 0 1441306929 gl localhost 0018S7901 0 +iowx * midnight-1C620195 fwAAAQ== :realname
        # <- :001 UID GL| 0 1441389007 gl 10.120.0.6 001ZO8F03 0 +iwx * 391A9CB9.26A16454.D9847B69.IP CngABg== :realname
        # arguments: nick, number???, ts, ident, real-host, UID, number???, modes,
        #            star???, hidden host, some base64 thing???, and realname
        # TODO: find out what all the "???" fields mean.
        nick = args[0]
        ts, ident, realhost, uid = args[2:6]
        modestring = args[7]
        host = args[9]
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:  # Invalid for IP
            # XXX: find a way of getting the real IP of the user (protocol-wise)
            #      without looking up every hostname ourselves (that's expensive!)
            #      NICKIP doesn't seem to work for the UID command...
            ip = "0.0.0.0"
        realname = args[-1]
        self.irc.users[uid] = IrcUser(nick, ts, uid, ident, host, realname, realhost, ip)
        parsedmodes = utils.parseModes(self.irc, uid, [modestring])
        utils.applyModes(self.irc, uid, parsedmodes)
        self.irc.servers[numeric].users.add(uid)
        return {'uid': uid, 'ts': ts, 'nick': nick, 'realhost': realhost, 'host': host, 'ident': ident, 'ip': ip}

    def handle_pass(self, numeric, command, args):
        # <- PASS :abcdefg
        if args[0] != self.irc.serverdata['recvpass']:
            raise ProtocolError("Error: RECVPASS from uplink does not match configuration!")

    def handle_ping(self, numeric, command, args):
        if numeric == self.irc.uplink:
            self.irc.send('PONG %s :%s' % (self.irc.serverdata['hostname'], args[-1]))

    def handle_pong(self, source, command, args):
        log.debug('(%s) Ping received from %s for %s.', self.irc.name, source, args[-1])
        if source in (self.irc.uplink, self.irc.servers[self.irc.uplink].name) and args[-1] == self.irc.serverdata['hostname']:
            log.debug('(%s) Set self.irc.lastping.', self.irc.name)
            self.irc.lastping = time.time()

    def handle_server(self, numeric, command, args):
        """Handles the SERVER command, which is used for both authentication and
        introducing legacy (non-SID) servers."""
        # <- SERVER unreal.midnight.vpn 1 :U3999-Fhin6OoEM UnrealIRCd test server
        sname = args[0]
        if numeric == self.irc.uplink:  # We're doing authentication
            for cap in self._neededCaps:
                if cap not in self.caps:
                    raise ProtocolError("Not all required capabilities were met "
                                        "by the remote server. Your version of UnrealIRCd "
                                        "is probably too old! (Got: %s, needed: %s)" %
                                        (sorted(self.caps.keys()),
                                         sorted(_neededCaps)))
            sdesc = args[-1].split(" ")
            # Get our protocol version :)
            vline = sdesc[0].split('-', 1)
            try:
                protover = int(vline[0].strip('U'))
            except ValueError:
                raise ProtocolError("Protocol version too old! (needs at least %s "
                                    "(Unreal 4.0.0-rc1), got something invalid; "
                                    "is VL being sent?)" % self.min_proto_ver)
            sdesc = args[-1][1:]
            if protover < self.min_proto_ver:
                raise ProtocolError("Protocol version too old! (needs at least %s "
                                    "(Unreal 4.0.0-rc1), got %s)" % (self.min_proto_ver, protover))
            self.irc.servers[numeric] = IrcServer(None, sname)
        else:
            # Legacy (non-SID) servers can still be introduced using the SERVER command.
            # <- :services.int SERVER a.bc 2 :(H) [GL] a
            servername = args[0].lower()
            sdesc = args[-1]
            self.irc.servers[servername] = IrcServer(numeric, servername, desc=sdesc)
            return {'name': servername, 'sid': None, 'text': sdesc}

    def handle_sid(self, numeric, command, args):
        """Handles the SID command, used for introducing remote servers by our uplink."""
        # <- SID services.int 2 00A :Shaltúre IRC Services
        sname = args[0].lower()
        sid = args[2]
        sdesc = args[-1]
        self.irc.servers[sid] = IrcServer(numeric, sname, desc=sdesc)
        return {'name': sname, 'sid': sid, 'text': sdesc}

    def handle_squit(self, numeric, command, args):
        """Handles the SQUIT command."""
        # <- SQUIT services.int :Read error
        # Convert the server name to a SID...
        args[0] = self._getSid(args[0])
        # Then, use the SQUIT handler in TS6BaseProtocol as usual.
        return super(UnrealProtocol, self).handle_squit(numeric, 'SQUIT', args)

    def handle_protoctl(self, numeric, command, args):
        # <- PROTOCTL NOQUIT NICKv2 SJOIN SJOIN2 UMODE2 VL SJ3 TKLEXT TKLEXT2 NICKIP ESVID
        # <- PROTOCTL CHANMODES=beI,k,l,psmntirzMQNRTOVKDdGPZSCc NICKCHARS= SID=001 MLOCK TS=1441314501 EXTSWHOIS
        for cap in args:
            if cap.startswith('SID'):
                self.irc.uplink = cap.split('=', 1)[1]
                self.caps['SID'] = True
            elif cap.startswith('CHANMODES'):
                cmodes = cap.split('=', 1)[1]
                self.irc.cmodes['*A'], self.irc.cmodes['*B'], self.irc.cmodes['*C'], self.irc.cmodes['*D'] = cmodes.split(',')
                for m in cmodes:
                    if m in self._unrealCmodes:
                        self.irc.cmodes[self._unrealCmodes[m]] = m
                self.caps['CHANMODES'] = True
                self.irc.cmodes['*B'] += 'f'  # Add +f to the list too, dunno why it isn't there.
            # Because more than one PROTOCTL line is sent, we have to delay the
            # check to see whether our needed capabilities are all there...
            # That's done by handle_server(), which comes right after PROTOCTL.
            elif cap == 'VL':
                self.caps['VL'] = True
            elif cap == 'NOQUIT':
                self.caps['NOQUIT'] = True
            elif cap == 'SJ3':
                self.caps['SJ3'] = True

    def _getNick(self, target):
        """Converts a nick argument to its matching UID. This differs from utils.nickToUid()
        in that it returns the original text instead of None, if no matching nick is found."""
        target = utils.nickToUid(self.irc, target) or target
        if target not in self.irc.users:
            log.warning("(%s) Possible desync? Got command target %s, who "
                        "isn't in our user list!", self.irc.name, target)
        return target

    def handle_events(self, data):
        """Event handler for the UnrealIRCd 3.4+ protocol.

        This passes most commands to the various handle_ABCD() functions
        elsewhere in this module, coersing various sender prefixes from nicks
        to UIDs wherever possible.

        Unreal 3.4's protocol operates similarly to TS6, where lines can have :
        indicating a long argument lasting to the end of the line. Not all commands
        send an explicit sender prefix, in which case, it will be set to the SID
        of the uplink server.
        """
        data = data.split(" ")
        try:  # Message starts with a SID/UID prefix.
            args = self.parseTS6Args(data)
            sender = args[0]
            command = args[1]
            args = args[2:]
            # If the sender isn't in UID format, try to convert it automatically.
            # Unreal's protocol isn't quite consistent with this yet!
            numeric = self._getSid(sender) or utils.nickToUid(self.irc, sender) or \
                sender
        # parseTS6Args() will raise IndexError if the TS6 sender prefix is missing.
        except IndexError:
            # Raw command without an explicit sender; assume it's being sent by our uplink.
            args = self.parseArgs(data)
            numeric = self.irc.uplink
            command = args[0]
            args = args[1:]
        try:
            func = getattr(self, 'handle_'+command.lower())
        except AttributeError:  # unhandled command
            pass
        else:
            parsed_args = func(numeric, command, args)
            if parsed_args is not None:
                return [numeric, command, parsed_args]

    def handle_privmsg(self, source, command, args):
        # Convert nicks to UIDs, where they exist.
        target = self._getNick(args[0])
        # We use lowercase channels internally, but uppercase UIDs.
        if utils.isChannel(target):
            target = utils.toLower(self.irc, target)
        return {'target': target, 'text': args[1]}
    handle_notice = handle_privmsg

    def handle_join(self, numeric, command, args):
        """Handles the UnrealIRCd JOIN command."""
        # <- :GL JOIN #pylink,#test
        for channel in args[0].split(','):
            c = self.irc.channels[channel]
            if args[0] == '0':
                # /join 0; part the user from all channels
                oldchans = self.irc.users[numeric].channels.copy()
                log.debug('(%s) Got /join 0 from %r, channel list is %r',
                          self.irc.name, numeric, oldchans)
                for ch in oldchans:
                    self.irc.channels[ch].users.discard(numeric)
                    self.irc.users[numeric].channels.discard(ch)
                return {'channels': oldchans, 'text': 'Left all channels.', 'parse_as': 'PART'}

            self.irc.users[numeric].channels.add(channel)
            self.irc.channels[channel].users.add(numeric)
            # Call hooks manually, because one JOIN command in UnrealIRCd can
            # have multiple channels...
            self.irc.callHooks([numeric, command, {'channel': channel, 'users': [numeric], 'modes':
                                                   c.modes, 'ts': c.ts}])

    def handle_sjoin(self, numeric, command, args):
        """Handles the UnrealIRCd SJOIN command."""
        # <- :001 SJOIN 1444361345 #endlessvoid :001DJ1O02
        # memberlist should be a list of UIDs with their channel status prefixes, as
        # in ":001AAAAAA @001AAAAAB +001AAAAAC".
        # Interestingly, no modes are ever sent in this command as far as I've seen.
        channel = utils.toLower(self.irc, args[1])
        userlist = args[-1].split()
        our_ts = self.irc.channels[channel].ts
        their_ts = int(args[0])
        if their_ts < our_ts:
            # Channel timestamp was reset on burst
            log.debug('(%s) Setting channel TS of %s to %s from %s',
                      self.irc.name, channel, their_ts, our_ts)
            self.irc.channels[channel].ts = their_ts
            self.irc.channels[channel].modes.clear()
            for p in self.irc.channels[channel].prefixmodes.values():
                p.clear()

        namelist = []
        log.debug('(%s) handle_sjoin: got userlist %r for %r', self.irc.name, userlist, channel)
        for userpair in userlist:
            r = re.search(r'([^\d]*)(.*)', userpair)
            user = r.group(2)
            modeprefix = r.group(1) or ''
            finalprefix = ''
            assert user, 'Failed to get the UID from %r; our regex needs updating?' % userpair
            log.debug('(%s) handle_sjoin: got modeprefix %r for user %r', self.irc.name, modeprefix, user)
            for m in modeprefix:
                # Iterate over the mapping of prefix chars to prefixes, and
                # find the characters that match.
                for char, prefix in self.irc.prefixmodes.items():
                    if m == prefix:
                        finalprefix += char
            namelist.append(user)
            self.irc.users[user].channels.add(channel)
            # Only merge the remote's prefix modes if their TS is smaller or equal to ours.
            if their_ts <= our_ts:
                utils.applyModes(self.irc, channel, [('+%s' % mode, user) for mode in finalprefix])
            self.irc.channels[channel].users.add(user)
        return {'channel': channel, 'users': namelist, 'modes': self.irc.channels[channel].modes, 'ts': their_ts}

    def handle_mode(self, numeric, command, args):
        # <- :unreal.midnight.vpn MODE #endlessvoid +bb test!*@* *!*@bad.net
        # <- :unreal.midnight.vpn MODE #endlessvoid +q GL 1444361345
        # <- :unreal.midnight.vpn MODE #endlessvoid +ntCo GL 1444361345
        # <- :unreal.midnight.vpn MODE #endlessvoid +mntClfo 5 [10t]:5  GL 1444361345
        # Well... this seems relatively inconsistent.
        # Why does only setting some modes show a TS?
        # Also, we need to get rid of that extra space following the +f argument. :|
        if utils.isChannel(args[0]):
            channel = utils.toLower(self.irc, args[0])
            oldobj = self.irc.channels[channel].deepcopy()
            modes = list(filter(None, args[1:]))
            parsedmodes = utils.parseModes(self.irc, channel, modes)
            if parsedmodes:
                utils.applyModes(self.irc, channel, parsedmodes)
            return {'target': channel, 'modes': parsedmodes, 'oldchan': oldobj}
        else:
            log.warning("(%s) received MODE for non-channel target: %r",
                        self.irc.name, args)

    def handle_umode2(self, numeric, command, args):
        """Handles UMODE2, used to set user modes on oneself."""
        parsedmodes = utils.parseModes(self.irc, numeric, args)
        utils.applyModes(self.irc, numeric, parsedmodes)
        return {'target': numeric, 'modes': parsedmodes}

    def handle_topic(self, numeric, command, args):
        """Handles the TOPIC command."""
        # <- GL TOPIC #services GL 1444699395 :weeee
        channel = utils.toLower(self.irc, args[0])
        topic = args[-1]
        ts = args[2]
        oldtopic = self.irc.channels[channel].topic
        self.irc.channels[channel].topic = topic
        self.irc.channels[channel].topicset = True
        return {'channel': channel, 'setter': numeric, 'ts': ts, 'topic': topic,
                'oldtopic': oldtopic}

Class = UnrealProtocol
