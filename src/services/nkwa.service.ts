// src/services/nkwa.service.ts — Nkwa Mobile Money integration
import axios from 'axios';
import crypto from 'crypto';
import { config } from '../config.js';
import { query } from '../db/pool.js';

const nkwaClient = axios.create({
  baseURL: config.nkwa.baseUrl,
  headers: {
    'X-API-Key':    config.nkwa.apiKey,
    'X-API-Secret': config.nkwa.apiSecret,
    'Content-Type': 'application/json',
  },
  timeout: 30_000,
});

export const nkwaService = {
  /**
   * Initiate a MoMo collection request.
   * Returns the transaction ID from Nkwa.
   */
  async initiateCollection(params: {
    phoneNumber: string;
    amount: number;
    reason: string;
    payerId: string;
    landlordId: string;
    listingId?: string;
    paymentType: 'deposit' | 'rent';
  }) {
    // Store payment record
    const insertResult = await query(
      `INSERT INTO nkwa_payments (listing_id, payer_id, landlord_id, amount, phone_number, payment_type, nkwa_status)
       VALUES ($1, $2, $3, $4, $5, $6, 'initiated')
       RETURNING id`,
      [params.listingId ?? null, params.payerId, params.landlordId, params.amount, params.phoneNumber, params.paymentType],
    );
    const paymentId = insertResult.rows[0].id;

    // If Nkwa credentials are configured, call the API
    if (config.nkwa.apiKey && config.nkwa.apiKey !== 'your_nkwa_api_key') {
      try {
        const response = await nkwaClient.post('/api/v1/collect', {
          phone_number: params.phoneNumber,
          amount:       params.amount,
          currency:     'XAF',
          reason:       params.reason,
          external_ref: paymentId,
        });

        const txnId = response.data?.transaction_id ?? response.data?.data?.transaction_id;
        if (txnId) {
          await query(
            `UPDATE nkwa_payments SET nkwa_transaction_id = $1, nkwa_status = 'pending' WHERE id = $2`,
            [txnId, paymentId],
          );
        }

        return { paymentId, transactionId: txnId, status: 'pending' };
      } catch (err: any) {
        console.error('[Nkwa] Collection failed:', err.response?.data ?? err.message);
        await query(
          `UPDATE nkwa_payments SET nkwa_status = 'failed' WHERE id = $1`,
          [paymentId],
        );
        return { paymentId, transactionId: null, status: 'failed', error: err.response?.data?.message ?? 'Payment initiation failed' };
      }
    }

    // Mock mode — no real Nkwa credentials
    const mockTxnId = `MOCK_${Date.now()}`;
    await query(
      `UPDATE nkwa_payments SET nkwa_transaction_id = $1, nkwa_status = 'pending' WHERE id = $2`,
      [mockTxnId, paymentId],
    );

    return { paymentId, transactionId: mockTxnId, status: 'pending' };
  },

  /**
   * Verify Nkwa webhook HMAC signature.
   */
  verifyWebhookSignature(payload: string, signature: string): boolean {
    if (!config.nkwa.webhookSecret) return false;
    const expected = crypto
      .createHmac('sha256', config.nkwa.webhookSecret)
      .update(payload)
      .digest('hex');
    return crypto.timingSafeEqual(Buffer.from(signature), Buffer.from(expected));
  },

  /**
   * Handle Nkwa webhook callback — update payment status.
   */
  async handleWebhook(data: { transaction_id: string; status: string; amount: number }) {
    const nkwaStatus = data.status === 'success' ? 'confirmed' : 'failed';
    await query(
      `UPDATE nkwa_payments SET nkwa_status = $1, updated_at = NOW() WHERE nkwa_transaction_id = $2`,
      [nkwaStatus, data.transaction_id],
    );
    return { updated: true };
  },

  /**
   * List payments for a user.
   */
  async listForUser(userId: string) {
    const result = await query(
      `SELECT np.*, l.title as listing_title
       FROM nkwa_payments np
       LEFT JOIN listings l ON l.id = np.listing_id
       WHERE np.payer_id = $1
       ORDER BY np.created_at DESC`,
      [userId],
    );
    return result.rows;
  },
};
