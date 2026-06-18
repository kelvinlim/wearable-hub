# CASA Security Assessment — Tier Determination

## What CASA is

CASA (Cloud Application Security Assessment) is the App Defense Alliance security-assessment
framework Google requires for any app using **restricted** OAuth scopes. It is based on the OWASP
**Application Security Verification Standard (ASVS)**. The assessment is performed by an
**independent, Google-approved third-party assessor** — not by Google and not by UMN. UMN pays the
assessor directly; the fee is negotiated between UMN and the assessor with no Google involvement.

On passing, the assessor issues a **Letter of Validation (LOV)**, which is submitted to Google. The
assessment must be **renewed every 12 months** from the LOV date to keep restricted-scope access.

## Which tier applies to Wearable Hub: **Tier 2**

CASA is risk-tiered. The tier is driven by how the app accesses restricted data:

| Tier | When it applies | Wearable Hub? |
|------|-----------------|---------------|
| Tier 1 | Self-scan / lowest risk; not sufficient for restricted scopes through a server | No |
| **Tier 2** | **App accesses restricted data from or through a server** — DAST scan + ASVS questionnaire | **Yes** |
| Tier 3 | Lab-verified; required for Google Workspace Marketplace badges | No (we don't list on Marketplace) |

**Why Tier 2:** Wearable Hub's FastAPI backend pulls subjects' restricted health data from the
Google Health API and **stores it server-side** in MariaDB. Any app that can access Google user data
"from or through a server" must complete at least Tier 2 for restricted scopes. We are not seeking a
Workspace Marketplace badge, so Tier 3 is not required.

## What a Tier-2 assessment involves

1. Google assigns (or you select) an approved security assessor.
2. The assessor runs a **DAST** (Dynamic Application Security Testing) scan against the **production**
   app and produces a findings report.
3. You complete a **Self-Assessment Questionnaire** mapped to OWASP ASVS.
4. You remediate any findings; the assessor confirms and issues the **LOV**.

## Cost & timeline

- **Cost:** roughly **$500–$4,500 USD**, depending on complexity; Tier 2 typically sits at the lower
  end (~$500–$1,000). Recurring annually.
- **Timeline:** ~**2–3 weeks** for Tier 2 once engaged (Tier 3 is 4–6 weeks).
- **CASA Accelerator:** if UMN already holds a recognized security certification (e.g. SOC 2,
  ISO 27001) for the hosting environment, the Accelerator program can expedite/discount the review —
  worth asking UMN security whether any existing attestation applies.

## How our architecture maps to ASVS (prep notes)

Strengths to highlight to the assessor (already in the codebase):

- **Encryption of secrets at rest** — OAuth access/refresh tokens are Fernet-encrypted
  (`backend/app/crypto.py`); the key lives in the environment, never in the DB.
- **Access control** — role-based access (superuser / study-admin / member) scoped per study;
  researcher console requires authenticated Google sign-in.
- **Data deletion on request** — revocation clears stored tokens (`backend/app/accounts.py`); subject
  deletion cascades all health data. (Satisfies Google's "delete user data upon request" rule.)
- **Least privilege** — read-only scopes; intraday HR is per-study opt-in.

Likely questionnaire topics to prepare evidence for: transport security (HTTPS/TLS everywhere),
secrets management, dependency / patching hygiene, logging & access auditing, network exposure of
the backend (only via the host nginx), and a documented data-retention/deletion process.

## Recertification

- A fresh assessment is due **within 12 months** of the LOV date.
- Google notifies the OAuth Branding support/developer contacts by email when recertification is due
  — keep those mailboxes (`umn.edu`) monitored.
