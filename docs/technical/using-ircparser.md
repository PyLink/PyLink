# Using utils.IRCParser()

**As of 22/02/2017 (1.2-dev), PyLink allows plugin creators to either parse command arguments themselves
or use a sub-classed instance of [argparse.ArgumentParser()](https://docs.python.org/3/library/argparse.html)
to parse their arguments.**

First off, you will already have access to IRCParser due to importing `utils`.

Otherwise, this is how to include it...

```python
from pylinkirc import utils
```

When you add a command that you want to use `utils.IRCParser()` with, the following is a guide on how to add arguments.

**Note**: Most if not all the examples are from Python's argparse documentation, linked above.

#### Positional (Named) Arguments
```python
SomeParser.add_argument('argname')
```

#### Flag Arguments / Switch Arguments
```python

SomeParser = utils.IRCParser()
SomeParser.addargument('-a', '--argumentname')
```

##### Action

Actions define what to do when given an argument (i.e. whether it is used by itself or as some other sort of value).

Here are some of the actions that `argparse` defines:

* `store` - just stores the value given. This is the default when an action isn't provided.
    ```python
    >>> parser = argparse.ArgumentParser()
    >>> parser.add_argument('--foo')
    >>> parser.parse_args('--foo 1'.split())
    Namespace(foo='1')
    ```

* `store_true`/`store_false` - used when you just want to check if an argument was used.

    ```python
    >>> parser = argparse.ArgumentParser()
    >>> parser.add_argument('--foo', action='store_true')
    >>> parser.add_argument('--bar', action='store_false')
    >>> parser.add_argument('--baz', action='store_false')
    
    >>> parser.parse_args('--foo --bar'.split())
    Namespace(foo=True, bar=False, baz=True)
    ```

* `append` - additively stores arguments if a switch is given multiple times.

    ```python
    >>> parser = argparse.ArgumentParser()
    >>> parser.add_argument('--foo', action='append')
    >>> parser.parse_args('--foo 1 --foo 2'.split())
    Namespace(foo=['1', '2'])
    ```

* `count` - counts how many times an argument was used (for flag/switch arguments only)
    ```python
    >>> parser = argparse.ArgumentParser()
    >>> parser.add_argument('--verbose', '-v', action='count')
    >>> parser.parse_args(['-vvv'])
    Namespace(verbose=3)
    ```

You can also specify an arbitrary `Action` by sub-classing Action. If you want
to do this, you must `import argparse` in your plugin.

More info on that is available [here](https://docs.python.org/3/library/argparse.html#action).

##### Type Constraints

If you want an argument to be of a certain type, you can include a `type=TYPE` keyword, done like so.

```python
SomeParser.add_argument('argname', type=int)

```

As such this will return an error if the input can not be converted to an `int`.

Types usable are `str` and `int`,
there may be more that are allowed in this keyword argument,
but `str` and `int` are the only ones we have throughly used.

**Note**: TYPE can be technically any callable. More about that [here](https://docs.python.org/3/library/argparse.html#type)!



##### Choices
If you want to limit what the user can enter for an argument,
like if they have to choose something from a pre-existing list.

This can be used by adding `choices=['A', 'AAAA', 'CNAME']` into the
`SomeParser.add_argument()` call along with the option entries (-a/--argname).

```python
SomeParser.add_argument('argname', choices=['A', 'AAAA', 'CNAME'])

```

##### Needed Args (aka. nargs)

The keyword argument `nargs` or Needed Args associates a different number of arguments to an action.

* `N` - this is an integer; N arguments will be gathered into a list. nargs=1 produces a list of one item, while the default (not using nargs) produces just the argument itself.

* `'?'` - One argument will be used. If `default` is defined in the call, then default will be used if there is no given argument.

* `'*'` - All arguments are gathered into a list. It only makes sense to use this once in a command handler.

* `'+'` - Like '*' but raises an error if there wasn't at least one argument given.

* `utils.IRCParser.REMAINDER` - remaining arguments are gathered into a list; this is usually used when you need to get a phrase stored, such as the 'quote' text of a quote, a service bot part reason, etc. This is an alias to `argparse.REMAINDER`.

