# AI Usage Disclosure
**Merge Kingdom 2.5 — AI Engineer Take-Home Assignment**  
**Candidate:** Aditya Tiwary

## 1. AI Tools Used

I used **Antigravity** as the primary AI-assisted development environment for planning and implementing the backend prototype. I also used **ChatGPT** to review architectural decisions, examine assignment requirements, identify gaps, and improve the clarity of the final submission.

## 2. What I Asked AI to Help With

AI assistance was used for:

- Breaking down the assignment into system analysis, migration, architecture, testing, and rollout tasks.
- Designing the proposed server-authoritative save and synchronization architecture.
- Structuring the database models, API endpoints, wallet operations, purchase handling, and migration workflow.
- Implementing the FastAPI backend prototype and generating automated tests.
- Exploring multi-device conflicts, offline synchronization, idempotency, and currency migration edge cases.
- Reviewing the written submission for technical consistency, unsupported assumptions, and clarity.

## 3. What I Kept and What I Changed

I retained AI-generated implementation and documentation ideas where they aligned with the assignment requirements and could be reviewed against the prototype.

I also made or requested changes where the initial output was too broad or made assumptions not supported by the brief. Examples include:

- Replacing claims of guaranteed fairness in coin-to-gem conversion with an explicit explanation of the limitations caused by missing historical spending records.
- Treating the 1:1 coin-to-gem conversion as a proposal requiring Finance approval rather than an established business rule.
- Removing unsupported claims about revenue differences between multi-device and single-device players.
- Making the staged rollout dependent on actual app-store approval.
- Explicitly documenting limitations in legacy authentication, inventory reconciliation, and production receipt verification.

## 4. Where AI Output Required Caution or Correction

AI-generated output was not treated as automatically correct. Some initial drafts contained unsupported numerical claims, overly strong guarantees, and assumptions about historical player behavior.

The coin migration policy was particularly important: because historical coin spending was not recorded, no algorithm can reliably identify the original source of every remaining coin. The selected Purchased-First Protection policy is therefore a deliberate player-protective assumption, not a reconstruction of actual spending history.

The backend is a prototype. Test results demonstrate the reported prototype test coverage, but do not establish production readiness or validate PostgreSQL production concurrency and live app-store receipt verification.

## 5. Human Review and Responsibility

I reviewed the assignment requirements, evaluated the proposed architecture and trade-offs, and iteratively examined the generated implementation and documentation. I am responsible for the final design choices, assumptions, limitations, and submitted work.

AI assistance was used as a development and review aid, not as a substitute for technical evaluation.

## 6. Approximate Time Spent

**Total time spent:** ~4.5 Hours

This includes assignment analysis, AI-assisted implementation, testing, reviewing, and preparing the submission.
