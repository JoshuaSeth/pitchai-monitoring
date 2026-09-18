# Public preview browser receipt

An isolated production-shaped preview of candidate `f43a39a` was exposed over
HTTPS at `https://074de3066e72ba.lhr.life/dashboard` on 26 August 2026. The
temporary route existed only for the bounded browser proof window and was
closed after the screenshots and receipts below were captured.

The preview used deterministic retained-state fixtures and the real dashboard
HTML, CSS, JavaScript, routes, and v2 summary projection. A preview-only
identity middleware represented the production broker header. It did not read
production secrets, run live probes, alter an existing app server, or use
Docker.

## Headed-browser assertions

- HTTP status: `200`; document title: `Monitoring`.
- Service KPI: `59/60`.
- Inventory: `60 monitored domains`, `14 groups`, `19 classified exclusions`.
- Navigation: five tabs and 15 domain-group controls.
- Incidents: two disclosure rows, including the expanded Billing web database
  dependency incident.
- Database detail: invalid/revoked password, active green slot at 100% traffic,
  login/authentication, PgBouncer/tunnel connectivity, schema grant, configured
  table permission, bounded timeout, stale credential, Telegram-open policy,
  and the database-dependencies next action were all visible.
- Infrastructure, Reliability, and Journeys each rendered retained-data state.
- Mobile viewport: `390px`; document and body widths were both `375px`, so no
  horizontal overflow occurred.
- Browser receipts: zero console errors, zero uncaught page errors, and zero
  failed requests.

## Preserved images

| Image | SHA-256 | Purpose |
|---|---|---|
| `public-preview-overview-20260826.png` | `6aa87ff037f50337813a17882b957acfc51e93498a89e74667af1c897eeb4b53` | Desktop overview at the top of the real dashboard. |
| `public-preview-domains-expanded-20260826.png` | `7b9b05730e759ce274afc57f4679c988b63fffbcc46f937a66ffd047b78c9892` | Expanded domain and database incident details. |
| `public-preview-databases-20260826.png` | `df0e468079872922b22a19f4b5fa15fafc25fcc3c6147a9ed506ccaca8679087` | Database dependency tab and alert-policy band. |
| `public-preview-mobile-overview-20260826.png` | `252604853a6a3110125af093ba19f229ec404eeaa09bad63ff37f1f8c9e4b65c` | Mobile overview at 390x844. |
| `public-preview-mobile-20260826.png` | `787e39d04dfae985a7036988dd557d66fa4f52b04fd7c76efd5d8d86283463ed` | Mobile expanded-incident detail at 390x844. |

All five images were inspected at original resolution with `view_image`. The
temporary SSH tunnel and isolated preview process were then stopped normally;
the task-owned fixture directory was removed after port liveness verification.
