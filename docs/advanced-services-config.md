# Advanced Services Configuration

There are some service configuration options that you may want to be aware of.

#### Nick / Ident

You can override the `nick` or `ident` of a service bot using a directive liek this:

```yaml
servers:
    somenet:
        # ...
        SERVICE_nick: OTHERNICK
        SERVICE_ident: OTHERIDENT
```

You can also set an arbitrary nick/ident using a per-**service** directive.

```yaml
SERVICE:
    nick: OTHERNICK
    ident: OTHERIDENT
```

#### joinmodes

By default, service bots join channels without giving themselves any modes. You can configure what modes a service bot joins channels with using this directive:

```yaml
SERVICE:
    joinmodes: 'o'
```

This would request the mode 'o' (op on most IRCds) when joining the channel.

Technically any mode can be put here, but if an IRCd in question doesn't support
the mode then it will be ignored.

You can also use combinations of modes, such as 'ao' (usually admin/protect + op)

```yaml
SERVICE:
    joinmodes: 'ao'
```

Combinations should work provided an IRCd in question supports it.

#### Fantasy prefix

You can also set the service bot's fantasy prefix; of course this is only
applicable if the `fantasy` plugin is loaded.

The setting allows for one or more characters to be set as the prefix.

```yaml
SERVICE:
    prefix: './'
```

The above is perfectly valid, as is any other string.

