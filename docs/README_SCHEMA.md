# WebApp Security Map Minimal

A practical, machine-readable schema for **LLM-driven web application crawling and mapping**, designed to capture the **minimum security-relevant structure** of a web application **without embedding security findings**.

This repository defines a normalized exchange format that lets one tool:

1. crawl a web application like a human,
2. record views, UI interactions, client-side state, API activity, entities, and flows,
3. pass that structured map to another tool for later **security analysis**.

The schema is intentionally **security-neutral**. It describes **what the application does**, not whether it is secure.

---

## Why this exists

For later vulnerability analysis, a crawler should not only collect pages or endpoints in isolation. It should preserve the relationships between:

- **who** acted,
- **where** they acted,
- **which UI element** triggered something,
- **which state** was read or written,
- **which endpoint** was called,
- **which concrete request** was observed,
- **which business entity** was involved,
- **which flow** the action belonged to.

This schema is built for exactly that purpose.

---

## Design goals

- **Machine-readable** and easy to validate with JSON Schema
- **LLM-friendly**: supports observed facts, inferred facts, and merged facts
- **Security-relevant**: captures data flows, state changes, and navigation/interaction chains
- **Security-neutral**: contains no findings, no severity, no exploitability claims
- **Composable**: can be produced by one tool and consumed by another
- **Evidence-aware**: every important object can point back to crawl evidence

---

## Core model

The schema is split into these top-level sections:

### `metadata`
Basic information about the crawl run and target scope.

### `actors`
Execution contexts such as anonymous user, authenticated user, admin, service account, or role variant.

### `views`
Application surfaces such as pages, modals, drawers, tabs, wizard steps, popups, or embedded frames.

### `ui_elements`
Interactive frontend elements such as buttons, forms, links, inputs, uploads, pagination, and menu items.

### `state_items`
Client-side state relevant to behavior, such as cookies, local storage, session storage, IndexedDB, memory state, URL parameters, or caches.

### `endpoints`
Abstract backend/API operations such as HTTP endpoints, WebSocket channels, SSE streams, or GraphQL-over-HTTP operations.

### `observed_requests`
Concrete runtime requests observed during the crawl. These are distinct from abstract endpoint definitions.

### `entities`
Business/domain objects observed across views, requests, or flows, such as users, profiles, files, invoices, sessions, or projects.

### `flows`
Named high-level workflows such as login, profile update, checkout, onboarding, password reset, or upload.

### `flow_steps`
Ordered steps inside a flow. A step can point to a UI action, navigation event, request, state read/write, entity load, or mutation.

### `sessions`
Optional crawl session groupings for observed activity.

### `relations`
Explicit cross-object edges when the producer wants to emit graph-style relations directly.

### `evidence`
References to crawl evidence such as DOM snapshots, screenshots, request captures, storage snapshots, and replay traces.

---

## Important modeling decisions

### 1. Endpoints vs observed requests
This repository distinguishes:

- **`endpoints[]`** = the abstract operation
- **`observed_requests[]`** = the concrete call seen during execution

That distinction is essential. A later analysis engine often needs both:

- the structural API shape, and
- the runtime context in which it was actually triggered.

### 2. Flows are first-class
A security analysis rarely depends on pages alone. It depends on chains such as:

- open login page,
- submit credentials,
- receive token,
- set client state,
- redirect to dashboard.

That is why `flows[]` and `flow_steps[]` are first-class citizens.

### 3. Client-side state is explicit
State is not hidden inside views or requests. It is modeled directly because cookies, local storage, session storage, memory state, and URL parameters often influence navigation, behavior, and request generation.

### 4. Observation vs inference is explicit
Because an LLM-driven crawler may infer some relationships instead of directly observing them, objects include:

- `source_mode`: `observed`, `inferred`, or `merged`
- `confidence`: numeric confidence score
- `evidence_refs`: references into `evidence[]`

This allows downstream tools to reason differently about hard evidence and inferred structure.

---

## Repository structure

```text
webapp-security-map-schema/
├── README.md
└── schema/
    └── webapp-security-map-minimal.schema.json
```

---

## Top-level document shape

A valid document has this top-level structure:

```json
{
  "schema_name": "WebAppSecurityMapMinimal",
  "schema_version": "1.0",
  "metadata": { ... },
  "actors": [],
  "views": [],
  "ui_elements": [],
  "state_items": [],
  "endpoints": [],
  "observed_requests": [],
  "entities": [],
  "flows": [],
  "flow_steps": [],
  "sessions": [],
  "relations": [],
  "evidence": []
}
```

All sections are required. They may be empty arrays if the crawl did not discover anything for that section.

---

## Minimal example

