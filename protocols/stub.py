def connect(irc):
    print('%s: Using PyLink stub/testing protocol.' % irc.name)
    print('Send password: %s' % irc.serverdata['sendpass'])
    print('Receive password: %s' % irc.serverdata['recvpass'])
    print('Server: %s:%s' % (irc.serverdata["ip"], irc.serverdata["port"]))

def handle_events(irc, data):
    print('%s: Received event: %s' % (irc.name, data))
