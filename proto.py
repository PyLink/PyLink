import socket
import time
import sys
from utils import *
from copy import copy

global bot_commands
# This should be a mapping of command names to functions
bot_commands = {}

class IrcUser():
    def __init__(self, nick, ts, uid, ident='null', host='null',
                 realname='PyLink dummy client', realhost='null',
                 ip='0.0.0.0'):
        self.nick = nick
        self.ts = ts
        self.uid = uid
        self.ident = ident
        self.host = host
        self.realhost = realhost
        self.ip = ip
        self.realname = realname

    def __repr__(self):
        return repr(self.__dict__)

class IrcServer():
    def __init__(self, uplink):
        self.uplink = uplink
        self.users = []
    def __repr__(self):
        return repr(self.__dict__)

def _sendFromServer(irc, msg):
    irc.send(':%s %s' % (irc.sid, msg))

def _sendFromUser(irc, msg, user=None):
    if user is None:
        user = irc.pseudoclient.uid
    irc.send(':%s %s' % (user, msg))

def _join(irc, channel):
    _sendFromUser(irc, "JOIN {channel} {ts} +nt :,{uid}".format(sid=irc.sid,
             ts=int(time.time()), uid=irc.pseudoclient.uid, channel=channel))

def _nicktoUid(irc, nick):
    for k, v in irc.users.items():
        if v.nick == nick:
            return k

def introduceUser(irc, nick, user, host):
    uid = next_uid(irc.sid)
    _sendFromServer(irc, "UID {uid} {ts} {nick} {host} {host} {user} 0.0.0.0 {ts} +o +"
                    " :PyLink Client".format(ts=int(time.time()), host=host,
                                             nick=nick, user=user, uid=uid))
    irc.users[uid] = IrcUser(nick, ts, uid, ident, host, realname, realhost, ip)
    irc.servers[irc.sid].users.append(uid)

def connect(irc):
    ts = int(time.time())
    host = irc.serverdata["hostname"]
    uid = next_uid(irc.sid)
    irc.pseudoclient = IrcUser('PyLink', ts, uid, 'pylink', host,
                               'PyLink Client')
    irc.users[uid] = irc.pseudoclient
    irc.servers[irc.sid] = IrcServer(None)
    irc.servers[irc.sid].users = [uid]

    f = irc.send
    f('CAPAB START 1203')
    # This is hard coded atm... We should fix it eventually...
    f('CAPAB CAPABILITIES :NICKMAX=32 HALFOP=0 CHANMAX=65 MAXMODES=20'
      ' IDENTMAX=12 MAXQUIT=255 PROTOCOL=1203')
    f('CAPAB END')
    # TODO: check recvpass here
    f('SERVER {host} {Pass} 0 {sid} :PyLink Service'.format(host=host,
      Pass=irc.serverdata["sendpass"], sid=irc.sid))
    f(':%s BURST %s' % (irc.sid, ts))
    # InspIRCd documentation:
    # :751 UID 751AAAAAA 1220196319 Brain brainwave.brainbox.cc
    # netadmin.chatspike.net brain 192.168.1.10 1220196324 +Siosw
    # +ACKNOQcdfgklnoqtx :Craig Edwards
    f(":{sid} UID {uid} {ts} PyLink {host} {host} pylink 0.0.0.0 {ts} +o +"
      " :PyLink Client".format(sid=irc.sid, ts=ts,
                               host=host,
                               uid=uid))
    f(':%s ENDBURST' % (irc.sid))
    _join(irc, irc.serverdata["channel"])

# :7NU PING 7NU 0AL
def handle_ping(irc, servernumeric, command, args):
    if args[1] == irc.sid:
        _sendFromServer(irc, 'PONG %s' % args[1])

def handle_privmsg(irc, source, command, args):
    prefix = irc.conf['bot']['prefix']
    if args[0] == irc.pseudoclient.uid:
        cmd_args = args[1].split(' ')
        cmd = cmd_args[0]
        try:
            cmd_args = cmd_args[1:]
        except IndexError:
            cmd_args = []
        try:
            bot_commands[cmd](irc, source, cmd_args)
        except KeyError:
            _sendFromUser(irc, 'PRIVMSG %s :unknown command %r' % (source, cmd))

