"""
hybrid.py: IRCD-Hybrid protocol module for PyLink.
"""

import time

from pylinkirc import conf
from pylinkirc.classes import *
from pylinkirc.log import log
from pylinkirc.protocols.ts6 import TS6Protocol

__all__ = ['HybridProtocol']


# This protocol module inherits from the TS6 protocol.
class HybridProtocol(TS6Protocol):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.casemapping = 'ascii'
        self.hook_map = {'EOB': 'ENDBURST', 'TBURST': 'TOPIC', 'SJOIN': 'JOIN'}
        self.protocol_caps -= {'slash-in-hosts'}

    def post_connect(self):
        """Initializes a connection to a server."""
        ts = self.start_ts
        f = self.send

        # https://github.com/grawity/irc-docs/blob/master/server/ts6.txt#L80
        # Note: according to hybrid source code, +p is paranoia, noknock,
        # AND rfc1459-style private, though the last isn't documented.
        cmodes = {
            # TS6 generic modes:
            'op': 'o', 'halfop': 'h', 'voice': 'v', 'ban': 'b', 'key': 'k',
            'limit': 'l', 'moderated': 'm', 'noextmsg': 'n',
            'secret': 's', 'topiclock': 't', 'private': 'p',
            # hybrid-specific modes:
            'blockcolor': 'c', 'inviteonly': 'i', 'noctcp': 'C',
            'regmoderated': 'M', 'operonly': 'O', 'regonly': 'R',
            'sslonly': 'S', 'banexception': 'e', 'noknock': 'p',
            'registered': 'r', 'invex': 'I', 'paranoia': 'p',
            'banexception': 'e',
            # Now, map all the ABCD type modes:
            '*A': 'beI', '*B': 'k', '*C': 'l', '*D': 'cimnprstCMORS'
        }

        self.cmodes = cmodes

        umodes = {
            'oper': 'o', 'invisible': 'i', 'wallops': 'w', 'locops': 'l',
            'cloak': 'x', 'hidechans': 'p', 'regdeaf': 'R', 'deaf': 'D',
            'callerid': 'g', 'admin': 'a', 'deaf_commonchan': 'G', 'hideoper': 'H',
            'webirc': 'W', 'sno_clientconnections': 'c', 'sno_badclientconnections': 'u',
            'sno_rejectedclients': 'j', 'sno_skill': 'k', 'sno_fullauthblock': 'f',
            'sno_remoteclientconnections': 'F', 'sno_stats': 'y', 'sno_debug': 'd',
            'sno_nickchange': 'n', 'hideidle': 'q', 'registered': 'r',
            'snomask': 's', 'ssl': 'S', 'sno_serverconnects': 'e', 'sno_botfloods': 'b',
            # Now, map all the ABCD type modes:
            '*A': '', '*B': '', '*C': '', '*D': 'DFGHRSWabcdefgijklnopqrsuwxy'
        }

        self.umodes = umodes
        self.extbans_matching.clear()

        # halfops is mandatory on Hybrid
        self.prefixmodes = {'o': '@', 'h': '%', 'v': '+'}

        # https://github.com/grawity/irc-docs/blob/master/server/ts6.txt#L55
        f('PASS %s TS 6 %s' % (self.serverdata["sendpass"], self.sid))

        # We request the following capabilities (for hybrid):

        # ENCAP: message encapsulation for certain commands
        # EX: Support for ban exemptions (+e)
        # IE: Support for invite exemptions (+e)
        # CHW: Allow sending messages to @#channel and the like.
        # KNOCK: Support for /knock
        # SVS: Deal with extended NICK/UID messages that contain service IDs/stamps
        # TBURST: Topic Burst command; we send this in topic_burst
        # DLN: DLINE command
        # UNDLN: UNDLINE command
        # KLN: KLINE command
        # UNKLN: UNKLINE command
        # HOPS: Supports HALFOPS
        # CHW: Can do channel wall (@#)
        # CLUSTER: Supports server clustering
        # EOB: Supports EOB (end of burst) command
        f('CAPAB :TBURST DLN KNOCK UNDLN UNKLN KLN ENCAP IE EX HOPS CHW SVS CLUSTER EOB QS')

        f('SERVER %s 0 :%s' % (self.serverdata["hostname"],
                               self.serverdata.get('serverdesc') or conf.conf['pylink']['serverdesc']))

        # send endburst now
        self.send(':%s EOB' % (self.sid,))

    def spawn_client(self, nick, ident='null', host='null', realhost=None, modes=set(),
            server=None, ip='0.0.0.0', realname=None, ts=None, opertype=None,
            manipulatable=False):
        """
        Spawns a new client with the given options.

        Note: No nick collision / valid nickname checks are done here; it is
        up to plugins to make sure they don't introduce anything invalid.
        """

        server = server or self.sid
        if not self.is_internal_server(server):
            raise ValueError('Server %r is not a PyLink server!' % server)

        uid = self.uidgen[server].next_uid()

        ts = ts or int(time.time())
        realname = realname or conf.conf['pylink']['realname']
        realhost = realhost or host
        raw_modes = self.join_modes(modes)

        u = self.users[uid] = User(self, nick, ts, uid, server, ident=ident, host=host, realname=realname,
            realhost=realhost, ip=ip, manipulatable=manipulatable)

        self.apply_modes(uid, modes)
        self.servers[server].users.add(uid)

        self._send_with_prefix(server, "UID {nick} {hopcount} {ts} {modes} {ident} {host} {ip} {uid} "
                "* :{realname}".format(ts=ts, host=host,
                nick=nick, ident=ident, uid=uid,
                modes=raw_modes, ip=ip, realname=realname,
                hopcount=self.servers[server].hopcount))
        return u

    def update_client(self, target, field, text):
        """Updates the ident, host, or realname of a PyLink client."""
        # https://github.com/ircd-hybrid/ircd-hybrid/blob/58323b8/modules/m_svsmode.c#L40-L103
        # parv[0] = command
        # parv[1] = nickname <-- UID works too -jlu5
        # parv[2] = TS <-- Of the user, not the current time. -jlu5
        # parv[3] = mode
        # parv[4] = optional argument (services account, vhost)
        field = field.upper()

        ts = self.users[target].ts

        if field == 'HOST':
            self.users[target].host = text
            # On Hybrid, it appears that host changing is actually just forcing umode
            # "+x <hostname>" on the target. -jlu5
            self._send_with_prefix(self.sid, 'SVSMODE %s %s +x %s' % (target, ts, text))
        else:
            raise NotImplementedError("Changing field %r of a client is unsupported by this protocol." % field)

    def oper_notice(self, source, text):
        """
        Send a message to all opers.
        """
        self._send_with_prefix(source, 'GLOBOPS :%s' % text)

    def set_server_ban(self, source, duration, user='*', host='*', reason='User banned'):
        """
        Sets a server ban.
        """
        # source: user
        # parameters: target server mask, duration, user mask, host mask, reason
        assert not (user == host == '*'), "Refusing to set ridiculous ban on *@*"

        if not source in self.users:
            log.debug('(%s) Forcing KLINE sender to %s as TS6 does not allow KLINEs from servers', self.name, self.pseudoclient.uid)
            source = self.pseudoclient.uid

        self._send_with_prefix(source, 'KLINE * %s %s %s :%s' % (duration, user, host, reason))

    def topic_burst(self, numeric, target, text):
        """Sends a topic change from a PyLink server. This is usually used on burst."""
        # <- :0UY TBURST 1459308205 #testchan 1459309379 dan!~d@localhost :sdf
        if not self.is_internal_server(numeric):
            raise LookupError('No such PyLink server exists.')

        ts = self._channels[target].ts
        servername = self.servers[numeric].name

        self._send_with_prefix(numeric, 'TBURST %s %s %s %s :%s' % (ts, target, int(time.time()), servername, text))
        self._channels[target].topic = text
        self._channels[target].topicset = True

    # command handlers

    def handle_capab(self, numeric, command, args):
        # We only get a list of keywords here. Hybrid obviously assumes that
        # we know what modes it supports (indeed, this is a standard list).
        # <- CAPAB :UNDLN UNKLN KLN TBURST KNOCK ENCAP DLN IE EX HOPS CHW SVS CLUSTER EOB QS
        self._caps = caps = args[0].split()
        for required_cap in ('SVS', 'EOB', 'HOPS', 'QS', 'TBURST'):
             if required_cap not in caps:
                 raise ProtocolError('%s not found in TS6 capabilities list; this is required! (got %r)' % (required_cap, caps))

    def handle_uid(self, numeric, command, args):
        """
        Handles Hybrid-style UID commands (user introduction). This is INCOMPATIBLE
        with standard TS6 implementations, as the arguments are slightly different.
        """
        # <- :0UY UID dan 1 1451041551 +Facdeiklosuw ~ident localhost 127.0.0.1 0UYAAAAAB * :realname
        nick = args[0]
        self._check_nick_collision(nick)
        ts, modes, ident, host, ip, uid, account, realname = args[2:10]
        ts = int(ts)
        if account == '*':
            account = None
        log.debug('(%s) handle_uid: got args nick=%s ts=%s uid=%s ident=%s '
                  'host=%s realname=%s ip=%s', self.name, nick, ts, uid,
                  ident, host, realname, ip)

        self.users[uid] = User(self, nick, ts, uid, numeric, ident, host, realname, host, ip)

        parsedmodes = self.parse_modes(uid, [modes])
        log.debug('(%s) handle_uid: Applying modes %s for %s', self.name, parsedmodes, uid)
        self.apply_modes(uid, parsedmodes)
        self.servers[numeric].users.add(uid)

        # Call the OPERED UP hook if +o is being added to the mode list.
        self._check_oper_status_change(uid, parsedmodes)

        # Track SSL/TLS status
        has_ssl = self.users[uid].ssl = ('+S', None) in parsedmodes

        # Set the account name if present
        if account:
            self.call_hooks([uid, 'CLIENT_SERVICES_LOGIN', {'text': account}])

        return {'uid': uid, 'ts': ts, 'nick': nick, 'realname': realname, 'host': host, 'ident': ident, 'ip': ip, 'secure': has_ssl}

    def handle_tburst(self, numeric, command, args):
        """Handles incoming topic burst (TBURST) commands."""
        # <- :0UY TBURST 1459308205 #testchan 1459309379 dan!~d@localhost :sdf
        channel = args[1]
        ts = args[2]
        setter = args[3]
        topic = args[-1]
        self._channels[channel].topic = topic
        self._channels[channel].topicset = True
        return {'channel': channel, 'setter': setter, 'ts': ts, 'text': topic}

    def handle_eob(self, numeric, command, args):
        """EOB (end-of-burst) handler."""
        log.debug('(%s) end of burst received from %s', self.name, numeric)
        if not self.servers[numeric].has_eob:
            # Don't fight with TS6's generic PING-as-EOB
            self.servers[numeric].has_eob = True

            if numeric == self.uplink:
                self.connected.set()
            return {}

    def handle_svsmode(self, numeric, command, args):
        """
        Handles SVSMODE, which is used for sending services metadata
        (vhosts, account logins), and other forced usermode changes.
        """

        target = args[0]
        ts = args[1]
        modes = args[2:]
        parsedmodes = self.parse_modes(target, modes)

        for modepair in parsedmodes:
            if modepair[0] == '+d':
                # Login sequence (tested with Anope 2.0.4-git):
                # A mode change +d accountname is used to propagate logins,
                # before setting umode +r on the target.
                # <- :5ANAAAAAG SVSMODE 5HYAAAAAA 1460175209 +d jlu5
                # <- :5ANAAAAAG SVSMODE 5HYAAAAAA 1460175209 +r

                # Logout sequence:
                # <- :5ANAAAAAG SVSMODE 5HYAAAAAA 1460175209 +d *
                # <- :5ANAAAAAG SVSMODE 5HYAAAAAA 1460175209 -r

                account = args[-1]
                if account == '*':
                    account = ''  # Logout

                # Send the login hook, and remove this mode from the mode
                # list, as it shouldn't be parsed literally.
                self.call_hooks([target, 'CLIENT_SERVICES_LOGIN', {'text': account}])
                parsedmodes.remove(modepair)

            elif modepair[0] == '+x':
                # SVSMODE is also used to set cloaks on Hybrid.
                # "SVSMODE 001TARGET +x some.host" would change 001TARGET's host
                # to some.host, for example.
                host = args[-1]

                self.users[target].host = host

                # Propagate the hostmask change as a hook.
                self.call_hooks([numeric, 'CHGHOST',
                                 {'target': target, 'newhost': host}])

                parsedmodes.remove(modepair)

        if parsedmodes:
            self.apply_modes(target, parsedmodes)

        return {'target': target, 'modes': parsedmodes}

Class = HybridProtocol
