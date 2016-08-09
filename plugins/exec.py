"""
exec.py: Provides commands for executing raw code and debugging PyLink.
"""

from pylinkirc import utils, world
from pylinkirc.log import log

# These imports are not strictly necessary, but make the following modules
# easier to access through eval and exec.
import threading
import re
import time
import pylinkirc
import importlib

def _exec(irc, source, args):
    """<code>

    Admin-only. Executes <code> in the current PyLink instance. This command performs backslash escaping of characters, so things like \\n and \\ will work.
    \x02**WARNING: THIS CAN BE DANGEROUS IF USED IMPROPERLY!**\x02"""
    irc.checkAuthenticated(source, allowOper=False)

    # Allow using \n in the code, while escaping backslashes correctly otherwise.
    args = bytes(' '.join(args), 'utf-8').decode("unicode_escape")
    if not args.strip():
        irc.reply('No code entered!')
        return

    log.info('(%s) Executing %r for %s', irc.name, args,
             irc.getHostmask(source))
    exec(args, globals(), locals())

utils.add_cmd(_exec, 'exec')

def _eval(irc, source, args):
    """<Python expression>

    Admin-only. Evaluates the given Python expression and returns the result.
    \x02**WARNING: THIS CAN BE DANGEROUS IF USED IMPROPERLY!**\x02"""
    irc.checkAuthenticated(source, allowOper=False)

    args = ' '.join(args)
    if not args.strip():
        irc.reply('No code entered!')
        return

    log.info('(%s) Evaluating %r for %s', irc.name, args,
             irc.getHostmask(source))
    irc.reply(repr(eval(args)))
utils.add_cmd(_eval, 'eval')

@utils.add_cmd
def raw(irc, source, args):
    """<text>

    Admin-only. Sends raw text to the uplink IRC server.
    \x02**WARNING: THIS CAN BREAK YOUR NETWORK IF USED IMPROPERLY!**\x02"""
    irc.checkAuthenticated(source, allowOper=False)

    args = ' '.join(args)
    if not args.strip():
        irc.reply('No text entered!')
        return

    log.info('(%s) Sending raw text %r to IRC for %s', irc.name, args,
             irc.getHostmask(source))
    irc.send(args)

    irc.reply("Done.")

@utils.add_cmd
def inject(irc, source, args):
    """<text>

    Admin-only. Injects raw text into the running PyLink protocol module, replying with the hook data returned.
    \x02**WARNING: THIS CAN BREAK YOUR NETWORK IF USED IMPROPERLY!**\x02"""
    irc.checkAuthenticated(source, allowOper=False)

    args = ' '.join(args)
    if not args.strip():
        irc.reply('No text entered!')
        return

    log.info('(%s) Injecting raw text %r into protocol module for %s', irc.name,
             args, irc.getHostmask(source))
    irc.reply(irc.runline(args))