```json
{
  "schema_name": "WebAppSecurityMapMinimal",
  "schema_version": "1.0",
  "metadata": {
    "target_base_url": "https://example.test",
    "app_name": "Example App",
    "crawl_started_at": "2026-03-30T12:00:00Z",
    "crawl_finished_at": "2026-03-30T12:10:00Z",
    "crawl_scope": {
      "allowed_hosts": ["example.test"],
      "allowed_path_prefixes": ["/"]
    },
    "crawler_context": {
      "run_id": "run-001",
      "model_name": "example-llm",
      "browser_profile_id": "profile-001",
      "notes": null
    }
  },
  "actors": [
    {
      "id": "actor-anon",
      "label": "Anonymous",
      "kind": "anonymous",
      "auth_state": "unauthenticated",
      "role_labels": [],
      "parent_actor_id": null,
      "session_capabilities": [],
      "source_mode": "observed",
      "confidence": 1,
      "evidence_refs": ["ev-url-login"],
      "notes": null
    }
  ],
  "views": [
    {
      "id": "view-login",
      "label": "Login",
      "view_type": "page",
      "canonical_route": "/login",
      "url_examples": ["https://example.test/login"],
      "title_text": "Login",
      "parent_view_id": null,
      "reachable_actor_ids": ["actor-anon"],
      "required_state_tags": [],
      "produced_state_tags": [],
      "entity_ids": [],
      "source_mode": "observed",
      "confidence": 1,
      "evidence_refs": ["ev-url-login"],
      "notes": null
    }
  ],
  "ui_elements": [
    {
      "id": "ui-login-submit",
      "view_id": "view-login",
      "kind": "button",
      "label": "Sign in",
      "selector_hint": "button[type=submit]",
      "action_type": "submit",
      "parameter_defs": [],
      "reads_state_item_ids": [],
      "writes_state_item_ids": [],
      "expected_endpoint_ids": ["ep-login"],
      "source_mode": "observed",
      "confidence": 0.95,
      "evidence_refs": ["ev-dom-login"],
      "notes": null
    }
  ],
  "state_items": [
    {
      "id": "state-session-cookie",
      "storage_kind": "cookie",
      "key": "session",
      "scope": "/",
      "persistence": "browser_session",
      "observed_shape": "opaque string",
      "example_redacted": "<redacted>",
      "produced_by_ids": ["req-login-1"],
      "consumed_by_ids": [],
      "source_mode": "observed",
      "confidence": 0.95,
      "evidence_refs": ["ev-resp-login"],
      "notes": null
    }
  ],
  "endpoints": [
    {
      "id": "ep-login",
      "protocol": "https",
      "host": "example.test",
      "method": "POST",
      "path_template": "/api/login",
      "operation_name": null,
      "request_contract": {
        "header_names": ["content-type"],
        "path_params": [],
        "query_params": [],
        "body_content_types": ["application/json"],
        "body_shape": "json object"
      },
      "response_contract": {
        "status_codes": [200, 401],
        "header_names": ["set-cookie"],
        "body_content_types": ["application/json"],
        "body_shape": "json object"
      },
      "auth_inputs_observed": [],
      "entity_ids": [],
      "source_mode": "observed",
      "confidence": 1,
      "evidence_refs": ["ev-req-login"],
      "notes": null
    }
  ],
  "observed_requests": [
    {
      "id": "req-login-1",
      "session_id": "sess-1",
      "order": 1,
      "actor_id": "actor-anon",
      "endpoint_id": "ep-login",
      "initiated_by_ui_element_id": "ui-login-submit",
      "preceding_request_id": null,
      "request_instance": {
        "url": "https://example.test/api/login",
        "header_names": ["content-type"],
        "query_keys": [],
        "body_keys": ["username", "password"],
        "body_shape": "json object",
        "body_example_redacted": {
          "username": "<redacted>",
          "password": "<redacted>"
        }
      },
      "response_instance": {
        "status_code": 200,
        "header_names": ["set-cookie"],
        "body_shape": "json object",
        "body_keys": ["redirectUrl"] ,
        "body_example_redacted": {
          "redirectUrl": "/dashboard"
        }
      },
      "correlation": {
        "traceparent_present": false,
        "tracestate_present": false,
        "request_id_headers": []
      },
      "state_reads": [],
      "state_writes": ["state-session-cookie"],
      "resulting_view_id": "view-dashboard",
      "resulting_entity_ids": [],
      "source_mode": "observed",
      "confidence": 0.95,
      "evidence_refs": ["ev-req-login", "ev-resp-login"],
      "notes": null
    }
  ],
  "entities": [],
  "flows": [
    {
      "id": "flow-login",
      "name": "Login",
      "goal": "Authenticate a user",
      "actor_ids": ["actor-anon"],
      "entry_view_id": "view-login",
      "trigger_ui_element_id": "ui-login-submit",
      "preconditions": [],
      "postconditions": ["authenticated"],
      "step_ids": ["flow-step-1", "flow-step-2"],
      "entity_ids": [],
      "source_mode": "merged",
      "confidence": 0.9,
      "evidence_refs": ["ev-dom-login", "ev-req-login", "ev-resp-login"],
      "notes": null
    }
  ],
  "flow_steps": [
    {
      "id": "flow-step-1",
      "flow_id": "flow-login",
      "order": 1,
      "step_type": "ui_action",
      "ref_id": "ui-login-submit",
      "expects_from_step_id": null,
      "produces_state_tags": [],
      "consumes_state_tags": [],
      "source_mode": "observed",
      "confidence": 1,
      "evidence_refs": ["ev-dom-login"],
      "notes": null
    },
    {
      "id": "flow-step-2",
      "flow_id": "flow-login",
      "order": 2,
      "step_type": "request",
      "ref_id": "req-login-1",
      "expects_from_step_id": "flow-step-1",
      "produces_state_tags": ["authenticated"],
      "consumes_state_tags": [],
      "source_mode": "observed",
      "confidence": 0.95,
      "evidence_refs": ["ev-req-login", "ev-resp-login"],
      "notes": null
    }
  ],
  "sessions": [
    {
      "id": "sess-1",
      "actor_id": "actor-anon",
      "started_at": "2026-03-30T12:00:00Z",
      "ended_at": "2026-03-30T12:10:00Z",
      "initial_url": "https://example.test/login",
      "final_url": "https://example.test/dashboard",
      "observed_view_ids": ["view-login"],
      "observed_flow_ids": ["flow-login"],
      "observed_request_ids": ["req-login-1"],
      "source_mode": "observed",
      "confidence": 1,
      "evidence_refs": ["ev-url-login"],
      "notes": null
    }
  ],
  "relations": [],
  "evidence": [
    {
      "id": "ev-url-login",
      "kind": "url_observation",
      "source_ref": "crawl://url/1",
      "excerpt_redacted": null,
      "timestamp": "2026-03-30T12:00:00Z",
      "notes": null
    },
    {
      "id": "ev-dom-login",
      "kind": "dom_snapshot",
      "source_ref": "crawl://dom/1",
      "excerpt_redacted": null,
      "timestamp": "2026-03-30T12:00:01Z",
      "notes": null
    },
    {
      "id": "ev-req-login",
      "kind": "request_capture",
      "source_ref": "crawl://req/1",
      "excerpt_redacted": null,
      "timestamp": "2026-03-30T12:00:02Z",
      "notes": null
    },
    {
      "id": "ev-resp-login",
      "kind": "response_capture",
      "source_ref": "crawl://resp/1",
      "excerpt_redacted": null,
      "timestamp": "2026-03-30T12:00:03Z",
      "notes": null
    }
  ]
}
```

