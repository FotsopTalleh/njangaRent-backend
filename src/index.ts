import express from 'express';
import cors from 'cors';
import { clerkMiddleware } from '@clerk/express';
import { config } from './config.js';
import { errorHandler } from './middleware/errorHandler.js';
import { authRouter } from './routes/auth.routes.js';
import { listingsRouter } from './routes/listings.routes.js';
import { campayRouter } from './routes/campay.routes.js';
import { messagesRouter } from './routes/messages.routes.js';
import { visitsRouter } from './routes/visits.routes.js';
import { propertiesRouter } from './routes/properties.routes.js';
import { tenantsRouter } from './routes/tenants.routes.js';
import { paymentsRouter } from './routes/payments.routes.js';
import { receiptsRouter } from './routes/receipts.routes.js';
import { notificationsRouter } from './routes/notifications.routes.js';
import { appointmentsRouter } from './routes/appointments.routes.js';

const app = express();

// ── Global middleware ──────────────────────────────────────────────────────────
app.use(cors({
  origin: [
    config.frontendUrl,
    'http://localhost:3000',
    'http://127.0.0.1:3000',
    'http://localhost:5173',
    'http://localhost:8080',  // TanStack Start dev server
  ],
  credentials: true,
}));
app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// Clerk middleware must be global so getAuth(req) works on every route
app.use(clerkMiddleware());

// Static files (uploads)
app.use('/uploads', express.static(config.upload.dir));

// Health check
app.get('/health', (_req, res) => {
  res.json({ status: 'ok', ts: new Date().toISOString() });
});

// ── API Routes ─────────────────────────────────────────────────────────────────
app.use('/api/auth',          authRouter);
app.use('/api/listings',      listingsRouter);
app.use('/api/campay',        campayRouter);
app.use('/api/messages',      messagesRouter);
app.use('/api/visits',        visitsRouter);
app.use('/api/properties',    propertiesRouter);
app.use('/api/tenants',       tenantsRouter);
app.use('/api/payments',      paymentsRouter);
app.use('/api/receipts',      receiptsRouter);
app.use('/api/notifications', notificationsRouter);
app.use('/api/appointments',  appointmentsRouter);

// ── Error handling ─────────────────────────────────────────────────────────────
app.use(errorHandler);

// ── Start server ───────────────────────────────────────────────────────────────
app.listen(config.port, () => {
  console.log(`[server] NjangaRent API listening on port ${config.port}`);
  console.log(`[server] Env: ${config.nodeEnv}`);
});
