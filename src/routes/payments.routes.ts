// src/routes/payments.routes.ts — Rent payment proof submission & landlord review
import { Router } from 'express';
import { query } from '../db/pool.js';
import { requireAuth, requireRole } from '../middleware/auth.js';
import { upload } from '../middleware/upload.js';
import { success, paginated, error } from '../utils/response.js';
import { uploadToSupabase } from '../utils/uploadToSupabase.js';

export const paymentsRouter = Router();
paymentsRouter.use(requireAuth);

// ── GET /api/payments ─────────────────────────────────────────────────────────
// Landlord: list all payments for my tenants (optional ?status=pending)
// Tenant:   list own payment submissions
paymentsRouter.get('/', async (req, res) => {
  try {
    const page   = Math.max(1, parseInt(String(req.query.page  ?? '1')));
    const limit  = Math.min(100, parseInt(String(req.query.limit ?? '20')));
    const offset = (page - 1) * limit;
    const status = req.query.status as string | undefined;
    const propertyId = req.query.propertyId as string | undefined;

    const conditions: string[] = [];
    const params: any[] = [];

    if (req.user!.role === 'landlord') {
      params.push(req.user!.sub);
      conditions.push(`rp.landlord_id = $${params.length}`);
    } else if (req.user!.role === 'tenant') {
      // Get the tenant's id from the tenants table
      const tenantRes = await query(
        'SELECT id FROM tenants WHERE user_id = $1 AND status = $2 LIMIT 1',
        [req.user!.sub, 'active'],
      );
      if (tenantRes.rows.length) {
        params.push(tenantRes.rows[0].id);
        conditions.push(`rp.tenant_id = $${params.length}`);
      }
    }

    if (status) {
      params.push(status);
      conditions.push(`rp.status = $${params.length}`);
    }
    if (propertyId) {
      params.push(propertyId);
      conditions.push(`rp.property_id = $${params.length}`);
    }

    const where = conditions.length ? `WHERE ${conditions.join(' AND ')}` : '';

    const countRes = await query(
      `SELECT COUNT(*) FROM rent_payments rp ${where}`,
      params,
    );
    const total = parseInt(countRes.rows[0].count);

    const rows = await query(
      `SELECT rp.*, u.full_name AS tenant_name, p.name AS property_name
       FROM rent_payments rp
       LEFT JOIN tenants t ON t.id = rp.tenant_id
       LEFT JOIN users u ON u.id = t.user_id
       LEFT JOIN properties p ON p.id = rp.property_id
       ${where}
       ORDER BY rp.submitted_at DESC
       LIMIT $${params.length + 1} OFFSET $${params.length + 2}`,
      [...params, limit, offset],
    );

    return paginated(res, rows.rows.map(snakeToPayment), {
      page, limit, total, hasNext: offset + limit < total,
    });
  } catch (err: any) {
    console.error('[payments] list error:', err.message);
    return error(res, err.message, 500);
  }
});

// ── GET /api/payments/calendar ─────────────────────────────────────────────────
// 12-month payment calendar — used by tenant dashboard
paymentsRouter.get('/calendar', async (req, res) => {
  try {
    const year     = parseInt(String(req.query.year ?? new Date().getFullYear()));
    const tenantId = req.query.tenantId as string | undefined;

    let resolvedTenantId = tenantId;
    if (!resolvedTenantId) {
      const tenantRes = await query(
        'SELECT id, monthly_rent FROM tenants WHERE user_id = $1 AND status = $2 LIMIT 1',
        [req.user!.sub, 'active'],
      );
      if (!tenantRes.rows.length) return error(res, 'Tenant record not found', 404);
      resolvedTenantId = tenantRes.rows[0].id;
    }

    const tenantInfo = await query(
      'SELECT monthly_rent FROM tenants WHERE id = $1',
      [resolvedTenantId],
    );
    const monthlyRent = tenantInfo.rows[0]?.monthly_rent ?? 0;

    const payments = await query(
      `SELECT
         to_char(payment_date, 'YYYY-MM') AS month,
         id, amount_claimed AS amount_paid, payment_date, payment_method, status
       FROM rent_payments
       WHERE tenant_id = $1 AND status = 'approved'
         AND EXTRACT(YEAR FROM payment_date) = $2
       ORDER BY payment_date`,
      [resolvedTenantId, year],
    );

    // Group by month
    const byMonth: Record<string, any[]> = {};
    for (const p of payments.rows) {
      if (!byMonth[p.month]) byMonth[p.month] = [];
      byMonth[p.month].push({ id: p.id, amountPaid: p.amount_paid, paymentDate: p.payment_date, paymentMethod: p.payment_method });
    }

    const months = Array.from({ length: 12 }, (_, i) => {
      const m = String(i + 1).padStart(2, '0');
      const key = `${year}-${m}`;
      const list = byMonth[key] ?? [];
      const totalPaid = list.reduce((s: number, p: any) => s + Number(p.amountPaid), 0);
      const pct = monthlyRent > 0 ? Math.round((totalPaid / monthlyRent) * 100) : 0;
      return {
        month: key,
        totalPaid,
        monthlyRent,
        percentage: pct,
        status: totalPaid >= monthlyRent ? 'paid' : totalPaid > 0 ? 'partial' : 'unpaid',
        payments: list,
      };
    });

    return success(res, { year, months, monthlyRent });
  } catch (err: any) {
    console.error('[payments] calendar error:', err.message);
    return error(res, err.message, 500);
  }
});

