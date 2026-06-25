// src/services/listing.service.ts
import { query } from '../db/pool.js';
import { distanceFromMolyko } from '../utils/haversine.js';

export const listingService = {
  /**
   * Create a new listing and its images
   */
  async create(landlordId: string, data: any, images: { url: string; category: string }[]) {
    // Basic validation
    const status = 'active'; // Changed from 'pending_admin_review' to 'active' to make it instantly visible
    
    // Parse amenities
    let amenitiesJson = '[]';
    if (data.amenities) {
      amenitiesJson = JSON.stringify(data.amenities.split(',').filter(Boolean));
    }

    const sql = `
      INSERT INTO listings (
        landlord_id, title, description, property_type, rent_amount,
        rent_period, available_from, amenities, rules, max_occupants,
        lat, lng, display_address, distance_from_molyko_km, status
      ) VALUES (
        $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15
      ) RETURNING id
    `;
    
    // calculate distance if lat/lng are provided
    let distance = null;
    if (data.lat && data.lng) {
      distance = distanceFromMolyko(parseFloat(data.lat), parseFloat(data.lng));
    }

    const values = [
      landlordId,
      data.title,
      data.description || null,
      data.propertyType,
      parseInt(data.rentAmount, 10),
      data.rentPeriod || 'monthly',
      data.availableFrom || null,
      amenitiesJson,
      data.rules || null,
      parseInt(data.maxOccupants, 10) || 1,
      data.lat ? parseFloat(data.lat) : null,
      data.lng ? parseFloat(data.lng) : null,
      data.displayAddress || null,
      distance,
      status
    ];

    const result = await query(sql, values);
    const listingId = result.rows[0].id;

    // Insert images
    if (images && images.length > 0) {
      let extSort = 0;
      let roomSort = 0;
      for (const img of images) {
        const sort = img.category === 'exterior' ? extSort++ : roomSort++;
        await query(
          'INSERT INTO listing_images (listing_id, url, category, sort_order) VALUES ($1, $2, $3, $4)',
          [listingId, img.url, img.category, sort]
        );
      }
    }

    return this.getById(listingId);
  },

  /**
   * Get all listings for a specific landlord
   */
  async getMyListings(landlordId: string, status?: string) {
    let sql = `
      SELECT l.*,
        COALESCE(
          json_agg(
            json_build_object('url', li.url, 'category', li.category)
            ORDER BY li.sort_order
          ) FILTER (WHERE li.id IS NOT NULL), '[]'
        ) as images
      FROM listings l
      LEFT JOIN listing_images li ON l.id = li.listing_id
      WHERE l.landlord_id = $1
    `;
    const values: any[] = [landlordId];
    
    if (status) {
      sql += ` AND l.status = $2`;
      values.push(status);
    }
    
    sql += ' GROUP BY l.id ORDER BY l.created_at DESC';
    
    const result = await query(sql, values);
    return result.rows.map(row => this.formatListingObj(row));
  },
  /**
   * Browse public active listings with filters
   */
  async browse(params: {
    page?: number;
    limit?: number;
    propertyType?: string;
    minRent?: number;
    maxRent?: number;
    amenities?: string;
    maxDistanceKm?: number;
    sort?: 'newest' | 'price_asc' | 'price_desc' | 'closest';
  }) {
    const page = params.page ?? 1;
    const limit = params.limit ?? 20;
    const offset = (page - 1) * limit;

    let sql = `
      SELECT l.*,
        COALESCE(
          json_agg(
            json_build_object('url', li.url, 'category', li.category)
            ORDER BY li.sort_order
          ) FILTER (WHERE li.id IS NOT NULL), '[]'
        ) as images
      FROM listings l
      LEFT JOIN listing_images li ON l.id = li.listing_id
      WHERE l.status = 'active'
    `;
    const values: any[] = [];
    let paramIndex = 1;

    if (params.propertyType) {
      sql += ` AND l.property_type = $${paramIndex++}`;
      values.push(params.propertyType);
    }
    if (params.minRent) {
      sql += ` AND l.rent_amount >= $${paramIndex++}`;
      values.push(params.minRent);
    }
    if (params.maxRent) {
      sql += ` AND l.rent_amount <= $${paramIndex++}`;
      values.push(params.maxRent);
    }
    if (params.maxDistanceKm) {
      sql += ` AND l.distance_from_molyko_km <= $${paramIndex++}`;
      values.push(params.maxDistanceKm);
    }
    // simple amenities search if provided (e.g. 'wifi,water')
    if (params.amenities) {
      const amList = params.amenities.split(',');
      for (const am of amList) {
        sql += ` AND l.amenities ? $${paramIndex++}`;
        values.push(am);
      }
    }

    sql += ' GROUP BY l.id';

    if (params.sort === 'price_asc') {
      sql += ' ORDER BY l.rent_amount ASC, l.created_at DESC';
    } else if (params.sort === 'price_desc') {
      sql += ' ORDER BY l.rent_amount DESC, l.created_at DESC';
    } else if (params.sort === 'closest') {
      sql += ' ORDER BY l.distance_from_molyko_km ASC NULLS LAST, l.created_at DESC';
    } else {
      sql += ' ORDER BY l.created_at DESC';
    }

    const totalSql = `SELECT count(*) FROM (${sql}) as sub`;
    const totalResult = await query(totalSql, values);
    const total = parseInt(totalResult.rows[0].count, 10);

    sql += ` LIMIT $${paramIndex++} OFFSET $${paramIndex++}`;
    values.push(limit, offset);

    const result = await query(sql, values);

    // Format output
    const data = result.rows.map(row => this.formatListingObj(row));

    return {
      data,
      pagination: {
        page,
        limit,
        total,
        hasNext: offset + limit < total,
      },
    };
  },

  /**
   * Get single listing with images
   */
  async getById(id: string) {
    const sql = `
      SELECT l.*,
        COALESCE(
          json_agg(
            json_build_object('url', li.url, 'category', li.category)
            ORDER BY li.sort_order
          ) FILTER (WHERE li.id IS NOT NULL), '[]'
        ) as images
      FROM listings l
      LEFT JOIN listing_images li ON l.id = li.listing_id
      WHERE l.id = $1
      GROUP BY l.id
    `;
    const result = await query(sql, [id]);
    if (result.rows.length === 0) return null;

    // increment views
    await query(`UPDATE listings SET views_count = views_count + 1 WHERE id = $1`, [id]);

    return this.formatListingObj(result.rows[0]);
  },

  /**
   * Soft-delete: set status to 'deactivated'
   */
  async deactivate(id: string) {
    await query(
      `UPDATE listings SET status = 'deactivated', updated_at = NOW() WHERE id = $1`,
      [id]
    );
  },

  /**
   * Update listing fields and optionally replace images
   */
  async update(id: string, body: any, newImages: { url: string; category: string }[]) {
    const {
      title, description, propertyType, rentAmount, rentPeriod,
      availableFrom, amenities, rules, maxOccupants,
      lat, lng, displayAddress, distanceFromMolykoKm,
    } = body;

    await query(
      `UPDATE listings SET
        title                   = COALESCE($1,  title),
        description             = COALESCE($2,  description),
        property_type           = COALESCE($3,  property_type),
        rent_amount             = COALESCE($4,  rent_amount),
        rent_period             = COALESCE($5,  rent_period),
        available_from          = COALESCE($6,  available_from),
        amenities               = COALESCE($7::jsonb, amenities),
        rules                   = COALESCE($8::jsonb, rules),
        max_occupants           = COALESCE($9,  max_occupants),
        lat                     = COALESCE($10, lat),
        lng                     = COALESCE($11, lng),
        display_address         = COALESCE($12, display_address),
        distance_from_molyko_km = COALESCE($13, distance_from_molyko_km),
        updated_at              = NOW()
      WHERE id = $14`,
      [
        title ?? null, description ?? null, propertyType ?? null,
        rentAmount ? parseFloat(rentAmount) : null,
        rentPeriod ?? null, availableFrom ?? null,
        amenities ? JSON.stringify(amenities) : null,
        rules ? JSON.stringify(rules) : null,
        maxOccupants ? parseInt(maxOccupants) : null,
        lat ?? null, lng ?? null, displayAddress ?? null,
        distanceFromMolykoKm ?? null,
        id,
      ]
    );

    // If new images were provided, append them (don't delete old ones by default)
    if (newImages.length > 0) {
      const imageValues = newImages
        .map((_, i) => `($${i * 2 + 1}, $${i * 2 + 2}, '${_.category}')`)
        .join(', ');

      const flatParams: any[] = [];
      newImages.forEach((img) => { flatParams.push(id, img.url); });

      await query(
        `INSERT INTO listing_images (listing_id, url, category) VALUES ${newImages.map((_, i) => `($${i * 3 + 1}, $${i * 3 + 2}, $${i * 3 + 3})`).join(', ')}`,
        newImages.flatMap((img) => [id, img.url, img.category])
      );
    }

    return this.getById(id);
  },

  /**
   * Helper to format DB row to API JSON
   */
  formatListingObj(row: any) {
    const exteriorImages = row.images.filter((i: any) => i.category === 'exterior').map((i: any) => i.url);
    const roomImages = row.images.filter((i: any) => i.category === 'room').map((i: any) => i.url);

    return {
      id: row.id,
      landlordId: row.landlord_id,
      title: row.title,
      description: row.description,
      propertyType: row.property_type,
      rentAmount: row.rent_amount,
      rentPeriod: row.rent_period,
      availableFrom: row.available_from,
      amenities: row.amenities,
      rules: row.rules,
      maxOccupants: row.max_occupants,
      exteriorImages,
      roomImages,
      location: {
        lat: row.lat,
        lng: row.lng,
        displayAddress: row.display_address,
      },
      distanceFromUbKm: row.distance_from_molyko_km,
      status: row.status,
      viewsCount: row.views_count,
      createdAt: row.created_at,
      updatedAt: row.updated_at,
    };
  }
};
