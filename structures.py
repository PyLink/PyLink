"""
structures.py - PyLink data structures module.

This module contains custom data structures that may be useful in various situations.
"""

import collections
import collections.abc
import json
import os
import pickle
import string
import threading
from copy import copy, deepcopy

from . import conf
from .log import log

__all__ = ['KeyedDefaultdict', 'CopyWrapper', 'CaseInsensitiveFixedSet',
          'CaseInsensitiveDict', 'IRCCaseInsensitiveDict',
          'CaseInsensitiveSet', 'IRCCaseInsensitiveSet',
          'CamelCaseToSnakeCase', 'DataStore', 'JSONDataStore',
          'PickleDataStore']


_BLACKLISTED_COPY_TYPES = []

class KeyedDefaultdict(collections.defaultdict):
    """
    Subclass of defaultdict allowing the key to be passed to the default factory.
    """
    def __missing__(self, key):
        if self.default_factory is None:
            # If there is no default factory, just let defaultdict handle it
            super().__missing__(key)
        else:
            value = self[key] = self.default_factory(key)
            return value

class CopyWrapper():
    """
    Base container class implementing copy methods.
    """

    def copy(self):
        """Returns a shallow copy of this object instance."""
        return copy(self)

    def __deepcopy__(self, memo):
        """Returns a deep copy of the channel object."""
        newobj = copy(self)
        #log.debug('CopyWrapper: _BLACKLISTED_COPY_TYPES = %s', _BLACKLISTED_COPY_TYPES)
        for attr, val in self.__dict__.items():
            # We can't pickle IRCNetwork, so just return a reference of it.
            if not isinstance(val, tuple(_BLACKLISTED_COPY_TYPES)):
                #log.debug('CopyWrapper: copying attr %r', attr)
                setattr(newobj, attr, deepcopy(val))

        memo[id(self)] = newobj

        return newobj

    def deepcopy(self):
        """Returns a deep copy of this object instance."""
        return deepcopy(self)

class CaseInsensitiveFixedSet(collections.abc.Set, CopyWrapper):
    """
    Implements a fixed set storing items case-insensitively.
    """

    def __init__(self, *, data=None):
        if data is not None:
            self._data = data
        else:
            self._data = set()

    @staticmethod
    def _keymangle(key):
        """Converts the given key to lowercase."""
        if isinstance(key, str):
            return key.lower()
        return key

    @classmethod
    def _from_iterable(cls, it):
        """Returns a new iterable instance given the data in 'it'."""
        return cls(data=it)

    def __repr__(self):
        return "%s(%s)" % (self.__class__.__name__, self._data)

    def __iter__(self):
        return iter(self._data)

    def __len__(self):
        return len(self._data)

    def __contains__(self, key):
        return self._data.__contains__(self._keymangle(key))

    def __copy__(self):
        return self.__class__(data=self._data.copy())

class CaseInsensitiveDict(collections.abc.MutableMapping, CaseInsensitiveFixedSet):
    """
    A dictionary storing items case insensitively.
    """
    def __init__(self, *, data=None):
        if data is not None:
            self._data = data
        else:
            self._data = {}

    def __getitem__(self, key):
        key = self._keymangle(key)

        return self._data[key]

    def __setitem__(self, key, value):
        self._data[self._keymangle(key)] = value

    def __delitem__(self, key):
        del self._data[self._keymangle(key)]

class IRCCaseInsensitiveDict(CaseInsensitiveDict):
    """
    A dictionary storing items case insensitively, using IRC case mappings.
    """
    def __init__(self, irc, *, data=None):
        super().__init__(data=data)
        self._irc = irc

    def _keymangle(self, key):
        """Converts the given key to lowercase."""
        if isinstance(key, str):
            return self._irc.to_lower(key)
        return key

    def _from_iterable(self, it):
        """Returns a new iterable instance given the data in 'it'."""
        return self.__class__(self._irc, data=it)

    def __copy__(self):
        return self.__class__(self._irc, data=self._data.copy())

class CaseInsensitiveSet(collections.abc.MutableSet, CaseInsensitiveFixedSet):
    """
    A mutable set storing items case insensitively.
    """

    def add(self, key):
        self._data.add(self._keymangle(key))

    def discard(self, key):
        self._data.discard(self._keymangle(key))

