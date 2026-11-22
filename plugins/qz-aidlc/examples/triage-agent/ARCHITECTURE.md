# Support ticket triage

A fixed workflow with one model call classifies each new ticket, attaches the customer's shipments and sends anything uncertain or sensitive to a person.

## Enterprise view

Where the system sits: the people, the business systems around it and who owns what.

```mermaid
flowchart TB
  subgraph g_E1["People"]
    n_cust(["Customers<br/>raise tickets by e-mail and portal"])
    n_agents(["Support agents<br/>work tickets from their queue"])
    n_duty(["Duty manager<br/>handles escalations and low-confidence tickets"])
  end
  subgraph g_E2["Client systems"]
    n_helpdesk[/"Helpdesk<br/>system of record for tickets and queues"/]
    n_triage["Ticket triage<br/>the system being designed"]
    n_orders[/"Order system<br/>shipments by customer"/]
  end
  subgraph g_E3["Platform"]
    n_bedrock[/"Amazon Bedrock (EU)<br/>hosted models inside the client's AWS account"/]
    n_obs["Observability<br/>traces, cost and accuracy dashboards"]
  end
  n_cust -->|"new ticket"| n_helpdesk
  n_helpdesk -->|"ticket created event"| n_triage
  n_triage -->|"shipments for this customer"| n_orders
  n_triage -->|"ticket text for classification"| n_bedrock
  n_triage -->|"queue, reason, shipments"| n_helpdesk
  n_helpdesk -->|"ticket in the right queue"| n_agents
  n_triage -.->|"escalation or low confidence"| n_duty
  n_triage -->|"trace and cost per ticket"| n_obs
```

| Box | What it does | Kind |
|---|---|---|
| Customers | raise tickets by e-mail and portal | person |
| Support agents | work tickets from their queue | team |
| Duty manager | handles escalations and low-confidence tickets | person |
| Helpdesk | system of record for tickets and queues | external |
| Ticket triage | the system being designed | system |
| Order system | shipments by customer | external |
| Amazon Bedrock (EU) | hosted models inside the client's AWS account | external |
| Observability | traces, cost and accuracy dashboards | observability |

How it flows:

1. **A ticket arrives.** The customer raises a ticket; the helpdesk tells triage a new one exists.
2. **Triage gathers and decides.** Triage reads the customer's shipments and asks the model for a queue and a reason.
3. **The ticket lands.** Queue, reason and shipments are written back, and the ticket shows up in the right team's queue.
4. **People keep the hard ones.** Escalations and low-confidence tickets go to the duty manager, and every decision leaves a trace.

Animated: `arch/diagrams/enterprise/index.html`

## System view

What is inside: services, agents, stores, the model plane and the controls between them.

```mermaid
flowchart TB
  subgraph g_S1["Entry · trust boundary: untrusted input: ticket text"]
    n_hook["Webhook receiver<br/>verifies the helpdesk signature"]
    n_queue["Work queue<br/>one message per ticket, retried once"]
  end
  subgraph g_S2["Triage service"]
    n_worker["Triage worker<br/>orchestrates lookup, classification and write-back"]
    n_guard["Input and tool guard<br/>pins the customer id, screens injected instructions"]
    n_lookup["Shipment lookup<br/>order API client with a timeout"]
  end
  subgraph g_S3["Model plane"]
    n_classifier["Classifier call<br/>one structured call returning queue, reason, confidence"]
    n_budget["Token budget<br/>caps tokens per ticket"]
  end
  subgraph g_S4["State and evidence"]
    n_store[("Decision store<br/>queue, reason, confidence per ticket")]
    n_traces[("Trace store<br/>every call, 90 days")]
    n_ledger["Cost ledger<br/>tokens and cost per ticket"]
  end
  n_hook -->|"verified ticket id"| n_queue
  n_queue -->|"ticket to triage"| n_worker
  n_worker ==>|"ticket text and customer id"| n_guard
  n_guard -->|"customer id from the record"| n_lookup
  n_guard -->|"screened text"| n_classifier
  n_budget -->|"token cap"| n_classifier
  n_classifier -->|"queue, reason, confidence"| n_worker
  n_worker -->|"decision"| n_store
  n_worker -->|"spans"| n_traces
  n_classifier -->|"token usage"| n_ledger
  classDef qzguard fill:#E8F1FB,stroke:#0A2540,stroke-width:2px,color:#0A2540;
  class n_guard,n_budget qzguard;
```

