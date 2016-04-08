import time
import sys
import os
import re

curdir = os.path.dirname(__file__)
sys.path += [curdir, os.path.dirname(curdir)]
import utils
from log import log

from classes import *
from ts6 import TS6Protocol

class HybridProtocol(TS6Protocol):
    def __init__(self, irc):
        # This protocol module inherits from the TS6 protocol.
        super().__init__(irc)

        self.casemapping = 'ascii'
        self.caps = {}
        self.hook_map = {'EOB': 'ENDBURST', 'TBURST': 'TOPIC'}

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
            'op': 'o', 'halfop': 'h', 'voice': 'v', 'ban': 'b', 'key': 'k',
            'limit': 'l', 'moderated': 'm', 'noextmsg': 'n',
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

        # halfops is mandatory on Hybrid
        self.irc.prefixmodes = {'o': '@', 'h': '%', 'v': '+'}

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

        # send endburst now
        self.irc.send(':%s EOB' % (self.irc.sid,))

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

    # command handlers

    def handle_capab(self, numeric, command, args):
        # We only get a list of keywords here. Hybrid obviously assumes that
        # we know what modes it supports (indeed, this is a standard list).
        # <- CAPAB :BAN CHW CLUSTER ENCAP EOPMOD EUID EX IE KLN KNOCK MLOCK QS RSFNC SAVE SERVICES TB UNKLN
        self.irc.caps = caps = args[0].split()
        # for required_cap in ('EUID', 'SAVE', 'TB', 'ENCAP', 'QS'):
        #     if required_cap not in caps:
        #         raise ProtocolError('%s not found in TS6 capabilities list; this is required! (got %r)' % (required_cap, caps))

        log.debug('(%s) self.irc.connected set!', self.irc.name)
        self.irc.connected.set()

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

    def handle_tburst(self, numeric, command, args):
        """Handles incoming topic burst (TBURST) commands."""
        # <- :0UY TBURST 1459308205 #testchan 1459309379 dan!~d@localhost :sdf
        channel = args[1].lower()
        ts = args[2]
        setter = args[3]
        topic = args[-1]
        self.irc.channels[channel].topic = topic
        self.irc.channels[channel].topicset = True
        return {'channel': channel, 'setter': setter, 'ts': ts, 'text': topic}

    def handle_svstag(self, numeric, command, args):
        tag = args[2]
        if tag in ['313']:
            return
        raise Exception('COULD NOT PARSE SVSTAG: {} {} {}'.format(numeric, command, args))

    def handle_endburst(self, numeric, command, args):
        log.debug('(%s) end of burst received', self.irc.name)
        return {}


Class = HybridProtocol
