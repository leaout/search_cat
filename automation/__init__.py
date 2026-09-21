"""Stable automation services exposed to the plugin platform."""

__all__ = ['AutomationHost']


def __getattr__(name):
    if name == 'AutomationHost':
        from automation.services import AutomationHost
        return AutomationHost
    raise AttributeError(name)
