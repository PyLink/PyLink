def parseArgs(args):
    """<arg list>
    Parses a string of RFC1459-style arguments split into a list, where ":" may
    be used for multi-word arguments that last until the end of a line.
    """
    real_args = []
    for idx, arg in enumerate(args):
        real_args.append(arg)
        # If the argument starts with ':' and ISN'T the first argument.
        # The first argument is used for denoting the source UID/SID.
        if arg.startswith(':') and idx != 0:
            # : is used for multi-word arguments that last until the end
            # of the message. We can use list splicing here to turn them all
            # into one argument.
            # Set the last arg to a joined version of the remaining args
            arg = args[idx:]
            arg = ' '.join(arg)[1:]
            # Cut the original argument list right before the multi-word arg,
            # and then append the multi-word arg.
            real_args = args[:idx]
            real_args.append(arg)
            break
    return real_args


def parseTS6Args(args):
    """<arg list>

    Similar to parseArgs(), but stripping leading colons from the first argument
    of a line (usually the sender field)."""
    args = parseArgs(args)
    args[0] = args[0].split(':', 1)[1]
    return args

