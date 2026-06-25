// src/routes/notifications.routes.ts — In-app notifications
import { Router } from 'express';
import { query } from '../db/pool.js';
import { requireAuth } from '../middleware/auth.js';
import { success, paginated, error } from '../utils/response.js';

export const notificationsRouter = Router();
notificationsRouter.use(requireAuth);

// ── GET /api/notifications ────────────────────────────────────────────────────
notificationsRouter.get('/', async (req, res) => {
  try {
    const page   = Math.max(1, parseInt(String(req.query.page  ?? '1')));
    const limit  = Math.min(100, parseInt(String(req.query.limit ?? '20')));
    const offset = (page - 1) * limit;
    const readFilter = req.query.read;

    const conditions: string[] = ['n.user_id = $1'];
    const params: any[] = [req.user!.sub];

    if (readFilter !== undefined) {
      params.push(readFilter === 'true');
      conditions.push(`n.read = $${params.length}`);
    }

    const where = `WHERE ${conditions.join(' AND ')}`;

    const countRes = await query(`SELECT COUNT(*) FROM notifications n ${where}`, params);
    const total = parseInt(countRes.rows[0].count);

    const rows = await query(
      `SELECT n.* FROM notifications n
       ${where}
       ORDER BY n.created_at DESC
       LIMIT $${params.length + 1} OFFSET $${params.length + 2}`,
      [...params, limit, offset],
    );

    return paginated(res, rows.rows.map(snakeToNotification), {
      page, limit, total, hasNext: offset + limit < total,
    });
  } catch (err: any) {
    console.error('[notifications] list error:', err.message);
    return error(res, err.message, 500);
  }
});

// ── PATCH /api/notifications/read-all ────────────────────────────────────────
notificationsRouter.patch('/read-all', async (req, res) => {
  try {
    const result = await query(
      `UPDATE notifications SET read = true WHERE user_id = $1 AND read = false RETURNING id`,
      [req.user!.sub],
    );
    return success(res, { updatedCount: result.rows.length });
  } catch (err: any) {
    return error(res, err.message, 500);
  }
});

// ── PATCH /api/notifications/:id/read ────────────────────────────────────────
notificationsRouter.patch('/:id/read', async (req, res) => {
  try {
    await query(
      `UPDATE notifications SET read = true WHERE id = $1 AND user_id = $2`,
      [req.params.id, req.user!.sub],
    );
    return success(res, { read: true });
  } catch (err: any) {
    return error(res, err.message, 500);
  }
});

// ── POST /api/notifications/subscribe ────────────────────────────────────────
// FCM push token registration (stub — extend with Firebase Admin when needed)
notificationsRouter.post('/subscribe', async (req, res) => {
  // Silently accept the token — implement FCM storage when push is set up
  return success(res, { subscribed: true });
});

// ── DELETE /api/notifications/subscribe ──────────────────────────────────────
notificationsRouter.delete('/subscribe', async (req, res) => {
  return success(res, { unsubscribed: true });
});

// ── Helper ────────────────────────────────────────────────────────────────────
function snakeToNotification(row: any) {
  return {
    id:        row.id,
    userId:    row.user_id,
    type:      row.type,
    title:     row.title,
    body:      row.body,
    read:      row.read,
    data:      row.payload ?? {},
    createdAt: row.created_at,
  };
}
