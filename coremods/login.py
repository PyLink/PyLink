"""
login.py - Implement core login abstraction
"""

from pylinkirc import conf, utils, world
from pylinkirc.log import log
from passlib.apps import custom_app_context as pwd_context

def checkLogin(user, password):
    """Checks whether the given user and password is a valid combination."""
    try:
        passhash = conf.conf['login']['accounts'][user].get('password')
    except KeyError:  # Invalid combination
        return False

    return verifyHash(password, passhash)

def verifyHash(password, passhash):
    """Checks whether the password given matches the hash."""
    if password:
        # ... good we have a password inputted
        # XXX: the greatest thing here is that the hash
        # is just a string either way, not a object with
        # a method to output the hash
        return pwd_context.verify(password, passhash)
    return False


@utils.add_cmd
def mkpasswd(irc, source, args):
    """<password>
    Hashes a password for use in the configuration file."""
    # TODO: restrict to only certain users?
    try:
        password = args[0]
    except IndexError:
        irc.error("Not enough arguments. (Needs 1, password)")
        return
    if not password:
        irc.error("Password cannot be empty.")

    hashed_pass = pwd_context.encrypt(password)
    irc.reply(hashed_pass, private=True)
