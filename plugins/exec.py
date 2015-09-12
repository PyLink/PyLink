# exec.py: Provides an 'exec' command to execute raw code
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import utils
from log import log

def _exec(irc, source, args):
    """<code>

    Admin-only. Executes <code> in the current PyLink instance.
    \x02**WARNING: THIS CAN BE DANGEROUS IF USED IMPROPERLY!**\x02"""
    utils.checkAuthenticated(irc, source, allowOper=False)
    args = ' '.join(args)
    if not args.strip():
        utils.msg(irc, source, 'No code entered!')
        return
    log.info('(%s) Executing %r for %s', irc.name, args, utils.getHostmask(irc, source))
    exec(args, globals(), locals())
utils.add_cmd(_exec, 'exec')
