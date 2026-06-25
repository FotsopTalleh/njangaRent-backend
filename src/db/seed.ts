// src/db/seed.ts
import { pool } from './pool.js';
// removed authService import
import { config } from '../config.js';

async function seed() {
  console.log('[seed] Seeding database...');

  // 1. Seed Admin
  console.log(`[seed] Admin user: ${config.seed.adminEmail}`);
  const adminId = 'user_admin_seed_123';
  
  // Create or update admin
  await pool.query(`
    INSERT INTO users (id, email, full_name, role, status)
    VALUES ($1, $2, $3, 'admin', 'ACTIVE')
    ON CONFLICT (email) DO UPDATE 
    SET role = 'admin', status = 'ACTIVE'
  `, [adminId, config.seed.adminEmail, config.seed.adminName]);

  // 2. Clear old dummy listings if rerunning
  await pool.query(`DELETE FROM listings`);

  // 3. Insert 14 dummy listings (using landlord = admin just to have an owner)
  console.log('[seed] Inserting 14 dummy listings...');
  
  const dummies = [
    { title: 'Clean single room — Molyko Junction', type: 'single_room', price: 35000, period: 'monthly', addr: 'Molyko Junction', lat: 4.1537, lng: 9.2443, dist: 0.1, images: ['https://images.unsplash.com/photo-1522771731478-44eb10e5c8f4?auto=format&fit=crop&w=800'] },
    { title: 'Furnished single room — Molyko main road', type: 'single_room', price: 45000, period: 'monthly', addr: 'Molyko', lat: 4.1550, lng: 9.2450, dist: 0.3, images: ['https://images.unsplash.com/photo-1560448204-e02f11c3d0e2?auto=format&fit=crop&w=800'] },
    { title: 'Budget single room — Great Soppo', type: 'single_room', price: 30000, period: 'monthly', addr: 'Great Soppo', lat: 4.1620, lng: 9.2310, dist: 1.5, images: ['https://images.unsplash.com/photo-1493809842364-78817add7ffb?auto=format&fit=crop&w=800'] },
    { title: 'Spacious room — Bonduma', type: 'single_room', price: 40000, period: 'monthly', addr: 'Bonduma', lat: 4.1500, lng: 9.2550, dist: 1.2, images: ['https://images.unsplash.com/photo-1540518614846-7eded433c457?auto=format&fit=crop&w=800'] },
    { title: 'Single room — Mile 16 Bolifamba', type: 'single_room', price: 32000, period: 'monthly', addr: 'Mile 16', lat: 4.1400, lng: 9.2700, dist: 3.5, images: ['https://images.unsplash.com/photo-1554995207-c18c203602cb?auto=format&fit=crop&w=800'] },
    
    { title: 'Self-contained — Molyko', type: 'self_contained', price: 60000, period: 'monthly', addr: 'Molyko', lat: 4.1560, lng: 9.2460, dist: 0.4, images: ['https://images.unsplash.com/photo-1502672260266-1c1de2d9d000?auto=format&fit=crop&w=800'] },
    { title: 'Self-contained — Santa Barbara', type: 'self_contained', price: 70000, period: 'monthly', addr: 'Santa Barbara', lat: 4.1480, lng: 9.2500, dist: 0.8, images: ['https://images.unsplash.com/photo-1560185127-6ed189bf02f4?auto=format&fit=crop&w=800'] },
    
    { title: 'Furnished studio — Molyko', type: 'studio', price: 600000, period: 'yearly', addr: 'Molyko', lat: 4.1530, lng: 9.2440, dist: 0.1, images: ['https://images.unsplash.com/photo-1536376072261-38c75010e6c9?auto=format&fit=crop&w=800'] },
    { title: 'Modern studio — Bonduma', type: 'studio', price: 650000, period: 'yearly', addr: 'Bonduma', lat: 4.1510, lng: 9.2540, dist: 1.1, images: ['https://images.unsplash.com/photo-1502005229762-cf1b2da7c5d6?auto=format&fit=crop&w=800'] },
    
    { title: '2-bedroom apartment — Molyko', type: 'apartment', price: 850000, period: 'yearly', addr: 'Molyko', lat: 4.1540, lng: 9.2450, dist: 0.2, images: ['https://images.unsplash.com/photo-1522708323590-d24dbb6b0267?auto=format&fit=crop&w=800'] },
    { title: 'Executive 3-bedroom — Buea Town', type: 'apartment', price: 1000000, period: 'yearly', addr: 'Buea Town', lat: 4.1700, lng: 9.2200, dist: 3.2, images: ['https://images.unsplash.com/photo-1560448204-e02f11c3d0e2?auto=format&fit=crop&w=800'] },
    { title: '1-bedroom apartment — Mile 17', type: 'apartment', price: 700000, period: 'yearly', addr: 'Mile 17', lat: 4.1350, lng: 9.2600, dist: 2.8, images: ['https://images.unsplash.com/photo-1512918728675-ed5a9ecdebfd?auto=format&fit=crop&w=800'] },
    
    { title: 'Hostel block room — Molyko', type: 'hostel_block', price: 25000, period: 'monthly', addr: 'Molyko', lat: 4.1545, lng: 9.2435, dist: 0.15, images: ['https://images.unsplash.com/photo-1555854877-bab0e564b8d5?auto=format&fit=crop&w=800'] },
    { title: 'Private hostel room — Great Soppo', type: 'hostel_block', price: 28000, period: 'monthly', addr: 'Great Soppo', lat: 4.1610, lng: 9.2320, dist: 1.4, images: ['https://images.unsplash.com/photo-1513694203232-719a280e022f?auto=format&fit=crop&w=800'] },
  ];

  for (const d of dummies) {
    const lRes = await pool.query(`
      INSERT INTO listings (
        landlord_id, title, description, property_type, rent_amount, rent_period,
        display_address, lat, lng, distance_from_molyko_km, status, amenities
      ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, 'active', '["water", "electricity"]')
      RETURNING id
    `, [adminId, d.title, 'Beautiful room in Buea', d.type, d.price, d.period, d.addr, d.lat, d.lng, d.dist]);

    const lId = lRes.rows[0].id;
    
    for (const img of d.images) {
      await pool.query(`
        INSERT INTO listing_images (listing_id, url, category, sort_order)
        VALUES ($1, $2, 'exterior', 0)
      `, [lId, img]);
    }
  }

  console.log('[seed] Done!');
  await pool.end();
}

seed().catch(err => {
  console.error('[seed] Error:', err);
  process.exit(1);
});
