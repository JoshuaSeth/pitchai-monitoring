# Registry administration and read routes

PR204 moves the two administration routes and four run/artifact/status routes
from the app factory into `app_admin_routes.py` and `app_read_routes.py`.
The app includes each router at its original registration position. Request
contexts read settings from the current ASGI application; they hold no global
tenant or application state. Concrete request-model aliases remain available
at runtime for FastAPI's annotation resolution.

Public request/response schemas, dependency admission, tenant-scoped database
arguments, token generation/hash storage, query limits and error responses
are preserved. Six route descriptions are now documented in OpenAPI. The
remaining OpenAPI schema and route order match the retained parent. File
responses explicitly have no Pydantic response model, as before. The original
synchronous artifact checks remain synchronous; this does not claim a new
filesystem cancellation or nonblocking guarantee.

Status filtering retains its previous display-only malformed-value fallback.
It does not establish incident recovery. Admin/monitor credentials retain
global reads; tenant credentials retain tenant-only results. Invalid tenant
credentials cannot reach status observation. Database cancellation propagates.

The existing local packet
`/mnt/pitchai-dev-data/artifacts/monitoring-dft-746-20261004/` contains:

- `app-read-admin-tests-final.log`: seven focused tests with real in-memory
  ASGI routing. One owned temporary artifact tree is created and removed;
  database operations are substituted. No lifespan is started.
- `app-read-admin-compatibility.json` and its retained runner: 85 comparisons
  against `87ae584`, including response bytes, relevant headers, query/write
  arguments, malformed retained values, cancellation, route order and OpenAPI
  excluding only the six documented descriptions. Network, process and real
  database guards record zero attempts; the fixture tree is removed.
- `app-read-admin-gates-final.log`: all nine scoped analyzers pass for the two
  runtime modules and test. The repository anti-bypass check still fails on
  15 existing findings. Initial typing/style and import-resolution failures
  remain retained; no diagnostic rule or baseline changed.

This component proof does not satisfy the whole-app or required Quality
ratchet gate. PR204 remains a draft and has no runtime admission. Producer
and installed checker/config/clock/reader/journal, internal/off-host receiver,
throughput, retained-copy disposition and Infrastructure624's finite window
remain separate. The original 300-second adoption/drain coverage, durable
selection followed by the next selected read, matching acknowledgement and
fresh health still govern any eventual DFT cutover.
