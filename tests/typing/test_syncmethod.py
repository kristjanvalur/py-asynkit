from __future__ import annotations

from asynkit import syncmethod


class Base:
    async def arun(self, *, yield_every: int | None = None) -> None:
        pass

    run = syncmethod(arun)


class Derived(Base):
    def run(self, *, yield_every: int | None = None) -> None:
        raise NotImplementedError


def accepts_sync_runner(runner: Base) -> None:
    runner.run(yield_every=1)
    Base.run(runner, yield_every=1)
