// src/routes/tenants.routes.ts — Tenant management for landlords
import { Router } from 'express';
import { query } from '../db/pool.js';
import { requireAuth, requireRole } from '../middleware/auth.js';
import { success, paginated, error } from '../utils/response.js';

export const tenantsRouter = Router();
tenantsRouter.use(requireAuth);

// ── GET /api/tenants/me ───────────────────────────────────────────────────────
// Tenant: fetch own tenant record (rent, property, etc.)
tenantsRouter.get('/me', async (req, res) => {
  try {
    const result = await query(
      `SELECT t.*, p.name AS property_name, p.address AS property_address, p.monthly_rent
       FROM tenants t
       LEFT JOIN properties p ON p.id = t.property_id
       WHERE t.user_id = $1 AND t.status = 'active'
       LIMIT 1`,
      [req.user!.sub],
    );
    if (!result.rows.length) return error(res, 'Tenant record not found', 404);
    return success(res, { tenant: snakeToTenant(result.rows[0]) });
  } catch (err: any) {
    console.error('[tenants] me error:', err.message);
    return error(res, err.message, 500);
  }
});

// ── GET /api/tenants ──────────────────────────────────────────────────────────
// Landlord: list tenants for my properties
tenantsRouter.get('/', requireRole('landlord', 'admin'), async (req, res) => {
  try {
    const page       = Math.max(1, parseInt(String(req.query.page  ?? '1')));
    const limit      = Math.min(100, parseInt(String(req.query.limit ?? '20')));
    const offset     = (page - 1) * limit;
    const propertyId = req.query.propertyId as string | undefined;
    const status     = (req.query.status as string | undefined) ?? 'active';

    const conditions: string[] = ['t.status = $1'];
    const params: any[] = [status];

    if (req.user!.role !== 'admin') {
      params.push(req.user!.sub);
      conditions.push(`p.landlord_id = $${params.length}`);
    }
    if (propertyId) {
      params.push(propertyId);
      conditions.push(`t.property_id = $${params.length}`);
    }

    const where = conditions.length ? `WHERE ${conditions.join(' AND ')}` : '';

    const countRes = await query(
      `SELECT COUNT(*)
       FROM tenants t
       LEFT JOIN properties p ON p.id = t.property_id
       ${where}`,
      params,
    );
    const total = parseInt(countRes.rows[0].count);

    const rows = await query(
      `SELECT t.*, u.full_name, u.email, p.name AS property_name
       FROM tenants t
       LEFT JOIN users u ON u.id = t.user_id
       LEFT JOIN properties p ON p.id = t.property_id
       ${where}
       ORDER BY t.created_at DESC
       LIMIT $${params.length + 1} OFFSET $${params.length + 2}`,
      [...params, limit, offset],
    );

    return paginated(res, rows.rows.map(snakeToTenant), {
      page, limit, total, hasNext: offset + limit < total,
    });
  } catch (err: any) {
    console.error('[tenants] list error:', err.message);
    return error(res, err.message, 500);
  }
});

// ── GET /api/tenants/:id ──────────────────────────────────────────────────────
tenantsRouter.get('/:id', requireRole('landlord', 'admin'), async (req, res) => {
  try {
    const result = await query(
      `SELECT t.*, u.full_name, u.email, p.name AS property_name, p.address AS property_address
       FROM tenants t
       LEFT JOIN users u ON u.id = t.user_id
       LEFT JOIN properties p ON p.id = t.property_id
       WHERE t.id = $1`,
      [req.params.id],
    );
    if (!result.rows.length) return error(res, 'Tenant not found', 404);
    const tenant = result.rows[0];
    if (req.user!.role !== 'admin') {
      // Verify this tenant belongs to one of the landlord's properties
      const ownership = await query(
        'SELECT 1 FROM properties WHERE id = $1 AND landlord_id = $2',
        [tenant.property_id, req.user!.sub],
      );
      if (!ownership.rows.length) return error(res, 'Forbidden', 403);
    }

    // Fetch recent payments
    const paymentsRes = await query(
      `SELECT * FROM rent_payments WHERE tenant_id = $1 ORDER BY submitted_at DESC LIMIT 5`,
      [req.params.id],
    );

    return success(res, {
      tenant: snakeToTenant(tenant),
      user:   { fullName: tenant.full_name, email: tenant.email },
      recentPayments: paymentsRes.rows.map(snakeToPayment),
    });
  } catch (err: any) {
    return error(res, err.message, 500);
  }
});

