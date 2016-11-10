"""
structures.py - PyLink data structures module.

This module contains custom data structures that may be useful in various situations.
"""

import collections
import json
import pickle
import os
import threading

from .log import log
from . import conf

class KeyedDefaultdict(collections.defaultdict):
    """
    Subclass of defaultdict allowing the key to be passed to the default factory.
    """
    def __missing__(self, key):
        if self.default_factory is None:
            # If there is no default factory, just let defaultdict handle it
            super().__missing__(self, key)
        else:
            value = self[key] = self.default_factory(key)
            return value

class DataStore:
    """
    Generic database class. Plugins should use a subclass of this such as JSONDataStore or
    PickleDataStore.
    """
    def __init__(self, name, filename, save_frequency=None, default_db=None):
        self.name = name
        self.filename = filename
        self.tmp_filename = filename + '.tmp'

        log.debug('(DataStore:%s) using implementation %s', self.name, self.__class__.__name__)
        log.debug('(DataStore:%s) database path set to %s', self.name, self.filename)

        self.save_frequency = save_frequency or conf.conf['bot'].get('save_delay', 300)
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
