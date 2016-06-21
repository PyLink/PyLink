# ctcp.py: Handles basic CTCP requests.
from pylinkirc import utils
from pylinkirc.log import log

def handle_ctcpversion(irc, source, args):
    """
    Handles CTCP version requests.
    """
    irc.msg(source, '\x01VERSION %s\x01' % irc.version(), notice=True)

utils.add_cmd(handle_ctcpversion, '\x01version')
utils.add_cmd(handle_ctcpversion, '\x01version\x01')
