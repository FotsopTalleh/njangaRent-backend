import pkg from 'pg';
const { Pool } = pkg;
import fs from 'fs';

const pool = new Pool({
  connectionString: process.env.DATABASE_URL
});

async function run() {
  const sql = `
-- 1. Make existing tenant_id and property_id nullable
ALTER TABLE receipts ALTER COLUMN tenant_id DROP NOT NULL;
ALTER TABLE receipts ALTER COLUMN property_id DROP NOT NULL;

-- 2. Add campay_payment_id
ALTER TABLE receipts ADD COLUMN IF NOT EXISTS campay_payment_id UUID REFERENCES campay_payments(id) ON DELETE CASCADE;

-- 3. Add an index for quick lookups
CREATE INDEX IF NOT EXISTS idx_receipts_campay ON receipts(campay_payment_id);
`;
  try {
    await pool.query(sql);
    console.log("Migration executed successfully!");
  } catch (e) {
    console.error("Migration failed:", e);
  } finally {
    await pool.end();
  }
}

run();