class IRCCaseInsensitiveSet(CaseInsensitiveSet):
    """
    A set storing items case insensitively, using IRC case mappings.
    """
    def __init__(self, irc, *, data=None):
        super().__init__(data=data)
        self._irc = irc

    def _keymangle(self, key):
        """Converts the given key to lowercase."""
        if isinstance(key, str):
            return self._irc.to_lower(key)
        return key

    def _from_iterable(self, it):
        """Returns a new iterable instance given the data in 'it'."""
        return self.__class__(self._irc, data=it)

    def __copy__(self):
        return self.__class__(self._irc, data=self._data.copy())

class CamelCaseToSnakeCase():
    """
    Class which automatically converts missing attributes from camel case to snake case.
    """

    def __getattr__(self, attr):
        """
        Attribute fetching fallback function which normalizes camel case attributes to snake case.
        """
        assert isinstance(attr, str), "Requested attribute %r is not a string!" % attr

        normalized_attr = ''  # Start off with the first letter, which is ignored when processing
        for char in attr:
            if char in string.ascii_uppercase:
                char = '_' + char.lower()
            normalized_attr += char

        classname = self.__class__.__name__
        if normalized_attr == attr:
            # __getattr__ only fires if normal attribute fetching fails, so we can assume that
            # the attribute was tried already and failed.
            raise AttributeError('%s object has no attribute with normalized name %r' % (classname, attr))

        target = getattr(self, normalized_attr)
        log.warning('%s.%s is deprecated, considering migrating to %s.%s!', classname, attr, classname, normalized_attr)
        return target

class DataStore:
    """
    Generic database class. Plugins should use a subclass of this such as JSONDataStore or
    PickleDataStore.
    """
    def __init__(self, name, filename, save_frequency=None, default_db=None, data_dir=None):
        if data_dir is None:
            data_dir = conf.conf['pylink'].get('data_dir', '')

        filename = os.path.join(data_dir, filename)

        self.name = name
        self.filename = filename
        self.tmp_filename = filename + '.tmp'

        log.debug('(DataStore:%s) using implementation %s', self.name, self.__class__.__name__)
        log.debug('(DataStore:%s) database path set to %s', self.name, self.filename)

        self.save_frequency = save_frequency or conf.conf['pylink'].get('save_delay', 300)
        log.debug('(DataStore:%s) saving every %s seconds', self.name, self.save_frequency)

        if default_db is not None:
            self.store = default_db
        else:
            self.store = {}
        self.store_lock = threading.Lock()
        self.exportdb_timer = None

        self.load()

        if self.save_frequency > 0:
            # If autosaving is enabled, start the save_callback loop.
            self.save_callback(starting=True)

    def load(self):
        """
        DataStore load stub. Database implementations should subclass DataStore
        and implement this.
        """
        raise NotImplementedError

    def save_callback(self, starting=False):
        """Start the DB save loop."""
        # don't actually save the first time
        if not starting:
            self.save()

        # schedule saving in a loop.
        self.exportdb_timer = threading.Timer(self.save_frequency, self.save_callback)
        self.exportdb_timer.name = 'DataStore {} save_callback loop'.format(self.name)
        self.exportdb_timer.start()

    def save(self):
        """
        DataStore save stub. Database implementations should subclass DataStore
        and implement this.
        """
        raise NotImplementedError

    def die(self):
        """
        Saves the database and stops any save loops.
        """
        if self.exportdb_timer:
            self.exportdb_timer.cancel()

        self.save()

class JSONDataStore(DataStore):
    def load(self):
        """Loads the database given via JSON."""
        with self.store_lock:
            try:
                with open(self.filename, "r") as f:
                    self.store.clear()
                    self.store.update(json.load(f))
            except (ValueError, IOError, OSError):
                log.info("(DataStore:%s) failed to load database %s; creating a new one in "
                         "memory", self.name, self.filename)

    def save(self):
        """Saves the database given via JSON."""
        with self.store_lock:
            with open(self.tmp_filename, 'w') as f:
                # Pretty print the JSON output for better readability.
                json.dump(self.store, f, indent=4)

                os.rename(self.tmp_filename, self.filename)

class PickleDataStore(DataStore):
    def load(self):
        """Loads the database given via pickle."""
        with self.store_lock:
            try:
                with open(self.filename, "rb") as f:
                    self.store.clear()
                    self.store.update(pickle.load(f))
            except (ValueError, IOError, OSError):
                log.info("(DataStore:%s) failed to load database %s; creating a new one in "
                         "memory", self.name, self.filename)

    def save(self):
        """Saves the database given via pickle."""
        with self.store_lock:
            with open(self.tmp_filename, 'wb') as f:
                # Force protocol version 4 as that is the lowest Python 3.4 supports.
                pickle.dump(self.store, f, protocol=4)

                os.rename(self.tmp_filename, self.filename)
