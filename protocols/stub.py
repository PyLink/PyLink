def connect(name, networkdata):
    print('%s: Using PyLink stub/testing protocol.' % name)
    print('Send password: %s' % networkdata['sendpass'])
    print('Receive password: %s' % networkdata['recvpass'])
    print('Server: %s:%s' % (networkdata['ip'], networkdata['port']))
