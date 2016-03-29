import time
import sys
import os
import re

curdir = os.path.dirname(__file__)
sys.path += [curdir, os.path.dirname(curdir)]
import utils
from log import log

from classes import *
from ts6_common import TS6BaseProtocol

class HybridProtocol(TS6BaseProtocol):
    def __init__(self, irc):
        super(HybridProtocol, self).__init__(irc)
        self.casemapping = 'ascii'
        self.sidgen = utils.TS6SIDGenerator(self.irc)
        self.uidgen = {}

        self.caps = {}
        # halfops is mandatory on Hybrid
        self.irc.prefixmodes = {'o': '@', 'h': '%', 'v': '+'}

        self.hook_map = {'EOB': 'ENDBURST'}

    def connect(self):
        """Initializes a connection to a server."""
        ts = self.irc.start_ts

        f = self.irc.send
        # Valid keywords (from mostly InspIRCd's named modes):
        # admin allowinvite autoop ban banexception blockcolor
        # c_registered exemptchanops filter forward flood halfop history invex
        # inviteonly joinflood key kicknorejoin limit moderated nickflood
        # noctcp noextmsg nokick noknock nonick nonotice official-join op
        # operonly opmoderated owner permanent private redirect regonly
        # regmoderated secret sslonly stripcolor topiclock voice

        # https://github.com/grawity/irc-docs/blob/master/server/ts6.txt#L80
        cmodes = {
            # TS6 generic modes:
            'op': 'o', 'voice': 'v', 'ban': 'b', 'key': 'k', 'limit':
            'l', 'moderated': 'm', 'noextmsg': 'n',
            'secret': 's', 'topiclock': 't',
            # hybrid-specific modes:
            'blockcolor': 'c', 'inviteonly': 'i', 'noctcp': 'C',
            'regmoderated': 'M', 'operonly': 'O', 'regonly': 'R',
            'sslonly': 'S', 'banexception': 'e', 'paranoia': 'p',
            'registered': 'r', 'invex': 'I',
            # Now, map all the ABCD type modes:
            '*A': 'beI', '*B': 'k', '*C': 'l', '*D': 'cimnprstCMORS'
        }

        self.irc.cmodes.update(cmodes)

        # Same thing with umodes:
        # bot callerid cloak deaf_commonchan helpop hidechans hideoper invisible oper
        # regdeaf servprotect showwhois snomask u_registered u_stripcolor wallops
        umodes = {
            'oper': 'o', 'invisible': 'i', 'wallops': 'w', 'chary_locops': 'l',
            'cloak': 'x', 'hidechans': 'p', 'regdeaf': 'R', 'deaf': 'D',
            'callerid': 'g', 'showadmin': 'a', 'softcallerid': 'G', 'hideops': 'H',
            'webirc': 'W', 'client_connections': 'c', 'bad_client_connections': 'u',
            'rejected_clients': 'j', 'skill_notices': 'k', 'fullauthblock': 'f',
            'remote_client_connections': 'F', 'admin_requests': 'y', 'debug': 'd',
            'nickchange_notices': 'n', 'hideidle': 'q', 'registered': 'r',
            'smessages': 's', 'ssl': 'S', 'sjoins': 'e', 'botfloods': 'b',
            # Now, map all the ABCD type modes:
            '*A': '', '*B': '', '*C': '', '*D': 'oiwlxpRDg'
        }

        self.irc.umodes.update(umodes)

        # https://github.com/grawity/irc-docs/blob/master/server/ts6.txt#L55
        f('PASS %s TS 6 %s' % (self.irc.serverdata["sendpass"], self.irc.sid))

        # We request the following capabilities (for hybrid):

        # ENCAP: message encapsulation for certain commands
        # EX: Support for ban exemptions (+e)
        # IE: Support for invite exemptions (+e)
        # CHW: Allow sending messages to @#channel and the like.
        # KNOCK: Support for /knock
        # SVS: Deal with extended NICK/UID messages that contain service IDs/stamps
        # TBURST: Topic Burst command; we send this in topicServer
        # DLN: DLINE command
        # UNDLN: UNDLINE command
        # KLN: KLINE command
        # UNKLN: UNKLINE command
        # HOPS: Supports HALFOPS
        # CHW: Can do channel wall (@#)
        # CLUSTER: Supports server clustering
        # EOB: Supports EOB (end of burst) command
        f('CAPAB :TBURST DLN KNOCK UNDLN UNKLN KLN ENCAP IE EX HOPS CHW SVS CLUSTER EOB QS')

        f('SERVER %s 0 :%s' % (self.irc.serverdata["hostname"],
                               self.irc.serverdata.get('serverdesc') or self.irc.botdata['serverdesc']))

    def spawnClient(self, nick, ident='null', host='null', realhost=None, modes=set(),
            server=None, ip='0.0.0.0', realname=None, ts=None, opertype=None,
            manipulatable=False):
        """Spawns a client with nick <nick> on the given IRC connection.

        Note: No nick collision / valid nickname checks are done here; it is
        up to plugins to make sure they don't introduce anything invalid."""
        server = server or self.irc.sid
        if not self.irc.isInternalServer(server):
            raise ValueError('Server %r is not a PyLink internal PseudoServer!' % server)
        # Create an UIDGenerator instance for every SID, so that each gets
        # distinct values.
        uid = self.uidgen.setdefault(server, utils.TS6UIDGenerator(server)).next_uid()
        # EUID:
        # parameters: nickname, hopcount, nickTS, umodes, username,
        # visible hostname, IP address, UID, real hostname, account name, gecos
        ts = ts or int(time.time())
        realname = realname or self.irc.botdata['realname']
        realhost = realhost or host
        raw_modes = utils.joinModes(modes)
        u = self.irc.users[uid] = IrcUser(nick, ts, uid, ident=ident, host=host, realname=realname,
            realhost=realhost, ip=ip, manipulatable=manipulatable)
        utils.applyModes(self.irc, uid, modes)
        self.irc.servers[server].users.add(uid)
        self._send(server, "UID {nick} 1 {ts} {modes} {ident} {host} {ip} {uid} "
                "* :{realname}".format(ts=ts, host=host,
                nick=nick, ident=ident, uid=uid,
                modes=raw_modes, ip=ip, realname=realname))
        return u

    def updateClient(self, numeric, field, text):
        """Updates the ident, host, or realname of a PyLink client."""
        field = field.upper()
        if field == 'IDENT':
            self.irc.users[numeric].ident = text
            self._send(numeric, 'SETIDENT %s' % text)
        elif field == 'HOST':
            self.irc.users[numeric].host = text
            self._send(numeric, 'SETHOST %s' % text)
        elif field in ('REALNAME', 'GECOS'):
            self.irc.users[numeric].realname = text
            self._send(numeric, 'SETNAME :%s' % text)
        else:
            raise NotImplementedError("Changing field %r of a client is unsupported by this protocol." % field)

    def join(self, client, channel):
        """Joins a PyLink client to a channel."""
        channel = utils.toLower(self.irc, channel)
        if not self.irc.isInternalClient(client):
            raise LookupError('No such PyLink client exists.')
        self._send(client, "JOIN 0 %s +" % channel)
        self.irc.channels[channel].users.add(client)
        self.irc.users[client].channels.add(channel)

    def ping(self, source=None, target=None):
        """Sends a PING to a target server. Periodic PINGs are sent to our uplink
        automatically by the Irc() internals; plugins shouldn't have to use this."""
        source = source or self.irc.sid
        target = target or self.irc.uplink
        if not (target is None or source is None):
            self._send(source, 'PING :%s' % (source,))

    def handle_events(self, data):
        """Event handler for the Hybrid protocol.

        This passes most commands to the various handle_ABCD() functions
        elsewhere in this module, coersing various sender prefixes from nicks
        to UIDs wherever possible.
        """
        data = data.split(" ")
        if not data:
            # No data??
            return
        try:  # Message starts with a SID/UID prefix.
            args = self.parseTS6Args(data)
            sender = args[0]
            command = args[1]
            args = args[2:]
            # If the sender isn't in UID format, try to convert it automatically
            sender_server = self._getSid(sender)
            if sender_server in self.irc.servers:
                # Sender is a server when converted from name to SID.
                numeric = sender_server
            else:
                # Sender is a user.
                numeric = self._getNick(sender)
        # parseTS6Args() will raise IndexError if the TS6 sender prefix is missing.
        except IndexError:
            # Raw command without an explicit sender; assume it's being sent by our uplink.
            args = self.parseArgs(data)
            numeric = self.irc.uplink
            command = args[0]
            args = args[1:]
        try:
            command = self.hook_map.get(command.upper(), command).lower()
            func = getattr(self, 'handle_'+command.lower())
        except AttributeError:  # unhandled command
            # self._send(self.irc.sid, 'ERROR', 'Unknown Command')
            print('Unknown command.\nOffending line: {}'.format(data))
            exit(1)
        else:
            log.debug('(%s) Handling event %s - %s - %s', self.irc.name, numeric, command, str(args))
            parsed_args = func(numeric, command, args)
            if parsed_args is not None:
                return [numeric, command, parsed_args]

    # command handlers
    def handle_pass(self, numeric, command, args):
        # <- PASS $somepassword TS 6 42X
        if args[0] != self.irc.serverdata['recvpass']:
            raise ProtocolError("Error: RECVPASS from uplink does not match configuration!")
        ver = args[args.index('TS') + 1]
        if ver != '6':
            raise ProtocolError("Remote protocol version {} is too old! Is this even TS6?".format())
        numeric = args[3]
        log.debug('(%s) Found uplink SID as %r', self.irc.name, numeric)
        self.irc.servers[numeric] = IrcServer(None, 'unknown')
        self.irc.uplink = numeric

    def handle_capab(self, numeric, command, args):
        # We only get a list of keywords here. Charybdis obviously assumes that
        # we know what modes it supports (indeed, this is a standard list).
        # <- CAPAB :BAN CHW CLUSTER ENCAP EOPMOD EUID EX IE KLN KNOCK MLOCK QS RSFNC SAVE SERVICES TB UNKLN
        self.irc.caps = caps = args[0].split()
        # for required_cap in ('EUID', 'SAVE', 'TB', 'ENCAP', 'QS'):
        #     if required_cap not in caps:
        #         raise ProtocolError('%s not found in TS6 capabilities list; this is required! (got %r)' % (required_cap, caps))

        log.debug('(%s) self.irc.connected set!', self.irc.name)
        self.irc.connected.set()

    def handle_server(self, numeric, command, args):
        # <- SERVER charybdis.midnight.vpn 1 :charybdis test server
        sname = args[0].lower()
        log.debug('(%s) Found uplink server name as %r', self.irc.name, sname)
        self.irc.servers[self.irc.uplink].name = sname
        self.irc.servers[self.irc.uplink].desc = args[2]
        # According to the TS6 protocol documentation, we should send SVINFO
        # when we get our uplink's SERVER command.
        self.irc.send('SVINFO 6 6 0 :%s' % int(time.time()))

    def handle_uid(self, numeric, command, args):
        """Handles incoming UID commands (user introduction)."""
        # <- :0UY UID dan 1 1451041551 +Facdeiklosuw ~ident localhost 127.0.0.1 0UYAAAAAB * :realname
        nick = args[0]
        ts, modes, ident, host, ip, uid, account, realname = args[2:10]
        if account == '*':
            account = None
        log.debug('(%s) handle_uid got args: nick=%s ts=%s uid=%s ident=%s '
                  'host=%s realname=%s ip=%s', self.irc.name, nick, ts, uid,
                  ident, host, realname, ip)

        self.irc.users[uid] = IrcUser(nick, ts, uid, ident, host, realname, realname, ip)
        parsedmodes = utils.parseModes(self.irc, uid, [modes])
        log.debug('Applying modes %s for %s', parsedmodes, uid)
        utils.applyModes(self.irc, uid, parsedmodes)
        self.irc.servers[numeric].users.add(uid)
        # Call the OPERED UP hook if +o is being added to the mode list.
        if ('+o', None) in parsedmodes:
            self.irc.callHooks([uid, 'CLIENT_OPERED', {'text': 'IRC_Operator'}])
        return {'uid': uid, 'ts': ts, 'nick': nick, 'realname': realname, 'host': host, 'ident': ident, 'ip': ip}

    def handle_svstag(self, numeric, command, args):
        tag = args[2]
        if tag in ['313']:
            return
        raise Exception('COULD NOT PARSE SVSTAG: {} {} {}'.format(numeric, command, args))

    def handle_join(self, numeric, command, args):
        """Handles incoming channel JOINs."""
        # parameters: channelTS, channel, '+' (a plus sign)
        # <- :0UYAAAAAF JOIN 0 #channel +
        ts = int(args[0])
        uid = numeric
        channel = args[1]
        if channel == '0':
            # /join 0; part the user from all channels
            oldchans = self.irc.users[uid].channels.copy()
            log.debug('(%s) Got /join 0 from %r, channel list is %r',
                      self.irc.name, uid, oldchans)
            for channel in oldchans:
                self.irc.channels[channel].users.discard(uid)
                self.irc.users[uid].channels.discard(channel)
        else:
            channel = utils.toLower(self.irc, args[1])
            self.updateTS(channel, ts)
        parsedmodes = utils.parseModes(self.irc, channel, [args[2]])
        utils.applyModes(self.irc, channel, parsedmodes)
        return {'channel': channel, 'users': [uid], 'modes':
                self.irc.channels[channel].modes, 'ts': ts}

    def handle_sjoin(self, numeric, command, args):
        """Handles incoming channel SJOINs."""
        # parameters: channelTS, channel, modes, prefixed uids
        # <- :0UY SJOIN 1451041566 #channel +nt :@0UYAAAAAB
        ts = int(args[0])
        uids = args[3].split()
        users = {}
        umodes = ['+']
        modeprefixes = {v: k for k, v in self.irc.prefixmodes.items()}
        for uid in uids:
            modes = ''
            while uid and uid[0] in modeprefixes:
                modes += uid[0]
                uid = uid[1:]
            for mode in modes:
                umodes[0] += modeprefixes[mode]
                umodes.append(uid)
        if args[1] == '0':
            # /join 0; part the user from all channels
            for uid in users:
                oldchans = self.irc.users[uid].channels.copy()
                log.debug('(%s) Got /join 0 from %r, channel list is %r',
                          self.irc.name, uid, oldchans)
                for channel in oldchans:
                    self.irc.channels[channel].users.discard(uid)
                    self.irc.users[uid].channels.discard(channel)
            # return {'channels': oldchans, 'text': 'Left all channels.', 'parse_as': 'PART'}
        else:
            channel = utils.toLower(self.irc, args[1])
            self.updateTS(channel, ts)
        parsedmodes = utils.parseModes(self.irc, channel, [args[2]])
        utils.applyModes(self.irc, channel, parsedmodes)
        parsedmodes = utils.parseModes(self.irc, channel, umodes)
        utils.applyModes(self.irc, channel, parsedmodes)
        # We send users and modes here because SJOIN and JOIN both use one hook,
        # for simplicity's sake (with plugins).
        return {'channel': channel, 'users': uids, 'modes':
                self.irc.channels[channel].modes, 'ts': ts}

    def handle_ping(self, source, command, args):
        """Handles incoming PING commands."""
        # PING:
        # source: any
        # parameters: origin, opt. destination server
        # PONG:
        # source: server
        # parameters: origin, destination

        # Sends a PING to the destination server, which will reply with a PONG. If the
        # destination server parameter is not present, the server receiving the message
        # must reply.
        try:
            destination = args[1]
        except IndexError:
            destination = self.irc.sid
        if self.irc.isInternalServer(destination):
            self._send(destination, 'PONG %s :%s' % (self.irc.servers[destination].name, source))

    def handle_pong(self, source, command, args):
        """Handles incoming PONG commands."""
        log.debug('(%s) Ping received from %s for %s.', self.irc.name, source, args[1])
        if source == self.irc.uplink and args[1] == self.irc.sid:
            log.debug('(%s) Set self.irc.lastping.', self.irc.name)
            self.irc.lastping = time.time()

    # empty handlers
    # TODO: there's a better way to do this
    def handle_svinfo(self, numeric, command, args):
        pass

    def handle_endburst(self, numeric, command, args):
        self.irc.send(':%s EOB' % (self.irc.sid,))
        pass

Class = HybridProtocol