---

## Recommended producer behavior

If you are building the crawler that emits this format:

- **Do not store secrets in cleartext**. Redact values but preserve structural shape.
- **Do not collapse abstract API shape and concrete runtime traffic** into one object.
- **Do not mix inference and observation silently**. Use `source_mode` and `confidence`.
- **Do not drop ordering information** for requests or flow steps.
- **Do not emit free-form text when you can emit structure**.
- **Do not emit security findings here**. Keep this schema descriptive only.

---

## Recommended consumer behavior

If you are building the downstream security-analysis engine:

- treat `observed` as stronger than `inferred`
- use `evidence_refs` for traceability
- use `flow_steps.order` and `observed_requests.order` for sequence reasoning
- use `state_reads` and `state_writes` for stateful logic reasoning
- use `entity_ids` and identifier fields for object-level reasoning
- use `reachable_actor_ids` and actor context for permission- and path-based reasoning

---

## Validation

The authoritative schema file is:

```text
schema/webapp-security-map-minimal.schema.json
```

You can validate a document with any JSON Schema validator that supports **Draft 2020-12**.

Example with `ajv-cli`:

```bash
ajv validate \
  -s schema/webapp-security-map-minimal.schema.json \
  -d your-map.json
```

---

## Suggested repository title

Recommended repository name:

```text
webapp-security-map-schema
```

Why this name:

- **webapp**: clearly states the target domain
- **security-map**: indicates that the output is intended for later security analysis
- **schema**: makes it explicit that this repository is the format definition, not the crawler itself

Alternative names:

- `webapp-flowmap-schema`
- `app-cartography-schema`
- `webapp-behavior-map`
- `security-relevant-webapp-map`

If you want the most professional and self-explanatory name, use:

**`webapp-security-map-schema`**

---

## Versioning approach

Recommended:

- use semantic versioning for the repository
- keep `schema_version` in produced documents
- treat new required fields or removed fields as breaking changes
- keep optional enrichment backward-compatible when possible

---

## Scope boundary

This schema is for:

- web application mapping
- interaction mapping
- API mapping
- client-state mapping
- entity/flow mapping
- structured handoff into later security tooling

This schema is **not** for:

- vulnerability findings
- CVSS scoring
- exploit payload libraries
- remediation tracking
- test-case results
- risk acceptance

Those belong in separate schemas.

---

## License

Choose the license that matches your intended usage. If you want broad reuse, MIT is usually the simplest default.
