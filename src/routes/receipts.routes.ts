// src/routes/receipts.routes.ts — Receipt management
import { Router } from 'express';
import { query } from '../db/pool.js';
import { requireAuth, requireRole } from '../middleware/auth.js';
import { success, paginated, error } from '../utils/response.js';

export const receiptsRouter = Router();
receiptsRouter.use(requireAuth);

// ── GET /api/receipts ─────────────────────────────────────────────────────────
receiptsRouter.get('/', async (req, res) => {
  try {
    const page       = Math.max(1, parseInt(String(req.query.page  ?? '1')));
    const limit      = Math.min(100, parseInt(String(req.query.limit ?? '20')));
    const offset     = (page - 1) * limit;
    const propertyId = req.query.propertyId as string | undefined;

    const conditions: string[] = [];
    const params: any[] = [];

    if (req.user!.role === 'landlord') {
      params.push(req.user!.sub);
      conditions.push(`r.landlord_id = $${params.length}`);
    } else {
      // Tenant: find by user_id → tenants.id
      const tenantRes = await query(
        'SELECT id FROM tenants WHERE user_id = $1 AND status = $2 LIMIT 1',
        [req.user!.sub, 'active'],
      );
      if (tenantRes.rows.length) {
        params.push(tenantRes.rows[0].id);
        conditions.push(`r.tenant_id = $${params.length}`);
      }
    }

    if (propertyId) {
      params.push(propertyId);
      conditions.push(`r.property_id = $${params.length}`);
    }

    const where = conditions.length ? `WHERE ${conditions.join(' AND ')}` : '';

    const countRes = await query(`SELECT COUNT(*) FROM receipts r ${where}`, params);
    const total = parseInt(countRes.rows[0].count);

    const rows = await query(
      `SELECT r.*,
              ut.full_name AS tenant_name,
              ul.full_name AS landlord_name,
              p.name AS property_name,
              p.address AS property_address,
              rp.payment_method,
              rp.reference_number,
              rp.notes
       FROM receipts r
       LEFT JOIN tenants t  ON t.id = r.tenant_id
       LEFT JOIN users ut   ON ut.id = t.user_id
       LEFT JOIN users ul   ON ul.id = r.landlord_id
       LEFT JOIN properties p ON p.id = r.property_id
       LEFT JOIN rent_payments rp ON rp.id = r.payment_id
       ${where}
       ORDER BY r.created_at DESC
       LIMIT $${params.length + 1} OFFSET $${params.length + 2}`,
      [...params, limit, offset],
    );

    return paginated(res, rows.rows.map(snakeToReceipt), {
      page, limit, total, hasNext: offset + limit < total,
    });
  } catch (err: any) {
    console.error('[receipts] list error:', err.message);
    return error(res, err.message, 500);
  }
});

// ── GET /api/receipts/:id ─────────────────────────────────────────────────────
receiptsRouter.get('/:id', async (req, res) => {
  try {
    const result = await query(
      `SELECT r.*,
              ut.full_name AS tenant_name,
              ul.full_name AS landlord_name,
              p.name AS property_name,
              p.address AS property_address,
              rp.payment_method,
              rp.reference_number,
              rp.notes
       FROM receipts r
       LEFT JOIN tenants t  ON t.id = r.tenant_id
       LEFT JOIN users ut   ON ut.id = t.user_id
       LEFT JOIN users ul   ON ul.id = r.landlord_id
       LEFT JOIN properties p ON p.id = r.property_id
       LEFT JOIN rent_payments rp ON rp.id = r.payment_id
       WHERE r.id = $1`,
      [req.params.id],
    );
    if (!result.rows.length) return error(res, 'Receipt not found', 404);
    return success(res, snakeToReceipt(result.rows[0]));
  } catch (err: any) {
    return error(res, err.message, 500);
  }
});

// ── GET /api/receipts/:id/draft ───────────────────────────────────────────────
receiptsRouter.get('/:id/draft', requireRole('landlord', 'admin'), async (req, res) => {
  try {
    const result = await query(
      `SELECT r.*,
              ut.full_name AS tenant_name,
              p.name AS property_name, p.address AS property_address,
              rp.payment_method, rp.reference_number, rp.notes
       FROM receipts r
       LEFT JOIN tenants t  ON t.id = r.tenant_id
       LEFT JOIN users ut   ON ut.id = t.user_id
       LEFT JOIN properties p ON p.id = r.property_id
       LEFT JOIN rent_payments rp ON rp.id = r.payment_id
       WHERE r.id = $1 AND r.status = 'draft'`,
      [req.params.id],
    );
    if (!result.rows.length) return error(res, 'Draft receipt not found', 404);
    return success(res, snakeToReceipt(result.rows[0]));
  } catch (err: any) {
    return error(res, err.message, 500);
  }
});

