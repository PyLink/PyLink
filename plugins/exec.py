# exec.py: Provides an 'exec' command to execute raw code
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import utils
from log import log

# Easier access to world through eval/exec.
import world

def _exec(irc, source, args):
    """<code>

    Admin-only. Executes <code> in the current PyLink instance.
    \x02**WARNING: THIS CAN BE DANGEROUS IF USED IMPROPERLY!**\x02"""
    utils.checkAuthenticated(irc, source, allowOper=False)
    args = ' '.join(args)
    if not args.strip():
        irc.reply('No code entered!')
        return
    log.info('(%s) Executing %r for %s', irc.name, args, utils.getHostmask(irc, source))
    exec(args, globals(), locals())
utils.add_cmd(_exec, 'exec')

def _eval(irc, source, args):
    """<Python expression>

    Admin-only. Evaluates the given Python expression and returns the result.
    \x02**WARNING: THIS CAN BE DANGEROUS IF USED IMPROPERLY!**\x02"""
    utils.checkAuthenticated(irc, source, allowOper=False)
    args = ' '.join(args)
    if not args.strip():
        irc.reply('No code entered!')
        return
    log.info('(%s) Evaluating %r for %s', irc.name, args, utils.getHostmask(irc, source))
    irc.reply(eval(args))
utils.add_cmd(_eval, 'eval')
