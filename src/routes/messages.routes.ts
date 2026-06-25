// src/routes/messages.routes.ts
import { Router } from 'express';
import { getAuth } from '@clerk/express';
import { query } from '../db/pool.js';
import { success, error } from '../utils/response.js';
import { EventEmitter } from 'events';

export const messageEmitter = new EventEmitter();
messageEmitter.setMaxListeners(100);

export const messagesRouter = Router();
// clerkMiddleware() is applied globally in index.ts — no need to repeat here

// GET /api/messages/stream — Server-Sent Events for real-time messages
messagesRouter.get('/stream', (req, res) => {
  const userId = getAuth(req).userId;

  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');

  const onMessage = (msg: any) => {
    // Only send to the recipient
    if (msg.recipientId === userId) {
      res.write(`data: ${JSON.stringify(msg)}\n\n`);
    }
  };

  messageEmitter.on('new_message', onMessage);

  req.on('close', () => {
    messageEmitter.off('new_message', onMessage);
  });
});

// GET /api/messages/threads — all threads for current user
messagesRouter.get('/threads', async (req, res) => {
  const userId = getAuth(req).userId;
  try {
    const result = await query(
      `SELECT 
        mt.*,
        l.title AS listing_title, l.id AS listing_id,
        tenant.id AS tenant_id, tenant.full_name AS tenant_name,
        landlord.id AS landlord_id, landlord.full_name AS landlord_name,
        (SELECT body FROM messages m WHERE m.thread_id = mt.id ORDER BY m.created_at DESC LIMIT 1) AS last_message_preview,
        (SELECT COUNT(*) FROM messages m WHERE m.thread_id = mt.id AND m.is_read = false AND m.sender_id != $1) AS unread_count
       FROM message_threads mt
       LEFT JOIN listings l ON mt.listing_id = l.id
       LEFT JOIN users tenant  ON mt.tenant_id  = tenant.id
       LEFT JOIN users landlord ON mt.landlord_id = landlord.id
       WHERE mt.tenant_id = $1 OR mt.landlord_id = $1
       ORDER BY mt.last_message_at DESC NULLS LAST`,
      [userId]
    );

    const threads = result.rows.map((row) => ({
      id: row.id,
      listing_id: row.listing_id,
      tenant_id: row.tenant_id,
      landlord_id: row.landlord_id,
      last_message_at: row.last_message_at,
      last_message_preview: row.last_message_preview,
      created_at: row.created_at,
      unread_count: parseInt(row.unread_count, 10),
      listing: row.listing_id ? { id: row.listing_id, title: row.listing_title } : null,
      tenant: { id: row.tenant_id, full_name: row.tenant_name },
      landlord: { id: row.landlord_id, full_name: row.landlord_name },
    }));

    return success(res, threads);
  } catch (err: any) {
    console.error('[messages/threads GET]', err.message);
    return error(res, err.message, 500);
  }
});

// GET /api/messages/threads/:threadId — paginated messages
messagesRouter.get('/threads/:threadId', async (req, res) => {
  const userId = getAuth(req).userId;
  const { threadId } = req.params;
  const cursor = req.query.cursor as string | undefined;

  try {
    // Verify user is part of this thread
    const threadCheck = await query(
      `SELECT id FROM message_threads WHERE id = $1 AND (tenant_id = $2 OR landlord_id = $2)`,
      [threadId, userId]
    );
    if (!threadCheck.rows.length) return error(res, 'Thread not found', 404);

    const msgs = await query(
      `SELECT m.*, u.full_name AS sender_name
       FROM messages m
       LEFT JOIN users u ON m.sender_id = u.id
       WHERE m.thread_id = $1 ${cursor ? 'AND m.created_at < $3' : ''}
       ORDER BY m.created_at ASC
       LIMIT 50`,
      cursor ? [threadId, userId, cursor] : [threadId, userId]
    );

    // Mark messages as read
    await query(
      `UPDATE messages SET is_read = true WHERE thread_id = $1 AND sender_id != $2 AND is_read = false`,
      [threadId, userId]
    );

    return success(res, msgs.rows);
  } catch (err: any) {
    console.error('[messages/thread GET]', err.message);
    return error(res, err.message, 500);
  }
});

// POST /api/messages/threads — create thread + first message
messagesRouter.post('/threads', async (req, res) => {
  const userId = getAuth(req).userId;
  const { landlordId, listingId, body } = req.body;

  if (!landlordId || !body?.trim()) return error(res, 'landlordId and body are required', 400);

  try {
    // Upsert thread (idempotent)
    const threadResult = await query(
      `INSERT INTO message_threads (tenant_id, landlord_id, listing_id, last_message_at)
       VALUES ($1, $2, $3, now())
       ON CONFLICT (listing_id, tenant_id) DO UPDATE SET last_message_at = now()
       RETURNING id, tenant_id, landlord_id`,
      [userId, landlordId, listingId || null]
    );
    const threadData = threadResult.rows[0];
    const threadId = threadData.id;

    const msgResult = await query(
      `INSERT INTO messages (thread_id, sender_id, body) VALUES ($1, $2, $3) RETURNING *`,
      [threadId, userId, body.trim()]
    );

    await query(
      `UPDATE message_threads SET last_message_at = now(), last_message_preview = $1 WHERE id = $2`,
      [body.trim().substring(0, 100), threadId]
    );

    // Emit event to landlord (recipient of the first message)
    messageEmitter.emit('new_message', {
      ...msgResult.rows[0],
      recipientId: landlordId
    });

    return success(res, { threadId, message: msgResult.rows[0] }, 201);
  } catch (err: any) {
    console.error('[messages/threads POST]', err.message);
    return error(res, err.message, 500);
  }
});

// POST /api/messages/threads/:threadId — send message
messagesRouter.post('/threads/:threadId', async (req, res) => {
  const userId = getAuth(req).userId;
  const { threadId } = req.params;
  const { body } = req.body;

  if (!body?.trim()) return error(res, 'Message body is required', 400);

  try {
    const threadCheck = await query(
      `SELECT id, tenant_id, landlord_id FROM message_threads WHERE id = $1 AND (tenant_id = $2 OR landlord_id = $2)`,
      [threadId, userId]
    );
    if (!threadCheck.rows.length) return error(res, 'Thread not found', 404);

    const msgResult = await query(
      `INSERT INTO messages (thread_id, sender_id, body) VALUES ($1, $2, $3) RETURNING *`,
      [threadId, userId, body.trim()]
    );

    await query(
      `UPDATE message_threads SET last_message_at = now(), last_message_preview = $1 WHERE id = $2`,
      [body.trim().substring(0, 100), threadId]
    );

    // Emit event to the other party
    const threadData = threadCheck.rows[0];
    const recipientId = threadData.tenant_id === userId ? threadData.landlord_id : threadData.tenant_id;
    messageEmitter.emit('new_message', {
      ...msgResult.rows[0],
      recipientId
    });

    return success(res, msgResult.rows[0], 201);
  } catch (err: any) {
    console.error('[messages/thread POST]', err.message);
    return error(res, err.message, 500);
  }
});

// PATCH /api/messages/threads/:threadId/read — mark as read
messagesRouter.patch('/threads/:threadId/read', async (req, res) => {
  const userId = getAuth(req).userId;
  const { threadId } = req.params;
  try {
    await query(
      `UPDATE messages SET is_read = true WHERE thread_id = $1 AND sender_id != $2`,
      [threadId, userId]
    );
    return success(res, { ok: true });
  } catch (err: any) {
    return error(res, err.message, 500);
  }
});
