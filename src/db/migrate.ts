// src/db/migrate.ts — Run SQL migrations
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { pool } from './pool.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

async function migrate() {
  console.log('[migrate] Running database migrations...');

  const migrationsDir = path.join(__dirname, 'migrations');
  const files = fs.readdirSync(migrationsDir)
    .filter((f) => f.endsWith('.sql'))
    .sort();

  for (const file of files) {
    const filePath = path.join(migrationsDir, file);
    const sql = fs.readFileSync(filePath, 'utf-8');
    console.log(`[migrate]  → ${file}`);
    await pool.query(sql);
  }

  console.log('[migrate] ✓ All migrations applied.');
  await pool.end();
}

migrate().catch((err) => {
  console.error('[migrate] ✗ Migration failed:', err.message);
  process.exit(1);
});
