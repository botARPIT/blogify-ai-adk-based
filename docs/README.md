# Blogify documentation

This is the single canonical documentation tree for the repository.

| Area | Contents |
| --- | --- |
| [Architecture](architecture/README.md) | Current system and workflow diagrams, backend architecture, and schema view. |
| [API guide](API.md) | Authentication, generation lifecycle, review actions, errors, OpenAPI, and Postman. |
| [Backend notes](backend/) | Observability, feature behavior, and performance plans. |
| [Architecture decisions](decisions/) | Historical ADRs for workflow recovery and schema decisions. |
| [Runbooks](runbooks/) | Azure VM Docker Compose deployment, legacy AWS notes, and Vercel frontend instructions. |
| [Incident notes](blogs/) | Historical postmortems that motivated recovery and idempotency safeguards. |

The repository root README is the portfolio entry point. The `backend/` and `frontend/` directories contain implementation-specific READMEs and scripts, but no separate documentation tree.
