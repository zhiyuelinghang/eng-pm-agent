# -*- coding: utf-8 -*-
"""The mixin for agentscope."""


class DictMixin(dict):
    """The dictionary mixin that allows attribute-style access."""

    __setattr__ = dict.__setitem__

    def __getattr__(self, key: str) -> object:
        """Get a dictionary item through attribute-style access.

        Missing dictionary keys must follow normal attribute semantics so
        ``hasattr`` and ``getattr(..., default)`` continue to work.
        """
        try:
            return dict.__getitem__(self, key)
        except KeyError as error:
            raise AttributeError(key) from error
