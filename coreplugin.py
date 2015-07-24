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
    sourceisOper = ('o', None) in irc.users[source].modes
    # https://www.alien.net.au/irc/irc2numerics.html
    # 311: sends nick!user@host information
    f(irc, server, 311, source, "%s %s %s * :%s" % (nick, user.ident, user.host, user.realname))
    # 312: sends the server the target is on, and the name
    f(irc, server, 312, source, "%s %s :PyLink Server" % (nick, irc.serverdata['hostname']))
    # 313: sends a string denoting the target's operator privilege;
    # we'll only send it if the user has umode +o.
    if ('o', None) in user.modes:
        f(irc, server, 313, source, "%s :is an IRC Operator" % nick)
    # 379: RPL_WHOISMODES, used by UnrealIRCd and InspIRCd.
    # Only shown to opers!
    if sourceisOper:
        f(irc, server, 379, source, '%s :is using modes %s' % (nick, utils.joinModes(user.modes)))
    # 319: RPL_WHOISCHANNELS, shows channel list
    public_chans = []
    for chan in user.channels:
        # Here, we'll want to hide secret/private channels from non-opers
        # who are not in them.
        c = irc.channels[chan]
        if ((irc.cmodes.get('secret'), None) in c.modes or \
            (irc.cmodes.get('private'), None) in c.modes) \
            and not (sourceisOper or source in c.users):
                continue
        # TODO: show prefix modes like a regular IRCd does.
        public_chans.append(chan)
    if public_chans:
        f(irc, server, 319, source, '%s :%s' % (nick, ' '.join(public_chans)))
    # 317: shows idle and signon time. Though we don't track the user's real
    # idle time; we just return 0.
    # 317 GL GL 15 1437632859 :seconds idle, signon time
    f(irc, server, 317, source, "%s 0 %s :seconds idle, signon time" % (nick, user.ts))
    try:
        # Iterate over plugin-created WHOIS handlers. They return a tuple
        # or list with two arguments: the numeric, and the text to send.
        for func in utils.whois_handlers:
            res = func(irc, target)
            if res:
                num, text = res
                f(irc, server, num, source, text)
    except Exception as e:
        # Again, we wouldn't want this to crash our service, in case
        # something goes wrong!
        log.exception('Error caught in WHOIS handler: %s', e)
    finally:
        # 318: End of WHOIS.
        f(irc, server, 318, source, "%s :End of /WHOIS list" % nick)
utils.add_hook(handle_whois, 'WHOIS')