// ── GET /api/receipts/:id/download ───────────────────────────────────────────
receiptsRouter.get('/:id/download', async (req, res) => {
  try {
    const result = await query('SELECT pdf_url FROM receipts WHERE id = $1', [req.params.id]);
    if (!result.rows.length) return error(res, 'Receipt not found', 404);
    return success(res, { pdfUrl: result.rows[0].pdf_url ?? '', hasPreview: false });
  } catch (err: any) {
    return error(res, err.message, 500);
  }
});

// ── PATCH /api/receipts/:id/disburse ─────────────────────────────────────────
// Landlord finalises draft and disburses to tenant
receiptsRouter.patch('/:id/disburse', requireRole('landlord', 'admin'), async (req, res) => {
  try {
    const { tenantName, amountPaid, paymentDate, paymentMethod, referenceNumber, notes, periodLabel } = req.body;
    const result = await query(
      `UPDATE receipts
       SET status = 'disbursed',
           period_label = COALESCE($1, period_label),
           updated_at = NOW()
       WHERE id = $2 AND status = 'draft'
       RETURNING *`,
      [periodLabel ?? null, req.params.id],
    );
    if (!result.rows.length) return error(res, 'Draft receipt not found', 404);
    return success(res, snakeToReceipt(result.rows[0]));
  } catch (err: any) {
    return error(res, err.message, 500);
  }
});

// ── POST /api/receipts/manual ─────────────────────────────────────────────────
// Landlord creates a manual receipt (cash payment, no proof image)
receiptsRouter.post('/manual', requireRole('landlord', 'admin'), async (req, res) => {
  try {
    const { tenantId, amountPaid, paymentDate, paymentMethod, referenceNumber, notes } = req.body;
    if (!tenantId || !amountPaid || !paymentDate || !paymentMethod) {
      return error(res, 'tenantId, amountPaid, paymentDate, and paymentMethod are required');
    }

    const tenantRes = await query(
      'SELECT property_id, landlord_id FROM tenants WHERE id = $1',
      [tenantId],
    );
    if (!tenantRes.rows.length) return error(res, 'Tenant not found', 404);
    const { property_id, landlord_id } = tenantRes.rows[0];

    // Create an approved payment record
    const paymentRes = await query(
      `INSERT INTO rent_payments
         (tenant_id, landlord_id, property_id, amount_claimed, payment_date,
          payment_method, reference_number, notes, status, is_manual)
       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,'approved',true)
       RETURNING id`,
      [tenantId, landlord_id, property_id, amountPaid, paymentDate, paymentMethod, referenceNumber ?? null, notes ?? null],
    );

    const receiptRes = await query(
      `INSERT INTO receipts
         (payment_id, tenant_id, landlord_id, property_id, amount_paid, payment_date, is_manual, status)
       VALUES ($1,$2,$3,$4,$5,$6,true,'disbursed')
       RETURNING *`,
      [paymentRes.rows[0].id, tenantId, landlord_id, property_id, amountPaid, paymentDate],
    );

    return success(res, snakeToReceipt(receiptRes.rows[0]), 201);
  } catch (err: any) {
    console.error('[receipts] manual error:', err.message);
    return error(res, err.message, 500);
  }
});

// ── Helper ────────────────────────────────────────────────────────────────────
function snakeToReceipt(row: any) {
  return {
    id:              row.id,
    paymentId:       row.payment_id,
    tenantId:        row.tenant_id,
    landlordId:      row.landlord_id,
    propertyId:      row.property_id,
    receiptNumber:   row.receipt_number ?? '',
    amountPaid:      row.amount_paid,
    paymentDate:     row.payment_date,
    pdfUrl:          row.pdf_url ?? '',
    createdAt:       row.created_at,
    isManual:        row.is_manual,
    status:          row.status,
    tenantName:      row.tenant_name,
    landlordName:    row.landlord_name,
    propertyName:    row.property_name,
    propertyAddress: row.property_address,
    paymentMethod:   row.payment_method,
    referenceNumber: row.reference_number,
    notes:           row.notes,
    periodLabel:     row.period_label,
  };
}
