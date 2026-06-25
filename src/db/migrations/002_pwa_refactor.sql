-- NjangaRent — Migration 002: PWA Refactor Schema
-- Fixes role naming, messaging tables, visit slots, reviews, payment methods

-- ── Fix role constraint (student → tenant) ──────────────────────────────────
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check;
ALTER TABLE users ADD CONSTRAINT users_role_check 
  CHECK (role IN ('tenant','landlord','admin'));

-- Update any existing 'student' roles to 'tenant'
UPDATE users SET role = 'tenant' WHERE role = 'student';

-- ── Rename conversations → message_threads ───────────────────────────────────
ALTER TABLE conversations RENAME TO message_threads;
ALTER TABLE message_threads RENAME COLUMN student_id TO tenant_id;
ALTER TABLE message_threads RENAME CONSTRAINT conversations_pkey TO message_threads_pkey;
ALTER INDEX IF EXISTS idx_conv_student  RENAME TO idx_mt_tenant;
ALTER INDEX IF EXISTS idx_conv_landlord RENAME TO idx_mt_landlord;
ALTER INDEX IF EXISTS idx_conv_unique   RENAME TO idx_mt_unique;

-- ── Update messages table ────────────────────────────────────────────────────
ALTER TABLE messages RENAME COLUMN conversation_id TO thread_id;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS is_read BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE messages DROP CONSTRAINT IF EXISTS messages_conversation_id_fkey;
ALTER TABLE messages ADD CONSTRAINT messages_thread_id_fkey 
  FOREIGN KEY (thread_id) REFERENCES message_threads(id) ON DELETE CASCADE;

-- Add last message preview to threads
ALTER TABLE message_threads ADD COLUMN IF NOT EXISTS last_message_preview TEXT;

-- ── Add payment_method to nkwa_payments ──────────────────────────────────────
ALTER TABLE nkwa_payments ADD COLUMN IF NOT EXISTS payment_method VARCHAR(10) DEFAULT 'mtn'
  CHECK (payment_method IN ('mtn', 'orange'));

-- ── Add verification_status to users (landlord gating) ───────────────────────
ALTER TABLE users ADD COLUMN IF NOT EXISTS verification_status VARCHAR(20) DEFAULT 'pending'
  CHECK (verification_status IN ('pending','verified','rejected'));
ALTER TABLE users ADD COLUMN IF NOT EXISTS verification_note TEXT;

-- Set all existing landlords to verified (they pre-exist the gate)
UPDATE users SET verification_status = 'verified' WHERE role = 'landlord';

-- ── Visit slots table (replaces appointments model for new flow) ──────────────
CREATE TABLE IF NOT EXISTS visit_slots (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  listing_id    UUID NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
  landlord_id   VARCHAR(100) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  slot_datetime TIMESTAMPTZ NOT NULL,
  is_booked     BOOLEAN NOT NULL DEFAULT false,
  booked_by     VARCHAR(100) REFERENCES users(id) ON DELETE SET NULL,
  status        VARCHAR(20) NOT NULL DEFAULT 'available'
                CHECK (status IN ('available','pending','confirmed','cancelled','completed')),
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_visit_slots_listing  ON visit_slots(listing_id);
CREATE INDEX IF NOT EXISTS idx_visit_slots_landlord ON visit_slots(landlord_id);
CREATE INDEX IF NOT EXISTS idx_visit_slots_booked   ON visit_slots(booked_by);

-- ── Reviews table ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS reviews (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  listing_id            UUID NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
  reviewer_id           VARCHAR(100) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  landlord_id           VARCHAR(100) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  rating_overall        INT NOT NULL CHECK (rating_overall BETWEEN 1 AND 5),
  rating_responsiveness INT CHECK (rating_responsiveness BETWEEN 1 AND 5),
  rating_condition      INT CHECK (rating_condition BETWEEN 1 AND 5),
  rating_value          INT CHECK (rating_value BETWEEN 1 AND 5),
  body                  TEXT,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(listing_id, reviewer_id)
);

CREATE INDEX IF NOT EXISTS idx_reviews_listing  ON reviews(listing_id);
CREATE INDEX IF NOT EXISTS idx_reviews_landlord ON reviews(landlord_id);

-- ── SSE / notification payload field ─────────────────────────────────────────
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS payload JSONB DEFAULT '{}'::jsonb;
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS action_url TEXT;
