# phase_security_requirements.md

## Overview

This document defines the initial production security requirements and hardening plan for Friend Hub before wider beta onboarding, public signup, payments, or broader data ingestion.

The goal is not enterprise-grade zero-trust infrastructure yet. The goal is:

* Protect user data
* Prevent accidental exposure
* Prevent broken access control
* Reduce operational risk
* Establish trustworthy foundations
* Prepare for future monetisation and scaling

This phase focuses on practical, high-impact security improvements appropriate for an early-stage social platform handling:

* Private messages
* Photos/media
* Events/reminders
* AI interactions
* Imported chat history
* Potential future payment data

---

# Security Philosophy

Friend Hub should operate under these principles:

1. Users should not feel their private content is casually accessible.
2. The platform owner should avoid unnecessary visibility into user data.
3. All access to private data should be deliberate, controlled, and auditable.
4. Security should be layered:

   * infrastructure
   * authentication
   * permissions
   * storage
   * transport
   * operational processes
5. Simplicity is preferred over premature complexity.
6. Security hardening is required before:

   * public signup
   * Stripe/payment integration
   * large-scale onboarding
   * public launch

---

# Phase Goals

This phase must achieve:

* Removal of exposed secrets and sensitive data from repositories
* Stronger authentication/session handling
* Correct room-level access isolation
* Safer media storage and delivery
* Secure infrastructure defaults
* Auditability of privileged/admin actions
* Basic GDPR/privacy compliance foundations
* Safer backup and deployment workflows

---

# Core Threat Model

Primary realistic threats:

## High Risk

* Users accessing other rooms' data
* Exposed uploads/media
* Exposed secrets/API keys
* Publicly accessible databases/admin tooling
* Weak invite/auth flows
* Leaked backups
* Misconfigured object storage
* Session hijacking
* Insecure AI tooling exposing cross-room data

## Medium Risk

* Spam accounts
* Rate abuse
* Malicious file uploads
* Brute-force attacks
* Social engineering
* Prompt injection via AI features

## Lower Priority (For Later)

* Nation-state threats
* Full E2EE architecture
* Hardware-backed key management
* Advanced SOC monitoring
* Full compliance certifications

---

# Section 1 — Repository & Secret Cleanup

## Requirements

### Remove tracked sensitive data

Must remove from git tracking/history:

* `.env`
* `.env.prod`
* `.env.local`
* uploads/media
* backups
* terraform state
* SSH keys
* API tokens
* local config containing secrets

### Rotate all exposed credentials

Must rotate:

* OpenRouter keys
* JWT secrets
* database passwords
* cloud credentials
* VPS credentials
* SSH keys if required
* Stripe keys once introduced

### Git hygiene

Implement:

* robust `.gitignore`
* `.env.example`
* production secret injection only at deploy/runtime
* pre-commit secret scanning (optional but recommended)

---

# Section 2 — Authentication & Session Security

## Requirements

### Session handling

Sessions must:

* use HTTPS-only cookies
* use `HttpOnly`
* use `SameSite=Lax` or stricter
* expire correctly
* support logout invalidation

### Authentication

Initial acceptable auth:

* invite-based onboarding
* magic links OR PIN auth
* optional email verification

Avoid:

* weak anonymous auth
* long-lived bearer tokens
* storing plaintext secrets

### Rate limiting

Must implement rate limits for:

* login attempts
* invite redemption
* AI endpoints
* uploads
* search endpoints
* websocket connection attempts

---

# Section 3 — Room Isolation & Permissions

## Critical Requirement

Users must NEVER access data from rooms they are not members of.

This must be enforced server-side for:

* messages
* photos
* reminders
* events
* polls
* AI memories
* search results
* websocket subscriptions
* notification payloads
* uploads/downloads

## Requirements

### Backend enforcement

Every endpoint must validate:

* authenticated user
* room membership
* action permissions

Never trust frontend filtering.

### WebSocket isolation

Websocket connections must:

* bind to authenticated identity
* bind to allowed rooms only
* reject cross-room subscriptions
* isolate broadcasts correctly

### AI isolation

AI tooling/search/summaries must:

* remain room-scoped
* never leak cross-room context
* validate permissions before retrieval

