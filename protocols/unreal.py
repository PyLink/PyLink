import time
import sys
import os
import time
import ipaddress

curdir = os.path.dirname(__file__)
sys.path += [curdir, os.path.dirname(curdir)]
import utils
from log import log
from ts6_common import parseArgs, removeClient, _send
from ts6_common import handle_quit, handle_part, handle_nick, handle_kill
from classes import *

casemapping = 'ascii'
proto_ver = 2351

hook_map = {}

def spawnClient(irc, nick, ident, host, **kwargs):
    pass

def joinClient(irc, client, channel):
    pass

def pingServer(irc, source=None, target=None):
    source = source or irc.sid
    target = target or irc.uplink
    if not (target is None or source is None):
        _send(irc, source, 'PING %s %s' % (irc.servers[source].name, irc.servers[target].name))

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
    # <- :001 UID GL| 1 1441312224 gl localhost 001J7FZ02 0 +iwx midnight-1C620195 midnight-1C620195 fwAAAQ== :realname
    pass

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
    # <- SERVER unreal.midnight.vpn 1 :UnrealIRCd test server
    sname = args[0]
    # TODO: handle server introductions from other servers
    if numeric == irc.uplink:
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
def handle_protoctl(irc, numeric, command, args):
    # <- PROTOCTL NOQUIT NICKv2 SJOIN SJOIN2 UMODE2 VL SJ3 TKLEXT TKLEXT2 NICKIP ESVID
    # <- PROTOCTL CHANMODES=beI,k,l,psmntirzMQNRTOVKDdGPZSCc NICKCHARS= SID=001 MLOCK TS=1441314501 EXTSWHOIS
    irc.caps += args
    for cap in args:
        if cap.startswith('SID'):
            irc.uplink = cap.split('=', 1)[1]
        elif cap.startswith('CHANMODES'):
            cmodes = cap.split('=', 1)[1]
            irc.cmodes['*A'], irc.cmodes['*B'], irc.cmodes['*C'], irc.cmodes['*D'] = cmodes.split(',')
            for m in cmodes:
                if m in _unrealCmodes:
                    irc.cmodes[_unrealCmodes[m]] = m

def _sidToServer(irc, sname):
    """<irc object> <server name>

    Returns the SID of a server named <server name>, if present."""
    nick = sname.lower()
    for k, v in irc.servers.items():
        if v.name.lower() == nick:
            return k

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
        # Raw command w/o explicit sender, assume it's being sent by our uplink.
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
