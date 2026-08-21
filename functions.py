"""comm Function providers of stapel-forms — deliberately empty in v1.

``forms.get_schema`` as a comm Function has no consumer today: the renderer
reaches the schema over HTTP, and so can a server-side caller. Declaring an
empty provider surface is cheaper than maintaining an unused one — the
first real consumer (Studio hosted mode, onboarding) is what earns the
first entry, and the file exists so that entry has an obvious home.

Everything this module CALLS goes the other way: ``workspaces.check_capability``
through the core client (``authz.py``), and nothing else.
"""

__all__ = []
