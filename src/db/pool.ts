// src/db/pool.ts — PostgreSQL connection pool
import pg from 'pg';
import { config } from '../config.js';

const { Pool } = pg;

export const pool = new Pool({
  connectionString: config.db.url,
  max: 20,
  idleTimeoutMillis: 30_000,
  connectionTimeoutMillis: 5_000,
});

// Log connection events in dev
if (config.isDev()) {
  pool.on('error', (err) => {
    console.error('[DB] Unexpected pool error:', err.message);
  });
}

/** Helper: run a single query */
export async function query<T extends pg.QueryResultRow = any>(
  text: string,
  params?: any[],
): Promise<pg.QueryResult<T>> {
  return pool.query<T>(text, params);
}

/** Helper: get a client for transactions */
export async function getClient() {
  return pool.connect();
}
