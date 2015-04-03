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
def handle_ping(irc, data):
    m = re.search('\:(\d[A-Z0-9]{1,2}) PING (\d[A-Z0-9]{1,2}) %s' % irc.sid, data)
    if m:
        irc.send(':%s PONG %s' % (irc.sid, m.group(0)))

def handle_events(irc, data):
    handle_ping(irc, data)

def connect(irc):
    authenticate(irc)
