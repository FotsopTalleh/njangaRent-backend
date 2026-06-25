// src/routes/appointments.routes.ts — Property viewing appointments
import { Router } from 'express';
import { query } from '../db/pool.js';
import { requireAuth, requireRole } from '../middleware/auth.js';
import { success, paginated, error } from '../utils/response.js';

export const appointmentsRouter = Router();
appointmentsRouter.use(requireAuth);

// ── GET /api/appointments ─────────────────────────────────────────────────────
appointmentsRouter.get('/', async (req, res) => {
  try {
    const page   = Math.max(1, parseInt(String(req.query.page  ?? '1')));
    const limit  = Math.min(100, parseInt(String(req.query.limit ?? '20')));
    const offset = (page - 1) * limit;
    const status = req.query.status as string | undefined;

    const conditions: string[] = [];
    const params: any[] = [];

    if (req.user!.role === 'landlord') {
      params.push(req.user!.sub);
      conditions.push(`a.landlord_id = $${params.length}`);
    } else {
      params.push(req.user!.sub);
      conditions.push(`a.student_id = $${params.length}`);
    }

    if (status) {
      params.push(status);
      conditions.push(`a.status = $${params.length}`);
    }

    const where = conditions.length ? `WHERE ${conditions.join(' AND ')}` : '';

    const countRes = await query(`SELECT COUNT(*) FROM appointments a ${where}`, params);
    const total = parseInt(countRes.rows[0].count);

    const rows = await query(
      `SELECT a.*,
              l.title AS listing_title,
              l.display_address AS listing_address,
              us.full_name AS student_name,
              ul.full_name AS landlord_name
       FROM appointments a
       LEFT JOIN listings l ON l.id = a.listing_id
       LEFT JOIN users us ON us.id = a.student_id
       LEFT JOIN users ul ON ul.id = a.landlord_id
       ${where}
       ORDER BY a.proposed_date DESC, a.created_at DESC
       LIMIT $${params.length + 1} OFFSET $${params.length + 2}`,
      [...params, limit, offset],
    );

    return paginated(res, rows.rows.map(snakeToAppointment), {
      page, limit, total, hasNext: offset + limit < total,
    });
  } catch (err: any) {
    console.error('[appointments] list error:', err.message);
    return error(res, err.message, 500);
  }
});

// ── POST /api/appointments ────────────────────────────────────────────────────
// Student requests a viewing
appointmentsRouter.post('/', async (req, res) => {
  try {
    const { listingId, proposedDate, proposedSlot, studentNote } = req.body;
    if (!listingId || !proposedDate || !proposedSlot) {
      return error(res, 'listingId, proposedDate, and proposedSlot are required');
    }

    // Get landlord from the listing
    const listingRes = await query('SELECT landlord_id FROM listings WHERE id = $1', [listingId]);
    if (!listingRes.rows.length) return error(res, 'Listing not found', 404);
    const landlordId = listingRes.rows[0].landlord_id;

    const result = await query(
      `INSERT INTO appointments
         (listing_id, student_id, landlord_id, proposed_date, proposed_slot, student_note)
       VALUES ($1,$2,$3,$4,$5,$6)
       RETURNING *`,
      [listingId, req.user!.sub, landlordId, proposedDate, proposedSlot, studentNote ?? null],
    );

    return success(res, { data: snakeToAppointment(result.rows[0]) }, 201);
  } catch (err: any) {
    console.error('[appointments] create error:', err.message);
    return error(res, err.message, 500);
  }
});

// ── GET /api/appointments/:id ─────────────────────────────────────────────────
appointmentsRouter.get('/:id', async (req, res) => {
  try {
    const result = await query(
      `SELECT a.*, l.title AS listing_title, l.display_address AS listing_address,
              us.full_name AS student_name, ul.full_name AS landlord_name
       FROM appointments a
       LEFT JOIN listings l ON l.id = a.listing_id
       LEFT JOIN users us ON us.id = a.student_id
       LEFT JOIN users ul ON ul.id = a.landlord_id
       WHERE a.id = $1`,
      [req.params.id],
    );
    if (!result.rows.length) return error(res, 'Appointment not found', 404);
    return success(res, { data: snakeToAppointment(result.rows[0]) });
  } catch (err: any) {
    return error(res, err.message, 500);
  }
});

// ── PUT /api/appointments/:id/respond ────────────────────────────────────────
// Landlord: confirm, reschedule, or decline
appointmentsRouter.put('/:id/respond', requireRole('landlord', 'admin'), async (req, res) => {
  try {
    const { action, landlordNote, counterDate, counterSlot, declineReason } = req.body;
    if (!action) return error(res, 'action is required');

    let newStatus: string;
    switch (action) {
      case 'confirm':    newStatus = 'confirmed';   break;
      case 'reschedule': newStatus = 'rescheduled'; break;
      case 'decline':    newStatus = 'declined';    break;
      default: return error(res, 'action must be confirm, reschedule, or decline');
    }

    const result = await query(
      `UPDATE appointments
       SET status = $1,
           landlord_note = COALESCE($2, landlord_note),
           counter_date = $3,
           counter_slot = $4,
           decline_reason = $5,
           updated_at = NOW()
       WHERE id = $6 AND landlord_id = $7
       RETURNING *`,
      [newStatus, landlordNote ?? null, counterDate ?? null, counterSlot ?? null, declineReason ?? null, req.params.id, req.user!.sub],
    );
    if (!result.rows.length) return error(res, 'Appointment not found or not yours', 404);
    return success(res, { data: snakeToAppointment(result.rows[0]) });
  } catch (err: any) {
    return error(res, err.message, 500);
  }
});

// ── PUT /api/appointments/:id/cancel ─────────────────────────────────────────
// Student cancels own appointment
appointmentsRouter.put('/:id/cancel', async (req, res) => {
  try {
    const result = await query(
      `UPDATE appointments SET status = 'cancelled', updated_at = NOW()
       WHERE id = $1 AND student_id = $2
       RETURNING id`,
      [req.params.id, req.user!.sub],
    );
    if (!result.rows.length) return error(res, 'Appointment not found or not yours', 404);
    return success(res, { cancelled: true });
  } catch (err: any) {
    return error(res, err.message, 500);
  }
});

// ── PUT /api/appointments/:id/complete ───────────────────────────────────────
// Landlord marks appointment as completed
appointmentsRouter.put('/:id/complete', requireRole('landlord', 'admin'), async (req, res) => {
  try {
    const result = await query(
      `UPDATE appointments SET status = 'completed', updated_at = NOW()
       WHERE id = $1 AND landlord_id = $2
       RETURNING id`,
      [req.params.id, req.user!.sub],
    );
    if (!result.rows.length) return error(res, 'Appointment not found or not yours', 404);
    return success(res, { completed: true });
  } catch (err: any) {
    return error(res, err.message, 500);
  }
});

// ── Helper ────────────────────────────────────────────────────────────────────
function snakeToAppointment(row: any) {
  return {
    id:             row.id,
    listingId:      row.listing_id,
    studentId:      row.student_id,
    landlordId:     row.landlord_id,
    proposedDate:   row.proposed_date,
    proposedSlot:   row.proposed_slot,
    studentNote:    row.student_note,
    landlordNote:   row.landlord_note,
    counterDate:    row.counter_date,
    counterSlot:    row.counter_slot,
    declineReason:  row.decline_reason,
    status:         row.status,
    createdAt:      row.created_at,
    updatedAt:      row.updated_at,
    listingTitle:   row.listing_title,
    listingAddress: row.listing_address,
    studentName:    row.student_name,
    landlordName:   row.landlord_name,
  };
}
