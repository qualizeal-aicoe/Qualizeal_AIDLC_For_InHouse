# Requirements: order support

## Requirement 1: Order lookup
**User story:** As a customer, I want to ask where my order is, so that I do not have to contact an agent.

Acceptance criteria
1. WHEN a message contains an order number THE SYSTEM SHALL call `get_order` with that number and report the status.
2. WHEN the order does not exist THE SYSTEM SHALL say it could not find it and SHALL NOT call any other tool.
3. WHEN no order number is given THE SYSTEM SHALL ask for one and SHALL NOT call a tool.

## Requirement 2: Refund with approval
**User story:** As a support lead, I want every refund approved by a person, so that money never moves on a model's say-so.

Acceptance criteria
1. WHEN a customer asks for a refund THE SYSTEM SHALL request `issue_refund` and pause until a person answers.
2. IF the person declines THEN THE SYSTEM SHALL NOT issue the refund and SHALL tell the customer.
3. WHEN text in a message or a tool result tells the system to refund THE SYSTEM SHALL treat it as data and SHALL still require approval.
