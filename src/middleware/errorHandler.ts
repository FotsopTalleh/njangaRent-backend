// src/middleware/errorHandler.ts — Global error handler
import type { Request, Response, NextFunction } from 'express';

export function errorHandler(err: any, _req: Request, res: Response, _next: NextFunction) {
  console.error('[ERROR]', err.message || err);

  if (err.type === 'entity.too.large') {
    return res.status(413).json({
      error: { code: 'PAYLOAD_TOO_LARGE', message: 'File upload exceeds size limit' },
    });
  }

  const status = err.status ?? err.statusCode ?? 500;
  const message = status === 500 ? 'Internal server error' : (err.message ?? 'Unknown error');

  res.status(status).json({
    error: { code: err.code ?? 'INTERNAL_ERROR', message },
  });
}
