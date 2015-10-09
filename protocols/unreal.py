import time
import sys
import os
import time
import ipaddress

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
        self.proto_ver = 2351
        self.hook_map = {}
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
                         'I': 'invex', 't': 'topiclock'}
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
        # Now, we wait until remote sends its NETINFO command (handle_netinfo),
        # so we can find and use a matching netname, preventing netname mismatch
        # errors.

    def handle_netinfo(self, numeric, command, args):
        # <- NETINFO maxglobal currenttime protocolversion cloakhash 0 0 0 :networkname
        # "maxglobal" is the amount of maximum global users we've seen so far.
        # We'll just set it to 1 (the PyLink client), since this is completely
        # arbitrary.
        self.irc.send('NETINFO 1 %s %s * 0 0 0 :%s' % (self.irc.start_ts, self.proto_ver, args[-1]))
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
        # <- SERVER unreal.midnight.vpn 1 :U2351-Fhin6OoEM UnrealIRCd test server
        sname = args[0]
        # TODO: handle introductions for other servers
        if numeric == self.irc.uplink:
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
                raise ProtocolError("Protocol version too old! (needs at least 2351 "
                                    "(Unreal 3.4-beta1/2), got something invalid; "
                                    "is VL being sent?)")
            sdesc = args[-1][1:]
            if protover < 2351:
                raise ProtocolError("Protocol version too old! (needs at least 2351 "
                                    "(Unreal 3.4-beta1/2), got %s)" % protover)
            self.irc.servers[numeric] = IrcServer(None, sname)
        else:
            raise NotImplementedError

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
            # Because more than one PROTOCTL line is sent, we have to delay the
            # check to see whether our needed capabilities are all there...
            # That's done by handle_server(), which comes right after PROTOCTL.
            elif cap == 'VL':
                self.caps['VL'] = True
            elif cap == 'NOQUIT':
                self.caps['NOQUIT'] = True
            elif cap == 'SJ3':
                self.caps['SJ3'] = True

    def _sidToServer(self, sname):
        """Returns the SID of a server with the given name, if present."""
        nick = sname.lower()
        for k, v in self.irc.servers.items():
            if v.name.lower() == nick:
                return k

    def _convertNick(self, target):
        """Converts a nick argument to its matching UID."""
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
            numeric = self._sidToServer(sender) or utils.nickToUid(self.irc, sender) or \
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
        target = self._convertNick(args[0])
        # We use lowercase channels internally, but uppercase UIDs.
        if utils.isChannel(target):
            target = utils.toLower(self.irc, target)
        return {'target': target, 'text': args[1]}
    handle_notice = handle_privmsg

    def handle_join(self, numeric, command, args):
        # <- GL JOIN #pylink,#test
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
            # Call hooks manually, because one JOIN command in UnrealIRCd can
            # have multiple channels...
            self.irc.callHooks([numeric, command, {'channel': channel, 'users': [numeric], 'modes':
                                              c.modes, 'ts': c.ts}])

Class = UnrealProtocol
