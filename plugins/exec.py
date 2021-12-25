"""
exec.py: Provides commands for executing raw code and debugging PyLink.
"""
import pprint
# These imports are not strictly necessary, but make the following modules
# easier to access through eval and exec.
import threading

from pylinkirc import utils, world, conf
from pylinkirc.coremods import permissions
from pylinkirc.log import log

exec_locals_dict = {}
PPRINT_MAX_LINES = 20
PPRINT_WIDTH = 200

if not conf.conf['pylink'].get("debug_enabled", False):
    raise RuntimeError("pylink::debug_enabled must be enabled to load this plugin. "
                       "This should ONLY be used in test environments for debugging and development, "
                       "as anyone with access to this plugin's commands can run arbitrary code as the PyLink user!")

def _exec(irc, source, args, locals_dict=None):
    """<code>

    Admin-only. Executes <code> in the current PyLink instance. This command performs backslash escaping of characters, so things like \\n and \\ will work.

    \x02**WARNING: THIS CAN BE DANGEROUS IF USED IMPROPERLY!**\x02"""
    permissions.check_permissions(irc, source, ['exec.exec'])

    # Allow using \n in the code, while escaping backslashes correctly otherwise.
    args = bytes(' '.join(args), 'utf-8').decode("unicode_escape")
    if not args.strip():
        irc.reply('No code entered!')
        return

    log.info('(%s) Executing %r for %s', irc.name, args,
             irc.get_hostmask(source))
    if locals_dict is None:
        locals_dict = locals()
    else:
        # Add irc, source, and args to the given locals_dict, to allow basic things like irc.reply()
        # to still work.
        locals_dict['irc'] = irc
        locals_dict['source'] = source
        locals_dict['args'] = args

    exec(args, globals(), locals_dict)

    irc.reply("Done.")
utils.add_cmd(_exec, 'exec')

@utils.add_cmd
def iexec(irc, source, args):
    """<code>

    Admin-only. Executes <code> in the current PyLink instance with a persistent, isolated
    locals scope (world.plugins['exec'].exec_local_dict).

    Note: irc, source, and args are added into this locals dict to allow things like irc.reply()
    to still work.

    \x02**WARNING: THIS CAN BE DANGEROUS IF USED IMPROPERLY!**\x02
    """
    _exec(irc, source, args, locals_dict=exec_locals_dict)

def _eval(irc, source, args, locals_dict=None, pretty_print=False):
    """<Python expression>

    Admin-only. Evaluates the given Python expression and returns the result.

    \x02**WARNING: THIS CAN BE DANGEROUS IF USED IMPROPERLY!**\x02"""
    permissions.check_permissions(irc, source, ['exec.eval'])

    args = ' '.join(args)
    if not args.strip():
        irc.reply('No code entered!')
        return

    if locals_dict is None:
        locals_dict = locals()
    else:
        # Add irc, source, and args to the given locals_dict, to allow basic things like irc.reply()
        # to still work.
        locals_dict['irc'] = irc
        locals_dict['source'] = source
        locals_dict['args'] = args

    log.info('(%s) Evaluating %r for %s', irc.name, args,
             irc.get_hostmask(source))

    result = eval(args, globals(), locals_dict)

    if pretty_print:
        lines = pprint.pformat(result, width=PPRINT_WIDTH, compact=True).splitlines()
        for line in lines[:PPRINT_MAX_LINES]:
            irc.reply(line)
        if len(lines) > PPRINT_MAX_LINES:
            irc.reply('Suppressing %s more line(s) of output.' % (len(lines) - PPRINT_MAX_LINES))
    else:
        # Purposely disable text wrapping so results are cut instead of potentially flooding;
        # 'peval' is specifically designed to work around that.
        irc.reply(repr(result), wrap=False)

utils.add_cmd(_eval, 'eval')

@utils.add_cmd
def peval(irc, source, args):
    """<Python expression>

    Admin-only. This command is the same as 'eval', except that results are pretty formatted.

    \x02**WARNING: THIS CAN BE DANGEROUS IF USED IMPROPERLY!**\x02
    """
    _eval(irc, source, args, pretty_print=True)

@utils.add_cmd
def ieval(irc, source, args):
    """<Python expression>

    Admin-only. Evaluates the given Python expression using a persistent, isolated
    locals scope (world.plugins['exec'].exec_local_dict).

    Note: irc, source, and args are added into this locals dict to allow things like irc.reply()
    to still work.

    \x02**WARNING: THIS CAN BE DANGEROUS IF USED IMPROPERLY!**\x02
    """
    _eval(irc, source, args, locals_dict=exec_locals_dict)

@utils.add_cmd
def pieval(irc, source, args):
    """<Python expression>

    Admin-only. This command is the same as 'ieval', except that results are pretty formatted.

    \x02**WARNING: THIS CAN BE DANGEROUS IF USED IMPROPERLY!**\x02
    """
    _eval(irc, source, args, locals_dict=exec_locals_dict, pretty_print=True)

@utils.add_cmd
def inject(irc, source, args):
    """<text>

    Admin-only. Injects raw text into the running PyLink protocol module, replying with the hook data returned.

    \x02**WARNING: THIS CAN BREAK YOUR NETWORK IF USED IMPROPERLY!**\x02"""
    permissions.check_permissions(irc, source, ['exec.inject'])

    args = ' '.join(args)
    if not args.strip():
        irc.reply('No text entered!')
        return

    log.info('(%s) Injecting raw text %r into protocol module for %s', irc.name,
             args, irc.get_hostmask(source))
    irc.reply(repr(irc.parse_irc_command(args)))

@utils.add_cmd
def threadinfo(irc, source, args):
    """takes no arguments.

    Lists all threads currently present in this PyLink instance."""
    permissions.check_permissions(irc, source, ['exec.threadinfo'])

    for t in sorted(threading.enumerate(), key=lambda t: t.name.lower()):
        name = t.name
        # Unnamed threads are something we want to avoid throughout PyLink.
        if name.startswith('Thread-'):
            name = '\x0305%s\x03' % t.name
        # Also VERY bad: remaining threads for networks not in the networks index anymore!
        elif name.startswith(('Listener for', 'Ping timer loop for', 'Queue thread for')) and name.rsplit(" ", 1)[-1] not in world.networkobjects:
            name = '\x0304%s\x03' % t.name

        irc.reply('\x02%s\x02[%s]: daemon=%s; alive=%s' % (name, t.ident, t.daemon, t.is_alive()), private=True)

    irc.reply("Total of %s threads." % threading.active_count())
