"""Upstream's queue on the ``krita`` stand-in (TASK-28, REQ-17): seeds for a batch of jobs, the
three queue modes, and what cancelling sends to ComfyUI (a mocked client).

Runs with the stand-in loaded (``python -m pytest -p tests.photocraft.upstream_shim ...``); under
upstream's own mock the module is skipped.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import krita
import pytest

from ai_diffusion.backend.api import WorkflowInput
from ai_diffusion.backend.client import ClientEvent, ClientMessage
from ai_diffusion.model.jobs import JobState
from ai_diffusion.model.model import QueueMode
from ai_diffusion.settings import settings

from ..conftest import qtapp
from ..mock.client import MockClient
from ..test_model import _model_env, _wait_for_enqueue

if not hasattr(krita, "attach"):
    pytest.skip("needs the PhotoCraft krita stand-in", allow_module_level=True)


class RecordingClient(MockClient):
    """The mock client, also recording where jobs were queued and what was cancelled."""

    def __init__(self):
        super().__init__()
        self.fronts: list[bool] = []
        self.cancelled: list[list[str]] = []
        self.interrupts = 0

    async def enqueue(self, work: WorkflowInput, front: bool = False) -> str:
        self.fronts.append(front)
        return await super().enqueue(work, front)

    async def cancel(self, job_ids: Any):
        self.cancelled.append(list(job_ids))

    async def interrupt(self):
        self.interrupts += 1


@pytest.fixture(autouse=True)
def recording_client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("tests.test_model.MockClient", RecordingClient)


async def _settle(condition, steps: int = 200):
    for _ in range(steps):
        if condition():
            return
        await asyncio.sleep(0)
    raise TimeoutError("condition not met")


@qtapp
async def test_a_batch_gets_one_seed_per_job(tmp_path: Path):
    async with _model_env(krita.Document(), tmp_path) as (model, client):
        model.fixed_seed = True
        model.seed = 100
        model.batch_count = 3
        model.generate()
        works = await _wait_for_enqueue(client, 3)
        step = settings.batch_size
        assert [w.sampling.seed for w in works if w.sampling] == [100, 100 + step, 100 + 2 * step]
        assert [job.params.seed for job in model.jobs] == [100, 100 + step, 100 + 2 * step]


@qtapp
async def test_queue_modes(tmp_path: Path):
    async with _model_env(krita.Document(), tmp_path) as (model, client):
        assert isinstance(client, RecordingClient)
        model.queue_mode = QueueMode.back
        model.generate()
        await _wait_for_enqueue(client, 1)
        model.queue_mode = QueueMode.front
        model.generate()
        await _wait_for_enqueue(client, 2)
        assert client.fronts == [False, True]

        # Replace cancels what is still queued, then queues at the back.
        queued = [job.id for job in model.jobs if job.state is JobState.queued]
        model.queue_mode = QueueMode.replace
        model.generate()
        await _wait_for_enqueue(client, 3)
        assert client.cancelled == [queued]
        assert client.fronts[-1] is False
        assert [job.id for job in model.jobs] == ["mock-job-2"]


@qtapp
async def test_cancelling_sends_cancel_and_interrupt(tmp_path: Path):
    async with _model_env(krita.Document(), tmp_path) as (model, client):
        assert isinstance(client, RecordingClient)
        model.batch_count = 2
        model.generate()
        await _wait_for_enqueue(client, 2)
        first, second = list(model.jobs)
        assert first.id is not None
        client.push(ClientMessage(ClientEvent.progress, first.id, 0.5))
        await _settle(lambda: first.state is JobState.executing)

        model.cancel(queued=True)
        await _settle(lambda: bool(client.cancelled))
        assert client.cancelled == [[second.id]] and client.interrupts == 0
        model.cancel(active=True)
        await _settle(lambda: client.interrupts == 1)
        assert list(model.jobs) == [first], "the running job stays until ComfyUI reports it"
