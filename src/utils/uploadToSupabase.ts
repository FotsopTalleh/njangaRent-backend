// src/utils/uploadToSupabase.ts — Upload a multer MemoryStorage file to Supabase Storage
import { supabase } from '../lib/supabase.js';
import { randomUUID } from 'crypto';
import path from 'path';

export interface SupabaseUploadResult {
  url: string;
  path: string;
}

/**
 * Upload a multer file (memoryStorage buffer) to a Supabase Storage bucket.
 *
 * @param file   - multer file object (must have .buffer and .originalname)
 * @param bucket - Supabase bucket name e.g. 'listing-images'
 * @param folder - path prefix inside the bucket e.g. 'exterior' | 'room'
 * @returns public URL to the uploaded file
 */
export async function uploadToSupabase(
  file: Express.Multer.File,
  bucket: string,
  folder: string,
): Promise<SupabaseUploadResult> {
  const ext = path.extname(file.originalname).toLowerCase() || '.jpg';
  const uniqueName = `${folder}/${randomUUID()}${ext}`;

  const { error } = await supabase.storage
    .from(bucket)
    .upload(uniqueName, file.buffer, {
      contentType: file.mimetype,
      upsert: false,
    });

  if (error) {
    throw new Error(`Supabase upload failed: ${error.message}`);
  }

  const { data } = supabase.storage.from(bucket).getPublicUrl(uniqueName);

  return {
    url: data.publicUrl,
    path: uniqueName,
  };
}

/**
 * Delete a file from a Supabase Storage bucket by its path.
 * Non-fatal — logs on failure but doesn't throw.
 */
export async function deleteFromSupabase(bucket: string, filePath: string): Promise<void> {
  const { error } = await supabase.storage.from(bucket).remove([filePath]);
  if (error) {
    console.warn(`[supabase] Failed to delete ${filePath} from ${bucket}:`, error.message);
  }
}
