// src/middleware/auth.ts — Clerk authentication middleware
import type { Request, Response, NextFunction } from 'express';
import { clerkMiddleware, getAuth } from '@clerk/express';
import { error } from '../utils/response.js';
import { pool } from '../db/pool.js';

export interface JwtPayload {
  sub: string;   // user id (clerk id)
  email: string;
  role: string;
  name: string;
}

declare global {
  namespace Express {
    interface Request {
      user?: JwtPayload;
      auth?: any; // populated by @clerk/express
    }
  }
}

/**
 * Base clerk middleware — verifies the JWT and populates req.auth.
 * Use this on routes that only need identity, not a DB user record.
 */
export const clerkAuth = clerkMiddleware();

/**
 * Middleware to fetch the user from our database using the Clerk ID
 * and populate `req.user` for compatibility with the rest of the app.
 */
async function attachDbUser(req: Request, res: Response, next: NextFunction) {
  const auth = getAuth(req);
  const userId = auth?.userId;

  // Expose auth on req for routes that read req.auth directly
  req.auth = auth;

  if (!userId) {
    return error(res, 'Authentication required', 401, 'UNAUTHORIZED');
  }

  try {
    const result = await pool.query('SELECT * FROM users WHERE id = $1', [userId]);
    const user = result.rows[0];

    if (!user) {
      // User is Clerk-authenticated but not yet in our DB.
      // This can happen briefly between signup and the /api/auth/sync call.
      return error(res, 'User record not found. Please complete sign-up.', 404, 'USER_NOT_FOUND');
    }

    req.user = {
      sub:   user.id,
      email: user.email,
      role:  user.role,
      name:  user.full_name,
    };
    next();
  } catch (err: any) {
    console.error('[auth] DB error:', err.message);
    return error(res, 'Internal server error', 500, 'INTERNAL_SERVER_ERROR');
  }
}

/**
 * Verify the Clerk token AND populate req.user from the DB.
 * Use on all protected routes that need role-based access.
 */
export const requireAuth = [
  clerkAuth,
  attachDbUser,
];

/**
 * Role guard — must come after requireAuth.
 */
export function requireRole(...roles: string[]) {
  return (req: Request, res: Response, next: NextFunction) => {
    if (!req.user) {
      return error(res, 'Authentication required', 401, 'UNAUTHORIZED');
    }
    if (!roles.includes(req.user.role)) {
      return error(res, 'Insufficient permissions', 403, 'FORBIDDEN');
    }
    next();
  };
}
