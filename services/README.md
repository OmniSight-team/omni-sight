# services

The system is not one program. It is five parts, each with one job, talking to each other
through a message queue and a shared database.

`common` holds what they all agree on. `ingestion` takes video in. `ai_workers` turns it into
searchable meaning. `pfm` predicts and verifies. `query` answers requests, from the dashboard
and from other software.

Each part can be updated or replaced on its own without touching the others.
