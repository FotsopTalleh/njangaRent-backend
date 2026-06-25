import { Router, Request, Response } from 'express';
import { listingService } from '../services/listing.service.js';
import { paginated, success, error } from '../utils/response.js';
import { requireAuth, requireRole } from '../middleware/auth.js';
import { upload } from '../middleware/upload.js';
import { uploadToSupabase } from '../utils/uploadToSupabase.js';

export const listingsRouter = Router();

listingsRouter.get('/', async (req: Request, res: Response) => {
  try {
    const params = {
      page: req.query.page ? parseInt(req.query.page as string, 10) : undefined,
      limit: req.query.limit ? parseInt(req.query.limit as string, 10) : undefined,
      propertyType: req.query.propertyType as string,
      minRent: req.query.minRent ? parseInt(req.query.minRent as string, 10) : undefined,
      maxRent: req.query.maxRent ? parseInt(req.query.maxRent as string, 10) : undefined,
      amenities: req.query.amenities as string,
      maxDistanceKm: req.query.maxDistanceKm ? parseFloat(req.query.maxDistanceKm as string) : undefined,
      sort: req.query.sort as any,
    };
    const result = await listingService.browse(params);
    return paginated(res, result.data, result.pagination);
  } catch (err: any) {
    return error(res, err.message, 500);
  }
});

listingsRouter.get('/my', requireAuth, requireRole('landlord', 'admin'), async (req: Request, res: Response) => {
  try {
    const status = req.query.status as string | undefined;
    const listings = await listingService.getMyListings(req.user!.sub, status);
    return success(res, listings);
  } catch (err: any) {
    return error(res, err.message, 500);
  }
});

listingsRouter.post(
  '/',
  requireAuth,
  requireRole('landlord', 'admin'),
  upload.fields([{ name: 'exteriorImages', maxCount: 8 }, { name: 'roomImages', maxCount: 8 }]),
  async (req: Request, res: Response) => {
    try {
      const files = req.files as { [fieldname: string]: Express.Multer.File[] };

      if (!files.exteriorImages?.length) {
        return error(res, 'At least one exterior image is required', 400);
      }

      const uploadResults = await Promise.all([
        ...(files.exteriorImages ?? []).map((f) =>
          uploadToSupabase(f, 'listing-images', 'exterior').then((r) => ({ ...r, category: 'exterior' }))
        ),
        ...(files.roomImages ?? []).map((f) =>
          uploadToSupabase(f, 'listing-images', 'room').then((r) => ({ ...r, category: 'room' }))
        ),
      ]);

      const listing = await listingService.create(req.user!.sub, req.body, uploadResults);
      return success(res, listing, 201);
    } catch (err: any) {
      console.error('[listings] create error:', err.message);
      return error(res, err.message, 500);
    }
  }
);

listingsRouter.get('/:id', async (req: Request, res: Response) => {
  try {
    const listing = await listingService.getById(req.params.id);
    if (!listing) return error(res, 'Listing not found', 404);
    return success(res, listing);
  } catch (err: any) {
    return error(res, err.message, 500);
  }
});

// PUT /api/listings/:id — landlord updates own listing fields
listingsRouter.put(
  '/:id',
  requireAuth,
  requireRole('landlord', 'admin'),
  upload.fields([{ name: 'exteriorImages', maxCount: 8 }, { name: 'roomImages', maxCount: 8 }]),
  async (req: Request, res: Response) => {
    try {
      const existing = await listingService.getById(req.params.id);
      if (!existing) return error(res, 'Listing not found', 404);
      if (req.user!.role !== 'admin' && existing.landlordId !== req.user!.sub) {
        return error(res, 'Forbidden', 403);
      }

      const files = req.files as { [fieldname: string]: Express.Multer.File[] };
      const newImages: { url: string; category: string }[] = [];

      if (files?.exteriorImages?.length) {
        const uploaded = await Promise.all(
          files.exteriorImages.map((f) =>
            uploadToSupabase(f, 'listing-images', 'exterior').then((r) => ({ ...r, category: 'exterior' }))
          )
        );
        newImages.push(...uploaded);
      }
      if (files?.roomImages?.length) {
        const uploaded = await Promise.all(
          files.roomImages.map((f) =>
            uploadToSupabase(f, 'listing-images', 'room').then((r) => ({ ...r, category: 'room' }))
          )
        );
        newImages.push(...uploaded);
      }

      const updated = await listingService.update(req.params.id, req.body, newImages);
      return success(res, updated);
    } catch (err: any) {
      console.error('[listings] update error:', err.message);
      return error(res, err.message, 500);
    }
  }
);

// DELETE /api/listings/:id — soft-delete (sets status to 'deactivated')
listingsRouter.delete('/:id', requireAuth, requireRole('landlord', 'admin'), async (req: Request, res: Response) => {
  try {
    const existing = await listingService.getById(req.params.id);
    if (!existing) return error(res, 'Listing not found', 404);
    if (req.user!.role !== 'admin' && existing.landlordId !== req.user!.sub) {
      return error(res, 'Forbidden', 403);
    }

    await listingService.deactivate(req.params.id);
    return success(res, { deactivated: true });
  } catch (err: any) {
    console.error('[listings] delete error:', err.message);
    return error(res, err.message, 500);
  }
});
