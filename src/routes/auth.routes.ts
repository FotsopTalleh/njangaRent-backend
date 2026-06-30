// src/routes/auth.routes.ts
import { Router } from 'express';
import { getAuth } from '@clerk/express';
import { query } from '../db/pool.js';
import { success, error } from '../utils/response.js';
import { clerkClient } from '@clerk/express';

export const authRouter = Router();
// clerkMiddleware() is applied globally in index.ts

authRouter.post('/sync', async (req, res) => {
  const auth = getAuth(req);
  const userId = auth?.userId;
  if (!userId) return error(res, 'Unauthorized', 401);

  try {
    const clerkUser = await clerkClient.users.getUser(userId);
    const email = clerkUser.emailAddresses[0]?.emailAddress || '';
    const fullName = `${clerkUser.firstName || ''} ${clerkUser.lastName || ''}`.trim() || email;
    const phone = clerkUser.phoneNumbers[0]?.phoneNumber || null;
    
    const role = (clerkUser.unsafeMetadata?.role as string) || 'tenant';

    let result;
    try {
      result = await query(
        `INSERT INTO users (id, email, full_name, phone, role, status)
         VALUES ($1, $2, $3, $4, $5, 'ACTIVE')
         ON CONFLICT (id) DO UPDATE 
         SET email = EXCLUDED.email, full_name = EXCLUDED.full_name, phone = EXCLUDED.phone, role = EXCLUDED.role
         RETURNING id, email, full_name, role, status`,
        [userId, email, fullName, phone, role]
      );
    } catch (dbErr: any) {
      // Handle case where user was deleted from Clerk but not Supabase, and recreated with same email
      if (dbErr.code === '23505' && dbErr.constraint === 'users_email_key') {
        await query('DELETE FROM users WHERE email = $1', [email]);
        result = await query(
          `INSERT INTO users (id, email, full_name, phone, role, status)
           VALUES ($1, $2, $3, $4, $5, 'ACTIVE')
           RETURNING id, email, full_name, role, status`,
          [userId, email, fullName, phone, role]
        );
      } else {
        throw dbErr;
      }
    }

    return success(res, { user: result.rows[0] });
  } catch (err: any) {
    console.error('[sync] Error:', err.message);
    return error(res, 'Failed to sync user', 500);
  }
});
