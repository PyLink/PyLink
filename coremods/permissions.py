"""
permissions.py - Permissions Abstraction for PyLink IRC Services.
"""

from collections import defaultdict
import threading

# Global variables: these store mappings of hostmasks/exttargets to lists of permissions each target has.
default_permissions = defaultdict(set)
permissions = defaultdict(set)

# Only allow one thread to change the permissions index at once.
permissions_lock = threading.Lock()

from pylinkirc import conf, utils
from pylinkirc.log import log

def resetPermissions():
    """
    Loads the permissions specified in the permissions: block of the PyLink configuration,
    if such a block exists. Otherwise, fallback to the default permissions specified by plugins.
    """
    with permissions_lock:
        global permissions
        log.debug('permissions.resetPermissions: old perm list: %s', permissions)

        new_permissions = default_permissions.copy()
        log.debug('permissions.resetPermissions: new_permissions %s', new_permissions)
        if not conf.conf.get('permissions_merge_defaults', True):
            log.debug('permissions.resetPermissions: clearing perm list due to permissions_merge_defaults set False.')
            new_permissions.clear()

        # Convert all perm lists to sets.
        for k, v in conf.conf.get('permissions', {}).items():
            new_permissions[k] |= set(v)

        log.debug('permissions.resetPermissions: new_permissions %s', new_permissions)
        permissions.clear()
        permissions.update(new_permissions)
        log.debug('permissions.resetPermissions: new perm list: %s', permissions)

def addDefaultPermissions(perms):
    """Adds default permissions to the index."""
    with permissions_lock:
        global default_permissions
        for target, permlist in perms.items():
            default_permissions[target] |= set(permlist)

def removeDefaultPermissions(perms):
    """Remove default permissions from the index."""
    with permissions_lock:
        global default_permissions
        for target, permlist in perms.items():
            default_permissions[target] -= set(permlist)

def checkPermissions(irc, uid, perms, also_show=[]):
    """
    Checks permissions of the caller. If the caller has any of the permissions listed in perms,
    this function returns True. Otherwise, NotAuthorizedError is raised.
    """
    # If the user is logged in, they automatically have all permissions.
    if irc.matchHost('$pylinkacc', uid):
        log.debug('permissions: overriding permissions check for admin user %s', irc.getHostmask(uid))
        return True

    # Iterate over all hostmask->permission list mappings.
    for host, permlist in permissions.copy().items():
        log.debug('permissions: permlist for %s: %s', host, permlist)
        if irc.matchHost(host, uid):
            # Now, iterate over all the perms we are looking for.
            for perm in permlist:
                # Use irc.matchHost to expand globs in an IRC-case insensitive and wildcard
                # friendly way. e.g. 'xyz.*.#Channel\' will match 'xyz.manage.#channel|' on IRCds
                # using the RFC1459 casemapping.
                log.debug('permissions: checking if %s glob matches anything in %s', perm, permlist)
                if any(irc.matchHost(perm, p) for p in perms):
                    return True
    raise utils.NotAuthorizedError("You are missing one of the following permissions: %s" %
                                   (', '.join(perms+also_show)))
