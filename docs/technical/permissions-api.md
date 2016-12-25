# The Permissions API

Permissions were introduced in PyLink 1.0 as a better (but optional) way for plugins to manage access to commands. The permissions system in PyLink is fairly simple, globally assigning a list of permissions to each hostmask/exttarget.

Permissions take the format `pluginname.commandname.optional_extra_portion(s)`, and support wildcards in matching. Permission nodes are case-insensitive and casemapping aware, but are conventionally defined as being all lowercase.

## Checking for permissions

Individual functions check for permissions using the `permissions.checkPermissions(irc, source, ['perm.1', 'perm.2'])` function, where the last argument is an OR'ed list of permissions (i.e. users only need one out of all of them). This function returns `True` when a permission check passes, and raises `utils.NotAuthorizedError` when a check fails, automatically aborting the execution of the command function.

## Assigning default permissions

Plugins are also allowed to assign default permissions to their commands, though this should be used sparingly to ensure maximum configurability (explicitly removing permissions isn't supported yet). Default permissions are specified as a `dict` mapping targets to permission lists.

Example of this in [Automode](https://github.com/GLolol/PyLink/blob/1.1-alpha1/plugins/automode.py#L38-L39):

```python
# The default set of Automode permissions.
default_permissions = {"$ircop": ['automode.manage.relay_owned', 'automode.sync.relay_owned',
                                  'automode.list']}
```

Default permissions are registered in a plugin's `main()` function via `permissions.addDefaultPermissions(default_permissions_dict)`, and should always be erased on `die()` through `permissions.removeDefaultPermissions(default_permissions_dict)`.
