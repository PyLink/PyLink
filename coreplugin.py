## coreplugin.py - Core PyLink plugin

import utils
from log import log

# Handle KILLs sent to the PyLink client and respawn
def handle_kill(irc, source, command, args):
    if args['target'] == irc.pseudoclient.uid:
        irc.spawnMain()
utils.add_hook(handle_kill, 'KILL')          

# Handle KICKs to the PyLink client, rejoining the channels
def handle_kick(irc, source, command, args):
    kicked = args['target']
    channel = args['channel']
    if kicked == irc.pseudoclient.uid:
        irc.proto.joinClient(irc, irc.pseudoclient.uid, channel)
utils.add_hook(handle_kick, 'KICK')  

# Handle commands sent to the PyLink client (PRIVMSG)
def handle_commands(irc, source, command, args):
    if args['target'] == irc.pseudoclient.uid:
        cmd_args = args['text'].split(' ')
        cmd = cmd_args[0].lower()
        cmd_args = cmd_args[1:]
        try:
            func = utils.bot_commands[cmd]
        except KeyError:
            utils.msg(irc, source, 'Unknown command %r.' % cmd)
            return
        try:
            func(irc, source, cmd_args)
        except Exception as e:
            log.exception('Unhandled exception caught in command %r' % cmd)
            utils.msg(irc, source, 'Uncaught exception in command %r: %s: %s' % (cmd, type(e).__name__, str(e)))
            return
utils.add_hook(handle_commands, 'PRIVMSG')
