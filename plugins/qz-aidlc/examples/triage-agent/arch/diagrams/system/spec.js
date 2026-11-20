/* Generated from arch/architecture.json by qz arch diagrams. Edit the model, not this file. */
window.QZ_ARCH = {
  "brand": {
    "client": "Northwind Logistics",
    "clientLogo": "",
    "product": "Support ticket triage",
    "title": "Support ticket triage · System view"
  },
  "eyebrow": "System view",
  "title": "Inside ticket triage",
  "subtitle": "What is inside: services, agents, stores, the model plane and the controls between them.",
  "layers": [
    {
      "id": "S1",
      "name": "Entry · untrusted input: ticket text",
      "nodes": [
        {
          "id": "hook",
          "label": "Webhook receiver",
          "sub": "verifies the helpdesk signature",
          "icon": "server"
        },
        {
          "id": "queue",
          "label": "Work queue",
          "sub": "one message per ticket, retried once",
          "icon": "layers"
        }
      ]
    },
    {
      "id": "S2",
      "name": "Triage service",
      "nodes": [
        {
          "id": "worker",
          "label": "Triage worker",
          "sub": "orchestrates lookup, classification and write-back",
          "icon": "server"
        },
        {
          "id": "guard",
          "label": "Input and tool guard",
          "sub": "pins the customer id, screens injected instructions",
          "icon": "shield-check"
        },
        {
          "id": "lookup",
          "label": "Shipment lookup",
          "sub": "order API client with a timeout",
          "icon": "wrench"
        }
      ]
    },
    {
      "id": "S3",
      "name": "Model plane",
      "nodes": [
        {
          "id": "classifier",
          "label": "Classifier call",
          "sub": "one structured call returning queue, reason, confidence",
          "icon": "brain"
        },
        {
          "id": "budget",
          "label": "Token budget",
          "sub": "caps tokens per ticket",
          "icon": "shield-check"
        }
      ]
    },
    {
      "id": "S4",
      "name": "State and evidence",
      "nodes": [
        {
          "id": "store",
          "label": "Decision store",
          "sub": "queue, reason, confidence per ticket",
          "icon": "database"
        },
        {
          "id": "traces",
          "label": "Trace store",
          "sub": "every call, 90 days",
          "icon": "database"
        },
        {
          "id": "ledger",
          "label": "Cost ledger",
          "sub": "tokens and cost per ticket",
          "icon": "gauge"
        }
      ]
    }
  ],
  "flows": [
    {
      "from": "hook",
      "to": "queue",
      "label": "verified ticket id"
    },
    {
      "from": "queue",
      "to": "worker",
      "label": "ticket to triage"
    },
    {
      "from": "worker",
      "to": "guard",
      "label": "ticket text and customer id",
      "tone": "accent"
    },
    {
      "from": "guard",
      "to": "lookup",
      "label": "customer id from the record"
    },
    {
      "from": "guard",
      "to": "classifier",
      "label": "screened text"
    },
    {
      "from": "budget",
      "to": "classifier",
      "label": "token cap"
    },
    {
      "from": "classifier",
      "to": "worker",
      "label": "queue, reason, confidence"
    },
    {
      "from": "worker",
      "to": "store",
      "label": "decision"
    },
    {
      "from": "worker",
      "to": "traces",
      "label": "spans"
    },
    {
      "from": "classifier",
      "to": "ledger",
      "label": "token usage"
    }
  ],
  "steps": [
    {
      "title": "Verified in",
      "flows": [
        0,
        1
      ],
      "caption": "Only signed helpdesk events enter; each ticket becomes one queued message."
    },
    {
      "title": "Guarded before anything runs",
      "flows": [
        2,
        3,
        4
      ],
      "caption": "The guard fixes the customer id from the ticket record and screens the text before any tool or model sees it."
    },
    {
      "title": "One bounded model call",
      "flows": [
        5,
        6
      ],
      "caption": "A single structured call returns queue, reason and confidence, inside a per-ticket token cap."
    },
    {
      "title": "Everything is kept",
      "flows": [
        7,
        8,
        9
      ],
      "caption": "The decision, the trace and the cost of every ticket are stored for 90 days."
    }
  ]
};
