"""Request-scoped memoizing wrapper: identical repo calls hit the database once."""


class Memo:
    def __init__(self, repo):
        self._repo = repo
        self._cache = {}

    def __getattr__(self, name):
        fn = getattr(self._repo, name)
        if not callable(fn):
            return fn

        def call(*a, **k):
            key = (name, a, tuple(sorted(k.items())))
            if key not in self._cache:
                self._cache[key] = fn(*a, **k)
            return self._cache[key]

        return call
