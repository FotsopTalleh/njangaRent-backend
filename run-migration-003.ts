// run-migration-003.ts — One-shot runner for migration 003
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { pool } from './src/db/pool.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

async function run() {
  const sql = fs.readFileSync(
    path.join(__dirname, 'src/db/migrations/003_landlord_tables.sql'),
    'utf-8',
  );
  console.log('[migrate] Running 003_landlord_tables.sql …');
  await pool.query(sql);
  console.log('[migrate] ✓ Done');
  await pool.end();
}

run().catch((err) => {
  console.error('[migrate] ✗ Failed:', err.message);
  process.exit(1);
});
