// src/routes/campay.routes.ts — Campay MoMo payment endpoints
import { Router, type Request, type Response } from 'express';
import { requireAuth, requireRole } from '../middleware/auth.js';
import { campayService } from '../services/campay.service.js';
import { success, error } from '../utils/response.js';

export const campayRouter = Router();

// ── Public: Campay webhook ────────────────────────────────────────────────────
// Campay sends a POST to this URL when a payment status changes.
// Register this URL in your Campay dashboard as the webhook endpoint.
campayRouter.post('/webhook', async (req: Request, res: Response) => {
  try {
    // Campay may send signature in X-Campay-Signature header
    const signature = (req.headers['x-campay-signature'] ?? '') as string;

    if (signature) {
      const rawBody = JSON.stringify(req.body);
      if (!campayService.verifyWebhookSignature(rawBody, signature)) {
        return res.status(401).json({ error: 'Invalid webhook signature' });
      }
    }

    const { reference, status, amount } = req.body;
    if (!reference || !status) {
      return res.status(400).json({ error: 'Missing reference or status' });
    }

    const result = await campayService.handleWebhook({ reference, status, amount });
    return res.status(200).json({ ok: true, updated: result.updated });
  } catch (err: any) {
    console.error('[campay] webhook error:', err.message);
    return res.status(500).json({ error: 'Webhook processing failed' });
  }
});

// ── Protected routes ──────────────────────────────────────────────────────────
campayRouter.use(requireAuth);

/**
 * GET /api/campay/listing-info/:listingId
 * Returns listing title, rent amount, and landlord's name + masked phone.
 * Used by the pay page to show the student who they're paying.
 */
campayRouter.get('/listing-info/:listingId', async (req: Request, res: Response) => {
  try {
    const { pool } = await import('../db/pool.js');
    const result = await pool.query(
      `SELECT l.id, l.title, l.rent_amount, l.display_address,
              u.full_name AS landlord_name, u.phone AS landlord_phone, u.id AS landlord_id
       FROM listings l
       JOIN users u ON u.id = l.landlord_id
       WHERE l.id = $1`,
      [req.params.listingId]
    );
    if (!result.rows.length) return error(res, 'Listing not found', 404);

    const row = result.rows[0];
    // Mask the phone — show first 3 and last 2 digits e.g. 670XXXX45
    const rawPhone: string = (row.landlord_phone ?? '').replace(/^\+?237/, '').replace(/\s/g, '');
    const maskedPhone = rawPhone.length >= 5
      ? `+237 ${rawPhone.slice(0, 3)}${'X'.repeat(rawPhone.length - 5)}${rawPhone.slice(-2)}`
      : row.landlord_phone ?? 'N/A';

    return success(res, {
      listingId:      row.id,
      title:          row.title,
      rentAmount:     row.rent_amount,
      displayAddress: row.display_address,
      landlordId:     row.landlord_id,
      landlordName:   row.landlord_name,
      landlordPhone:  maskedPhone,        // masked for privacy
    });
  } catch (err: any) {
    return error(res, err.message, 500);
  }
});



/**
 * POST /api/campay/pay
 * Initiate a MoMo collection (student or tenant pays).
 * Body: { phoneNumber, amount, description, landlordId, listingId?, paymentType }
 */
campayRouter.post('/pay', async (req: Request, res: Response) => {
  try {
    const {
      phoneNumber,
      amount,
      description,
      landlordId,
      listingId,
      paymentType,
    } = req.body;

    if (!phoneNumber || !amount) {
      return error(res, 'phoneNumber and amount are required', 400);
    }

    let finalLandlordId = landlordId;
    
    // Deduce landlordId from listingId if not provided
    if (!finalLandlordId && listingId) {
      const { pool } = await import('../db/pool.js');
      const listingRes = await pool.query(`SELECT landlord_id FROM listings WHERE id = $1`, [listingId]);
      if (listingRes.rows.length > 0) {
        finalLandlordId = listingRes.rows[0].landlord_id;
      }
    }

    if (!finalLandlordId) {
      return error(res, 'landlordId is required, or provide a valid listingId to deduce it', 400);
    }

    // Normalise phone number — ensure it starts with 237
    const phone = String(phoneNumber).replace(/^\+/, '');
    const normPhone = phone.startsWith('237') ? phone : `237${phone}`;

    const result = await campayService.initiateCollection({
      phoneNumber:  normPhone,
      amount:       Number(amount),
      description:  description ?? 'NjangaRent Payment',
      payerId:      req.user!.sub,
      landlordId:   finalLandlordId,
      listingId,
      paymentType:  paymentType ?? 'rent',
    });

    if (result.status === 'failed') {
      return error(res, result.error ?? 'Payment initiation failed', 400);
    }

    return success(res, {
      paymentId:  result.paymentId,
      reference:  result.reference,
      ussd_code:  result.ussd_code,
      operator:   result.operator,
      status:     result.status,
    });
  } catch (err: any) {
    console.error('[campay] pay error:', err.message);
    return error(res, err.message, 500);
  }
});

/**
 * GET /api/campay/status/:reference
 * Poll the live status of a Campay transaction.
 */
campayRouter.get('/status/:reference', async (req: Request, res: Response) => {
  try {
    const txn = await campayService.getTransactionStatus(req.params.reference);
    if (!txn) return error(res, 'Transaction not found or unreachable', 404);
    
    // Sync to DB locally since webhooks might not arrive in dev or might be delayed
    if (txn.status === 'SUCCESSFUL' || txn.status === 'FAILED') {
      await campayService.handleWebhook({
        reference: txn.reference,
        status: txn.status,
        amount: txn.amount,
      });
    }

    return success(res, txn);
  } catch (err: any) {
    return error(res, err.message, 500);
  }
});

/**
 * GET /api/campay/my
 * List all Campay payments made by the authenticated user.
 */
campayRouter.get('/my', async (req: Request, res: Response) => {
  try {
    const payments = await campayService.listForUser(req.user!.sub);
    return success(res, payments);
  } catch (err: any) {
    return error(res, err.message, 500);
  }
});

/**
 * GET /api/campay/received
 * Landlord: list all payments received.
 */
campayRouter.get(
  '/received',
  requireRole('landlord', 'admin'),
  async (req: Request, res: Response) => {
    try {
      const payments = await campayService.listForLandlord(req.user!.sub);
      return success(res, payments);
    } catch (err: any) {
      return error(res, err.message, 500);
    }
  },
);
