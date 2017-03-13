# Advanced Service Config

There are some service configuration options that you may want to be aware of.

**NOTE**: Your SERVICE name in the `utils.registerService("SERVICE", desc=desc)`
call and the service configuration in 'SERVICE::' **MUST** match for these
directives to apply.


#### Nick / Ident

In addition to setting a per-server 'nick' or 'ident' using,

```yaml
servers:
    somenet:
        # ...
        SERVICE_nick: OTHERNICK
        SERVICE_ident: OTHERIDENT
``` 

You can also just set an arbitrary nick/ident using a per-**service** directive.

```yaml
SERVICE:
    nick: OTHERNICK
    ident: OTHERIDENT
```

#### JoinModes

When joining a channel, ServiceBot Instances will just join and sit there.
However, you can set a mode that the bot will ask for when it joins any channel.

```yaml
SERVICE:
    joinmodes: 'o'
```

This would request the mode 'o' (usually op on most IRCds) when joining the channel.

Technically any mode can be put here, but if an IRCd in question doesn't support
the mode then it just ignores it.

You can also use combinations of modes, such as 'ao' (usually admin/protect + op)

```yaml
SERVICE:
    joinmodes: 'ao'
```

Combinations should work provided an IRCd in question supports it.

#### Prefix

You can also set the Service Bots fantasy prefix, of course this is only
applicable if the 'fantasy' plugin is loaded.

The setting allows for one or more characters to be set as the prefix.

```yaml
SERVICE:
    prefix: './' 
```

This is perfectly valid, as is any other string.

