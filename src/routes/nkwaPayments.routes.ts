// src/routes/nkwaPayments.routes.ts
import { Router } from 'express';
import { requireAuth } from '../middleware/auth.js';
import { nkwaService } from '../services/nkwa.service.js';
import { success, error } from '../utils/response.js';

export const nkwaPaymentsRouter = Router();

// Public webhook
nkwaPaymentsRouter.post('/webhook', async (req, res) => {
  try {
    const signature = req.headers['x-nkwa-signature'] as string;
    if (!signature) return res.status(400).send('Missing signature');

    const rawBody = JSON.stringify(req.body);
    if (!nkwaService.verifyWebhookSignature(rawBody, signature)) {
      return res.status(401).send('Invalid signature');
    }

    await nkwaService.handleWebhook(req.body);
    return res.status(200).send('OK');
  } catch (err: any) {
    return res.status(500).send('Webhook error');
  }
});

// Protected routes
nkwaPaymentsRouter.use(requireAuth);

nkwaPaymentsRouter.post('/pay', async (req, res) => {
  try {
    const { listingId, landlordId, amount, phoneNumber, paymentType, reason } = req.body;
    const payerId = req.user!.sub;

    if (!landlordId || !amount || !phoneNumber) {
      return error(res, 'Missing required payment details');
    }

    const result = await nkwaService.initiateCollection({
      phoneNumber,
      amount,
      reason: reason || 'NjangaRent Payment',
      payerId,
      landlordId,
      listingId,
      paymentType: paymentType || 'rent',
    });

    if (result.status === 'failed') {
      return error(res, result.error || 'Payment failed', 400);
    }

    return success(res, result);
  } catch (err: any) {
    return error(res, err.message, 500);
  }
});

nkwaPaymentsRouter.get('/my', async (req, res) => {
  try {
    const payments = await nkwaService.listForUser(req.user!.sub);
    return success(res, payments);
  } catch (err: any) {
    return error(res, err.message, 500);
  }
});

nkwaPaymentsRouter.get('/:paymentId/status', async (req, res) => {
  try {
    const { paymentId } = req.params;
    // Just fetch the payment from DB
    const { query } = await import('../db/pool.js');
    const result = await query(`SELECT status FROM payments WHERE id = $1 AND payer_id = $2`, [paymentId, req.user!.sub]);
    
    if (result.rows.length === 0) {
      return error(res, 'Payment not found', 404);
    }
    
    return success(res, { status: result.rows[0].status });
  } catch (err: any) {
    return error(res, err.message, 500);
  }
});
