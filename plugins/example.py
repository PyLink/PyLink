# example.py: An example PyLink plugin.
from pylinkirc import utils
from pylinkirc.log import log

import random

# Example PRIVMSG hook that returns "hi there!" when PyLink's nick is mentioned
# in a channel.

# irc: The IRC object where the hook was called.
# source: The UID/numeric of the sender.
# command: The true command name where the hook originates. This may or may not be
#          the same as the name of the hook, depending on context.
# args: The hook data (a dict) associated with the command. The available data
#       keys differ by hook name (see the hooks reference for a list of which can
#       be used).
def hook_privmsg(irc, source, command, args):
    channel = args['target']
    text = args['text']

    # irc.pseudoclient stores the IrcUser object of the main PyLink client.
    # (i.e. the user defined in the bot: section of the config)
    if utils.isChannel(channel) and irc.pseudoclient.nick in text:
        irc.msg(channel, 'hi there!')
        # log.debug, log.info, log.warning, log.error, log.exception (within except: clauses)
        # and log.critical are supported here.
        log.info('%s said my name on channel %s (PRIVMSG hook caught)' % (source, channel))

utils.add_hook(hook_privmsg, 'PRIVMSG')


# Example command function. @utils.add_cmd binds it to an IRC command of the same name,
# but you can also use a different name by specifying a second 'name' argument (see below).
@utils.add_cmd
# irc: The IRC object where the command was called.
# source: The UID/numeric of the calling user.
# args: A list of command args (excluding the command name) that the command was called with.
def randint(irc, source, args):
    # The docstring here is used as command help by the 'help' command, and formatted using the
    # same line breaks as the raw string. You shouldn't make this text or any one line too long,
    # to prevent flooding users or getting long lines cut off.

    # The same applies to message replies in general: plugins sending long strings of text should
    # be wary that long messages can get cut off. Automatic word-wrap may be added in the future:
    # https://github.com/GLolol/PyLink/issues/153
    """[<min> <max>]
    Returns a random number between <min> and <max>. <min> and <max> default
    to 1 and 10 respectively, if both aren't given."""
    try:
        rmin = args[0]
        rmax = args[1]
    except IndexError:
       rmin, rmax = 1, 10
    n = random.randint(rmin, rmax)

    # irc.reply() is intelligent and will automatically reply to the caller in
    # right context. If fantasy is loaded and you call the command via it,
    # it will send replies into the channel instead of in your PM.
    irc.reply(str(n))

# You can also bind a command function multiple times, and/or to different command names via a
# second argument.
utils.add_cmd(randint, "random")
