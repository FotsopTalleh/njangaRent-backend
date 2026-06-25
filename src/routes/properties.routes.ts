// src/routes/properties.routes.ts — Property management for landlords
import { Router } from 'express';
import { query } from '../db/pool.js';
import { requireAuth, requireRole } from '../middleware/auth.js';
import { success, paginated, error } from '../utils/response.js';

export const propertiesRouter = Router();
propertiesRouter.use(requireAuth);

// ── GET /api/properties ───────────────────────────────────────────────────────
// Landlord: list own properties. Admin: list all.
propertiesRouter.get('/', async (req, res) => {
  try {
    const page  = Math.max(1, parseInt(String(req.query.page  ?? '1')));
    const limit = Math.min(100, parseInt(String(req.query.limit ?? '20')));
    const offset = (page - 1) * limit;

    const landlordId = req.user!.role === 'admin' ? null : req.user!.sub;

    const whereClause = landlordId ? 'WHERE p.landlord_id = $1' : '';
    const countParams  = landlordId ? [landlordId]           : [];
    const selectParams = landlordId
      ? [landlordId, limit, offset]
      : [limit, offset];

    const countRes = await query(
      `SELECT COUNT(*) FROM properties p ${whereClause}`,
      countParams,
    );
    const total = parseInt(countRes.rows[0].count);

    const limitIdx  = landlordId ? '$2' : '$1';
    const offsetIdx = landlordId ? '$3' : '$2';

    const rows = await query(
      `SELECT p.*,
              (SELECT COUNT(*) FROM tenants t WHERE t.property_id = p.id AND t.status = 'active') AS tenant_count
       FROM properties p
       ${whereClause}
       ORDER BY p.created_at DESC
       LIMIT ${limitIdx} OFFSET ${offsetIdx}`,
      selectParams,
    );

    return paginated(res, rows.rows.map(snakeToProperty), {
      page, limit, total, hasNext: offset + limit < total,
    });
  } catch (err: any) {
    console.error('[properties] list error:', err.message);
    return error(res, err.message, 500);
  }
});

// ── POST /api/properties ──────────────────────────────────────────────────────
propertiesRouter.post('/', requireRole('landlord', 'admin'), async (req, res) => {
  try {
    const { name, address, propertyType, monthlyRent, description } = req.body;
    if (!name || !address || !propertyType || !monthlyRent) {
      return error(res, 'name, address, propertyType and monthlyRent are required');
    }

    const result = await query(
      `INSERT INTO properties (landlord_id, name, address, property_type, monthly_rent, description)
       VALUES ($1, $2, $3, $4, $5, $6)
       RETURNING *`,
      [req.user!.sub, name, address, propertyType, monthlyRent, description ?? null],
    );

    return success(res, snakeToProperty(result.rows[0]), 201);
  } catch (err: any) {
    console.error('[properties] create error:', err.message);
    return error(res, err.message, 500);
  }
});

// ── GET /api/properties/:id ───────────────────────────────────────────────────
propertiesRouter.get('/:id', async (req, res) => {
  try {
    const result = await query(
      `SELECT p.*,
              (SELECT COUNT(*) FROM tenants t WHERE t.property_id = p.id AND t.status = 'active') AS tenant_count
       FROM properties p
       WHERE p.id = $1`,
      [req.params.id],
    );
    if (!result.rows.length) return error(res, 'Property not found', 404);

    const prop = result.rows[0];
    // Landlords can only see their own properties
    if (req.user!.role !== 'admin' && prop.landlord_id !== req.user!.sub) {
      return error(res, 'Forbidden', 403);
    }
    return success(res, snakeToProperty(prop));
  } catch (err: any) {
    return error(res, err.message, 500);
  }
});

// ── PUT /api/properties/:id ───────────────────────────────────────────────────
propertiesRouter.put('/:id', requireRole('landlord', 'admin'), async (req, res) => {
  try {
    const { name, address, propertyType, monthlyRent, description } = req.body;

    const existing = await query('SELECT * FROM properties WHERE id = $1', [req.params.id]);
    if (!existing.rows.length) return error(res, 'Property not found', 404);
    if (req.user!.role !== 'admin' && existing.rows[0].landlord_id !== req.user!.sub) {
      return error(res, 'Forbidden', 403);
    }

    const result = await query(
      `UPDATE properties
       SET name = COALESCE($1, name),
           address = COALESCE($2, address),
           property_type = COALESCE($3, property_type),
           monthly_rent = COALESCE($4, monthly_rent),
           description = COALESCE($5, description),
           updated_at = NOW()
       WHERE id = $6
       RETURNING *`,
      [name ?? null, address ?? null, propertyType ?? null, monthlyRent ?? null, description ?? null, req.params.id],
    );

    return success(res, snakeToProperty(result.rows[0]));
  } catch (err: any) {
    return error(res, err.message, 500);
  }
});

// ── DELETE /api/properties/:id ────────────────────────────────────────────────
propertiesRouter.delete('/:id', requireRole('landlord', 'admin'), async (req, res) => {
  try {
    const existing = await query('SELECT * FROM properties WHERE id = $1', [req.params.id]);
    if (!existing.rows.length) return error(res, 'Property not found', 404);
    if (req.user!.role !== 'admin' && existing.rows[0].landlord_id !== req.user!.sub) {
      return error(res, 'Forbidden', 403);
    }

    await query('DELETE FROM properties WHERE id = $1', [req.params.id]);
    return success(res, { deleted: true });
  } catch (err: any) {
    return error(res, err.message, 500);
  }
});

// ── Helper ────────────────────────────────────────────────────────────────────
function snakeToProperty(row: any) {
  return {
    id:           row.id,
    landlordId:   row.landlord_id,
    name:         row.name,
    address:      row.address,
    propertyType: row.property_type,
    monthlyRent:  row.monthly_rent,
    description:  row.description,
    tenantCount:  parseInt(row.tenant_count ?? '0'),
    createdAt:    row.created_at,
    updatedAt:    row.updated_at,
  };
}
