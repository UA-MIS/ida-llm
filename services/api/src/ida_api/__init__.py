"""ida_api -- the platform's HTTP API.

SCAFFOLDING except for the health endpoints, which are NOT scaffolding: the chart
probes /healthz and /readyz, so their semantics are part of the deployment
contract. See app.py for why the two differ.
"""

__version__ = "0.1.0"
