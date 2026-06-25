// src/middleware/upload.ts — Multer config using memory storage (for Supabase upload)
import multer from 'multer';
import { config } from '../config.js';

// Use memoryStorage: files land in file.buffer, never written to disk.
// The upload utility then streams the buffer to Supabase Storage.
const storage = multer.memoryStorage();

const fileFilter = (_req: any, file: Express.Multer.File, cb: multer.FileFilterCallback) => {
  const allowed = ['image/jpeg', 'image/jpg', 'image/png', 'image/webp'];
  if (allowed.includes(file.mimetype)) {
    cb(null, true);
  } else {
    cb(new Error('Only JPEG, PNG, and WebP images are allowed'));
  }
};

export const upload = multer({
  storage,
  fileFilter,
  limits: { fileSize: config.upload.maxSizeMb * 1024 * 1024 },
});
