"""Keep SPA routes while dropping ordinary in-page anchors."""


def route_fragment(fragment):
    return fragment if fragment.startswith(("/", "!/")) else ""
