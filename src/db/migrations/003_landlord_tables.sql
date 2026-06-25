-- NjangaRent — Migration 003: Missing tables for landlord dashboard
-- Run with: psql -d njangrent -f src/db/migrations/003_landlord_tables.sql

-- ── Properties table ─────────────────────────────────────────────────────────
-- Distinct from "listings" (public adverts): a property is the physical unit
-- a landlord manages, to which tenants are assigned.
CREATE TABLE IF NOT EXISTS properties (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  landlord_id   VARCHAR(100) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name          VARCHAR(200) NOT NULL,
  address       VARCHAR(300) NOT NULL,
  property_type VARCHAR(50) NOT NULL DEFAULT 'apartment',
  monthly_rent  INTEGER NOT NULL DEFAULT 0,
  description   TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_properties_landlord ON properties(landlord_id);

-- ── Tenants table ─────────────────────────────────────────────────────────────
-- Associates a user (tenant) with a property managed by a landlord.
CREATE TABLE IF NOT EXISTS tenants (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id      VARCHAR(100) REFERENCES users(id) ON DELETE SET NULL,
  landlord_id  VARCHAR(100) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  property_id  UUID NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
  monthly_rent INTEGER NOT NULL,
  rent_due_day INTEGER NOT NULL DEFAULT 1
               CHECK (rent_due_day BETWEEN 1 AND 28),
  status       VARCHAR(20) NOT NULL DEFAULT 'active'
               CHECK (status IN ('active','removed')),
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tenants_landlord  ON tenants(landlord_id);
CREATE INDEX IF NOT EXISTS idx_tenants_user      ON tenants(user_id);
CREATE INDEX IF NOT EXISTS idx_tenants_property  ON tenants(property_id);

-- ── Tenant invitations ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tenant_invitations (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  landlord_id  VARCHAR(100) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  property_id  UUID NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
  email        VARCHAR(320) NOT NULL,
  monthly_rent INTEGER NOT NULL,
  rent_due_day INTEGER NOT NULL DEFAULT 1,
  token        TEXT NOT NULL,
  accepted     BOOLEAN NOT NULL DEFAULT FALSE,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (email, property_id)
);

-- ── Rent payments ────────────────────────────────────────────────────────────
-- Proof-of-payment submissions by tenants.
CREATE TABLE IF NOT EXISTS rent_payments (
  id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id            UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  user_id              VARCHAR(100) REFERENCES users(id) ON DELETE SET NULL,
  landlord_id          VARCHAR(100) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  property_id          UUID NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
  amount_claimed       INTEGER NOT NULL,
  amount_verified      INTEGER,
  payment_date         DATE NOT NULL,
  payment_method       VARCHAR(50) NOT NULL,
  reference_number     VARCHAR(200),
  notes                TEXT,
  proof_image_url      TEXT,
  status               VARCHAR(20) NOT NULL DEFAULT 'pending'
                       CHECK (status IN ('pending','approved','rejected')),
  rejection_reason     TEXT,
  landlord_note        TEXT,
  ocr_extracted_amount INTEGER,
  is_manual            BOOLEAN NOT NULL DEFAULT FALSE,
  submitted_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  reviewed_at          TIMESTAMPTZ,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_rent_payments_landlord ON rent_payments(landlord_id, status);
CREATE INDEX IF NOT EXISTS idx_rent_payments_tenant   ON rent_payments(tenant_id, submitted_at DESC);

-- ── Receipts ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS receipts (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  payment_id      UUID REFERENCES rent_payments(id) ON DELETE SET NULL,
  tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  landlord_id     VARCHAR(100) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  property_id     UUID NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
  receipt_number  VARCHAR(50),
  amount_paid     INTEGER NOT NULL,
  payment_date    DATE NOT NULL,
  pdf_url         TEXT,
  period_label    TEXT,
  is_manual       BOOLEAN NOT NULL DEFAULT FALSE,
  status          VARCHAR(20) NOT NULL DEFAULT 'disbursed'
                  CHECK (status IN ('draft','disbursed')),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_receipts_landlord ON receipts(landlord_id);
CREATE INDEX IF NOT EXISTS idx_receipts_tenant   ON receipts(tenant_id, created_at DESC);

-- ── Add counter_date / counter_slot / decline_reason to appointments ──────────
ALTER TABLE appointments ADD COLUMN IF NOT EXISTS counter_date  DATE;
ALTER TABLE appointments ADD COLUMN IF NOT EXISTS counter_slot  VARCHAR(30);
ALTER TABLE appointments ADD COLUMN IF NOT EXISTS decline_reason TEXT;
