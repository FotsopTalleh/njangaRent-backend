// src/lib/supabase.ts — Server-side Supabase admin client
// Uses the service_role key — NEVER expose this on the frontend.
import { createClient } from '@supabase/supabase-js';
import { config } from '../config.js';

if (!config.supabase.url || !config.supabase.serviceRoleKey) {
  console.warn('[supabase] SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY is not set. Image uploads will fail.');
}

export const supabase = createClient(
  config.supabase.url,
  config.supabase.serviceRoleKey,
  {
    auth: {
      // Service role bypasses RLS — safe for server-only use
      persistSession: false,
      autoRefreshToken: false,
    },
  }
);
