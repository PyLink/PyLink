"""
login.py - Implement core login abstraction.
"""

from pylinkirc import conf, utils, world
from pylinkirc.log import log
from passlib.context import CryptContext

pwd_context = CryptContext(["sha512_crypt", "sha256_crypt"],
                           all__vary_rounds=0.1,
                           sha256_crypt__default_rounds=180000,
                           sha512_crypt__default_rounds=90000)

def checkLogin(user, password):
    """Checks whether the given user and password is a valid combination."""
    accounts = conf.conf['login'].get('accounts')
    if not accounts:
        # No accounts specified, return.
        return False

    # Lowercase account names to make them case insensitive. TODO: check for
    # duplicates.
    user = user.lower()
    accounts = {k.lower(): v for k, v in accounts.items()}

    try:
        account = accounts[user]
    except KeyError:  # Invalid combination
        return False
    else:
        passhash = account.get('password')
        if not passhash:
            # No password given, return. XXX: we should allow plugins to override
            # this in the future.
            return False

        # Encryption in account passwords is optional (to not break backwards
        # compatibility).
        if account.get('encrypted', False):
            return verifyHash(password, passhash)
        else:
            return password == passhash

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
        return

    hashed_pass = pwd_context.encrypt(password)
    irc.reply(hashed_pass, private=True)
