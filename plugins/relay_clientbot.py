# relay_clientbot.py: Clientbot extensions for Relay
import string

from pylinkirc import utils, conf, world
from pylinkirc.log import log

default_styles = {'MESSAGE': '\x02[$colored_netname]\x02 <$colored_nick> $text',
                 }

def color_text(s):
    """
    Returns a colorized version of the given text based on a simple hash algorithm
    (sum of all characters).
    """
    colors = ('02', '03', '04', '05', '06', '07', '08', '09', '10', '11',
              '12', '13')
    num = sum([ord(char) for char in s])
    num = num % len(colors)
    return "\x03%s%s\x03" % (colors[num], s)

def cb_relay_core(irc, source, command, args):
    """
    This function takes Clientbot actions and outputs them to a channel as regular text.
    """
    real_command = command.split('_')[-1]

    relay = world.plugins.get('relay')
    if irc.pseudoclient and relay:
        sourcename = irc.getFriendlyName(source)

        # .get() chains are lovely. Try to fetch the format for the given command from the
        # relay:clientbot_format:$command key, falling back to one defined in default_styles
        # above, and then nothing if not found.
        text_template = conf.conf.get('relay', {}).get('clientbot_format', {}).get(real_command,
                        default_styles.get(real_command, ''))
        text_template = string.Template(text_template)

        if text_template:
            origuser = relay.getOrigUser(irc, source) or ('undefined', 'undefined')
            netname = origuser[0]

            # Figure out where the message is destined to.
            target = args.get('channel') or args.get('target')
            if target is None or not utils.isChannel(target):
                return

            if source in irc.users:
                identhost = irc.getHostmask(source).split('!')[-1]
                # This is specifically spaced so that ident@host is only shown for users that have
                # one, and not servers.
                identhost = ' (%s)' % identhost
            else:
                identhost = ''

            args.update({'netname': netname, 'nick': sourcename, 'identhost': identhost,
                         'colored_nick': color_text(sourcename), 'colored_netname': color_text(netname)})

            text = text_template.substitute(args)

            irc.proto.message(irc.pseudoclient.uid, target, text)

utils.add_hook(cb_relay_core, 'CLIENTBOT_MESSAGE')
