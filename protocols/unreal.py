import time
import sys
import os
import time
import ipaddress

curdir = os.path.dirname(__file__)
sys.path += [curdir, os.path.dirname(curdir)]
import utils
from log import log
from ts6_common import parseArgs, removeClient, _send, messageClient, noticeClient
from ts6_common import handle_quit, handle_part, handle_nick, handle_kill
from classes import *

casemapping = 'ascii'
proto_ver = 2351

hook_map = {}

### OUTGOING COMMAND FUNCTIONS

def spawnClient(irc, nick, ident='null', host='null', realhost=None, modes=set(),
        server=None, ip='0.0.0.0', realname=None, ts=None, opertype=None):
    server = server or irc.sid
    if not utils.isInternalServer(irc, server):
        raise ValueError('Server %r is not a PyLink internal PseudoServer!' % server)
    # Unreal 3.4 uses TS6-style UIDs. They don't start from AAAAAA like other IRCd's
    # do, but we can do that fine...
    if server not in irc.uidgen:
        irc.uidgen[server] = utils.TS6UIDGenerator(server)
    uid = irc.uidgen[server].next_uid()
    ts = ts or int(time.time())
    realname = realname or irc.botdata['realname']
    realhost = realhost or host
    raw_modes = utils.joinModes(modes)
    u = irc.users[uid] = IrcUser(nick, ts, uid, ident=ident, host=host, realname=realname,
        realhost=realhost, ip=ip)
    utils.applyModes(irc, uid, modes)
    irc.servers[server].users.add(uid)
    # <- :001 UID GL 0 1441306929 gl localhost 0018S7901 0 +iowx * midnight-1C620195 fwAAAQ== :realname
    _send(irc, server, "UID {nick} 0 {ts} {ident} {realhost} {uid} 0 {modes} "
                       "* {host} * :{realname}".format(ts=ts, host=host,
                            nick=nick, ident=ident, uid=uid,
                            modes=raw_modes, realname=realname,
                            realhost=realhost))
    return u

def joinClient(irc, client, channel):
    pass

def pingServer(irc, source=None, target=None):
    source = source or irc.sid
    target = target or irc.uplink
    if not (target is None or source is None):
        _send(irc, source, 'PING %s %s' % (irc.servers[source].name, irc.servers[target].name))

### HANDLERS

def connect(irc):
    ts = irc.start_ts
    irc.caps = []

    f = irc.send
    host = irc.serverdata["hostname"]
    f('PASS :%s' % irc.serverdata["sendpass"])
    # https://github.com/unrealircd/unrealircd/blob/2f8cb55e/doc/technical/protoctl.txt
    # We support the following protocol features:
    # SJ3 - extended SJOIN
    # NOQUIT - QUIT messages aren't sent for all users in a netsplit
    # NICKv2 - Extended NICK command, sending MODE and CHGHOST info with it
    # SID - Use UIDs and SIDs (unreal 3.4)
    # VL - Sends version string in below SERVER message
    # UMODE2 - used for users setting modes on themselves (one less argument needed)
    # EAUTH - Early auth? (Unreal 3.4 linking protocol)
    # ~~NICKIP - sends the IP in the NICK/UID command~~ Doesn't work with SID/UID support
    f('PROTOCTL SJ3 NOQUIT NICKv2 VL UMODE2 PROTOCTL EAUTH=%s SID=%s' % (irc.serverdata["hostname"], irc.sid))
    sdesc = irc.serverdata.get('serverdesc') or irc.botdata['serverdesc']
    f('SERVER %s 1 U%s-h6e-%s :%s' % (host, proto_ver, irc.sid, sdesc))
    # Now, we wait until remote sends its NETINFO command (handle_netinfo),
    # so we can find and use a matching netname, preventing netname mismatch
    # errors.

def handle_netinfo(irc, numeric, command, args):
    # <- NETINFO maxglobal currenttime protocolversion cloakhash 0 0 0 :networkname
    # "maxglobal" is the amount of maximum global users we've seen so far.
    # We'll just set it to 1 (the PyLink client), since this is completely
    # arbitrary.
    irc.send('NETINFO 1 %s %s * 0 0 0 :%s' % (irc.start_ts, proto_ver, args[-1]))
    _send(irc, irc.sid, 'EOS')

def handle_uid(irc, numeric, command, args):
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
    irc.users[uid] = IrcUser(nick, ts, uid, ident, host, realname, realhost, ip)
    parsedmodes = utils.parseModes(irc, uid, [modestring])
    utils.applyModes(irc, uid, parsedmodes)
    irc.servers[numeric].users.add(uid)
    return {'uid': uid, 'ts': ts, 'nick': nick, 'realhost': realhost, 'host': host, 'ident': ident, 'ip': ip}

def handle_pass(irc, numeric, command, args):
    # <- PASS :abcdefg
    if args[0] != irc.serverdata['recvpass']:
        raise ProtocolError("Error: RECVPASS from uplink does not match configuration!")

def handle_ping(irc, numeric, command, args):
    if numeric == irc.uplink:
        irc.send('PONG %s :%s' % (irc.serverdata['hostname'], args[-1]))

def handle_pong(irc, source, command, args):
    log.debug('(%s) Ping received from %s for %s.', irc.name, source, args[-1])
    if source in (irc.uplink, irc.servers[irc.uplink].name) and args[-1] == irc.serverdata['hostname']:
        log.debug('(%s) Set irc.lastping.', irc.name)
        irc.lastping = time.time()

