// src/services/campay.service.ts — Campay Mobile Money integration
// Docs: https://campay.net/api/docs/
import axios from 'axios';
import crypto from 'crypto';
import { config } from '../config.js';
import { query } from '../db/pool.js';

// ── Campay REST client ────────────────────────────────────────────────────────
// Uses the Permanent Access Token for all authenticated requests.
const campayClient = axios.create({
  baseURL: config.campay.baseUrl,
  headers: {
    Authorization: `Token ${config.campay.permanentToken}`,
    'Content-Type': 'application/json',
  },
  timeout: 30_000,
});

// ── Types ─────────────────────────────────────────────────────────────────────
export interface CampayCollectResult {
  paymentId:     string;
  reference:     string | null; // Campay transaction reference
  ussd_code?:    string;        // USSD code for the user to dial
  status:        'pending' | 'failed';
  operator?:     string;
  error?:        string;
}

export interface CampayTransactionStatus {
  reference:    string;
  status:       'SUCCESSFUL' | 'FAILED' | 'PENDING';
  amount:       number;
  currency:     string;
  operator:     string;
  code:         string;
  operator_ref: string;
  description:  string;
}

// ── Service ───────────────────────────────────────────────────────────────────
export const campayService = {

  /**
   * Initiate a MoMo collection request (MTN or Orange Money).
   * Phone number format: 237XXXXXXXXX (Cameroon country code + 9-digit number).
   */
  async initiateCollection(params: {
    phoneNumber:  string;   // e.g. "237670000000"
    amount:       number;   // XAF
    description:  string;
    payerId:      string;
    landlordId:   string;
    listingId?:   string;
    paymentType:  'deposit' | 'rent';
    externalRef?: string;   // optional idempotency key
  }): Promise<CampayCollectResult> {

    // 1. Insert a pending payment record
    const insertResult = await query(
      `INSERT INTO nkwa_payments
         (listing_id, payer_id, landlord_id, amount, phone_number, payment_type, nkwa_status)
       VALUES ($1, $2, $3, $4, $5, $6, 'initiated')
       RETURNING id`,
      [
        params.listingId ?? null,
        params.payerId,
        params.landlordId,
        params.amount,
        params.phoneNumber,
        params.paymentType,
      ],
    );
    const paymentId = insertResult.rows[0].id as string;

    // 2. Call Campay if credentials are configured
    if (config.campay.permanentToken) {
      try {
        const response = await campayClient.post('/collect/', {
          amount:            String(params.amount),
          currency:          'XAF',
          from:              params.phoneNumber,
          description:       params.description,
          external_reference: params.externalRef ?? paymentId,
        });

        const data = response.data as any;
        const reference = data?.reference ?? null;
        const ussd_code  = data?.ussd_code ?? undefined;
        const operator   = data?.operator  ?? undefined;

        if (reference) {
          await query(
            `UPDATE nkwa_payments
               SET nkwa_transaction_id = $1, nkwa_status = 'pending', updated_at = NOW()
             WHERE id = $2`,
            [reference, paymentId],
          );
        }

        return { paymentId, reference, ussd_code, operator, status: 'pending' };

      } catch (err: any) {
        const errMsg = err.response?.data?.detail
          ?? err.response?.data?.message
          ?? err.message
          ?? 'Payment initiation failed';

        console.error('[Campay] collect error:', err.response?.data ?? err.message);

        await query(
          `UPDATE nkwa_payments SET nkwa_status = 'failed', updated_at = NOW() WHERE id = $1`,
          [paymentId],
        );

        return { paymentId, reference: null, status: 'failed', error: errMsg };
      }
    }

    // 3. Mock mode — no real credentials configured
    const mockRef = `MOCK_${Date.now()}`;
    await query(
      `UPDATE nkwa_payments
         SET nkwa_transaction_id = $1, nkwa_status = 'pending', updated_at = NOW()
       WHERE id = $2`,
      [mockRef, paymentId],
    );
    return { paymentId, reference: mockRef, status: 'pending' };
  },

  /**
   * Poll Campay for the current status of a transaction.
   */
  async getTransactionStatus(reference: string): Promise<CampayTransactionStatus | null> {
    try {
      const response = await campayClient.get(`/transaction/${reference}/`);
      return response.data as CampayTransactionStatus;
    } catch (err: any) {
      console.error('[Campay] status check error:', err.response?.data ?? err.message);
      return null;
    }
  },

  /**
   * Verify Campay webhook signature using the webhook key (HMAC-SHA256).
   */
  verifyWebhookSignature(payload: string, signature: string): boolean {
    if (!config.campay.webhookKey) return false;
    try {
      const expected = crypto
        .createHmac('sha256', config.campay.webhookKey)
        .update(payload)
        .digest('hex');
      return crypto.timingSafeEqual(
        Buffer.from(signature.toLowerCase()),
        Buffer.from(expected.toLowerCase()),
      );
    } catch {
      return false;
    }
  },

  /**
   * Handle Campay webhook — update nkwa_payments status.
   * Campay sends: { reference, status, amount, operator, ... }
   */
  async handleWebhook(data: {
    reference: string;
    status:    string;
    amount?:   number;
  }) {
    // Campay statuses: SUCCESSFUL | FAILED | PENDING
    const dbStatus = data.status === 'SUCCESSFUL' ? 'confirmed' : 'failed';

    const result = await query(
      `UPDATE nkwa_payments
         SET nkwa_status = $1, updated_at = NOW()
       WHERE nkwa_transaction_id = $2
       RETURNING id`,
      [dbStatus, data.reference],
    );

    return { updated: result.rowCount ?? 0 };
  },

  /**
   * List all Campay payments for a given user (payer).
   */
  async listForUser(userId: string) {
    const result = await query(
      `SELECT np.*, l.title AS listing_title
         FROM nkwa_payments np
         LEFT JOIN listings l ON l.id = np.listing_id
        WHERE np.payer_id = $1
        ORDER BY np.created_at DESC`,
      [userId],
    );
    return result.rows;
  },

  /**
   * List all payments received by a landlord.
   */
  async listForLandlord(landlordId: string) {
    const result = await query(
      `SELECT np.*, l.title AS listing_title
         FROM nkwa_payments np
         LEFT JOIN listings l ON l.id = np.listing_id
        WHERE np.landlord_id = $1
        ORDER BY np.created_at DESC`,
      [landlordId],
    );
    return result.rows;
  },
};