| Box | What it does | Kind |
|---|---|---|
| Webhook receiver | verifies the helpdesk signature | service |
| Work queue | one message per ticket, retried once | queue |
| Triage worker | orchestrates lookup, classification and write-back | service |
| Input and tool guard | pins the customer id, screens injected instructions | guard |
| Shipment lookup | order API client with a timeout | tool |
| Classifier call | one structured call returning queue, reason, confidence | model |
| Token budget | caps tokens per ticket | guard |
| Decision store | queue, reason, confidence per ticket | store |
| Trace store | every call, 90 days | store |
| Cost ledger | tokens and cost per ticket | observability |

How it flows:

1. **Verified in.** Only signed helpdesk events enter; each ticket becomes one queued message.
2. **Guarded before anything runs.** The guard fixes the customer id from the ticket record and screens the text before any tool or model sees it.
3. **One bounded model call.** A single structured call returns queue, reason and confidence, inside a per-ticket token cap.
4. **Everything is kept.** The decision, the trace and the cost of every ticket are stored for 90 days.

Animated: `arch/diagrams/system/index.html`

## Workflow view

How one task moves: agent steps, tool calls, the checks on each and where a person approves.

```mermaid
flowchart TB
  subgraph g_W1["Input · trust boundary: untrusted content"]
    n_ticket[/"New ticket<br/>text written by a customer"/]
  end
  subgraph g_W2["Checks"]
    n_screen["Screen and pin<br/>strip instructions, pin customer id"]
    n_conf["Confidence check<br/>0.70 threshold and escalation terms"]
  end
  subgraph g_W3["Work"]
    n_agent{{"Triage step<br/>classifies with one model call"}}
    n_ship["get_shipments<br/>read-only order lookup"]
    n_write["set_queue<br/>writes queue and reason to the helpdesk"]
  end
  subgraph g_W4["People"]
    n_gate{{"Duty manager review<br/>approves or re-routes uncertain and sensitive tickets"}}
    n_assigned(["Queue owner<br/>receives the ticket"])
  end
  n_ticket -->|"raw text"| n_screen
  n_screen -->|"pinned customer id"| n_ship
  n_screen -->|"screened text"| n_agent
  n_ship -->|"open shipments"| n_agent
  n_agent -->|"queue, reason, confidence"| n_conf
  n_conf -->|"confident and not sensitive"| n_write
  n_conf -.->|"below 0.70 or escalation term"| n_gate
  n_gate -.->|"approved or corrected queue"| n_write
  n_write -->|"ticket in queue"| n_assigned
  classDef qzgate fill:#FFF4E5,stroke:#F47B20,stroke-width:2px,color:#0A2540;
  class n_gate qzgate;
  classDef qzguard fill:#E8F1FB,stroke:#0A2540,stroke-width:2px,color:#0A2540;
  class n_screen,n_conf qzguard;
```

| Box | What it does | Kind |
|---|---|---|
| New ticket | text written by a customer | external |
| Screen and pin | strip instructions, pin customer id | guard |
| Confidence check | 0.70 threshold and escalation terms | guard |
| Triage step | classifies with one model call | agent |
| get_shipments | read-only order lookup | tool |
| set_queue | writes queue and reason to the helpdesk | tool |
| Duty manager review | approves or re-routes uncertain and sensitive tickets | gate |
| Queue owner | receives the ticket | team |

How it flows:

1. **Treat the ticket as data.** The text is screened and the customer id is taken from the ticket record, so nothing in the text can redirect a lookup.
2. **Classify with context.** With the customer's shipments in hand, one model call proposes a queue, a reason and a confidence.
3. **Confident tickets flow through.** If confidence is 0.70 or more and no escalation term appears, the queue is set and the owner sees the ticket.
4. **A person decides the rest.** Anything uncertain or sensitive waits for the duty manager, who approves or corrects the queue.

Animated: `arch/diagrams/workflow/index.html`
