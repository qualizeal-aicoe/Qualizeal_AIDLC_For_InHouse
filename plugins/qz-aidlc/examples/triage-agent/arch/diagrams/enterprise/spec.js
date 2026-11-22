/* Generated from arch/architecture.json by qz arch diagrams. Edit the model, not this file. */
window.QZ_ARCH = {
  "brand": {
    "client": "Northwind Logistics",
    "clientLogo": "",
    "product": "Support ticket triage",
    "title": "Support ticket triage · Enterprise view"
  },
  "eyebrow": "Enterprise view",
  "title": "Where triage sits",
  "subtitle": "Where the system sits: the people, the business systems around it and who owns what.",
  "layers": [
    {
      "id": "E1",
      "name": "People",
      "nodes": [
        {
          "id": "cust",
          "label": "Customers",
          "sub": "raise tickets by e-mail and portal",
          "icon": "user"
        },
        {
          "id": "agents",
          "label": "Support agents",
          "sub": "work tickets from their queue",
          "icon": "users"
        },
        {
          "id": "duty",
          "label": "Duty manager",
          "sub": "handles escalations and low-confidence tickets",
          "icon": "user"
        }
      ]
    },
    {
      "id": "E2",
      "name": "Client systems",
      "nodes": [
        {
          "id": "helpdesk",
          "label": "Helpdesk",
          "sub": "system of record for tickets and queues",
          "icon": "globe"
        },
        {
          "id": "triage",
          "label": "Ticket triage",
          "sub": "the system being designed",
          "icon": "box"
        },
        {
          "id": "orders",
          "label": "Order system",
          "sub": "shipments by customer",
          "icon": "globe"
        }
      ]
    },
    {
      "id": "E3",
      "name": "Platform",
      "nodes": [
        {
          "id": "bedrock",
          "label": "Amazon Bedrock (EU)",
          "sub": "hosted models inside the client's AWS account",
          "icon": "globe"
        },
        {
          "id": "obs",
          "label": "Observability",
          "sub": "traces, cost and accuracy dashboards",
          "icon": "gauge"
        }
      ]
    }
  ],
  "flows": [
    {
      "from": "cust",
      "to": "helpdesk",
      "label": "new ticket"
    },
    {
      "from": "helpdesk",
      "to": "triage",
      "label": "ticket created event"
    },
    {
      "from": "triage",
      "to": "orders",
      "label": "shipments for this customer"
    },
    {
      "from": "triage",
      "to": "bedrock",
      "label": "ticket text for classification"
    },
    {
      "from": "triage",
      "to": "helpdesk",
      "label": "queue, reason, shipments"
    },
    {
      "from": "helpdesk",
      "to": "agents",
      "label": "ticket in the right queue"
    },
    {
      "from": "triage",
      "to": "duty",
      "label": "escalation or low confidence",
      "tone": "warn"
    },
    {
      "from": "triage",
      "to": "obs",
      "label": "trace and cost per ticket"
    }
  ],
  "steps": [
    {
      "title": "A ticket arrives",
      "flows": [
        0,
        1
      ],
      "caption": "The customer raises a ticket; the helpdesk tells triage a new one exists."
    },
    {
      "title": "Triage gathers and decides",
      "flows": [
        2,
        3
      ],
      "caption": "Triage reads the customer's shipments and asks the model for a queue and a reason."
    },
    {
      "title": "The ticket lands",
      "flows": [
        4,
        5
      ],
      "caption": "Queue, reason and shipments are written back, and the ticket shows up in the right team's queue."
    },
    {
      "title": "People keep the hard ones",
      "flows": [
        6,
        7
      ],
      "caption": "Escalations and low-confidence tickets go to the duty manager, and every decision leaves a trace."
    }
  ]
};
