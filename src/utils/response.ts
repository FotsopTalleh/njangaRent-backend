// src/utils/response.ts — Consistent API response helpers
import type { Response } from 'express';

export function success(res: Response, data: any, status = 200) {
  return res.status(status).json({ data, status: 'success' });
}

export function paginated(
  res: Response,
  data: any[],
  pagination: { page: number; limit: number; total: number; hasNext: boolean },
) {
  return res.json({ data, pagination, status: 'success' });
}

export function error(
  res: Response,
  message: string,
  status = 400,
  code?: string,
  field?: string,
) {
  return res.status(status).json({
    error: { code: code ?? 'ERROR', message, ...(field ? { field } : {}) },
  });
}
