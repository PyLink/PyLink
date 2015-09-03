import time
import sys
import os
import re
import time

curdir = os.path.dirname(__file__)
sys.path += [curdir, os.path.dirname(curdir)]
import utils
from log import log
import proto_common
from classes import *

casemapping = 'ascii'

hook_map = {}

def spawnClient(irc, nick, ident, host, **kwargs):
    pass

def joinClient(irc, client, channel):
    pass

def pingServer(irc, source=None, target=None):
    pass

def connect(irc):
    ts = irc.start_ts
    proto_ver = 2351

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
    # TS - Sends TS in burst to mitigate time-based desyncs.
    f('PROTOCTL SJ3 NOQUIT NICKv2 VL UMODE TS EAUTH=%s' % irc.serverdata["hostname"])
    f('PROTOCTL SID=%s TS=%s' % (irc.sid, ts))
    f('SERVER %s 1 U%s-h6e-%s' % (host, proto_ver, irc.sid))
    f('EOS')
    # NETINFO maxglobal currenttime protocolversion cloakhash 0 0 0 :networkname
    # "maxglobal" is the amount of maximum global users we've seen so far.
    # We'll just set it to 1 (the PyLink client), since this is completely
    # arbitrary.
    f('NETINFO 1 %s %s * 0 0 0 :networkname' % (ts, proto_ver))

def handle_uid(irc, numeric, command, args):
    # <- :001 UID GL 0 1441306929 gl localhost 0018S7901 0 +iowx * midnight-1C620195 fwAAAQ== :realname
    # <- :001 UID GL| 1 1441312224 gl localhost 001J7FZ02 0 +iwx midnight-1C620195 midnight-1C620195 fwAAAQ== :realname
    pass

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
    args = proto_common.parseArgs(data.split(" "))
    # Message starts with a SID/UID prefix.
    if args[0] in ':@':
        numeric = args[0].lstrip(':@')
        command = args[1]
        args = args[2:]
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
