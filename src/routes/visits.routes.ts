// src/routes/visits.routes.ts
import { Router } from 'express';
import { getAuth } from '@clerk/express';
import { query } from '../db/pool.js';
import { success, error } from '../utils/response.js';

export const visitsRouter = Router();
// clerkMiddleware() is applied globally in index.ts — no need to repeat here

// GET /api/visits/slots/my — landlord's own slots  ← must be BEFORE /slots/:listingId
visitsRouter.get('/slots/my', async (req, res) => {
  const userId = getAuth(req).userId;
  try {
    const result = await query(
      `SELECT vs.*, l.title AS listing_title, u.full_name AS tenant_name
       FROM visit_slots vs
       LEFT JOIN listings l ON vs.listing_id = l.id
       LEFT JOIN users u ON vs.booked_by = u.id
       WHERE vs.landlord_id = $1
       ORDER BY vs.slot_datetime DESC`,
      [userId]
    );
    return success(res, result.rows.map((r) => ({
      ...r,
      listing: r.listing_id ? { title: r.listing_title } : null,
      tenant: r.booked_by ? { full_name: r.tenant_name } : null,
    })));
  } catch (err: any) {
    return error(res, err.message, 500);
  }
});

// GET /api/visits/booked — tenant's booked visits  ← must be BEFORE /slots/:listingId
visitsRouter.get('/booked', async (req, res) => {
  const userId = getAuth(req).userId;
  try {
    const result = await query(
      `SELECT vs.*, l.title AS listing_title, u.full_name AS landlord_name
       FROM visit_slots vs
       LEFT JOIN listings l ON vs.listing_id = l.id
       LEFT JOIN users u ON vs.landlord_id = u.id
       WHERE vs.booked_by = $1
       ORDER BY vs.slot_datetime DESC`,
      [userId]
    );
    return success(res, result.rows.map((r) => ({
      ...r,
      listing: r.listing_id ? { title: r.listing_title } : null,
      landlord: { full_name: r.landlord_name },
    })));
  } catch (err: any) {
    return error(res, err.message, 500);
  }
});

// GET /api/visits/slots/:listingId — available slots for a listing (wildcard, must come LAST)
visitsRouter.get('/slots/:listingId', async (req, res) => {
  const { listingId } = req.params;
  try {
    const result = await query(
      `SELECT vs.*, u.full_name AS landlord_name
       FROM visit_slots vs
       LEFT JOIN users u ON vs.landlord_id = u.id
       WHERE vs.listing_id = $1 AND vs.status = 'available' AND vs.is_booked = false
         AND vs.slot_datetime > now()
       ORDER BY vs.slot_datetime ASC`,
      [listingId]
    );
    return success(res, result.rows);
  } catch (err: any) {
    return error(res, err.message, 500);
  }
});

// POST /api/visits/slots — landlord creates a slot
visitsRouter.post('/slots', async (req, res) => {
  const userId = getAuth(req).userId;
  const { listingId, slotDatetime } = req.body;

  if (!listingId || !slotDatetime) return error(res, 'listingId and slotDatetime are required', 400);

  try {
    // Verify landlord owns the listing
    const ownerCheck = await query(
      `SELECT id FROM listings WHERE id = $1 AND landlord_id = $2`,
      [listingId, userId]
    );
    if (!ownerCheck.rows.length) return error(res, 'Listing not found or unauthorized', 403);

    const result = await query(
      `INSERT INTO visit_slots (listing_id, landlord_id, slot_datetime) VALUES ($1, $2, $3) RETURNING *`,
      [listingId, userId, slotDatetime]
    );
    return success(res, result.rows[0], 201);
  } catch (err: any) {
    return error(res, err.message, 500);
  }
});

// POST /api/visits/book/:slotId — tenant books a slot
visitsRouter.post('/book/:slotId', async (req, res) => {
  const userId = getAuth(req).userId;
  const { slotId } = req.params;

  try {
    const slot = await query(`SELECT * FROM visit_slots WHERE id = $1`, [slotId]);
    if (!slot.rows.length) return error(res, 'Slot not found', 404);
    if (slot.rows[0].is_booked) return error(res, 'Slot already booked', 409);

    const result = await query(
      `UPDATE visit_slots SET is_booked = true, booked_by = $1, status = 'pending', updated_at = now()
       WHERE id = $2 AND is_booked = false RETURNING *`,
      [userId, slotId]
    );
    if (!result.rows.length) return error(res, 'Slot was just taken, please pick another', 409);

    // Insert notification for landlord
    await query(
      `INSERT INTO notifications (user_id, type, title, body)
       VALUES ($1, 'visit_booked', 'New visit request', 'A tenant has requested a viewing slot.')`,
      [result.rows[0].landlord_id]
    );

    return success(res, result.rows[0], 201);
  } catch (err: any) {
    return error(res, err.message, 500);
  }
});

// PATCH /api/visits/slots/:slotId — update slot status (confirm/cancel)
visitsRouter.patch('/slots/:slotId', async (req, res) => {
  const userId = getAuth(req).userId;
  const { slotId } = req.params;
  const { status } = req.body;

  const allowed = ['confirmed', 'cancelled', 'completed'];
  if (!allowed.includes(status)) return error(res, `status must be one of: ${allowed.join(', ')}`, 400);

  try {
    const slot = await query(`SELECT * FROM visit_slots WHERE id = $1`, [slotId]);
    if (!slot.rows.length) return error(res, 'Slot not found', 404);

    const s = slot.rows[0];
    const canUpdate = s.landlord_id === userId || s.booked_by === userId;
    if (!canUpdate) return error(res, 'Unauthorized', 403);

    const result = await query(
      `UPDATE visit_slots SET status = $1, updated_at = now() WHERE id = $2 RETURNING *`,
      [status, slotId]
    );

    // Notify the other party
    const notifyUserId = s.landlord_id === userId ? s.booked_by : s.landlord_id;
    if (notifyUserId) {
      await query(
        `INSERT INTO notifications (user_id, type, title, body)
         VALUES ($1, 'visit_status_changed', 'Visit update', $2)`,
        [notifyUserId, `Your visit has been ${status}.`]
      );
    }

    return success(res, result.rows[0]);
  } catch (err: any) {
    return error(res, err.message, 500);
  }
});
