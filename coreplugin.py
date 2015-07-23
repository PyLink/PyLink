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
            log.info('(%s) Calling command %r for %s', irc.name, cmd, utils.getHostmask(irc, source))
            func(irc, source, cmd_args)
        except Exception as e:
            log.exception('Unhandled exception caught in command %r', cmd)
            utils.msg(irc, source, 'Uncaught exception in command %r: %s: %s' % (cmd, type(e).__name__, str(e)))
            return
utils.add_hook(handle_commands, 'PRIVMSG')

# Return WHOIS replies to IRCds that use them.
def handle_whois(irc, source, command, args):
    target = args['target']
    user = irc.users.get(target)
    if user is None:
        log.warning('(%s) Got a WHOIS request for %r from %r, but the target doesn\'t exist in irc.users!', irc.name, target, source)
    f = irc.proto.numericServer
    server = utils.clientToServer(irc, target) or irc.sid
    nick = user.nick
    # https://www.alien.net.au/irc/irc2numerics.html
    # 311: sends nick!user@host information
    f(irc, server, 311, source, "%s %s %s * :%s" % (nick, user.ident, user.host, user.realname))
    # 312: sends the server the target is on, and the name
    f(irc, server, 312, source, "%s %s :PyLink Server" % (nick, irc.serverdata['hostname']))
    # 313: sends a string denoting the target's operator privilege;
    # we'll only send it if the user has umode +o.
    if ('o', None) in user.modes:
        f(irc, server, 313, source, "%s :is an IRC Operator" % nick)
    # 318: End of WHOIS.
    f(irc, server, 318, source, "%s :End of WHOIS" % nick.lower())
utils.add_hook(handle_whois, 'WHOIS')
