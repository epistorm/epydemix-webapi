"""Bounded simulation execution in a disposable, killable process."""

import logging
import multiprocessing
import threading
import time
import traceback

from ..api.v1.schemas.simulation import BuiltinPopulationConfig
from ..config import settings

logger = logging.getLogger(__name__)
_admission = threading.BoundedSemaphore(1)


class SimulationBusyError(Exception):
    """This API worker already has a simulation in progress."""


class SimulationTimeoutError(Exception):
    """The simulation exhausted its execution deadline."""


def _simulate(connection, request, population):
    from .simulation_service import run_simulation

    try:
        connection.send(("ok", run_simulation(request, population=population)))
    except ValueError as exc:
        connection.send(("invalid", str(exc)))
    except Exception:
        connection.send(("error", traceback.format_exc()))
    finally:
        connection.close()


def run_simulation(request):
    """Load cached inputs, admit one job per worker, terminate expired CPU work."""
    from .population_service import _resolve_contacts_source, get_simulation_population

    if not _admission.acquire(blocking=False):
        raise SimulationBusyError("A simulation is already running on this worker; retry shortly")
    deadline = time.monotonic() + settings.request_timeout
    process = None
    timer = None
    expired = threading.Event()
    receiver = sender = None
    try:
        population = get_simulation_population(
            request.population,
            timeout=min(settings.population_load_timeout, settings.request_timeout),
        )
        if isinstance(request.population, BuiltinPopulationConfig):
            # Resolve metadata here too; the CPU child must not fetch locations again.
            resolved = _resolve_contacts_source(
                request.population.name, request.population.contacts_source
            )
            request = request.model_copy(update={
                "population": request.population.model_copy(update={"contacts_source": resolved})
            })
        request.check_work_budget(len(population.Nk), len(population.contact_matrices))
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise SimulationTimeoutError("Simulation execution deadline exceeded")
        # Spawn avoids forking a multithreaded web worker and inheriting locked libraries.
        context = multiprocessing.get_context("spawn")
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(target=_simulate, args=(sender, request, population), daemon=True)
        process.start()
        sender.close()

        def expire():
            expired.set()
            if process.is_alive():
                process.kill()

        timer = threading.Timer(max(0, deadline - time.monotonic()), expire)
        timer.start()
        if not receiver.poll(max(0, deadline - time.monotonic())):
            raise SimulationTimeoutError("Simulation execution deadline exceeded")
        try:
            status, value = receiver.recv()
        except EOFError as exc:
            if expired.is_set():
                raise SimulationTimeoutError("Simulation execution deadline exceeded") from exc
            raise RuntimeError("Simulation worker exited without returning a result") from exc
        if expired.is_set():
            raise SimulationTimeoutError("Simulation execution deadline exceeded")
        if status == "invalid":
            raise ValueError(value)
        if status == "error":
            logger.error("Simulation worker failed:\n%s", value)
            raise RuntimeError("Simulation worker failed")
        return value
    finally:
        if timer is not None:
            timer.cancel()
            timer.join()
        if process is not None and process.pid is not None:
            if process.is_alive():
                process.kill()
            process.join()
            process.close()
        if receiver is not None:
            receiver.close()
        if sender is not None:
            sender.close()
        _admission.release()
