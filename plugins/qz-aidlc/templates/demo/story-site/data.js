/* Everything this demo says lives here. Replace it for each prospect; app.js never changes.
   brand.clientLogo: a data: URI of a logo the person supplied (leave "" to show the client name as text).
   corpus: documents with passages. Write them as the prospect's own documents would read: specific, dated, owned.
   questions: what the presenter clicks. Include one the corpus cannot answer, to show the honest "I don't know". */
window.QZ_DATA = {
  brand: {
    client: "Northwind Logistics",
    clientLogo: "",
    product: "Knowledge Fabric",
    title: "Northwind Logistics · Knowledge Fabric",
    cta: "Talk to our experts",
    ctaHref: "#contact",
    contact: "aicoe@qualizeal.com",
  },
  hero: {
    eyebrow: "Operations knowledge · live demonstration",
    headline: "Every answer,<br><em>traced to its source.</em>",
    lede: "Your SOPs, carrier contracts and incident reviews already hold the answers. Knowledge Fabric finds them, shows the page each one came from, and tells you how certain it is, so dispatchers act on what they read instead of hunting for it.",
    placeholder: "Ask Knowledge Fabric…",
  },
  questions: [
    "What happens when a cold-chain shipment goes above 8°C?",
    "Who can approve a carrier SLA exception?",
    "How long can a customs hold run before we tell the customer?",
    "Which lithium battery shipments need a dangerous goods declaration?",
    "What is the bonus policy for regional directors?",
  ],
  sections: {
    answer: { eyebrow: "Section 02 · Live answer", title: "Grounded answers: <em>quoted, never invented.</em>", lede: "Every sentence in an answer is lifted from a specific passage in a specific document. Click a citation to open the source." },
    explain: { eyebrow: "Section 03 · Explainability", title: "Every answer is a traceable chain.", lede: "From the question, through the passages retrieved and the concepts that link them, to each cited sentence. No black box." },
    health: { eyebrow: "Section 04 · Knowledge health", title: "Find the gaps before they cost you.", lede: "Knowledge that sits in one document, has no owner or has not been reviewed this year is a risk you cannot see on a shared drive. Knowledge Fabric measures it." },
    insights: { eyebrow: "Section 05 · Insights", title: "The corpus at a glance.", lede: "Where knowledge concentrates, which concepts tie teams together, and how current it is." },
  },
  pillars: [
    { t: "Verbatim citation", d: "Answers are assembled from source sentences; nothing is paraphrased or generated." },
    { t: "Document → page → section → passage", d: "A four-level address for every claim, so anyone can verify it in seconds." },
    { t: "Concept-graph traversal", d: "Linked concepts light up in the map, showing which teams' documents were combined." },
    { t: "Honest “I don't know”", d: "Weak evidence returns a clear non-answer and the closest documents, never a guess." },
  ],
  footer: "Knowledge Fabric: a demonstration prepared for Northwind Logistics by QualiZeal AI Center of Excellence. Illustrative corpus.",
  entities: [
    "cold chain", "temperature excursion", "data logger", "quarantine", "carrier SLA", "SLA exception", "customs hold", "broker",
    "dangerous goods", "lithium batteries", "DG declaration", "proof of delivery", "claims", "returns", "dispatch", "escalation",
    "on-time delivery", "penalty credit", "pharma customer", "duty manager", "regional director", "root cause", "dock door", "forklift",
  ],
  corpus: [
    { id: "SOP-CC-014", title: "Cold Chain Handling SOP", type: "SOP", owner: "Quality Assurance", updated: "2026-08-14", status: "trusted",
      passages: [
        { page: 3, section: "4.1 Temperature limits", text: "Refrigerated pharmaceutical freight must stay between 2°C and 8°C from pickup to proof of delivery. Every pallet travels with a calibrated data logger that records temperature every five minutes." },
        { page: 4, section: "4.3 Temperature excursions", text: "A temperature excursion is any logger reading above 8°C or below 2°C for more than fifteen consecutive minutes. When an excursion is detected, the driver moves the load to the nearest qualified cold store and the shipment is placed in quarantine. The duty manager must notify the pharma customer within two hours of the first out-of-range reading." },
        { page: 5, section: "4.4 Release from quarantine", text: "Quarantined product is released only after the customer's quality team reviews the data logger file and signs the release form. Product the customer rejects is returned at Northwind's cost and recorded as a claim." },
        { page: 7, section: "6.2 Records", text: "Data logger files are kept for five years in the quality archive. The duty manager attaches the excursion report to the shipment record before the end of the shift." },
      ] },
    { id: "POL-SLA-007", title: "Carrier Service Level Policy", type: "Policy", owner: "Carrier Management", updated: "2026-05-02", status: "trusted",
      passages: [
        { page: 2, section: "2. Service levels", text: "Contracted carriers commit to 97% on-time delivery measured monthly per lane. Missed service levels earn Northwind a penalty credit of 2% of the monthly lane spend for every point below target." },
        { page: 3, section: "3. SLA exceptions", text: "An SLA exception suspends penalty credits for a lane and a defined period, for example during a port strike or a declared weather event. Exceptions up to 14 days may be approved by the regional director. Exceptions longer than 14 days need approval from the VP of Carrier Management and must be logged in the carrier scorecard." },
        { page: 4, section: "4. Escalation", text: "Two consecutive months below 94% on-time delivery trigger a formal escalation and a corrective action plan from the carrier within ten business days." },
      ] },
    { id: "WI-CUS-022", title: "Customs Hold Work Instruction", type: "Work instruction", owner: "Trade Compliance", updated: "2026-03-19", status: "trusted",
      passages: [
        { page: 1, section: "1. Scope", text: "This instruction covers inbound and outbound shipments held by customs for document checks, physical inspection or duty disputes." },
        { page: 2, section: "3. Customer notification", text: "When a customs hold lasts more than 24 hours, dispatch notifies the customer with the hold reason, the broker's reference and the expected release date. Holds beyond 72 hours are escalated to the trade compliance lead, who decides whether to reroute or return the goods." },
        { page: 3, section: "4. Working with brokers", text: "The customs broker owns communication with the customs authority. Northwind staff do not contact customs directly unless the broker asks them to in writing." },
      ] },
    { id: "SOP-DG-031", title: "Dangerous Goods Acceptance SOP", type: "SOP", owner: "Safety & Compliance", updated: "2025-11-30", status: "trusted",
      passages: [
        { page: 2, section: "2.1 Lithium batteries", text: "Lithium ion batteries shipped on their own, without equipment, always need a dangerous goods declaration. Batteries packed with or inside equipment need a declaration when a single cell exceeds 20 watt-hours or a battery exceeds 100 watt-hours." },
        { page: 3, section: "2.4 State of charge", text: "Standalone lithium ion batteries offered for air transport must be at no more than 30% state of charge. The shipper certifies the state of charge on the DG declaration." },
        { page: 5, section: "5. Refusals", text: "Acceptance staff refuse any dangerous goods shipment with a missing or incomplete DG declaration and record the refusal in the safety log with photographs of the package marks." },
      ] },
    { id: "IR-2026-118", title: "Incident Review: Lane DAL-ATL temperature excursion", type: "Incident review", owner: "Quality Assurance", updated: "2026-07-09", status: "trusted",
      passages: [
        { page: 1, section: "Summary", text: "On 21 June a reefer trailer on the Dallas to Atlanta lane recorded 11°C for 48 minutes after a compressor fault. The load was quarantined at the Birmingham cold store and the pharma customer was notified 3 hours 20 minutes after the first reading, outside the two-hour requirement." },
        { page: 2, section: "Root cause", text: "The root cause was a data logger alert routed to a dispatcher inbox that is not monitored overnight. The duty manager learned of the excursion from the driver's phone call." },
        { page: 3, section: "Corrective actions", text: "Logger alerts now page the duty manager directly. The cold chain SOP was updated to name the duty manager as the person accountable for customer notification." },
      ] },
    { id: "SOP-RET-009", title: "Returns and Claims Procedure", type: "SOP", owner: "Customer Operations", updated: "2025-02-11", status: "needs-review",
      passages: [
        { page: 2, section: "2. Claims window", text: "Customers may file a damage or loss claim within 30 days of the proof of delivery date. Claims for temperature-sensitive freight must include the data logger file." },
        { page: 3, section: "3. Approval limits", text: "Claims up to $5,000 are approved by the customer operations supervisor. Claims above $5,000 go to the regional director for approval." },
      ] },
    { id: "GD-DSP-004", title: "Dispatch Playbook", type: "Playbook", owner: "Network Operations", updated: "2026-09-22", status: "trusted",
      passages: [
        { page: 4, section: "Escalation ladder", text: "Dispatchers escalate service failures to the duty manager, then to the regional director. The duty manager is on call around the clock and is the single point of contact for customers during an incident." },
        { page: 6, section: "Shift handover", text: "Each shift hands over open exceptions, customs holds and quarantined loads in the handover log. Anything open for more than one shift is flagged red." },
        { page: 8, section: "Proof of delivery", text: "Proof of delivery is captured in the driver app with a signature and photo. Missing proof of delivery blocks invoicing for the shipment." },
      ] },
    { id: "SAF-WH-012", title: "Warehouse Safety Standard", type: "Standard", owner: "Safety & Compliance", updated: "2024-06-18", status: "needs-review",
      passages: [
        { page: 2, section: "Dock doors", text: "Dock doors stay closed unless a trailer is restrained at the door. Forklift operators confirm the wheel restraint is engaged before entering a trailer." },
        { page: 3, section: "Forklifts", text: "Forklift operators complete a pre-shift inspection and renew certification every three years." },
      ] },
    { id: "CNT-PHX-2026", title: "Pharma Customer Master Agreement: Schedule C", type: "Contract", owner: "Commercial", updated: "2026-01-15", status: "restricted",
      passages: [
        { page: 11, section: "C.4 Notification", text: "Supplier shall notify Customer of any temperature excursion within two (2) hours of detection and provide the data logger record within twenty-four (24) hours." },
        { page: 12, section: "C.6 Service credits", text: "Each excursion not notified within the required window earns Customer a service credit of $2,500 per affected shipment." },
      ] },
    { id: "SOP-CC-014-v3", title: "Cold Chain Handling SOP (2023 edition)", type: "SOP", owner: "Quality Assurance", updated: "2023-04-02", status: "superseded",
      passages: [
        { page: 4, section: "4.3 Temperature excursions", text: "A temperature excursion is any reading above 8°C or below 2°C for more than thirty minutes. The dispatcher notifies the customer by the next business day." },
      ] },
  ],
};