// ── POST /api/tenants/invite ──────────────────────────────────────────────────
tenantsRouter.post('/invite', requireRole('landlord', 'admin'), async (req, res) => {
  try {
    const { email, propertyId, monthlyRent, rentDueDay } = req.body;
    if (!email || !propertyId || !monthlyRent) {
      return error(res, 'email, propertyId and monthlyRent are required');
    }

    // Verify property belongs to this landlord
    if (req.user!.role !== 'admin') {
      const propRes = await query(
        'SELECT 1 FROM properties WHERE id = $1 AND landlord_id = $2',
        [propertyId, req.user!.sub],
      );
      if (!propRes.rows.length) return error(res, 'Property not found or not yours', 404);
    }

    // Generate an invite token
    const token = Buffer.from(
      JSON.stringify({ email, propertyId, landlordId: req.user!.sub, monthlyRent, rentDueDay, ts: Date.now() })
    ).toString('base64url');

    // Store invitation
    const inviteRes = await query(
      `INSERT INTO tenant_invitations (landlord_id, property_id, email, monthly_rent, rent_due_day, token)
       VALUES ($1, $2, $3, $4, $5, $6)
       ON CONFLICT (email, property_id) DO UPDATE
         SET token = EXCLUDED.token, monthly_rent = EXCLUDED.monthly_rent, rent_due_day = EXCLUDED.rent_due_day, updated_at = NOW()
       RETURNING id`,
      [req.user!.sub, propertyId, email, monthlyRent, rentDueDay ?? 1, token],
    );

    const baseUrl = process.env.FRONTEND_URL ?? 'http://localhost:8080';
    return success(res, {
      invitationId: inviteRes.rows[0].id,
      inviteToken:  token,
      inviteUrl:    `${baseUrl}/invite?token=${token}`,
    }, 201);
  } catch (err: any) {
    console.error('[tenants] invite error:', err.message);
    return error(res, err.message, 500);
  }
});

// ── DELETE /api/tenants/:id ───────────────────────────────────────────────────
tenantsRouter.delete('/:id', requireRole('landlord', 'admin'), async (req, res) => {
  try {
    const result = await query('SELECT * FROM tenants WHERE id = $1', [req.params.id]);
    if (!result.rows.length) return error(res, 'Tenant not found', 404);

    if (req.user!.role !== 'admin') {
      const ownership = await query(
        'SELECT 1 FROM properties WHERE id = $1 AND landlord_id = $2',
        [result.rows[0].property_id, req.user!.sub],
      );
      if (!ownership.rows.length) return error(res, 'Forbidden', 403);
    }

    await query(`UPDATE tenants SET status = 'removed', updated_at = NOW() WHERE id = $1`, [req.params.id]);
    return success(res, { removed: true });
  } catch (err: any) {
    return error(res, err.message, 500);
  }
});

// ── Helpers ───────────────────────────────────────────────────────────────────
function snakeToTenant(row: any) {
  return {
    id:           row.id,
    userId:       row.user_id,
    landlordId:   row.landlord_id,
    propertyId:   row.property_id,
    monthlyRent:  row.monthly_rent,
    rentDueDay:   row.rent_due_day,
    status:       row.status,
    createdAt:    row.created_at,
    updatedAt:    row.updated_at,
    fullName:     row.full_name,
    email:        row.email,
    propertyName: row.property_name,
  };
}

function snakeToPayment(row: any) {
  return {
    id:              row.id,
    tenantId:        row.tenant_id,
    amountClaimed:   row.amount_claimed,
    status:          row.status,
    submittedAt:     row.submitted_at,
    paymentMethod:   row.payment_method,
  };
}