def handle_server(irc, numeric, command, args):
    # <- SERVER unreal.midnight.vpn 1 :U2351-Fhin6OoEM UnrealIRCd test server
    sname = args[0]
    # TODO: handle introductions for other servers
    if numeric == irc.uplink:
        for cap in _neededCaps:
            if cap not in irc.protodata:
                raise ProtocolError("Not all required capabilities were met "
                                    "by the remote server. Your version of UnrealIRCd "
                                    "is probably too old! (Got: %s, needed: %s)" %
                                    (sorted(irc.protodata.keys()),
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
        irc.servers[numeric] = IrcServer(None, sname)
    else:
        raise NotImplementedError

_unrealCmodes = {'l': 'limit', 'c': 'blockcolor', 'G': 'censor',
                 'D': 'delayjoin', 'n': 'noextmsg', 's': 'secret',
                 'T': 'nonotice', 'z': 'sslonly', 'b': 'ban', 'V': 'noinvite',
                 'Z': 'issecure', 'r': 'registered', 'N': 'nonick',
                 'e': 'banexception', 'R': 'regonly', 'M': 'regmoderated',
                 'p': 'private', 'Q': 'nokick', 'P': 'permanent', 'k': 'key',
                 'C': 'noctcp', 'O': 'operonly', 'S': 'stripcolor',
                 'm': 'moderated', 'K': 'noknock', 'o': 'op', 'v': 'voice',
                 'I': 'invex', 't': 'topiclock'}
_neededCaps = ["VL", "SID", "CHANMODES", "NOQUIT", "SJ3"]
def handle_protoctl(irc, numeric, command, args):
    # <- PROTOCTL NOQUIT NICKv2 SJOIN SJOIN2 UMODE2 VL SJ3 TKLEXT TKLEXT2 NICKIP ESVID
    # <- PROTOCTL CHANMODES=beI,k,l,psmntirzMQNRTOVKDdGPZSCc NICKCHARS= SID=001 MLOCK TS=1441314501 EXTSWHOIS
    irc.caps += args
    for cap in args:
        if cap.startswith('SID'):
            irc.uplink = cap.split('=', 1)[1]
            irc.protodata['SID'] = True
        elif cap.startswith('CHANMODES'):
            cmodes = cap.split('=', 1)[1]
            irc.cmodes['*A'], irc.cmodes['*B'], irc.cmodes['*C'], irc.cmodes['*D'] = cmodes.split(',')
            for m in cmodes:
                if m in _unrealCmodes:
                    irc.cmodes[_unrealCmodes[m]] = m
            irc.protodata['CHANMODES'] = True
        # Because more than one PROTOCTL line is sent, we have to delay the
        # check to see whether our needed capabilities are all there...
        # That's done by handle_server(), which comes right after PROTOCTL.
        elif cap == 'VL':
            irc.protodata['VL'] = True
        elif cap == 'NOQUIT':
            irc.protodata['NOQUIT'] = True
        elif cap == 'SJ3':
            irc.protodata['SJ3'] = True

def _sidToServer(irc, sname):
    """<irc object> <server name>

    Returns the SID of a server named <server name>, if present."""
    nick = sname.lower()
    for k, v in irc.servers.items():
        if v.name.lower() == nick:
            return k

def _convertNick(irc, target):
    target = utils.nickToUid(irc, target) or target
    if target not in irc.users:
        log.warning("(%s) Possible desync? Got command target %s, who "
                    "isn't in our user list!")
    return target

def handle_events(irc, data):
    # Unreal's protocol has three styles of commands, @servernumeric, :user, and plain commands.
    # e.g. NICK introduction looks like:
    #   <- NICK nick hopcount timestamp	username hostname server service-identifier-token +usermodes virtualhost :realname
    # while PRIVMSG looks like:
    #   <- :source ! target :message
    # and SJOIN looks like:
    #   <- @servernumeric SJOIN <ts> <chname> [<modes>] [<mode para> ...] :<[[*~@%+]member] [&"ban/except] ...>
    # Same deal as TS6 with :'s indicating a long argument lasting to the
    # end of the line.
    args = parseArgs(data.split(" "))
    # Message starts with a SID/UID prefix.
    if args[0][0] in ':@':
        sender = args[0].lstrip(':@')
        command = args[1]
        args = args[2:]
        # If the sender isn't in UID format, try to convert it automatically.
        # Unreal's protocol isn't quite consistent with this yet!
        numeric = _sidToServer(irc, sender) or utils.nickToUid(irc, sender) or \
            sender
    else:
        # Raw command without an explicit sender; assume it's being sent by our uplink.
        numeric = irc.uplink
        command = args[0]
        args = args[1:]
    try:
        func = globals()['handle_'+command.lower()]
    except KeyError:  # unhandled command
        pass
    else:
        parsed_args = func(irc, numeric, command, args)
        if parsed_args is not None:
            return [numeric, command, parsed_args]

def handle_privmsg(irc, source, command, args):
    # Convert nicks to UIDs, where they exist.
    target = _convertNick(irc, args[0])
    # We use lowercase channels internally, but uppercase UIDs.
    if utils.isChannel(target):
        target = utils.toLower(irc, target)
    return {'target': target, 'text': args[1]}
handle_notice = handle_privmsg
