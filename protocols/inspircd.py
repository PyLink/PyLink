import threading
import socket
import time
import re

class AuthenticationError:
    pass

class InspircdHandler(threading.Thread):

    def __init__(self, name, serverdata):
        threading.Thread.__init__(self)
        self.name = name
        self.authenticated = False
        self.connected = False
        self.serverdata = serverdata
        ip = self.serverdata["ip"]
        port = self.serverdata["port"]
        self.sid = self.serverdata["sid"]
        self.socket = socket.socket()
        self.socket.connect((ip, port))
        print("[+] New thread started for %s:%s" % (ip, port))
        self.authenticate(serverdata)
        self.listen()

    def send(self, data):
        data = data.encode("utf-8") + b"\n"
        print("-> {}".format(data.decode("utf-8").strip("\n")))
        self.socket.send(data)

    def authenticate(self, serverdata):
        f = self.send
        f('CAPAB START 1202')
        f('CAPAB CAPABILITIES :NICKMAX=32 HALFOP=0 CHANMAX=65 MAXMODES=20 IDENTMAX=12 MAXQUIT=255 PROTOCOL=1203')
        f('CAPAB END')
        f('SERVER %s %s 0 %s :PyLink Service' % (self.serverdata["hostname"],
          serverdata["sendpass"], self.sid))
        f(':%s BURST %s' % (self.sid, int(time.time())))
        # :751 UID 751AAAAAA 1220196319 Brain brainwave.brainbox.cc netadmin.chatspike.net brain 192.168.1.10 1220196324 +Siosw +ACKNOQcdfgklnoqtx :Craig Edwards
        f(":{sid} UID {sid}AAAAAA {ts} PyLink {host} {host} pylink 127.0.0.1 {ts} +o + :PyLink Client".format(sid=self.sid,
          ts=int(time.time()), host=self.serverdata["hostname"]))
        f(':%s ENDBURST' % (self.sid))
    # :7NU PING 7NU 0AL
    def handle_ping(self, data):
        m = re.search('\:(\d[A-Z0-9]{1,2}) PING (\d[A-Z0-9]{1,2}) %s' % self.sid, data)
        if m:
            self.send(':%s PONG %s' % (self.sid, m.group(0)))

    def listen(self):
        while True:
            data = self.socket.recv(2048)
            if not data:
                print("Connection reset.")
                break
            try:
                buf = data.decode("utf-8")
                for line in buf.split("\n"):
                    print("<- {}".format(line))
                    self.handle_ping(line)
            except socket.error as e:
                print("%s: Received socket error: '%s', aborting! =X=" % (self.name, e))
                break

def connect(name, serverdata):
    s = InspircdHandler(name, serverdata)
    s.start()
