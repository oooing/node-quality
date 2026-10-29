"""Shared errors and stable node identity; never connects to the user's controller."""
import hashlib
import json


class PanelError(Exception):
    pass


class QueryBlocked(PanelError):
    def __init__(self, message, kind=None):
        super().__init__(message)
        self.kind = kind


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def node_id(profile_id, proxy):
    return digest([profile_id, proxy.get('name'), proxy.get('type'), proxy.get('server'), proxy.get('port')])[:24]
