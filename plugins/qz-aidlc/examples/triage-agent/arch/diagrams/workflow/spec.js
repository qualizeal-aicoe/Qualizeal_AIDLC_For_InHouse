/* Generated from arch/architecture.json by qz arch diagrams. Edit the model, not this file. */
window.QZ_ARCH = {
  "brand": {
    "client": "Northwind Logistics",
    "clientLogo": "",
    "product": "Support ticket triage",
    "title": "Support ticket triage · Workflow view"
  },
  "eyebrow": "Workflow view",
  "title": "One ticket, start to finish",
  "subtitle": "How one task moves: agent steps, tool calls, the checks on each and where a person approves.",
  "layers": [
    {
      "id": "W1",
      "name": "Input · untrusted content",
      "nodes": [
        {
          "id": "ticket",
          "label": "New ticket",
          "sub": "text written by a customer",
          "icon": "globe"
        }
      ]
    },
    {
      "id": "W2",
      "name": "Checks",
      "nodes": [
        {
          "id": "screen",
          "label": "Screen and pin",
          "sub": "strip instructions, pin customer id",
          "icon": "shield-check"
        },
        {
          "id": "conf",
          "label": "Confidence check",
          "sub": "0.70 threshold and escalation terms",
          "icon": "shield-check"
        }
      ]
    },
    {
      "id": "W3",
      "name": "Work",
      "nodes": [
        {
          "id": "agent",
          "label": "Triage step",
          "sub": "classifies with one model call",
          "icon": "bot"
        },
        {
          "id": "ship",
          "label": "get_shipments",
          "sub": "read-only order lookup",
          "icon": "wrench"
        },
        {
          "id": "write",
          "label": "set_queue",
          "sub": "writes queue and reason to the helpdesk",
          "icon": "wrench"
        }
      ]
    },
    {
      "id": "W4",
      "name": "People",
      "nodes": [
        {
          "id": "gate",
          "label": "Duty manager review",
          "sub": "approves or re-routes uncertain and sensitive tickets",
          "icon": "user"
        },
        {
          "id": "assigned",
          "label": "Queue owner",
          "sub": "receives the ticket",
          "icon": "users"
        }
      ]
    }
  ],
  "flows": [
    {
      "from": "ticket",
      "to": "screen",
      "label": "raw text"
    },
    {
      "from": "screen",
      "to": "ship",
      "label": "pinned customer id"
    },
    {
      "from": "screen",
      "to": "agent",
      "label": "screened text"
    },
    {
      "from": "ship",
      "to": "agent",
      "label": "open shipments"
    },
    {
      "from": "agent",
      "to": "conf",
      "label": "queue, reason, confidence"
    },
    {
      "from": "conf",
      "to": "write",
      "label": "confident and not sensitive"
    },
    {
      "from": "conf",
      "to": "gate",
      "label": "below 0.70 or escalation term",
      "tone": "warn"
    },
    {
      "from": "gate",
      "to": "write",
      "label": "approved or corrected queue",
      "tone": "warn"
    },
    {
      "from": "write",
      "to": "assigned",
      "label": "ticket in queue"
    }
  ],
  "steps": [
    {
      "title": "Treat the ticket as data",
      "flows": [
        0,
        1,
        2
      ],
      "caption": "The text is screened and the customer id is taken from the ticket record, so nothing in the text can redirect a lookup."
    },
    {
      "title": "Classify with context",
      "flows": [
        3,
        4
      ],
      "caption": "With the customer's shipments in hand, one model call proposes a queue, a reason and a confidence."
    },
    {
      "title": "Confident tickets flow through",
      "flows": [
        5,
        8
      ],
      "caption": "If confidence is 0.70 or more and no escalation term appears, the queue is set and the owner sees the ticket."
    },
    {
      "title": "A person decides the rest",
      "flows": [
        6,
        7
      ],
      "caption": "Anything uncertain or sensitive waits for the duty manager, who approves or corrects the queue."
    }
  ]
};
