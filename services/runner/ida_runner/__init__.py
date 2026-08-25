"""``ida_runner`` -- the queue worker.

Per **D-5** the runner shares the Python image with the API and differs only by
entrypoint.  It is also where the LLM judge will live when it lands: a judge is
a harness code path invoked by this worker, **not** a separate service.

Loop: ``BLPOP`` a :class:`~ida_core.contracts.RunJobMessage` -> claim the run ->
:func:`ida_harness.runner.run_task` -> persist results + rollup -> repeat.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
