-- NjangaRent — PostgreSQL schema
-- Run with: psql -d njangrent -f src/db/migrations/001_initial.sql

-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ── Users ────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
  id              VARCHAR(100) PRIMARY KEY,
  email           VARCHAR(320) NOT NULL UNIQUE,
  full_name       VARCHAR(200) NOT NULL,
  phone           VARCHAR(30),
  role            VARCHAR(20) NOT NULL DEFAULT 'student'
                  CHECK (role IN ('student','landlord','admin')),
  status          VARCHAR(20) NOT NULL DEFAULT 'PENDING'
                  CHECK (status IN ('PENDING','ACTIVE','REJECTED')),
  national_id_front VARCHAR(500),
  national_id_back  VARCHAR(500),
  ownership_doc     VARCHAR(500),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_role  ON users(role);

-- ── Listings ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS listings (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  landlord_id           VARCHAR(100) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title                 VARCHAR(300) NOT NULL,
  description           TEXT,
  property_type         VARCHAR(30) NOT NULL
                        CHECK (property_type IN ('studio','single_room','self_contained','apartment','hostel_block')),
  rent_amount           INTEGER NOT NULL,
  rent_period           VARCHAR(20) NOT NULL DEFAULT 'monthly'
                        CHECK (rent_period IN ('monthly','termly','yearly')),
  available_from        DATE DEFAULT CURRENT_DATE,
  amenities             JSONB DEFAULT '[]'::jsonb,
  rules                 TEXT,
  max_occupants         INTEGER NOT NULL DEFAULT 1,
  lat                   DOUBLE PRECISION,
  lng                   DOUBLE PRECISION,
  display_address       VARCHAR(300),
  distance_from_molyko_km DOUBLE PRECISION,
  status                VARCHAR(30) NOT NULL DEFAULT 'active'
                        CHECK (status IN ('draft','pending_admin_review','active','rejected','deactivated','flagged')),
  views_count           INTEGER NOT NULL DEFAULT 0,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_listings_landlord ON listings(landlord_id);
CREATE INDEX IF NOT EXISTS idx_listings_status   ON listings(status);
CREATE INDEX IF NOT EXISTS idx_listings_type     ON listings(property_type);
CREATE INDEX IF NOT EXISTS idx_listings_rent     ON listings(rent_amount);

-- ── Listing images ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS listing_images (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  listing_id  UUID NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
  url         VARCHAR(1000) NOT NULL,
  category    VARCHAR(20) NOT NULL DEFAULT 'exterior'
              CHECK (category IN ('exterior','room')),
  sort_order  INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_listing_images_listing ON listing_images(listing_id);

-- ── Conversations ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS conversations (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  listing_id            UUID NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
  student_id            VARCHAR(100) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  landlord_id           VARCHAR(100) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  student_unread_count  INTEGER NOT NULL DEFAULT 0,
  landlord_unread_count INTEGER NOT NULL DEFAULT 0,
  last_message_at       TIMESTAMPTZ DEFAULT NOW(),
  created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_conv_student  ON conversations(student_id);
CREATE INDEX IF NOT EXISTS idx_conv_landlord ON conversations(landlord_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_conv_unique ON conversations(listing_id, student_id);

-- ── Messages ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS messages (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id  UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  sender_id        VARCHAR(100) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  body             TEXT NOT NULL,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, created_at);

-- ── Appointments ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS appointments (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  listing_id      UUID NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
  student_id      VARCHAR(100) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  landlord_id     VARCHAR(100) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  proposed_date   DATE NOT NULL,
  proposed_slot   VARCHAR(30) NOT NULL DEFAULT 'morning',
  status          VARCHAR(20) NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending','confirmed','declined','completed','cancelled','rescheduled')),
  student_note    TEXT,
  landlord_note   TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_appt_student  ON appointments(student_id);
CREATE INDEX IF NOT EXISTS idx_appt_landlord ON appointments(landlord_id);

-- ── Nkwa payments ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS nkwa_payments (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  listing_id          UUID REFERENCES listings(id) ON DELETE SET NULL,
  payer_id            VARCHAR(100) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  landlord_id         VARCHAR(100) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  amount              INTEGER NOT NULL,
  nkwa_transaction_id VARCHAR(200),
  nkwa_status         VARCHAR(20) NOT NULL DEFAULT 'initiated'
                      CHECK (nkwa_status IN ('initiated','pending','confirmed','failed')),
  phone_number        VARCHAR(30) NOT NULL,
  payment_type        VARCHAR(20) NOT NULL DEFAULT 'rent'
                      CHECK (payment_type IN ('deposit','rent')),
  created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_nkwa_payer    ON nkwa_payments(payer_id);
CREATE INDEX IF NOT EXISTS idx_nkwa_landlord ON nkwa_payments(landlord_id);
CREATE INDEX IF NOT EXISTS idx_nkwa_txn      ON nkwa_payments(nkwa_transaction_id);

-- ── Notifications ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS notifications (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id    VARCHAR(100) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  type       VARCHAR(50) NOT NULL,
  title      VARCHAR(300) NOT NULL,
  body       TEXT,
  read       BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_notif_user ON notifications(user_id, read, created_at DESC);

-- ── Admin verification queue (reuses users table status field) ────────────────
-- No separate table needed — we query users WHERE status = 'PENDING'
