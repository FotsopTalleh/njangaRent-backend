// src/services/campay.service.ts — Campay Mobile Money integration
// Docs: https://campay.net/api/docs/
import axios from 'axios';
import crypto from 'crypto';
import { config } from '../config.js';
import { query } from '../db/pool.js';

// Uses an interceptor to fetch and attach a fresh token before requests.
const campayClient = axios.create({
  baseURL: config.campay.baseUrl,
  headers: {
    'Content-Type': 'application/json',
  },
  timeout: 30_000,
});

let cachedToken: string | null = null;
let tokenExpiresAt = 0;

async function getCampayToken(): Promise<string> {
  // If we have a valid token (with 1 minute buffer), return it
  if (cachedToken && Date.now() < tokenExpiresAt - 60000) {
    return cachedToken;
  }

  // Otherwise, fetch a new one
  const response = await axios.post(`${config.campay.baseUrl}/token/`, {
    username: config.campay.appUsername,
    password: config.campay.appPassword,
  });

  cachedToken = response.data.token;
  // expires_in is in seconds, typically 3600
  tokenExpiresAt = Date.now() + (response.data.expires_in * 1000);
  
  return cachedToken!;
}

campayClient.interceptors.request.use(async (reqConfig) => {
  // Don't intercept the token request itself if we ever made one via this client
  if (!reqConfig.url?.includes('/token/')) {
    const token = await getCampayToken();
    reqConfig.headers.Authorization = `Token ${token}`;
  }
  return reqConfig;
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
      `INSERT INTO campay_payments
         (listing_id, payer_id, landlord_id, amount, phone_number, payment_type, status)
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
    if (config.campay.appUsername && config.campay.appPassword) {
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
            `UPDATE campay_payments
               SET transaction_id = $1, status = 'pending', updated_at = NOW()
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
          `UPDATE campay_payments SET status = 'failed', updated_at = NOW() WHERE id = $1`,
          [paymentId],
        );

        return { paymentId, reference: null, status: 'failed', error: errMsg };
      }
    }

    // 3. Mock mode — no real credentials configured
    const mockRef = `MOCK_${Date.now()}`;
    await query(
      `UPDATE campay_payments
         SET transaction_id = $1, status = 'pending', updated_at = NOW()
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
   * Handle Campay webhook — update campay_payments status.
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
      `UPDATE campay_payments
         SET status = $1, updated_at = NOW()
       WHERE transaction_id = $2
       RETURNING id, amount, landlord_id, payer_id, payment_type`,
      [dbStatus, data.reference],
    );

    if (dbStatus === 'confirmed' && result.rowCount && result.rowCount > 0) {
      const payment = result.rows[0];
      
      // Check if a receipt already exists
      const existing = await query(
        `SELECT id FROM receipts WHERE campay_payment_id = $1`,
        [payment.id]
      );
      
      if (existing.rowCount === 0) {
        const dateStr = new Date().toISOString().slice(0, 10).replace(/-/g, '');
        const randomStr = Math.random().toString(36).substring(2, 6).toUpperCase();
        const receiptNumber = `RCPT-${dateStr}-${randomStr}`;

        // Attempt to find tenant/property if they are already assigned
        const tenantRes = await query(
          `SELECT id, property_id FROM tenants WHERE user_id = $1 AND landlord_id = $2 AND status = 'active' LIMIT 1`,
          [payment.payer_id, payment.landlord_id]
        );
        
        const tenantId = tenantRes.rows[0]?.id ?? null;
        const propertyId = tenantRes.rows[0]?.property_id ?? null;

        await query(
          `INSERT INTO receipts 
             (campay_payment_id, landlord_id, tenant_id, property_id, receipt_number, amount_paid, payment_date, period_label, status)
           VALUES ($1, $2, $3, $4, $5, $6, NOW(), $7, 'disbursed')`,
          [
            payment.id,
            payment.landlord_id,
            tenantId,
            propertyId,
            receiptNumber,
            payment.amount,
            payment.payment_type === 'deposit' ? 'Deposit Payment' : 'Rent Payment'
          ]
        );
      }

      // Auto-disburse to landlord's registered phone number
      try {
        await campayService.disburseToLandlord({
          landlordId:  payment.landlord_id,
          amount:      Number(payment.amount),
          description: `NjangaRent rent payment disbursement`,
          paymentId:   payment.id,
        });
      } catch (disbErr: any) {
        // Non-fatal — log but don't fail the webhook
        console.warn('[campay] disburse to landlord failed (payout may not be enabled):', disbErr.message);
      }
    }

    return { updated: result.rowCount ?? 0 };
  },

  /**
   * Disburse (transfer) funds to the landlord's registered phone number.
   * Requires CamPay payout/disburse to be enabled on your account.
   * Gracefully skips if landlord has no phone number on file.
   */
  async disburseToLandlord(params: {
    landlordId:  string;
    amount:      number;
    description: string;
    paymentId:   string;   // our internal campay_payment id, used as external_reference
  }): Promise<void> {
    // Fetch landlord's phone from DB
    const landlordRes = await query(
      `SELECT phone, full_name FROM users WHERE id = $1`,
      [params.landlordId]
    );
    const landlord = landlordRes.rows[0];
    if (!landlord?.phone) {
      console.warn(`[campay] Landlord ${params.landlordId} has no phone — skipping disburse`);
      return;
    }

    // Normalize phone to 237XXXXXXXXX
    const rawPhone = String(landlord.phone).replace(/^\+/, '').replace(/\s/g, '');
    const normPhone = rawPhone.startsWith('237') ? rawPhone : `237${rawPhone}`;

    // CamPay /transfer/ (disburse) endpoint
    // Docs: https://campay.net/api/docs/#tag/Transfer
    const response = await campayClient.post('/transfer/', {
      amount:             String(params.amount),
      currency:           'XAF',
      to:                 normPhone,
      description:        params.description,
      external_reference: `DISB_${params.paymentId}`,
    });

    console.info(
      `[campay] Disbursed ${params.amount} XAF to landlord ${landlord.full_name} (${normPhone}):`,
      response.data
    );
  },

  /**
   * List all Campay payments for a given user (payer).
   */
  async listForUser(userId: string) {
    const result = await query(
      `SELECT np.*, l.title AS listing_title
         FROM campay_payments np
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
         FROM campay_payments np
         LEFT JOIN listings l ON l.id = np.listing_id
        WHERE np.landlord_id = $1
        ORDER BY np.created_at DESC`,
      [landlordId],
    );
    return result.rows;
  },
};
