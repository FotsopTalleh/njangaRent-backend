// src/config.ts — Environment configuration
import 'dotenv/config';

export const config = {
  port:        parseInt(process.env.PORT ?? '5000', 10),
  nodeEnv:     process.env.NODE_ENV ?? 'development',
  frontendUrl: process.env.FRONTEND_URL ?? 'http://localhost:3000',

  db: {
    url: process.env.DATABASE_URL ?? 'postgresql://postgres:postgres@localhost:5432/njangrent',
  },

  jwt: {
    accessSecret:  process.env.JWT_ACCESS_SECRET  ?? 'dev-access-secret-change-me',
    refreshSecret: process.env.JWT_REFRESH_SECRET ?? 'dev-refresh-secret-change-me',
    accessExpiry:  process.env.JWT_ACCESS_EXPIRY  ?? '15m',
    refreshExpiry: process.env.JWT_REFRESH_EXPIRY ?? '30d',
  },

  clerk: {
    publishableKey: process.env.CLERK_PUBLISHABLE_KEY ?? '',
    secretKey:      process.env.CLERK_SECRET_KEY      ?? '',
  },

  nkwa: {
    apiKey:        process.env.NKWA_API_KEY        ?? '',
    apiSecret:     process.env.NKWA_API_SECRET     ?? '',
    webhookSecret: process.env.NKWA_WEBHOOK_SECRET ?? '',
    baseUrl:       process.env.NKWA_BASE_URL       ?? 'https://sandbox.api.nkwa.com',
  },

  seed: {
    adminEmail:    process.env.SEED_ADMIN_EMAIL    ?? 'admin@njangrent.cm',
    adminPassword: process.env.SEED_ADMIN_PASSWORD ?? 'Admin123!',
    adminName:     process.env.SEED_ADMIN_NAME     ?? 'NjangaRent Admin',
  },

  upload: {
    maxSizeMb: parseInt(process.env.MAX_UPLOAD_SIZE_MB ?? '10', 10),
    dir:       process.env.UPLOAD_DIR ?? './public/uploads',
  },

  supabase: {
    url:            process.env.SUPABASE_URL            ?? '',
    serviceRoleKey: process.env.SUPABASE_SERVICE_ROLE_KEY ?? '',
  },

  isDev:  () => config.nodeEnv === 'development',
  isProd: () => config.nodeEnv === 'production',
};