---

# Section 4 — Media & Upload Security

## Requirements

### Upload validation

Must validate:

* file type
* MIME type
* file size
* extension consistency

Reject:

* executables
* scripts
* suspicious file types

### Private media

Uploads must NOT be publicly enumerable.

Avoid:

* guessable URLs
* public directory listing
* unauthenticated media access

### Media delivery

Preferred approach:

* authenticated media endpoints
* signed URLs later if object storage introduced

### Metadata stripping

Recommended:

* strip EXIF/location metadata on uploads
* especially for photos

---

# Section 5 — Infrastructure Security

## VPS Hardening

### SSH

* disable password auth
* key-only auth
* disable root login
* fail2ban recommended

### Firewall

Only expose:

* 80
* 443
* SSH (restricted if possible)

Database ports must NOT be public.

### Docker

* avoid privileged containers
* avoid mounting unnecessary host paths
* separate runtime volumes
* production compose separated from dev

### HTTPS

Must enforce HTTPS everywhere using Caddy.

Redirect all HTTP traffic to HTTPS.

---

# Section 6 — Database & Backup Security

## Requirements

### Database access

* database must not be publicly accessible
* use strong passwords
* separate dev/prod credentials
* least privilege where possible

### Backups

Backups must:

* be encrypted
* not be committed to git
* have retention policy
* support restore testing

### Logging

Sensitive data must not appear in logs:

* auth tokens
* passwords
* payment data
* session identifiers

---

# Section 7 — Admin Access & Auditability

## Philosophy

Admin access should exist, but should be:

* deliberate
* logged
* minimised

## Requirements

### Admin audit logging

Log:

* who accessed admin routes
* who viewed user content
* moderation actions
* deletions
* impersonation/debug actions

### No casual browsing

Avoid building:

* unrestricted "view all messages" tooling
* unrestricted photo browsers
* unrestricted user impersonation

---

# Section 8 — Privacy & GDPR Foundations

## Requirements

Before public onboarding:

### Privacy policy

Document:

* what data is collected
* why
* retention policy
* third-party services
* AI usage
* analytics usage

### User controls

Users should eventually be able to:

* delete account
* export data
* leave rooms
* remove uploads

### Data minimisation

Avoid collecting unnecessary:

* location
* contacts
* identifiers
* analytics

---

# Section 9 — AI Security Requirements

## Requirements

### Prompt safety

AI systems must:

* remain room scoped
* avoid arbitrary tool access
* validate permissions before retrieval

### Logging

AI prompts/responses may contain sensitive user data.

Therefore:

* logs should remain private
* avoid exposing raw prompts publicly
* consider retention policies later

### Agent execution

AI tools must not:

* execute arbitrary shell commands
* access unrestricted filesystem paths
* access unrestricted DB data

---

# Section 10 — Future Security Phases

Not required yet, but future roadmap:

## Phase 2

* Object storage security
* Signed media URLs
* Device/session management
* Email verification
* Abuse tooling
* Moderation tooling
* Safer invite systems

## Phase 3

* E2EE experimentation
* Security headers/CSP tightening
* Penetration testing
* Vulnerability scanning
* SSO/OAuth
* Stripe Connect compliance flows

---

# Immediate Recommended Priorities

## P0 — Must Complete Before Wider Beta

* Remove sensitive git history
* Rotate secrets
* Audit room permissions
* Secure uploads
* Lock down VPS/database
* Enforce HTTPS
* Add basic rate limiting
* Remove exposed admin tooling

## P1 — Strongly Recommended

* Admin audit logs
* Backup encryption
* Privacy policy
* Account deletion flow
* Media auth layer
* Invite hardening

## P2 — Later

* Object storage migration
* E2EE
* Advanced monitoring
* Formal compliance/security reviews

---

# Success Criteria

Friend Hub should reach a state where:

* Users cannot access data outside authorised rooms
* Private uploads are protected
* Secrets are no longer exposed
* Infrastructure is reasonably hardened
* Admin access is controlled and logged
* Users can reasonably trust the platform
* The platform is safe enough for small-group beta onboarding
* The system is prepared for future monetisation and scaling