// ── GET /api/payments/:id ─────────────────────────────────────────────────────
paymentsRouter.get('/:id', async (req, res) => {
  try {
    const result = await query(
      `SELECT rp.*, u.full_name AS tenant_name, p.name AS property_name
       FROM rent_payments rp
       LEFT JOIN tenants t ON t.id = rp.tenant_id
       LEFT JOIN users u ON u.id = t.user_id
       LEFT JOIN properties p ON p.id = rp.property_id
       WHERE rp.id = $1`,
      [req.params.id],
    );
    if (!result.rows.length) return error(res, 'Payment not found', 404);
    return success(res, snakeToPayment(result.rows[0]));
  } catch (err: any) {
    return error(res, err.message, 500);
  }
});

// ── POST /api/payments ────────────────────────────────────────────────────────
// Tenant submits payment proof
paymentsRouter.post(
  '/',
  upload.single('proofFile'),
  async (req, res) => {
    try {
      const { amountClaimed, paymentDate, paymentMethod, referenceNumber, notes } = req.body;
      if (!amountClaimed || !paymentDate || !paymentMethod) {
        return error(res, 'amountClaimed, paymentDate and paymentMethod are required');
      }

      // Get tenant record
      const tenantRes = await query(
        'SELECT id, property_id, landlord_id FROM tenants WHERE user_id = $1 AND status = $2 LIMIT 1',
        [req.user!.sub, 'active'],
      );
      if (!tenantRes.rows.length) return error(res, 'Active tenant record not found', 404);
      const tenant = tenantRes.rows[0];

      // Upload proof image to Supabase Storage
      let proofImageUrl: string | null = null;
      if ((req as any).file) {
        const uploaded = await uploadToSupabase((req as any).file, 'payment-proofs', 'proofs');
        proofImageUrl = uploaded.url;
      }

      const result = await query(
        `INSERT INTO rent_payments
           (tenant_id, user_id, landlord_id, property_id,
            amount_claimed, payment_date, payment_method,
            reference_number, notes, proof_image_url, status)
         VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,'pending')
         RETURNING id, proof_image_url`,
        [
          tenant.id, req.user!.sub, tenant.landlord_id, tenant.property_id,
          amountClaimed, paymentDate, paymentMethod,
          referenceNumber ?? null, notes ?? null, proofImageUrl,
        ],
      );

      return success(res, {
        paymentId: result.rows[0].id,
        proofImageUrl: result.rows[0].proof_image_url,
      }, 201);
    } catch (err: any) {
      console.error('[payments] submit error:', err.message);
      return error(res, err.message, 500);
    }
  },
);

// ── PATCH /api/payments/:id/approve ──────────────────────────────────────────
paymentsRouter.patch('/:id/approve', requireRole('landlord', 'admin'), async (req, res) => {
  try {
    const { note } = req.body;
    const result = await query(
      `UPDATE rent_payments
       SET status = 'approved', landlord_note = $1, reviewed_at = NOW()
       WHERE id = $2 AND landlord_id = $3
       RETURNING *`,
      [note ?? null, req.params.id, req.user!.sub],
    );
    if (!result.rows.length) return error(res, 'Payment not found or not yours', 404);

    // Create a draft receipt
    const receiptRes = await query(
      `INSERT INTO receipts (payment_id, tenant_id, landlord_id, property_id, amount_paid, payment_date, status)
       SELECT id, tenant_id, landlord_id, property_id, amount_claimed, payment_date, 'draft'
       FROM rent_payments WHERE id = $1
       RETURNING id, receipt_number`,
      [req.params.id],
    ).catch(() => ({ rows: [] as any[] }));

    return success(res, {
      paymentId:     req.params.id,
      receiptId:     receiptRes.rows[0]?.id ?? null,
      receiptNumber: receiptRes.rows[0]?.receipt_number ?? null,
    });
  } catch (err: any) {
    console.error('[payments] approve error:', err.message);
    return error(res, err.message, 500);
  }
});

// ── PATCH /api/payments/:id/reject ───────────────────────────────────────────
paymentsRouter.patch('/:id/reject', requireRole('landlord', 'admin'), async (req, res) => {
  try {
    const { rejectionReason } = req.body;
    const result = await query(
      `UPDATE rent_payments
       SET status = 'rejected', rejection_reason = $1, reviewed_at = NOW()
       WHERE id = $2 AND landlord_id = $3
       RETURNING id`,
      [rejectionReason ?? '', req.params.id, req.user!.sub],
    );
    if (!result.rows.length) return error(res, 'Payment not found or not yours', 404);
    return success(res, { rejected: true });
  } catch (err: any) {
    return error(res, err.message, 500);
  }
});

// ── Helper ────────────────────────────────────────────────────────────────────
function snakeToPayment(row: any) {
  return {
    id:                  row.id,
    tenantId:            row.tenant_id,
    userId:              row.user_id,
    landlordId:          row.landlord_id,
    propertyId:          row.property_id,
    amountClaimed:       row.amount_claimed,
    amountVerified:      row.amount_verified,
    paymentDate:         row.payment_date,
    paymentMethod:       row.payment_method,
    referenceNumber:     row.reference_number,
    notes:               row.notes,
    proofImageUrl:       row.proof_image_url,
    status:              row.status,
    rejectionReason:     row.rejection_reason,
    landlordNote:        row.landlord_note,
    submittedAt:         row.submitted_at,
    reviewedAt:          row.reviewed_at,
    ocrExtractedAmount:  row.ocr_extracted_amount,
    tenantName:          row.tenant_name,
    propertyName:        row.property_name,
  };
}
