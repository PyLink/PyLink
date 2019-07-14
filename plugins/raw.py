"""
raw.py: Provides a 'raw' command for sending raw text to IRC.
"""
from pylinkirc import utils
from pylinkirc.coremods import permissions
from pylinkirc.log import log


@utils.add_cmd
def raw(irc, source, args):
    """<text>

    Sends raw text to the IRC server.

    This command is not officially supported on non-Clientbot networks, where it
    requires a separate permission."""

    if irc.protoname == 'clientbot':
        # exec.raw is included for backwards compatibility with PyLink 1.x
        perms = ['raw.raw', 'exec.raw']
    else:
        perms = ['raw.raw.unsupported_network']
    permissions.check_permissions(irc, source, perms)

    args = ' '.join(args)
    if not args.strip():
        irc.reply('No text entered!')
        return

    # Note: This is loglevel debug so that we don't risk leaking things like
    # NickServ passwords on Clientbot networks.
    log.debug('(%s) Sending raw text %r to IRC for %s', irc.name, args,
              irc.get_hostmask(source))
    irc.send(args)

    irc.reply("Done.")