def handle_error(irc, numeric, command, args):
    print('Received an ERROR, killing!')
    irc.connected = False
    sys.exit(1)

def handle_fjoin(irc, servernumeric, command, args):
    # :70M FJOIN #chat 1423790411 +AFPfjnt 6:5 7:5 9:5 :o,1SRAABIT4 v,1IOAAF53R <...>
    channel = args[0]
    # tl;dr InspIRCd sends each user's channel data in the form of 'modeprefix(es),UID'
    # We'll save each user in this format too, at least for now.
    users = args[-1].split()
    users = [x.split(',') for x in users]

    '''
    if channel not in irc.channels.keys():
        irc.channels[channel]['users'] = users
    else:
        old_users = irc.channels[channel]['users'].copy()
        old_users.update(users)
    '''

def handle_uid(irc, numeric, command, args):
    # :70M UID 70MAAAAAB 1429934638 GL 0::1 hidden-7j810p.9mdf.lrek.0000.0000.IP gl 0::1 1429934638 +Wioswx +ACGKNOQXacfgklnoqvx :realname
    uid, ts, nick, realhost, host, ident, ip = args[0:7]
    realname = args[-1]
    irc.users[uid] = IrcUser(nick, ts, uid, ident, host, realname, realhost, ip)
    irc.servers[numeric].users.append(uid)

def handle_quit(irc, numeric, command, args):
    # :1SRAAGB4T QUIT :Quit: quit message goes here
    del irc.users[numeric]
    sid = numeric[:3]
    irc.servers[sid].users.remove(numeric)
    '''
    for k, v in irc.channels.items():
        try:
            del irc.channels[k][users][v]
        except KeyError:
            pass
    '''

def handle_burst(irc, numeric, command, args):
    # :70M BURST 1433044587
    irc.servers[numeric] = IrcServer(None)

def handle_server(irc, numeric, command, args):
    # :70M SERVER millennium.overdrive.pw * 1 1ML :a relatively long period of time... (Fremont, California)
    servername = args[0]
    sid = args[3]
    irc.servers[sid] = IrcServer(numeric)

def handle_nick(irc, numeric, command, args):
    newnick = args[0]
    irc.users[numeric].nick = newnick

def handle_squit(irc, numeric, command, args):
    # :70M SQUIT 1ML :Server quit by GL!gl@0::1
    split_server = args[0]
    print('Netsplit on server %s' % split_server)
    # Prevent RuntimeError: dictionary changed size during iteration
    old_servers = copy(irc.servers)
    for sid, data in old_servers.items():
        if data.uplink == split_server:
            print('Server %s also hosts server %s, removing those users too...' % (split_server, sid))
            handle_squit(irc, sid, 'SQUIT', [sid, "PyLink: Automatically splitting leaf servers of %s" % sid])
    for user in irc.servers[split_server].users:
        del irc.users[user]
    del irc.servers[split_server]

def handle_events(irc, data):
    # Each server message looks something like this:
    # :70M FJOIN #chat 1423790411 +AFPfjnt 6:5 7:5 9:5 :v,1SRAAESWE
    # :<sid> <command> <argument1> <argument2> ... :final multi word argument
    try:
        args = data.split()
        real_args = []
        for arg in args:
            real_args.append(arg)
            # If the argument starts with ':' and ISN'T the first argument.
            # The first argument is used for denoting the source UID/SID.
            if arg.startswith(':') and args.index(arg) != 0:
                # : is used for multi-word arguments that last until the end
                # of the message. We can use list splicing here to turn them all
                # into one argument.
                index = args.index(arg)  # Get the array index of the multi-word arg
                # Set the last arg to a joined version of the remaining args
                arg = args[index:]
                arg = ' '.join(arg)[1:]
                # Cut the original argument list right before the multi-word arg,
                # and then append the multi-word arg.
                real_args = args[:index]
                real_args.append(arg)
                break
        real_args[0] = real_args[0].split(':', 1)[1]
        args = real_args

        numeric = args[0]
        command = args[1]
        args = args[2:]
    except IndexError:
        return

    # We will do wildcard event handling here. Unhandled events are just ignored, yay!
    try:
        func = globals()['handle_'+command.lower()]
        func(irc, numeric, command, args)
    except KeyError:  # unhandled event
        pass

def add_cmd(func):
    bot_commands[func.__name__.lower()] = func
