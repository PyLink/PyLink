import threading
import socket
import time
import re

class AuthenticationError:
    pass

def authenticate(irc):
    f = irc.send
    f('CAPAB START 1202')
    f('CAPAB CAPABILITIES :NICKMAX=32 HALFOP=0 CHANMAX=65 MAXMODES=20 IDENTMAX=12 MAXQUIT=255 PROTOCOL=1203')
    f('CAPAB END')
    f('SERVER %s %s 0 %s :PyLink Service' % (irc.serverdata["hostname"],
      irc.serverdata["sendpass"], irc.sid))
    f(':%s BURST %s' % (irc.sid, int(time.time())))
    # :751 UID 751AAAAAA 1220196319 Brain brainwave.brainbox.cc netadmin.chatspike.net brain 192.168.1.10 1220196324 +Siosw +ACKNOQcdfgklnoqtx :Craig Edwards
    f(":{sid} UID {sid}AAAAAA {ts} PyLink {host} {host} pylink 127.0.0.1 {ts} +o + :PyLink Client".format(sid=irc.sid,
      ts=int(time.time()), host=irc.serverdata["hostname"]))
    f(':%s ENDBURST' % (irc.sid))

# :7NU PING 7NU 0AL
def handle_ping(irc, servernumeric, command, args):
    if args[3] == irc.sid:
        irc.send(':%s PONG %s' % (irc.sid, args[2]))

def handle_privmsg(irc, numeric, command, args):
    irc.send(':0ALAAAAAA PRIVMSG %s :hello!' % numeric)

def handle_error(irc, numeric, command, args):
    print('Received an ERROR, killing!')
    irc.restart()

def handle_events(irc, data):
    try:
        args = data.split()
        real_args = []
        for arg in args:
            real_args.append(arg)
            if arg.startswith(':') and args.index(arg) != 0:
                # : indicates that the argument has multiple words, and lasts until the remainder of the line
                index = args.index(arg)
                arg = ' '.join(args[index:])[1:]
                real_args = args[:index]
                real_args.append(arg)
                break
        real_args[0] = real_args[0].split(':', 1)[1]
        args = real_args
        # Strip leading :

        numeric = args[0]
        command = args[1]
        print(args)
    except IndexError:
        return

    try:
        func = globals()['handle_'+command.lower()]
        func(irc, numeric, command, args)
    except KeyError:  # unhandled event
        pass

def connect(irc):
    authenticate(irc)
