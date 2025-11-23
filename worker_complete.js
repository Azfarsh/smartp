// worker.js

// Helper function to parse request body
async function safeBody(request) {
  const ct = request.headers.get("content-type") || "";
  if (ct.includes("application/json")) {
    return await request.json();
  }
  if (ct.includes("application/x-www-form-urlencoded")) {
    const form = await request.formData();
    return Object.fromEntries([...form.entries()]);
  }
  // raw text fallback
  const text = await request.text();
  try {
    return JSON.parse(text);
  } catch {
    return {};
  }
}

// Helper function to create JSON response
function json(payload, status = 200, extraHeaders = {}) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json", ...extraHeaders },
  });
}

async function ensureVendorRegisterTable(env) {
  if (!env.DB) {
    return;
  }

  await env.DB.prepare(`
    CREATE TABLE IF NOT EXISTS "Vendor_register_details " (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      email TEXT NOT NULL UNIQUE,
      password_hash TEXT NOT NULL,
      vendor_name TEXT NOT NULL,
      phone_number TEXT NOT NULL,
      state TEXT NOT NULL,
      city TEXT NOT NULL,
      locality TEXT NOT NULL,
      shop_address TEXT NOT NULL,
      pincode TEXT NOT NULL,
      latitude TEXT,
      longitude TEXT,
      vendor_id TEXT NOT NULL,
      vendor_token TEXT NOT NULL,
      status TEXT DEFAULT 'pending',
      registration_timestamp TEXT DEFAULT (datetime('now')),
      updated_at TEXT DEFAULT (datetime('now'))
    )
  `).run();

  const canonicalEntry = await env.DB.prepare(`
    SELECT name, type FROM sqlite_master
    WHERE name = 'Vendor_register_details'
  `).first();

  if (!canonicalEntry) {
    await env.DB.prepare(`
      CREATE VIEW IF NOT EXISTS Vendor_register_details AS
      SELECT
        id,
        email,
        password_hash,
        vendor_name,
        phone_number,
        state,
        city,
        locality,
        shop_address,
        pincode,
        latitude,
        longitude,
        vendor_id,
        vendor_token,
        status,
        registration_timestamp,
        updated_at
      FROM "Vendor_register_details "
    `).run();
  }
}

// --- Vendor service availability helpers ---
const SERVICE_FLAG_KEYS = [
  "digital_print",
  "project_binding",
  "gloss_printing",
  "jumbo_printing",
  "regular_print",
  "passport_print",
  "photo_print",
];

const SERVICE_TEXT_DEFAULTS = {
  vendor_shop_avaliability: "online",
};

const EXTRA_COLUMN_KEY = "extra_json";

const SERVICE_DEFAULTS = (() => {
  const defaults = {};
  SERVICE_FLAG_KEYS.forEach((key) => {
    defaults[key] = true;
  });
  Object.entries(SERVICE_TEXT_DEFAULTS).forEach(([key, value]) => {
    defaults[key] = value;
  });
  return defaults;
})();

const SERVICE_TEXT_KEYS = Object.keys(SERVICE_TEXT_DEFAULTS);
const VENDOR_SERVICE_DB_COLUMNS = [
  ...SERVICE_FLAG_KEYS,
  ...SERVICE_TEXT_KEYS,
  EXTRA_COLUMN_KEY,
];
const KNOWN_SERVICE_KEYS = new Set([...SERVICE_FLAG_KEYS, ...SERVICE_TEXT_KEYS]);
const VENDOR_SERVICE_SELECT_FIELDS = [
  "vendor_email",
  "vendor_id",
  ...VENDOR_SERVICE_DB_COLUMNS,
  "updated_at",
  "updated_by",
].join(", ");

function getDefaultServiceAvailability() {
  return { ...SERVICE_DEFAULTS };
}

function normalizeBooleanFlag(value, fallback = true) {
  if (value === undefined || value === null) {
    return fallback ? 1 : 0;
  }
  if (typeof value === "boolean") {
    return value ? 1 : 0;
  }
  if (typeof value === "number") {
    return value !== 0 ? 1 : 0;
  }
  if (typeof value === "string") {
    const normalized = value.trim().toLowerCase();
    if (!normalized.length) {
      return fallback ? 1 : 0;
    }
    if (["1", "true", "yes", "on", "enabled"].includes(normalized)) {
      return 1;
    }
    if (["0", "false", "no", "off", "disabled"].includes(normalized)) {
      return 0;
    }
  }
  return fallback ? 1 : 0;
}

function normalizeTextField(key, value) {
  const fallback = SERVICE_TEXT_DEFAULTS[key] || "";
  if (value === undefined || value === null) {
    return fallback;
  }
  const strValue = String(value).trim();
  if (!strValue.length) {
    return fallback;
  }
  if (key === "vendor_shop_avaliability") {
    const normalized = strValue.toLowerCase();
    if (normalized === "online" || normalized === "offline") {
      return normalized;
    }
    return normalized;
  }
  return strValue;
}

function normalizeServicePayload(payload = {}) {
  const merged = { ...SERVICE_DEFAULTS, ...(payload || {}) };
  const columnValues = {};

  SERVICE_FLAG_KEYS.forEach((key) => {
    columnValues[key] = normalizeBooleanFlag(merged[key], SERVICE_DEFAULTS[key]);
  });

  SERVICE_TEXT_KEYS.forEach((key) => {
    columnValues[key] = normalizeTextField(key, merged[key]);
  });

  const extras = {};
  Object.entries(merged).forEach(([key, value]) => {
    if (KNOWN_SERVICE_KEYS.has(key)) {
      return;
    }
    if (value === undefined || value === null) {
      return;
    }
    extras[key] = value;
  });

  columnValues[EXTRA_COLUMN_KEY] =
    Object.keys(extras).length > 0 ? JSON.stringify(extras) : null;

  return { columnValues, extras };
}

function rowToServicePayload(row) {
  const payload = getDefaultServiceAvailability();
  if (!row) {
    return payload;
  }

  SERVICE_FLAG_KEYS.forEach((key) => {
    if (row[key] === undefined || row[key] === null) {
      return;
    }
    // Keep boolean for functionality, but we'll convert to "on"/"off" in admin endpoints
    payload[key] = !!row[key];
  });

  SERVICE_TEXT_KEYS.forEach((key) => {
    if (row[key] === undefined || row[key] === null) {
      return;
    }
    payload[key] = row[key];
  });

  const extraRaw = row[EXTRA_COLUMN_KEY];
  if (extraRaw) {
    try {
      const parsed = JSON.parse(extraRaw);
      if (parsed && typeof parsed === "object") {
        Object.assign(payload, parsed);
      }
    } catch (_err) {
      // Ignore JSON parse errors for malformed extra payloads
    }
  }

  return payload;
}

function convertServiceDataToOnOff(serviceData) {
  // Convert boolean service flags to "on"/"off" strings for display
  const converted = { ...serviceData };
  SERVICE_FLAG_KEYS.forEach((key) => {
    if (converted[key] !== undefined && converted[key] !== null) {
      // Handle both boolean and string "true"/"false" values
      const boolValue = converted[key] === true || converted[key] === "true" || converted[key] === 1 || converted[key] === "1";
      converted[key] = boolValue ? "on" : "off";
    }
  });
  return converted;
}

async function ensureVendorServiceTable(env) {
  if (!env || !env.DB) {
    throw new Error("Database not configured");
  }

  const flagColumnsSql = SERVICE_FLAG_KEYS.map(
    (key) =>
      `${key} INTEGER NOT NULL DEFAULT ${SERVICE_DEFAULTS[key] ? 1 : 0}`
  ).join(",\n      ");

  const textColumnsSql = SERVICE_TEXT_KEYS.map((key) => {
    const defaultValue = SERVICE_TEXT_DEFAULTS[key] || "";
    const escapedDefault = defaultValue.replace(/'/g, "''");
    return `${key} TEXT NOT NULL DEFAULT '${escapedDefault}'`;
  }).join(",\n      ");

  await env.DB.prepare(`
    CREATE TABLE IF NOT EXISTS Vendor_service_availability(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      vendor_email TEXT NOT NULL UNIQUE,
      vendor_id TEXT NOT NULL UNIQUE,
      ${flagColumnsSql},
      ${textColumnsSql},
      ${EXTRA_COLUMN_KEY} TEXT,
      updated_at TEXT NOT NULL,
      updated_by TEXT
    )
  `).run();
}

export default {
  async fetch(request, env) {
    env = env || {};
    // ---- Basic CORS (allow your origin) ----
    const corsHeaders = {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type, x-api-key",
    };

    if (request.method === "OPTIONS") {
      return new Response(null, { headers: corsHeaders });
    }

    // ---- API key guard (set API_KEY in Worker → Settings → Variables) ----
    // Check header case-insensitively (headers can be lowercase)
    const clientKey = request.headers.get("x-api-key") || request.headers.get("X-Api-Key") || request.headers.get("X-API-KEY");
    
    // Debug info (remove in production if needed)
    const hasApiKey = !!env.API_KEY;
    const receivedKey = clientKey ? "received" : "missing";
    
    if (!env.API_KEY) {
      return json({ 
        success: false, 
        error: "Server error: API_KEY not configured in Worker environment variables" 
      }, 500, corsHeaders);
    }
    
    if (!clientKey || clientKey !== env.API_KEY) {
      return json({ 
        success: false, 
        error: "Unauthorized: Invalid or missing API key" 
      }, 401, corsHeaders);
    }

    const url = new URL(request.url);

    try {
      // POST /add-contact  → inserts one row
      if (url.pathname === "/add-contact" && request.method === "POST") {
        // Check if D1 database binding is configured
        if (!env.DB) {
          return json({ success: false, error: "Database not configured. Please set up D1 Database Binding named 'DB' in Worker settings." }, 500, corsHeaders);
        }

        const body = await safeBody(request);

        // IMPORTANT: Store full data without truncation - .trim() only removes leading/trailing whitespace
        // All data is stored completely in the database (UI truncation is display-only)
        const name = (body.name || "").trim();
        const email = (body.email || "").trim();
        const subject = (body.subject || "").trim();
        const message = (body.message || "").trim();

        if (!name || !email || !subject || !message) {
          return json({ success: false, error: "All fields are required" }, 400, corsHeaders);
        }
        
        // Validate data length to ensure we're storing complete data (no truncation)
        // D1 TEXT columns can store up to 1GB, so we don't need to limit here
        if (email.length > 1000 || name.length > 1000 || subject.length > 1000 || message.length > 1000000) {
          return json({ success: false, error: "Data too long - please check input" }, 400, corsHeaders);
        }

        // NOTE: your table has spaces in two column names, so we must quote them
        // First, check the actual table schema to see what columns exist
        let actualColumns = [];
        try {
          const schema = await env.DB.prepare(`PRAGMA table_info(Contact_data)`).all();
          actualColumns = schema.results.map(r => r.name);
        } catch (schemaErr) {
          return json({ 
            success: false, 
            error: `Cannot access table Contact_data. Error: ${String(schemaErr)}. Please verify the D1 binding 'DB' points to 'printmax' database and the table exists.` 
          }, 500, corsHeaders);
        }
        
        // Now try the INSERT - use the actual column names from schema
        try {
          // Check if we have the expected columns
          const hasTimestamp = actualColumns.some(col => col.toLowerCase().includes('time') || col.toLowerCase().includes('stamp'));
          const hasStatus = actualColumns.some(col => col.toLowerCase().includes('status') || col.toLowerCase().includes('solved'));
          
          // Build column list based on what exists
          let timestampCol = actualColumns.find(col => col === "submitted time stamp") || 
                            actualColumns.find(col => col.toLowerCase() === "submitted time stamp") ||
                            actualColumns.find(col => col.includes("time") && col.includes("stamp"));
          let statusCol = actualColumns.find(col => col === "solved status") || 
                         actualColumns.find(col => col.toLowerCase() === "solved status") ||
                         actualColumns.find(col => col.includes("solved") || col.includes("status"));
          
          // Use the exact column names found in the schema
          if (!timestampCol || !statusCol) {
            return json({ 
              success: false, 
              error: `Column mismatch. Found columns: ${actualColumns.join(', ')}. Expected columns with spaces: "submitted time stamp" and "solved status". Please check your table schema.` 
            }, 500, corsHeaders);
          }
          
          // Insert using the actual column names (quote them if they have spaces)
          const timestampColQuoted = timestampCol.includes(' ') ? `"${timestampCol}"` : timestampCol;
          const statusColQuoted = statusCol.includes(' ') ? `"${statusCol}"` : statusCol;
          
          // Store complete data - no truncation applied
          // Note: Cloudflare D1 Studio UI may truncate display, but full data is stored
          const result = await env.DB.prepare(`
            INSERT INTO Contact_data (name, email, subject, message, ${timestampColQuoted}, ${statusColQuoted})
            VALUES (?, ?, ?, ?, datetime('now'), 'no')
          `).bind(name, email, subject, message).run();
          
          return json({ success: true, message: "Contact saved successfully" }, 200, corsHeaders);
        } catch (dbError) {
          return json({ 
            success: false, 
            error: `Database error: ${String(dbError)}. Actual table columns: ${actualColumns.join(', ')}.` 
          }, 500, corsHeaders);
        }
      }

      // GET /contacts → list rows (for admin usage)
      if (url.pathname === "/contacts" && request.method === "GET") {
        if (!env.DB) {
          return json({ success: false, error: "Database not configured" }, 500, corsHeaders);
        }
        
        const { results } = await env.DB.prepare(`
          SELECT rowid as rowid, id, name, email, subject, message, "submitted time stamp" as submitted_at, "solved status" as solved_status
          FROM Contact_data
          ORDER BY "submitted time stamp" DESC
          LIMIT 500
        `).all();

        return json({ success: true, data: results }, 200, corsHeaders);
      }

      // POST /update-contact → update contact solved status
      if (url.pathname === "/update-contact" && request.method === "POST") {
        if (!env.DB) {
          return json({ success: false, error: "Database not configured" }, 500, corsHeaders);
        }

        const body = await safeBody(request);
        const contact_id = parseInt(body.id || "0", 10) || 0;
        const solved_status = (body.solved_status || "yes").trim().toLowerCase();

        if (!contact_id) {
          return json({ success: false, error: "Contact ID is required" }, 400, corsHeaders);
        }

        try {
          // Check the actual table schema to get the correct column name
          const schema = await env.DB.prepare(`PRAGMA table_info(Contact_data)`).all();
          const actualColumns = schema.results.map(r => r.name);
          
          let statusCol = actualColumns.find(col => col === "solved status") || 
                         actualColumns.find(col => col.toLowerCase() === "solved status") ||
                         actualColumns.find(col => col.includes("solved") || col.includes("status"));
          
          if (!statusCol) {
            return json({ 
              success: false, 
              error: `Column "solved status" not found. Available columns: ${actualColumns.join(', ')}` 
            }, 500, corsHeaders);
          }

          const statusColQuoted = statusCol.includes(' ') ? `"${statusCol}"` : statusCol;
          const newStatus = solved_status === 'yes' ? 'yes' : 'no';

          const updateById = await env.DB.prepare(`
            UPDATE Contact_data 
            SET ${statusColQuoted} = ?
            WHERE id = ?
          `).bind(newStatus, contact_id).run();

          if (updateById.meta.changes > 0) {
            return json({ success: true, message: "Contact status updated successfully" }, 200, corsHeaders);
          }

          const updateByRowId = await env.DB.prepare(`
            UPDATE Contact_data 
            SET ${statusColQuoted} = ?
            WHERE rowid = ?
          `).bind(newStatus, contact_id).run();

          if (updateByRowId.meta.changes > 0) {
            return json({ success: true, message: "Contact status updated successfully" }, 200, corsHeaders);
          }

          return json({ success: false, error: "Contact not found or no changes made" }, 404, corsHeaders);
        } catch (dbError) {
          return json({ 
            success: false, 
            error: `Database error: ${String(dbError)}` 
          }, 500, corsHeaders);
        }
      }

      // POST /add-vendor-register → inserts vendor registration data
      if (url.pathname === "/add-vendor-register" && request.method === "POST") {
        // Check if D1 database binding is configured
        if (!env.DB) {
          return json({ success: false, error: "Database not configured. Please set up D1 Database Binding named 'DB' in Worker settings." }, 500, corsHeaders);
        }

        await ensureVendorRegisterTable(env);

        const body = await safeBody(request);

        // IMPORTANT: Store full data without truncation - .trim() only removes leading/trailing whitespace
        // All data is stored completely in the database (UI truncation in D1 Studio is display-only)
        const email = (body.email || "").trim();
        const password_hash = (body.password_hash || "").trim();
        const vendor_name = (body.vendor_name || "").trim();
        const phone_number = (body.phone_number || "").trim();
        const state = (body.state || "").trim();
        const city = (body.city || "").trim();
        const locality = (body.locality || "").trim();
        const shop_address = (body.shop_address || "").trim();
        const pincode = (body.pincode || "").trim();
        // Store latitude and longitude as TEXT to preserve complete decimal precision
        // Since column type is TEXT, store as string to preserve exact values (e.g., "18.658365", "73.856412")
        // No conversion applied - store the exact string value received
        const latitude = (body.latitude || "0").toString().trim();
        const longitude = (body.longitude || "0").toString().trim();
        const vendor_id = (body.vendor_id || "").trim();
        const vendor_token = (body.vendor_token || "").trim();
        const status = (body.status || "pending").trim();

        if (!email || !password_hash || !vendor_name || !phone_number || !state || !city || !locality || !shop_address || !pincode || !vendor_id || !vendor_token) {
          return json({ success: false, error: "All required fields are missing" }, 400, corsHeaders);
        }
        
        // Validate data length to ensure we're storing complete data (no truncation)
        // D1 TEXT columns can store up to 1GB, so we only validate reasonable limits
        const maxLengths = {
          email: 500,
          vendor_name: 500,
          phone_number: 50,
          state: 100,
          city: 200,
          locality: 300,
          shop_address: 2000,
          pincode: 20,
          vendor_id: 50,
          vendor_token: 50,
          password_hash: 500
        };
        
        if (email.length > maxLengths.email || vendor_name.length > maxLengths.vendor_name || 
            phone_number.length > maxLengths.phone_number || state.length > maxLengths.state ||
            city.length > maxLengths.city || locality.length > maxLengths.locality ||
            shop_address.length > maxLengths.shop_address || pincode.length > maxLengths.pincode ||
            vendor_id.length > maxLengths.vendor_id || vendor_token.length > maxLengths.vendor_token ||
            password_hash.length > maxLengths.password_hash) {
          return json({ success: false, error: "One or more fields exceed maximum length - please check input" }, 400, corsHeaders);
        }

        // Check for duplicate email before inserting
        try {
          // Try with trailing space first (as per actual schema)
          let existingVendor = await env.DB.prepare(`
            SELECT email FROM "Vendor_register_details " WHERE email = ? LIMIT 1
          `).bind(email).first();
          
          // If not found, try without space
          if (!existingVendor) {
            existingVendor = await env.DB.prepare(`
              SELECT email FROM Vendor_register_details WHERE email = ? LIMIT 1
            `).bind(email).first();
          }
          
          if (existingVendor) {
            return json({ 
              success: false, 
              error: "A vendor with this email address already exists. Please use a different email or login with your existing account." 
            }, 400, corsHeaders);
          }
        } catch (checkError) {
          // If check fails, continue anyway (table might not exist yet or schema issue)
          console.log(`Warning: Could not check for duplicate email: ${String(checkError)}`);
        }

        // NOTE: Check the actual table schema first (same pattern as contact page)
        // IMPORTANT: Table name has a trailing space: "Vendor_register_details " (with space)
        // First, check the actual table schema to see what columns exist
        let actualColumns = [];
        try {
          // Try with trailing space first (as per actual schema)
          const schema = await env.DB.prepare(`PRAGMA table_info("Vendor_register_details ")`).all();
          actualColumns = schema.results.map(r => r.name);
          
          // If no columns found, try without space as fallback
          if (actualColumns.length === 0) {
            try {
              const schemaNoSpace = await env.DB.prepare(`PRAGMA table_info(Vendor_register_details)`).all();
              actualColumns = schemaNoSpace.results.map(r => r.name);
            } catch (fallbackErr) {
              // If both fail, list available tables for debugging
              try {
                const tablesResult = await env.DB.prepare(`
                  SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'
                `).all();
                const tableNames = tablesResult.results.map(r => r.name).join(', ');
                return json({ 
                  success: false, 
                  error: `Table Vendor_register_details not found. Available tables in database: ${tableNames || 'none'}. Please verify the D1 binding 'DB' points to 'printmax' database.` 
                }, 500, corsHeaders);
              } catch (listErr) {
                return json({ 
                  success: false, 
                  error: `Cannot access table Vendor_register_details. Please verify the D1 binding 'DB' points to 'printmax' database and the table exists.` 
                }, 500, corsHeaders);
              }
            }
          }
        } catch (schemaErr) {
          // Try to list available tables for better error message
          try {
            const tablesResult = await env.DB.prepare(`
              SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'
            `).all();
            const tableNames = tablesResult.results.map(r => r.name).join(', ');
            return json({ 
              success: false, 
              error: `Cannot access table Vendor_register_details. Error: ${String(schemaErr)}. Available tables: ${tableNames || 'none'}. Please verify the table name and D1 binding.` 
            }, 500, corsHeaders);
          } catch (listErr) {
            return json({ 
              success: false, 
              error: `Cannot access table Vendor_register_details. Error: ${String(schemaErr)}. Please verify the D1 binding 'DB' points to 'printmax' database and the table exists.` 
            }, 500, corsHeaders);
          }
        }
        
        // Now try the INSERT - use the actual column names from schema (same pattern as contact page)
        try {
          // Check if we have the expected columns
          const hasTimestamp = actualColumns.some(col => col.toLowerCase().includes('time') || col.toLowerCase().includes('stamp'));
          
          // Build column list based on what exists
          let timestampCol = actualColumns.find(col => col === "registration_timestamp") || 
                            actualColumns.find(col => col.toLowerCase() === "registration_timestamp") ||
                            actualColumns.find(col => (col.includes("time") || col.includes("stamp")) && col.includes("registration"));
          
          // Use registration_timestamp if found, otherwise use datetime('now') directly
          const timestampColQuoted = timestampCol && timestampCol.includes(' ') ? `"${timestampCol}"` : (timestampCol || "registration_timestamp");
          
          // Store complete data - no truncation applied
          // Note: Cloudflare D1 Studio UI may truncate display, but full data is stored
          // Use table name with trailing space (as per actual schema: "Vendor_register_details ")
          const result = await env.DB.prepare(`
            INSERT INTO "Vendor_register_details " (
              email, password_hash, vendor_name, phone_number, state, city, locality, 
              shop_address, pincode, latitude, longitude, vendor_id, vendor_token, 
              ${timestampColQuoted}, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), ?)
          `).bind(
            email, password_hash, vendor_name, phone_number, state, city, locality,
            shop_address, pincode, latitude, longitude, vendor_id, vendor_token, status
          ).run();
          
          return json({ success: true, message: "Vendor registration saved successfully" }, 200, corsHeaders);
        } catch (dbError) {
          return json({ 
            success: false, 
            error: `Database error: ${String(dbError)}. Actual table columns: ${actualColumns.join(', ')}.` 
          }, 500, corsHeaders);
        }
      }

      // POST /add-vendor-pricing → inserts vendor pricing data
      if (url.pathname === "/add-vendor-pricing" && request.method === "POST") {
        // Check if D1 database binding is configured
        if (!env.DB) {
          return json({ success: false, error: "Database not configured. Please set up D1 Database Binding named 'DB' in Worker settings." }, 500, corsHeaders);
        }

        const body = await safeBody(request);

        const vendor_email = (body.vendor_email || "").trim();
        const last_updated = (body.last_updated || new Date().toISOString()).trim();
        const is_active = (body.is_active || "yes").trim();

        if (!vendor_email) {
          return json({ success: false, error: "Vendor email is required" }, 400, corsHeaders);
        }

        // IMPORTANT: Store all pricing values as REAL (floating-point) to preserve decimal precision
        // Map form field names to database column names
        const pricingData = {
          // Digital Print
          digital_print_a4_color: parseFloat(body.digital_print_a4_color || body.digital_print_a4_single_color || "0") || 0.0,
          digital_print_a3_color: parseFloat(body.digital_print_a3_color || body.digital_print_a3_single_color || "0") || 0.0,
          digital_print_12x18_color: parseFloat(body.digital_print_12x18_color || body.digital_print_12x18_single_color || "0") || 0.0,
          digital_print_a2_color: parseFloat(body.digital_print_a2_color || body.digital_print_a2_single_color || "0") || 0.0,
          digital_print_a1_color: parseFloat(body.digital_print_a1_color || body.digital_print_a1_single_color || body.digital_print_al_single_color || "0") || 0.0,
          digital_print_a0_color: parseFloat(body.digital_print_a0_color || body.digital_print_a0_single_color || "0") || 0.0,

          // Regular Print
          regular_print_a4_bw: parseFloat(body.regular_print_a4_bw || body.regular_print_a4_single_bw || "0") || 0.0,
          regular_print_a4_color: parseFloat(body.regular_print_a4_color || body.regular_print_a4_single_color || "0") || 0.0,

          // Photo Print
          photo_print_a4_bw: parseFloat(body.photo_print_a4_bw || body.photo_print_a4_standard_bw || "0") || 0.0,
          photo_print_a4_color: parseFloat(body.photo_print_a4_color || body.photo_print_a4_standard || "0") || 0.0,

          // Gloss Print
          gloss_print_a4_color: parseFloat(body.gloss_print_a4_color || "0") || 0.0,
          gloss_print_a3_color: parseFloat(body.gloss_print_a3_color || "0") || 0.0,
          gloss_print_a2_color: parseFloat(body.gloss_print_a2_color || "0") || 0.0,
          gloss_print_a1_color: parseFloat(body.gloss_print_a1_color || "0") || 0.0,
          gloss_print_a0_color: parseFloat(body.gloss_print_a0_color || "0") || 0.0,

          // Jumbo Print
          jumbo_print_a3_bw: parseFloat(body.jumbo_print_a3_bw || body.jumbo_print_a3_single_bw || "0") || 0.0,
          jumbo_print_a3_color: parseFloat(body.jumbo_print_a3_color || body.jumbo_print_a3_single_color || "0") || 0.0,
          jumbo_print_a2_bw: parseFloat(body.jumbo_print_a2_bw || body.jumbo_print_a2_single_bw || "0") || 0.0,
          jumbo_print_a2_color: parseFloat(body.jumbo_print_a2_color || body.jumbo_print_a2_single_color || "0") || 0.0,
          jumbo_print_a1_bw: parseFloat(body.jumbo_print_a1_bw || body.jumbo_print_a1_single_bw || "0") || 0.0,
          jumbo_print_a1_color: parseFloat(body.jumbo_print_a1_color || body.jumbo_print_a1_single_color || "0") || 0.0,
          jumbo_print_a0_bw: parseFloat(body.jumbo_print_a0_bw || body.jumbo_print_a0_single_bw || "0") || 0.0,
          jumbo_print_a0_color: parseFloat(body.jumbo_print_a0_color || body.jumbo_print_a0_single_color || "0") || 0.0,

          // Passport Photo
          passport_print_8: parseFloat(body.passport_print_8 || body.passport_photo_8_photos || "0") || 0.0,
          passport_print_16: parseFloat(body.passport_print_16 || body.passport_photo_16_photos || "0") || 0.0,
          passport_print_30: parseFloat(body.passport_print_30 || body.passport_photo_30_photos || "0") || 0.0,

          // Golden Embossing
          golden_emboss_cover: parseFloat(body.golden_emboss_cover || body.golden_embossing_per_book || "0") || 0.0,
          golden_emboss_bond_color: parseFloat(body.golden_emboss_bond_color || body.golden_emboss_color_per_page || "0") || 0.0,

          // Lamination
          lamination_a4_standard: parseFloat(body.lamination_a4_standard || body.lamination_a4 || "0") || 0.0,
          lamination_a4_glossy: parseFloat(body.lamination_a4_glossy || body.lamination_a4_high_gloss || "0") || 0.0,
          lamination_a3_standard: parseFloat(body.lamination_a3_standard || body.lamination_a3 || "0") || 0.0,
          lamination_a3_glossy: parseFloat(body.lamination_a3_glossy || body.lamination_a3_high_gloss || "0") || 0.0,
          lamination_a2_standard: parseFloat(body.lamination_a2_standard || body.lamination_a2 || "0") || 0.0,
          lamination_a2_glossy: parseFloat(body.lamination_a2_glossy || body.lamination_a2_high_gloss || "0") || 0.0,
          lamination_a1_standard: parseFloat(body.lamination_a1_standard || body.lamination_a1 || "0") || 0.0,
          lamination_a1_glossy: parseFloat(body.lamination_a1_glossy || body.lamination_a1_high_gloss || "0") || 0.0,
          lamination_a0_standard: parseFloat(body.lamination_a0_standard || body.lamination_a0 || "0") || 0.0,
          lamination_a0_glossy: parseFloat(body.lamination_a0_glossy || body.lamination_a0_high_gloss || "0") || 0.0,

          // Binding
          tape_binding_a4_100: parseFloat(body.tape_binding_a4_100 || body.tape_binding_per_book_100 || "0") || 0.0,
          tape_binding_a4_200: parseFloat(body.tape_binding_a4_200 || body.tape_binding_a4_150 || body.tape_binding_per_book_200 || "0") || 0.0,
          tape_binding_a3_100: parseFloat(body.tape_binding_a3_100 || "0") || 0.0,
          tape_binding_a3_200: parseFloat(body.tape_binding_a3_200 || body.tape_binding_a3_150 || "0") || 0.0,
          spiral_binding_a4_100: parseFloat(body.spiral_binding_a4_100 || body.spiral_binding_per_book_100 || "0") || 0.0,
          spiral_binding_a4_200: parseFloat(body.spiral_binding_a4_200 || body.spiral_binding_a4_150 || body.spiral_binding_per_book_200 || "0") || 0.0,
          spiral_binding_a3_100: parseFloat(body.spiral_binding_a3_100 || "0") || 0.0,
          spiral_binding_a3_200: parseFloat(body.spiral_binding_a3_200 || body.spiral_binding_a3_150 || "0") || 0.0,
        };

        // Check the actual table schema
        let actualColumns = [];
        try {
          const schema = await env.DB.prepare(`PRAGMA table_info(Vendor_pricing)`).all();
          actualColumns = schema.results.map(r => r.name);
        } catch (schemaErr) {
          return json({ 
            success: false, 
            error: `Cannot access table Vendor_pricing. Error: ${String(schemaErr)}. Please verify the D1 binding 'DB' points to 'printmax' database and the table exists.` 
          }, 500, corsHeaders);
        }
        
        // Build UPDATE or INSERT statement with all columns
        try {
          // Get all REAL columns from schema (excluding id, vendor_email, last_updated, is_active)
          const realColumns = actualColumns.filter(col => 
            col !== 'id' && 
            col !== 'vendor_email' && 
            col !== 'last_updated' && 
            col !== 'is_active'
          );
          
          // Build column list and values
          const insertColumns = ['vendor_email', 'last_updated', 'is_active', ...realColumns];
          const placeholders = insertColumns.map(() => '?').join(', ');
          
          // Prepare values array for INSERT
          const insertValues = [
            vendor_email,
            last_updated,
            is_active,
            ...realColumns.map(col => pricingData[col] || 0.0)
          ];
          
          // Prepare values array for UPDATE (vendor_email at the end for WHERE clause)
          const updateValues = [
            last_updated,
            is_active,
            ...realColumns.map(col => pricingData[col] || 0.0),
            vendor_email
          ];
          
          // Build SET clause for UPDATE
          const updateSet = ['last_updated', 'is_active', ...realColumns]
            .map(col => `${col} = ?`)
            .join(', ');
          
          // Try UPDATE first, then INSERT if no rows were affected
          const updateResult = await env.DB.prepare(`
            UPDATE Vendor_pricing 
            SET ${updateSet}
            WHERE vendor_email = ?
          `).bind(...updateValues).run();
          
          if (updateResult.meta.changes === 0) {
            // No existing record, insert new one
            await env.DB.prepare(`
              INSERT INTO Vendor_pricing (${insertColumns.join(', ')})
              VALUES (${placeholders})
            `).bind(...insertValues).run();
          }
          
          return json({ success: true, message: "Vendor pricing saved successfully" }, 200, corsHeaders);
        } catch (dbError) {
          return json({ 
            success: false, 
            error: `Database error: ${String(dbError)}. Actual table columns: ${actualColumns.join(', ')}.` 
          }, 500, corsHeaders);
        }
      }

      // POST /add-vendor-tokens → inserts vendor token data
      if (url.pathname === "/add-vendor-tokens" && request.method === "POST") {
        // Check if D1 database binding is configured
        if (!env.DB) {
          return json({ success: false, error: "Database not configured. Please set up D1 Database Binding named 'DB' in Worker settings." }, 500, corsHeaders);
        }

        const body = await safeBody(request);

        const vendor_email = (body.vendor_email || "").trim();
        const tokens = body.tokens || [];

        if (!vendor_email) {
          return json({ success: false, error: "Vendor email is required" }, 400, corsHeaders);
        }

        if (!Array.isArray(tokens) || tokens.length === 0) {
          return json({ success: false, error: "Tokens array is required and must not be empty" }, 400, corsHeaders);
        }

        // Ensure the table exists with the expected schema
        await env.DB.prepare(`
          CREATE TABLE IF NOT EXISTS Vendor_tokens(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vendor_email TEXT NOT NULL,
            token_number INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'free',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(vendor_email, token_number)
          )
        `).run();

        // Check the actual table schema
        let actualColumns = [];
        try {
          const schema = await env.DB.prepare(`PRAGMA table_info(Vendor_tokens)`).all();
          actualColumns = schema.results.map(r => r.name);
          
          if (actualColumns.length === 0) {
            return json({ 
              success: false, 
              error: `Table Vendor_tokens not found. Please verify the D1 binding 'DB' points to 'printmax' database and the table exists.` 
            }, 500, corsHeaders);
          }
        } catch (schemaErr) {
          return json({ 
            success: false, 
            error: `Cannot access table Vendor_tokens. Error: ${String(schemaErr)}. Please verify the D1 binding 'DB' points to 'printmax' database and the table exists.` 
          }, 500, corsHeaders);
        }
        
        // Insert tokens into database
        try {
          // First, delete existing tokens for this vendor (to handle re-initialization)
          await env.DB.prepare(`
            DELETE FROM Vendor_tokens WHERE vendor_email = ?
          `).bind(vendor_email).run();
          
          // Insert all tokens
          const insertPromises = tokens.map(token => {
            const token_number = parseInt(token.token_number || "0", 10) || 0;
            const status = (token.status || "free").trim();
            const created_at = new Date().toISOString();
            
            return env.DB.prepare(`
              INSERT INTO Vendor_tokens (vendor_email, token_number, status, created_at, updated_at)
              VALUES (?, ?, ?, ?, ?)
            `).bind(vendor_email, token_number, status, created_at, created_at).run();
          });
          
          await Promise.all(insertPromises);
          
          return json({ 
            success: true, 
            message: `Successfully created ${tokens.length} tokens for vendor ${vendor_email}` 
          }, 200, corsHeaders);
        } catch (dbError) {
          return json({ 
            success: false, 
            error: `Database error: ${String(dbError)}. Actual table columns: ${actualColumns.join(', ')}.` 
          }, 500, corsHeaders);
        }
      }

      // POST /assign-vendor-token → reserves the next available token for a vendor
      if (url.pathname === "/assign-vendor-token" && request.method === "POST") {
        if (!env.DB) {
          return json({ success: false, error: "Database not configured" }, 500, corsHeaders);
        }

        const body = await safeBody(request);
        const vendor_email = (body.vendor_email || "").trim();

        if (!vendor_email) {
          return json({ success: false, error: "vendor_email is required" }, 400, corsHeaders);
        }

        try {
          await env.DB.prepare(`
            CREATE TABLE IF NOT EXISTS Vendor_tokens(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              vendor_email TEXT NOT NULL,
              token_number INTEGER NOT NULL,
              status TEXT NOT NULL DEFAULT 'free',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              UNIQUE(vendor_email, token_number)
            )
          `).run();

          const maxAttempts = 3;
          for (let attempt = 0; attempt < maxAttempts; attempt++) {
            const nextToken = await env.DB.prepare(`
              SELECT token_number
              FROM Vendor_tokens
              WHERE vendor_email = ? AND status = 'free'
              ORDER BY token_number ASC
              LIMIT 1
            `).bind(vendor_email).first();

            if (!nextToken || nextToken.token_number === undefined || nextToken.token_number === null) {
              return json({ success: false, error: "No free tokens available for this vendor" }, 409, corsHeaders);
            }

            const token_number = parseInt(nextToken.token_number, 10);
            const nowIso = new Date().toISOString();

            const updateResult = await env.DB.prepare(`
              UPDATE Vendor_tokens
              SET status = 'busy', updated_at = ?
              WHERE vendor_email = ? AND token_number = ? AND status = 'free'
            `).bind(nowIso, vendor_email, token_number).run();

            if (updateResult.meta.changes > 0) {
              return json({
                success: true,
                token_number,
                message: `Token ${token_number} assigned successfully`
              }, 200, corsHeaders);
            }
          }

          return json({
            success: false,
            error: "Could not lock a token due to concurrent assignments. Please retry."
          }, 423, corsHeaders);
        } catch (dbError) {
          return json({
            success: false,
            error: `Database error: ${String(dbError)}`
          }, 500, corsHeaders);
        }
      }

      // POST /free-vendor-token → frees a token in Vendor_tokens table (sets status to 'free')
      if (url.pathname === "/free-vendor-token" && request.method === "POST") {
        if (!env.DB) {
          return json({ success: false, error: "Database not configured" }, 500, corsHeaders);
        }

        const body = await safeBody(request);
        const vendor_email = (body.vendor_email || "").trim().toLowerCase();
        const token_number = parseInt(body.token_number || body.token || "0", 10);

        if (!vendor_email) {
          return json({ success: false, error: "vendor_email is required" }, 400, corsHeaders);
        }

        if (!token_number || token_number <= 0) {
          return json({ success: false, error: "token_number is required and must be a positive integer" }, 400, corsHeaders);
        }

        try {
          await env.DB.prepare(`
            CREATE TABLE IF NOT EXISTS Vendor_tokens(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              vendor_email TEXT NOT NULL,
              token_number INTEGER NOT NULL,
              status TEXT NOT NULL DEFAULT 'free',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              UNIQUE(vendor_email, token_number)
            )
          `).run();

          const nowIso = new Date().toISOString();
          const updateResult = await env.DB.prepare(`
            UPDATE Vendor_tokens
            SET status = 'free', updated_at = ?
            WHERE LOWER(vendor_email) = LOWER(?) AND token_number = ?
          `).bind(nowIso, vendor_email, token_number).run();

          if (updateResult.meta.changes > 0) {
            return json({
              success: true,
              message: `Token ${token_number} freed successfully for vendor ${vendor_email}`,
              token_number: token_number
            }, 200, corsHeaders);
          } else {
            // Token might not exist, but that's okay - return success anyway
            return json({
              success: true,
              message: `Token ${token_number} not found in database (may have been already freed or never existed)`,
              token_number: token_number
            }, 200, corsHeaders);
          }
        } catch (dbError) {
          return json({
            success: false,
            error: `Database error: ${String(dbError)}`
          }, 500, corsHeaders);
        }
      }

      // GET /get-vendor-pricing → get vendor pricing from d1 database
      if (url.pathname === "/get-vendor-pricing" && request.method === "GET") {
        // Check if D1 database binding is configured
        if (!env.DB) {
          return json({ success: false, error: "Database not configured. Please set up D1 Database Binding named 'DB' in Worker settings." }, 500, corsHeaders);
        }

        const urlParams = new URL(request.url).searchParams;
        const vendor_email = (urlParams.get('vendor_email') || "").trim();

        if (!vendor_email) {
          return json({ success: false, error: "Vendor email is required" }, 400, corsHeaders);
        }

        try {
          // Fetch vendor pricing from d1 database
          const result = await env.DB.prepare(`
            SELECT * FROM Vendor_pricing 
            WHERE vendor_email = ? AND is_active = 'yes'
            LIMIT 1
          `).bind(vendor_email).first();

          if (!result) {
            return json({ 
              success: false, 
              error: 'No pricing data found for this vendor' 
            }, 404, corsHeaders);
          }

          // Transform database row into expected format
          // Create flat pricing object (all pricing columns)
          const pricing_data = {};
          const categorized_pricing = {
            'digital_print': {},
            'a4_print': {},
            'photo_print': {},
            'gloss_print': {},
            'jumbo_print': {},
            'passport_photo': {},
            'golden_embossing': {},
            'lamination': {},
            'binding': {}
          };

          // Get all columns from result (excluding metadata columns)
          const excludeColumns = ['id', 'vendor_email', 'last_updated', 'is_active'];
          
          for (const [key, value] of Object.entries(result)) {
            if (!excludeColumns.includes(key) && value !== null && value !== undefined) {
              const priceValue = parseFloat(value) || 0;
              pricing_data[key] = priceValue;

              // Categorize pricing
              if (key.startsWith('digital_print')) {
                categorized_pricing['digital_print'][key] = priceValue;
              } else if (key.startsWith('regular_print')) {
                categorized_pricing['a4_print'][key] = priceValue;
              } else if (key.startsWith('photo_print')) {
                categorized_pricing['photo_print'][key] = priceValue;
              } else if (key.startsWith('gloss_print')) {
                categorized_pricing['gloss_print'][key] = priceValue;
              } else if (key.startsWith('jumbo_print')) {
                categorized_pricing['jumbo_print'][key] = priceValue;
              } else if (key.startsWith('passport_print')) {
                categorized_pricing['passport_photo'][key] = priceValue;
              } else if (key.startsWith('golden_emboss')) {
                categorized_pricing['golden_embossing'][key] = priceValue;
              } else if (key.startsWith('lamination')) {
                categorized_pricing['lamination'][key] = priceValue;
              } else if (key.startsWith('tape_binding') || key.startsWith('spiral_binding')) {
                categorized_pricing['binding'][key] = priceValue;
              }
            }
          }

          // Calculate services summary
          const total_services = Object.keys(pricing_data).length;
          const available_services_count = Object.values(pricing_data).filter(v => v > 0).length;
          const not_available_services_count = total_services - available_services_count;

          return json({
            success: true,
            pricing: pricing_data,
            categorized_pricing: categorized_pricing,
            services_summary: {
              total_services: total_services,
              available_services_count: available_services_count,
              not_available_services_count: not_available_services_count
            }
          }, 200, corsHeaders);
        } catch (dbError) {
          return json({ 
            success: false, 
            error: `Database error: ${String(dbError)}` 
          }, 500, corsHeaders);
        }
      }

      // POST /add-user-notification → inserts user notification data
      if (url.pathname === "/add-user-notification" && request.method === "POST") {
        if (!env.DB) {
          return json({ success: false, error: "Database not configured" }, 500, corsHeaders);
        }

        const body = await safeBody(request);
        
        // Extract notification data
        const notification_id = (body.notification_id || "").trim();
        const user_email = (body.user_email || "").trim();
        const filename = (body.filename || "").trim();
        const vendor_id = (body.vendor_id || "").trim();
        const status = (body.status || "").trim();
        const completion_time = (body.completion_time || "").trim();
        const created_at = (body.created_at || new Date().toISOString()).trim();
        const read = body.read !== undefined ? (body.read ? 1 : 0) : 0;
        const type = (body.type || "").trim();
        const token = (body.token || "").trim();
        const service_type = (body.service_type || "").trim();
        const platform_profit = body.platform_profit !== undefined ? parseFloat(body.platform_profit) : 0;
        const total_price = body.total_price !== undefined ? parseFloat(body.total_price) : 0;

        if (!notification_id || !user_email) {
          return json({ success: false, error: "notification_id and user_email are required" }, 400, corsHeaders);
        }

        try {
          // Check if table exists, create if not
          try {
            await env.DB.prepare(`SELECT 1 FROM User_notifications LIMIT 1`).first();
          } catch (tableErr) {
            // Table doesn't exist, create it
            await env.DB.prepare(`
              CREATE TABLE IF NOT EXISTS User_notifications(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                notification_id TEXT,
                user_email TEXT,
                filename TEXT,
                vendor_id TEXT,
                status TEXT,
                completion_time TEXT,
                created_at TEXT,
                read INTEGER,
                type TEXT,
                token TEXT,
                service_type TEXT,
                platform_profit REAL,
                total_price REAL
              )
            `).run();
          }

          // Insert notification
          await env.DB.prepare(`
            INSERT INTO User_notifications (
              notification_id, user_email, filename, vendor_id, status, 
              completion_time, created_at, read, type, token, service_type, 
              platform_profit, total_price
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
          `).bind(
            notification_id, user_email, filename, vendor_id, status,
            completion_time, created_at, read, type, token, service_type,
            platform_profit, total_price
          ).run();

          return json({ success: true, message: "User notification saved successfully" }, 200, corsHeaders);
        } catch (dbError) {
          return json({ 
            success: false, 
            error: `Database error: ${String(dbError)}` 
          }, 500, corsHeaders);
        }
      }

      // POST /add-vendor-notification → inserts vendor notification data
      if (url.pathname === "/add-vendor-notification" && request.method === "POST") {
        if (!env.DB) {
          return json({ success: false, error: "Database not configured" }, 500, corsHeaders);
        }

        const body = await safeBody(request);
        
        // Extract notification data
        const notification_id = (body.notification_id || "").trim();
        const vendor_id = (body.vendor_id || "").trim();
        const vendor_email = (body.vendor_email || "").trim();
        const user_email = (body.user_email || "").trim();
        const filename = (body.filename || "").trim();
        const service_type = (body.service_type || "").trim();
        const platform_profit = body.platform_profit !== undefined ? parseFloat(body.platform_profit) : 0;
        const total_price = body.total_price !== undefined ? parseFloat(body.total_price) : 0;
        const completion_time = (body.completion_time || "").trim();
        const timestamp = (body.timestamp || new Date().toISOString()).trim();
        const token = (body.token || "").trim();
        const read = body.read !== undefined ? (body.read ? 1 : 0) : 0;

        if (!notification_id || !vendor_email) {
          return json({ success: false, error: "notification_id and vendor_email are required" }, 400, corsHeaders);
        }

        try {
          // Check if table exists, create if not
          try {
            await env.DB.prepare(`SELECT 1 FROM vendor_notification LIMIT 1`).first();
          } catch (tableErr) {
            // Table doesn't exist, create it
            await env.DB.prepare(`
              CREATE TABLE IF NOT EXISTS vendor_notification(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                notification_id TEXT,
                vendor_id TEXT,
                vendor_email TEXT,
                user_email TEXT,
                filename TEXT,
                service_type TEXT,
                platform_profit REAL,
                total_price REAL,
                completion_time TEXT,
                timestamp TEXT,
                token TEXT,
                read INTEGER
              )
            `).run();
          }

          // Insert notification
          await env.DB.prepare(`
            INSERT INTO vendor_notification (
              notification_id, vendor_id, vendor_email, user_email, filename,
              service_type, platform_profit, total_price, completion_time,
              timestamp, token, read
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
          `).bind(
            notification_id, vendor_id, vendor_email, user_email, filename,
            service_type, platform_profit, total_price, completion_time,
            timestamp, token, read
          ).run();

          return json({ success: true, message: "Vendor notification saved successfully" }, 200, corsHeaders);
        } catch (dbError) {
          return json({ 
            success: false, 
            error: `Database error: ${String(dbError)}` 
          }, 500, corsHeaders);
        }
      }

      // POST /get-user-notifications → get user notifications from User_notifications table
      if (url.pathname === "/get-user-notifications" && request.method === "POST") {
        if (!env.DB) {
          return json({ success: false, error: "Database not configured" }, 500, corsHeaders);
        }

        const body = await safeBody(request);
        const userEmail = (body.user_email || "").trim().toLowerCase();
        const dateFilter = (body.date || "").trim(); // Optional date filter (YYYY-MM-DD)

        if (!userEmail) {
          return json({ success: false, error: "user_email is required" }, 400, corsHeaders);
        }

        try {
          // Check if table exists
          const { results: tableExists } = await env.DB.prepare(`
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='User_notifications'
          `).all();

          if (!tableExists || tableExists.length === 0) {
            return json({ success: true, notifications: [] }, 200, corsHeaders);
          }

          // Build query
          let query = `
            SELECT * FROM User_notifications
            WHERE LOWER(COALESCE(user_email, '')) = ?
          `;
          const params = [userEmail];

          // Add date filter if provided
          if (dateFilter) {
            query += ` AND (substr(COALESCE(completion_time, created_at), 1, 10) = ? OR substr(COALESCE(created_at, completion_time), 1, 10) = ?)`;
            params.push(dateFilter);
            params.push(dateFilter);
          }

          query += ` ORDER BY COALESCE(completion_time, created_at) DESC`;

          const { results } = await env.DB.prepare(query).bind(...params).all();

          // Convert results to notification format
          const notifications = (results || []).map(row => ({
            notification_id: row.notification_id || '',
            user_email: row.user_email || '',
            filename: row.filename || '',
            vendor_id: row.vendor_id || '',
            status: row.status || 'completed',
            completion_time: row.completion_time || '',
            created_at: row.created_at || '',
            timestamp: row.completion_time || row.created_at || '',
            read: row.read === 1 || row.read === true,
            type: row.type || 'job_completed',
            token: row.token || '',
            service_type: row.service_type || '',
            platform_profit: row.platform_profit || 0.0,
            total_price: row.total_price || 0.0,
            title: '🎉 Print Job Successfully Completed!',
            message: `Your ${row.service_type || 'Document Printing'} order for "${row.filename || 'Document'}" has been completed and is ready for pickup. Token: #${row.token || 'Unknown'}`,
            document_name: (row.filename || '').replace(/\.[^/.]+$/, '')
          }));

          return json({ success: true, notifications: notifications }, 200, corsHeaders);
        } catch (dbError) {
          return json({ 
            success: false, 
            error: `Database error: ${String(dbError)}` 
          }, 500, corsHeaders);
        }
      }

      // GET /get-all-vendors → get all vendors from Vendor_register table
      if (url.pathname === "/get-all-vendors" && request.method === "GET") {
        if (!env.DB) {
          return json({ success: false, error: "Database not configured" }, 500, corsHeaders);
        }

        try {
          // First, try to find the correct table name by listing all tables
          let tableName = null;
          try {
            const tablesResult = await env.DB.prepare(`
              SELECT name FROM sqlite_master 
              WHERE type='table' 
              AND (name LIKE '%vendor%register%' OR name LIKE '%Vendor%register%')
              ORDER BY name
            `).all();
            
            if (tablesResult && tablesResult.results && tablesResult.results.length > 0) {
              // Use the first matching table
              tableName = tablesResult.results[0].name;
            }
          } catch (listErr) {
            // If listing fails, try common variations
            console.log(`Could not list tables: ${String(listErr)}`);
          }

          // Try different table name variations
          const tableVariations = [];
          if (tableName) {
            tableVariations.push(tableName);
          }
          // Add common variations
          tableVariations.push('Vendor_register_details', '"Vendor_register_details "', 'Vendor_register_details ');

          let vendors = null;
          let lastError = null;

          for (const table of tableVariations) {
            try {
              const query = `
                SELECT email, vendor_name, vendor_id, vendor_token, phone_number, state, city, locality, shop_address, pincode, latitude, longitude, status
                FROM ${table}
                WHERE status = 'approved' OR status = 'active' OR status IS NULL OR status = ''
                ORDER BY vendor_name
              `;
              vendors = await env.DB.prepare(query).all();
              
              if (vendors && vendors.results && vendors.results.length > 0) {
                console.log(`✅ Successfully fetched vendors from table: ${table}`);
                break;
              }
            } catch (err) {
              lastError = err;
              continue;
            }
          }

          // If still no results, try without status filter
          if (!vendors || !vendors.results || vendors.results.length === 0) {
            for (const table of tableVariations) {
              try {
                const query = `
                  SELECT email, vendor_name, vendor_id, vendor_token, phone_number, state, city, locality, shop_address, pincode, latitude, longitude, status
                  FROM ${table}
                  ORDER BY vendor_name
                `;
                vendors = await env.DB.prepare(query).all();
                
                if (vendors && vendors.results && vendors.results.length > 0) {
                  console.log(`✅ Successfully fetched vendors from table: ${table} (no status filter)`);
                  break;
                }
              } catch (err) {
                lastError = err;
                continue;
              }
            }
          }

          if (vendors && vendors.results && vendors.results.length > 0) {
            return json({ 
              success: true, 
              vendors: vendors.results || [] 
            }, 200, corsHeaders);
          } else {
            // If all attempts failed, list available tables for debugging
            try {
              const allTables = await env.DB.prepare(`
                SELECT name FROM sqlite_master 
                WHERE type='table' 
                AND name NOT LIKE 'sqlite_%'
                ORDER BY name
              `).all();
              const tableNames = allTables.results.map(r => r.name).join(', ');
              return json({ 
                success: false, 
                error: `No vendors found. Available tables: ${tableNames || 'none'}. Last error: ${String(lastError)}` 
              }, 404, corsHeaders);
            } catch (listErr) {
              return json({ 
                success: false, 
                error: `Database error: Could not fetch vendors. Error: ${String(lastError)}` 
              }, 500, corsHeaders);
            }
          }
        } catch (dbError) {
          return json({ 
            success: false, 
            error: `Database error: ${String(dbError)}` 
          }, 500, corsHeaders);
        }
      }

      // GET /get-vendor-by-email → get vendor details for authentication
      if (url.pathname === "/get-vendor-by-email" && request.method === "POST") {
        if (!env.DB) {
          return json({ success: false, error: "Database not configured" }, 500, corsHeaders);
        }

        await ensureVendorRegisterTable(env);

        const body = await safeBody(request);
        const email = (body.email || "").trim();

        if (!email) {
          return json({ success: false, error: "Email is required" }, 400, corsHeaders);
        }

        try {
          // Try with trailing space first
          let vendor = await env.DB.prepare(`
            SELECT email, password_hash, vendor_name, vendor_id, vendor_token, phone_number, state, city, locality, shop_address, pincode
            FROM "Vendor_register_details " WHERE email = ? LIMIT 1
          `).bind(email).first();

          // If not found, try without space
          if (!vendor) {
            vendor = await env.DB.prepare(`
              SELECT email, password_hash, vendor_name, vendor_id, vendor_token, phone_number, state, city, locality, shop_address, pincode
              FROM Vendor_register_details WHERE email = ? LIMIT 1
            `).bind(email).first();
          }

          if (!vendor) {
            return json({ success: false, error: "Vendor not found" }, 404, corsHeaders);
          }

          return json({ success: true, vendor: vendor }, 200, corsHeaders);
        } catch (dbError) {
          return json({ 
            success: false, 
            error: `Database error: ${String(dbError)}` 
          }, 500, corsHeaders);
        }
      }

      // POST /upsert-vendor-service → saves vendor service availability JSON
      if (url.pathname === "/upsert-vendor-service" && request.method === "POST") {
        if (!env.DB) {
          return json({ success: false, error: "Database not configured" }, 500, corsHeaders);
        }

        const body = await safeBody(request);
        const vendor_email = (body.vendor_email || "").trim();
        const vendor_id = (body.vendor_id || "").trim();
        const updated_by = (body.updated_by || "").trim() || null;
        let service_data = body.service_data || body.service_json || body.data || {};

        if (!vendor_email || !vendor_id) {
          return json({ success: false, error: "vendor_email and vendor_id are required" }, 400, corsHeaders);
        }

        if (typeof service_data === "string" && service_data.length > 0) {
          try {
            service_data = JSON.parse(service_data);
          } catch (err) {
            return json({ success: false, error: `Invalid service_data JSON: ${String(err)}` }, 400, corsHeaders);
          }
        }

        if (!service_data || typeof service_data !== "object") {
          service_data = {};
        }

        try {
          await ensureVendorServiceTable(env);

          let existingRow = null;
          if (vendor_email) {
            existingRow = await env.DB.prepare(`
              SELECT ${VENDOR_SERVICE_SELECT_FIELDS}
              FROM Vendor_service_availability
              WHERE vendor_email = ?
              LIMIT 1
            `).bind(vendor_email).first();
          }
          if (!existingRow && vendor_id) {
            existingRow = await env.DB.prepare(`
              SELECT ${VENDOR_SERVICE_SELECT_FIELDS}
              FROM Vendor_service_availability
              WHERE vendor_id = ?
              LIMIT 1
            `).bind(vendor_id).first();
          }

          const basePayload = existingRow
            ? rowToServicePayload(existingRow)
            : getDefaultServiceAvailability();
          const mergedPayload = { ...basePayload, ...service_data };
          const normalized = normalizeServicePayload(mergedPayload);
          const serviceColumnValues = VENDOR_SERVICE_DB_COLUMNS.map(
            (column) => normalized.columnValues[column]
          );

          await env.DB.prepare(`
            INSERT INTO Vendor_service_availability (
              vendor_email,
              vendor_id,
              ${VENDOR_SERVICE_DB_COLUMNS.join(", ")},
              updated_at,
              updated_by
            )
            VALUES (
              ?, ?,
              ${VENDOR_SERVICE_DB_COLUMNS.map(() => "?").join(", ")},
              datetime('now'),
              ?
            )
            ON CONFLICT(vendor_email) DO UPDATE SET
              vendor_id = excluded.vendor_id,
              ${VENDOR_SERVICE_DB_COLUMNS.map((col) => `${col} = excluded.${col}`).join(", ")},
              updated_at = datetime('now'),
              updated_by = excluded.updated_by
          `).bind(
            vendor_email,
            vendor_id,
            ...serviceColumnValues,
            updated_by
          ).run();

          const saved = await env.DB.prepare(`
            SELECT ${VENDOR_SERVICE_SELECT_FIELDS}
            FROM Vendor_service_availability
            WHERE vendor_email = ?
            LIMIT 1
          `).bind(vendor_email).first();

          const parsed = rowToServicePayload(saved);

          return json({
            success: true,
            message: "Service availability saved successfully",
            service: {
              vendor_email: saved.vendor_email,
              vendor_id: saved.vendor_id,
              updated_at: saved.updated_at,
              updated_by: saved.updated_by,
              service_data: parsed
            }
          }, 200, corsHeaders);
        } catch (dbError) {
          return json({
            success: false,
            error: `Database error: ${String(dbError)}`
          }, 500, corsHeaders);
        }
      }

      // POST /get-vendor-service → fetch vendor service availability
      if (url.pathname === "/get-vendor-service" && request.method === "POST") {
        if (!env.DB) {
          return json({ success: false, error: "Database not configured" }, 500, corsHeaders);
        }

        const body = await safeBody(request);
        const vendor_email = (body.vendor_email || "").trim();
        const vendor_id = (body.vendor_id || "").trim();

        if (!vendor_email && !vendor_id) {
          return json({ success: false, error: "vendor_email or vendor_id is required" }, 400, corsHeaders);
        }

        try {
          await ensureVendorServiceTable(env);

          let result = null;
          if (vendor_email) {
            result = await env.DB.prepare(`
              SELECT ${VENDOR_SERVICE_SELECT_FIELDS}
              FROM Vendor_service_availability
              WHERE vendor_email = ?
              LIMIT 1
            `).bind(vendor_email).first();
          }

          if (!result && vendor_id) {
            result = await env.DB.prepare(`
              SELECT ${VENDOR_SERVICE_SELECT_FIELDS}
              FROM Vendor_service_availability
              WHERE vendor_id = ?
              LIMIT 1
            `).bind(vendor_id).first();
          }

          if (!result) {
            return json({ success: false, error: "Service availability not found" }, 404, corsHeaders);
          }

          const parsed = rowToServicePayload(result);
          
          // Convert boolean values to "on"/"off" for admin display if requested
          const displayFormat = body.display_format === "on_off";
          const serviceData = displayFormat ? convertServiceDataToOnOff(parsed) : parsed;

          return json({
            success: true,
            service: {
              vendor_email: result.vendor_email,
              vendor_id: result.vendor_id,
              updated_at: result.updated_at,
              updated_by: result.updated_by,
              service_data: serviceData
            }
          }, 200, corsHeaders);
        } catch (dbError) {
          return json({
            success: false,
            error: `Database error: ${String(dbError)}`
          }, 500, corsHeaders);
        }
      }

      // POST /add-user-signup → upserts user signup metadata
      if (url.pathname === "/add-user-signup" && request.method === "POST") {
        if (!env.DB) {
          return json({ success: false, error: "Database not configured" }, 500, corsHeaders);
        }

        const body = await safeBody(request);
        const email = (body.email || "").trim().toLowerCase();
        const google_user_id = (body.google_user_id || "").trim();
        const name = (body.name || "").trim();
        const given_name = (body.given_name || "").trim();
        const family_name = (body.family_name || "").trim();
        const picture = (body.picture || "").trim();
        const email_verified = body.email_verified ? 1 : 0;
        const nowIso = new Date().toISOString();
        const signup_timestamp = (body.signup_timestamp || nowIso).trim();
        const last_login = (body.last_login || nowIso).trim();
        const is_active = body.is_active === undefined ? 1 : (body.is_active ? 1 : 0);

        if (!email) {
          return json({ success: false, error: "email is required" }, 400, corsHeaders);
        }

        try {
          await env.DB.prepare(`
            CREATE TABLE IF NOT EXISTS User_signup_details(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              email TEXT NOT NULL UNIQUE,
              google_user_id TEXT,
              name TEXT,
              given_name TEXT,
              family_name TEXT,
              picture TEXT,
              email_verified INTEGER DEFAULT 0,
              signup_timestamp TEXT,
              last_login TEXT,
              is_active INTEGER DEFAULT 1
            )
          `).run();
          await env.DB.prepare(`
            CREATE UNIQUE INDEX IF NOT EXISTS idx_user_signup_email
            ON User_signup_details(email)
          `).run();

          await env.DB.prepare(`
            INSERT INTO User_signup_details (
              email, google_user_id, name, given_name, family_name,
              picture, email_verified, signup_timestamp, last_login, is_active
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(email) DO UPDATE SET
              google_user_id = excluded.google_user_id,
              name = excluded.name,
              given_name = excluded.given_name,
              family_name = excluded.family_name,
              picture = excluded.picture,
              email_verified = excluded.email_verified,
              last_login = excluded.last_login,
              is_active = excluded.is_active,
              signup_timestamp = COALESCE(User_signup_details.signup_timestamp, excluded.signup_timestamp)
          `).bind(
            email,
            google_user_id || null,
            name || null,
            given_name || null,
            family_name || null,
            picture || null,
            email_verified,
            signup_timestamp,
            last_login,
            is_active
          ).run();

          const saved = await env.DB.prepare(`
            SELECT id, email, google_user_id, name, given_name, family_name,
                   picture, email_verified, signup_timestamp, last_login, is_active
            FROM User_signup_details
            WHERE email = ?
            LIMIT 1
          `).bind(email).first();

          return json({
            success: true,
            user_signup: saved
          }, 200, corsHeaders);
        } catch (dbError) {
          return json({ success: false, error: `Database error: ${String(dbError)}` }, 500, corsHeaders);
        }
      }

      // POST /get-user-signup → fetch signup metadata
      if (url.pathname === "/get-user-signup" && request.method === "POST") {
        if (!env.DB) {
          return json({ success: false, error: "Database not configured" }, 500, corsHeaders);
        }

        const body = await safeBody(request);
        const email = (body.email || "").trim().toLowerCase();
        const google_user_id = (body.google_user_id || "").trim();

        if (!email && !google_user_id) {
          return json({ success: false, error: "email or google_user_id is required" }, 400, corsHeaders);
        }

        try {
          await env.DB.prepare(`
            CREATE TABLE IF NOT EXISTS User_signup_details(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              email TEXT NOT NULL UNIQUE,
              google_user_id TEXT,
              name TEXT,
              given_name TEXT,
              family_name TEXT,
              picture TEXT,
              email_verified INTEGER DEFAULT 0,
              signup_timestamp TEXT,
              last_login TEXT,
              is_active INTEGER DEFAULT 1
            )
          `).run();

          let query = `
            SELECT id, email, google_user_id, name, given_name, family_name,
                   picture, email_verified, signup_timestamp, last_login, is_active
            FROM User_signup_details
            WHERE LOWER(email) = LOWER(?)
            LIMIT 1
          `;
          let args = [email];

          if (!email) {
            query = `
              SELECT id, email, google_user_id, name, given_name, family_name,
                     picture, email_verified, signup_timestamp, last_login, is_active
              FROM User_signup_details
              WHERE google_user_id = ?
              LIMIT 1
            `;
            args = [google_user_id];
          }

          const result = await env.DB.prepare(query).bind(args[0]).first();

          if (!result) {
            return json({ success: false, error: "User signup not found" }, 404, corsHeaders);
          }

          return json({
            success: true,
            user_signup: result
          }, 200, corsHeaders);
        } catch (dbError) {
          return json({ success: false, error: `Database error: ${String(dbError)}` }, 500, corsHeaders);
        }
      }

      // POST /add-user-points → inserts user points transaction
      if (url.pathname === "/add-user-points" && request.method === "POST") {
        if (!env.DB) {
          return json({ success: false, error: "Database not configured" }, 500, corsHeaders);
        }

        const body = await safeBody(request);
        
        const user_email = (body.user_email || "").trim();
        const points = parseInt(body.points || "0", 10) || 0;
        const date = (body.date || "").trim();
        const time = (body.time || "").trim();
        const reason = (body.reason || "").trim();
        const transaction_timestamp = (body.transaction_timestamp || new Date().toISOString()).trim();

        if (!user_email || !date || !time) {
          return json({ success: false, error: "user_email, date, and time are required" }, 400, corsHeaders);
        }

        try {
          // Check if table exists, create if not
          try {
            await env.DB.prepare(`SELECT 1 FROM User_points LIMIT 1`).first();
          } catch (tableErr) {
            // Table doesn't exist, create it
            await env.DB.prepare(`
              CREATE TABLE IF NOT EXISTS User_points(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_email TEXT NOT NULL,
                points INTEGER NOT NULL,
                date TEXT NOT NULL,
                time TEXT NOT NULL,
                reason TEXT,
                transaction_timestamp TEXT NOT NULL,
                UNIQUE(user_email, transaction_timestamp)
              )
            `).run();
          }

          // Insert points transaction
          await env.DB.prepare(`
            INSERT INTO User_points (user_email, points, date, time, reason, transaction_timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
          `).bind(user_email, points, date, time, reason || null, transaction_timestamp).run();

          return json({ success: true, message: "User points transaction saved successfully" }, 200, corsHeaders);
        } catch (dbError) {
          // Check if it's a unique constraint violation (duplicate)
          if (String(dbError).includes('UNIQUE constraint') || String(dbError).includes('duplicate')) {
            return json({ 
              success: false, 
              error: "Duplicate transaction - this points record already exists" 
            }, 400, corsHeaders);
          }
          return json({ 
            success: false, 
            error: `Database error: ${String(dbError)}` 
          }, 500, corsHeaders);
        }
      }

      // POST /get-user-total-points → get sum of all points for a user
      if (url.pathname === "/get-user-total-points" && request.method === "POST") {
        if (!env.DB) {
          return json({ success: false, error: "Database not configured" }, 500, corsHeaders);
        }

        const body = await safeBody(request);
        const user_email = (body.user_email || "").trim();

        if (!user_email) {
          return json({ success: false, error: "user_email is required" }, 400, corsHeaders);
        }

        try {
          const result = await env.DB.prepare(`
            SELECT COALESCE(SUM(points), 0) as total_points
            FROM User_points
            WHERE user_email = ?
          `).bind(user_email).first();

          const total_points = result ? (result.total_points || 0) : 0;

          return json({ 
            success: true, 
            total_points: parseInt(total_points, 10) 
          }, 200, corsHeaders);
        } catch (dbError) {
          return json({ 
            success: false, 
            error: `Database error: ${String(dbError)}` 
          }, 500, corsHeaders);
        }
      }

      // POST /add-vendor-print-job → inserts vendor print job data
      if (url.pathname === "/add-vendor-print-job" && request.method === "POST") {
        if (!env.DB) {
          return json({ success: false, error: "Database not configured" }, 500, corsHeaders);
        }

        const body = await safeBody(request);
        
        // Extract all fields
        const vendor_id = (body.vendor_id || "").trim();
        const vendor_email = (body.vendor_email || "").trim();
        const user_email = (body.user_email || "").trim();
        const filename = (body.filename || "").trim();
        const storage_folder = (body.storage_folder || "").trim(); // 'vendor_print_jobs' or 'vendor_manual_print_jobs'
        const r2_path = (body.r2_path || "").trim();
        const service_type = (body.service_type || "").trim();
        const status = (body.status || "pending").trim();
        const job_completed = (body.job_completed || "NO").trim();
        const vendor_status = (body.vendor_status || "not sended").trim();
        const token = (body.token || "").trim();
        const job_id = (body.job_id || "").trim();
        const copies = (body.copies || "1").trim();
        const color = (body.color || "").trim();
        const orientation = (body.orientation || "").trim();
        const pageSize = (body.pageSize || "").trim();
        const pageRange = (body.pageRange || "").trim();
        const specificPages = (body.specificPages || "").trim();
        const spiralBinding = (body.spiralBinding || "No").trim();
        const lamination = (body.lamination || "No").trim();
        const service_name = (body.service_name || "").trim();
        const feedback = (body.feedback || "").trim();
        const quality = (body.quality || "").trim();
        const thickness = (body.thickness || "").trim();
        const points_applied = (body.points_applied || "false").trim();
        const points_used = parseInt(body.points_used || "0", 10) || 0;
        const timestamp = (body.timestamp || new Date().toISOString()).trim();
        const completion_time = (body.completion_time || "").trim();
        const rendered_status = (body.rendered_status || "NO").trim();
        const trash = (body.trash || "NO").trim();
        
        // Decimal values
        const total_price = body.total_price !== undefined ? parseFloat(body.total_price) : null;
        const platform_profit = body.platform_profit !== undefined ? parseFloat(body.platform_profit) : null;
        const price_per_page = body.price_per_page !== undefined ? parseFloat(body.price_per_page) : null;
        const final_amount = body.final_amount !== undefined ? parseFloat(body.final_amount) : null;
        
        // Integer values
        const page_count = body.page_count !== undefined ? parseInt(body.page_count, 10) : null;
        const num_copies = body.num_copies !== undefined ? parseInt(body.num_copies, 10) : null;
        
        // Pricing details as JSON string
        const pricing_details = body.pricing_details || null;

        if (!vendor_id || !filename || !storage_folder) {
          return json({ 
            success: false, 
            error: "vendor_id, filename, and storage_folder are required" 
          }, 400, corsHeaders);
        }

        try {
          // Check if table exists, create if not
          try {
            await env.DB.prepare(`SELECT 1 FROM Vendor_print_jobs LIMIT 1`).first();
          } catch (tableErr) {
            // Table doesn't exist, create it
            await env.DB.prepare(`
              CREATE TABLE IF NOT EXISTS Vendor_print_jobs(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vendor_id TEXT NOT NULL,
                vendor_email TEXT,
                user_email TEXT NOT NULL,
                filename TEXT NOT NULL,
                storage_folder TEXT NOT NULL,
                r2_path TEXT NOT NULL,
                service_type TEXT,
                status TEXT,
                job_completed TEXT,
                vendor_status TEXT,
                token TEXT,
                job_id TEXT,
                copies TEXT,
                color TEXT,
                orientation TEXT,
                pageSize TEXT,
                pageRange TEXT,
                specificPages TEXT,
                spiralBinding TEXT,
                lamination TEXT,
                service_name TEXT,
                feedback TEXT,
                quality TEXT,
                thickness TEXT,
                points_applied TEXT,
                points_used INTEGER,
                timestamp TEXT NOT NULL,
                completion_time TEXT,
                rendered_status TEXT,
                trash TEXT,
                total_price REAL,
                platform_profit REAL,
                price_per_page REAL,
                final_amount REAL,
                page_count INTEGER,
                num_copies INTEGER,
                pricing_details TEXT,
                UNIQUE(vendor_id, filename, storage_folder)
              )
            `).run();
          }

          // Try INSERT first, if it fails due to unique constraint, do UPDATE
          try {
            await env.DB.prepare(`
              INSERT INTO Vendor_print_jobs (
                vendor_id, vendor_email, user_email, filename, storage_folder, r2_path,
                service_type, status, job_completed, vendor_status, token, job_id,
                copies, color, orientation, pageSize, pageRange, specificPages,
                spiralBinding, lamination, service_name, feedback, quality, thickness,
                points_applied, points_used, timestamp, completion_time, rendered_status,
                trash, total_price, platform_profit, price_per_page, final_amount,
                page_count, num_copies, pricing_details
              )
              VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            `).bind(
              vendor_id, vendor_email || null, user_email, filename, storage_folder, r2_path,
              service_type || null, status, job_completed, vendor_status, token || null, job_id || null,
              copies, color || null, orientation || null, pageSize || null, pageRange || null, specificPages || null,
              spiralBinding, lamination, service_name || null, feedback || null, quality || null, thickness || null,
              points_applied, points_used, timestamp, completion_time || null, rendered_status, trash,
              total_price, platform_profit, price_per_page, final_amount,
              page_count, num_copies, pricing_details
            ).run();
          } catch (insertError) {
            // If insert fails due to unique constraint, update existing record
            if (String(insertError).includes('UNIQUE constraint') || String(insertError).includes('duplicate')) {
              await env.DB.prepare(`
                UPDATE Vendor_print_jobs SET
                  vendor_email = ?,
                  user_email = ?,
                  r2_path = ?,
                  service_type = ?,
                  status = ?,
                  job_completed = ?,
                  vendor_status = ?,
                  token = ?,
                  job_id = ?,
                  copies = ?,
                  color = ?,
                  orientation = ?,
                  pageSize = ?,
                  pageRange = ?,
                  specificPages = ?,
                  spiralBinding = ?,
                  lamination = ?,
                  service_name = ?,
                  feedback = ?,
                  quality = ?,
                  thickness = ?,
                  points_applied = ?,
                  points_used = ?,
                  timestamp = ?,
                  completion_time = ?,
                  rendered_status = ?,
                  trash = ?,
                  total_price = ?,
                  platform_profit = ?,
                  price_per_page = ?,
                  final_amount = ?,
                  page_count = ?,
                  num_copies = ?,
                  pricing_details = ?
                WHERE vendor_id = ? AND filename = ? AND storage_folder = ?
              `).bind(
                vendor_email || null, user_email, r2_path,
                service_type || null, status, job_completed, vendor_status, token || null, job_id || null,
                copies, color || null, orientation || null, pageSize || null, pageRange || null, specificPages || null,
                spiralBinding, lamination, service_name || null, feedback || null, quality || null, thickness || null,
                points_applied, points_used, timestamp, completion_time || null, rendered_status, trash,
                total_price, platform_profit, price_per_page, final_amount,
                page_count, num_copies, pricing_details,
                vendor_id, filename, storage_folder
              ).run();
            } else {
              throw insertError;
            }
          }

          return json({ success: true, message: "Vendor print job saved successfully" }, 200, corsHeaders);
        } catch (dbError) {
          return json({ 
            success: false, 
            error: `Database error: ${String(dbError)}` 
          }, 500, corsHeaders);
        }
      }

      // GET /get-user-print-jobs → retrieves user print jobs by user_email
      // STRICT FILTER: Only return jobs where job_completed = 'NO' (pending jobs)
      if (url.pathname === "/get-user-print-jobs" && request.method === "POST") {
        if (!env.DB) {
          return json({ success: false, error: "Database not configured" }, 500, corsHeaders);
        }

        const body = await safeBody(request);
        const user_email = (body.user_email || "").trim();

        if (!user_email) {
          return json({ success: false, error: "user_email is required" }, 400, corsHeaders);
        }

        try {
          const { results } = await env.DB.prepare(`
            SELECT * FROM User_print_jobs
            WHERE user_email = ?
              AND UPPER(COALESCE(NULLIF(TRIM(job_completed), ''), 'NO')) != 'YES'
            ORDER BY timestamp DESC
          `).bind(user_email).all();

          return json({ success: true, data: results }, 200, corsHeaders);
        } catch (dbError) {
          return json({ 
            success: false, 
            error: `Database error: ${String(dbError)}` 
          }, 500, corsHeaders);
        }
      }

      // POST /get-all-user-jobs → retrieves all user notifications (for admin dashboard)
      // Uses User_notifications table instead of User_print_jobs
      if (url.pathname === "/get-all-user-jobs" && request.method === "POST") {
        if (!env.DB) {
          return json({ success: false, error: "Database not configured" }, 500, corsHeaders);
        }

        const body = await safeBody(request);
        const userEmailFilter = (body.user_email || "").trim();
        const monthFilter = (body.month || "").trim();
        const weekStart = (body.week_start || "").trim();
        const weekEnd = (body.week_end || "").trim();

        try {
          const { results: tableExists } = await env.DB.prepare(`
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='User_notifications'
          `).all();

          if (!tableExists || tableExists.length === 0) {
            return json({ success: true, data: [] }, 200, corsHeaders);
          }

          const conditions = [];
          const params = [];

          if (userEmailFilter) {
            conditions.push("LOWER(COALESCE(user_email, '')) = ?");
            params.push(userEmailFilter.toLowerCase());
          }

          // Use completion_time for date filtering, fallback to created_at
          if (monthFilter) {
            conditions.push("(substr(COALESCE(completion_time, created_at), 1, 7) = ?)");
            params.push(monthFilter);
          }

          if (weekStart && weekEnd) {
            conditions.push("(COALESCE(completion_time, created_at) BETWEEN ? AND ?)");
            params.push(weekStart);
            params.push(weekEnd);
          }

          const whereClause = conditions.length ? `WHERE ${conditions.join(" AND ")}` : "";
          const query = `
            SELECT * FROM User_notifications
            ${whereClause}
            ORDER BY COALESCE(completion_time, created_at) DESC
          `;

          const statement = env.DB.prepare(query);
          const { results } = params.length ? await statement.bind(...params).all() : await statement.all();

          return json({ success: true, data: results || [] }, 200, corsHeaders);
        } catch (dbError) {
          console.error("Error in /get-all-user-jobs:", dbError);
          return json({ 
            success: false, 
            error: `Database error: ${String(dbError)}` 
          }, 500, corsHeaders);
        }
      }

      if (url.pathname === "/get-user-job-months" && request.method === "POST") {
        if (!env.DB) {
          return json({ success: false, error: "Database not configured" }, 500, corsHeaders);
        }

        try {
          // Use User_notifications table with completion_time or created_at
          const query = `
            SELECT DISTINCT substr(COALESCE(completion_time, created_at), 1, 7) AS month_key
            FROM User_notifications
            WHERE (completion_time IS NOT NULL AND completion_time != '') 
               OR (created_at IS NOT NULL AND created_at != '')
            ORDER BY month_key DESC
          `;
          const { results } = await env.DB.prepare(query).all();
          const months = (results || [])
            .map((row) => row.month_key)
            .filter((value) => value && typeof value === "string" && value.length === 7);

          return json({ success: true, data: months }, 200, corsHeaders);
        } catch (dbError) {
          console.error("Error in /get-user-job-months:", dbError);
          return json({
            success: false,
            error: `Database error: ${String(dbError)}`
          }, 500, corsHeaders);
        }
      }

      // POST /get-all-vendor-jobs → retrieves vendor notifications with optional filtering
      // Uses vendor_notification table instead of Vendor_print_jobs
      if (url.pathname === "/get-all-vendor-jobs" && request.method === "POST") {
        if (!env.DB) {
          return json({ success: false, error: "Database not configured" }, 500, corsHeaders);
        }

        const body = await safeBody(request);
        const vendorId = (body.vendor_id || "").trim();
        const vendorEmail = (body.vendor_email || "").trim().toLowerCase();
        const monthFilter = (body.month || "").trim();
        const weekStart = (body.week_start || "").trim();
        const weekEnd = (body.week_end || "").trim();

        try {
          // Check if table exists (try both case variations)
          const { results: tableCheck1 } = await env.DB.prepare(`
            SELECT name FROM sqlite_master
            WHERE type='table' AND LOWER(name) = LOWER('vendor_notification')
          `).all();

          if (!tableCheck1 || tableCheck1.length === 0) {
            console.log("⚠️ vendor_notification table not found");
            return json({ success: true, data: [] }, 200, corsHeaders);
          }

          const tableName = tableCheck1[0].name; // Use actual table name from database
          console.log(`✅ Found table: ${tableName}`);

          const conditions = [];
          const params = [];

          if (vendorId) {
            conditions.push("vendor_id = ?");
            params.push(vendorId);
          }

          if (vendorEmail) {
            conditions.push("LOWER(COALESCE(vendor_email, '')) = ?");
            params.push(vendorEmail);
          }

          // Use completion_time for date filtering, fallback to timestamp (vendor_notification table has timestamp, not created_at)
          // Check both fields separately to avoid SQLite COALESCE issues
          if (monthFilter) {
            conditions.push("((completion_time IS NOT NULL AND completion_time != '' AND substr(completion_time, 1, 7) = ?) OR (timestamp IS NOT NULL AND timestamp != '' AND substr(timestamp, 1, 7) = ?))");
            params.push(monthFilter, monthFilter);
          }

          if (weekStart && weekEnd) {
            conditions.push("((completion_time IS NOT NULL AND completion_time != '' AND completion_time BETWEEN ? AND ?) OR (timestamp IS NOT NULL AND timestamp != '' AND timestamp BETWEEN ? AND ?))");
            params.push(weekStart, weekEnd, weekStart, weekEnd);
          }

          const whereClause = conditions.length ? `WHERE ${conditions.join(" AND ")}` : "";
          
          // Use simpler ORDER BY - prioritize completion_time, then timestamp
          const query = `
            SELECT * FROM ${tableName}
            ${whereClause}
            ORDER BY completion_time DESC, timestamp DESC
          `;

          console.log(`🔍 Executing query: ${query.substring(0, 200)}...`);
          const statement = env.DB.prepare(query);
          let result;
          if (params.length > 0) {
            result = await statement.bind(...params).all();
          } else {
            result = await statement.all();
          }
          const { results } = result || {};

          console.log(`✅ Retrieved ${(results || []).length} vendor notifications`);
          return json({ success: true, data: results || [] }, 200, corsHeaders);
        } catch (dbError) {
          console.error("❌ Error in /get-all-vendor-jobs:", dbError);
          console.error("Error details:", String(dbError));
          return json({ 
            success: false, 
            error: `Database error: ${String(dbError)}` 
          }, 500, corsHeaders);
        }
      }

      // POST /add-user-print-job → inserts user print job data (from users folder in R2)
      if (url.pathname === "/add-user-print-job" && request.method === "POST") {
        if (!env.DB) {
          return json({ success: false, error: "Database not configured" }, 500, corsHeaders);
        }

        const body = await safeBody(request);
        
        // Extract all fields (same structure as vendor print jobs)
        const vendor_id = (body.vendor_id || "").trim();
        const vendor_email = (body.vendor_email || "").trim();
        const user_email = (body.user_email || "").trim();
        const filename = (body.filename || "").trim();
        const storage_folder = (body.storage_folder || "users").trim(); // Default to 'users' for user folder
        const r2_path = (body.r2_path || `users/${user_email}/${filename}`).trim();
        const service_type = (body.service_type || "").trim();
        const status = (body.status || "pending").trim();
        const job_completed = (body.job_completed || "NO").trim();
        const vendor_status = (body.vendor_status || "not sended").trim();
        const token = (body.token || "").trim();
        const job_id = (body.job_id || "").trim();
        const copies = (body.copies || "1").trim();
        const color = (body.color || "").trim();
        const orientation = (body.orientation || "").trim();
        const pageSize = (body.pageSize || "").trim();
        const pageRange = (body.pageRange || "").trim();
        const specificPages = (body.specificPages || "").trim();
        const spiralBinding = (body.spiralBinding || "No").trim();
        const lamination = (body.lamination || "No").trim();
        const service_name = (body.service_name || "").trim();
        const feedback = (body.feedback || "").trim();
        const quality = (body.quality || "").trim();
        const thickness = (body.thickness || "").trim();
        const points_applied = (body.points_applied || "false").trim();
        const points_used = parseInt(body.points_used || "0", 10) || 0;
        const timestamp = (body.timestamp || new Date().toISOString()).trim();
        const completion_time = (body.completion_time || "").trim();
        const rendered_status = (body.rendered_status || "NO").trim();
        const trash = (body.trash || "NO").trim();
        
        // Decimal values
        const total_price = body.total_price !== undefined ? parseFloat(body.total_price) : null;
        const platform_profit = body.platform_profit !== undefined ? parseFloat(body.platform_profit) : null;
        const price_per_page = body.price_per_page !== undefined ? parseFloat(body.price_per_page) : null;
        const final_amount = body.final_amount !== undefined ? parseFloat(body.final_amount) : null;
        
        // Integer values
        const page_count = body.page_count !== undefined ? parseInt(body.page_count, 10) : null;
        const num_copies = body.num_copies !== undefined ? parseInt(body.num_copies, 10) : null;
        
        // Pricing details as JSON string
        const pricing_details = body.pricing_details || null;

        if (!user_email || !filename) {
          return json({ 
            success: false, 
            error: "user_email and filename are required" 
          }, 400, corsHeaders);
        }

        try {
          // Check if table exists, create if not
          try {
            await env.DB.prepare(`SELECT 1 FROM User_print_jobs LIMIT 1`).first();
          } catch (tableErr) {
            // Table doesn't exist, create it
            // Create table matching exact structure from Vendor_print_jobs
            // Adding PRIMARY KEY and UNIQUE constraint for better functionality
            await env.DB.prepare(`
              CREATE TABLE IF NOT EXISTS User_print_jobs(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vendor_id TEXT,
                vendor_email TEXT,
                user_email TEXT,
                filename TEXT,
                storage_folder TEXT,
                r2_path TEXT,
                service_type TEXT,
                status TEXT,
                job_completed TEXT,
                vendor_status TEXT,
                token TEXT,
                job_id TEXT,
                copies TEXT,
                color TEXT,
                orientation TEXT,
                pageSize TEXT,
                pageRange TEXT,
                specificPages TEXT,
                spiralBinding TEXT,
                lamination TEXT,
                service_name TEXT,
                feedback TEXT,
                quality TEXT,
                thickness TEXT,
                points_applied TEXT,
                points_used INTEGER,
                timestamp TEXT,
                completion_time TEXT,
                rendered_status TEXT,
                trash TEXT,
                total_price REAL,
                platform_profit REAL,
                price_per_page REAL,
                final_amount REAL,
                page_count INTEGER,
                num_copies INTEGER,
                pricing_details TEXT,
                UNIQUE(user_email, filename, storage_folder)
              )
            `).run();
          }

          // Try INSERT first, if it fails due to unique constraint, do UPDATE
          try {
            await env.DB.prepare(`
              INSERT INTO User_print_jobs (
                vendor_id, vendor_email, user_email, filename, storage_folder, r2_path,
                service_type, status, job_completed, vendor_status, token, job_id,
                copies, color, orientation, pageSize, pageRange, specificPages,
                spiralBinding, lamination, service_name, feedback, quality, thickness,
                points_applied, points_used, timestamp, completion_time, rendered_status,
                trash, total_price, platform_profit, price_per_page, final_amount,
                page_count, num_copies, pricing_details
              )
              VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            `).bind(
              vendor_id || null, vendor_email || null, user_email, filename, storage_folder, r2_path,
              service_type || null, status, job_completed, vendor_status, token || null, job_id || null,
              copies, color || null, orientation || null, pageSize || null, pageRange || null, specificPages || null,
              spiralBinding, lamination, service_name || null, feedback || null, quality || null, thickness || null,
              points_applied, points_used, timestamp, completion_time || null, rendered_status, trash,
              total_price, platform_profit, price_per_page, final_amount,
              page_count, num_copies, pricing_details
            ).run();
          } catch (insertError) {
            // If insert fails due to unique constraint, update existing record
            if (String(insertError).includes('UNIQUE constraint') || String(insertError).includes('duplicate')) {
              await env.DB.prepare(`
                UPDATE User_print_jobs SET
                  vendor_id = ?,
                  vendor_email = ?,
                  r2_path = ?,
                  service_type = ?,
                  status = ?,
                  job_completed = ?,
                  vendor_status = ?,
                  token = ?,
                  job_id = ?,
                  copies = ?,
                  color = ?,
                  orientation = ?,
                  pageSize = ?,
                  pageRange = ?,
                  specificPages = ?,
                  spiralBinding = ?,
                  lamination = ?,
                  service_name = ?,
                  feedback = ?,
                  quality = ?,
                  thickness = ?,
                  points_applied = ?,
                  points_used = ?,
                  timestamp = ?,
                  completion_time = ?,
                  rendered_status = ?,
                  trash = ?,
                  total_price = ?,
                  platform_profit = ?,
                  price_per_page = ?,
                  final_amount = ?,
                  page_count = ?,
                  num_copies = ?,
                  pricing_details = ?
                WHERE user_email = ? AND filename = ? AND storage_folder = ?
              `).bind(
                vendor_id || null, vendor_email || null, r2_path,
                service_type || null, status, job_completed, vendor_status, token || null, job_id || null,
                copies, color || null, orientation || null, pageSize || null, pageRange || null, specificPages || null,
                spiralBinding, lamination, service_name || null, feedback || null, quality || null, thickness || null,
                points_applied, points_used, timestamp, completion_time || null, rendered_status, trash,
                total_price, platform_profit, price_per_page, final_amount,
                page_count, num_copies, pricing_details,
                user_email, filename, storage_folder
              ).run();
            } else {
              throw insertError;
            }
          }

          return json({ success: true, message: "User print job saved successfully" }, 200, corsHeaders);
        } catch (dbError) {
          return json({ 
            success: false, 
            error: `Database error: ${String(dbError)}` 
          }, 500, corsHeaders);
        }
      }

      // POST /get-vendor-print-jobs → retrieves vendor print jobs for a vendor
      if (url.pathname === "/get-vendor-print-jobs" && request.method === "POST") {
        if (!env.DB) {
          return json({ success: false, error: "Database not configured" }, 500, corsHeaders);
        }

        const body = await safeBody(request);
        const vendor_id = (body.vendor_id || "").trim();
        const vendor_email = (body.vendor_email || "").trim().toLowerCase();
        const job_completed = (body.job_completed || body.job_completed_status || "NO").toString().trim().toUpperCase();

        if (!vendor_id && !vendor_email) {
          return json({ success: false, error: "vendor_id or vendor_email is required" }, 400, corsHeaders);
        }

        const vendorFilters = [];
        if (vendor_id) {
          vendorFilters.push("vendor_id = ?");
        }
        if (vendor_email) {
          vendorFilters.push("LOWER(vendor_email) = LOWER(?)");
        }

        const whereClause = vendorFilters.length > 1
          ? `(${vendorFilters.join(" OR ")})`
          : vendorFilters[0];

        const params = [];
        if (vendor_id) params.push(vendor_id);
        if (vendor_email) params.push(vendor_email);

        let query = `
          SELECT *
          FROM Vendor_print_jobs
          WHERE ${whereClause}
        `;

        if (job_completed) {
          query += `
            AND UPPER(
              COALESCE(
                NULLIF(TRIM(job_completed), ''),
                'NO'
              )
            ) = ?
          `;
          params.push(job_completed);
        }

        let orderClause = "ORDER BY rowid DESC";

        try {
          const { results: tableInfo } = await env.DB.prepare("PRAGMA table_info(Vendor_print_jobs)").all();
          const columnNames = new Set((tableInfo || []).map(col => (col.name || "").toLowerCase()));
          const orderingExpressions = [];

          if (columnNames.has("timestamp")) {
            orderingExpressions.push("NULLIF(timestamp, '')");
          }
          if (columnNames.has("created_at")) {
            orderingExpressions.push("created_at");
          }
          if (columnNames.has("updated_at")) {
            orderingExpressions.push("updated_at");
          }

          if (orderingExpressions.length) {
            const coalesceArgs = orderingExpressions.concat("'1970-01-01T00:00:00Z'");
            const orderExpr = `COALESCE(${coalesceArgs.join(", ")})`;
            orderClause = `ORDER BY datetime(${orderExpr}) DESC, rowid DESC`;
          }
        } catch (schemaError) {
          orderClause = "ORDER BY rowid DESC";
        }

        query += `
          ${orderClause}
        `;

        try {
          const statement = env.DB.prepare(query);
          const { results } = await statement.bind(...params).all();
          return json({ success: true, data: results }, 200, corsHeaders);
        } catch (dbError) {
          return json({ 
            success: false, 
            error: `Database error: ${String(dbError)}` 
          }, 500, corsHeaders);
        }
      }

      // POST /add-fcm-token → stores FCM registration token in D1 database
      if (url.pathname === "/add-fcm-token" && request.method === "POST") {
        if (!env.DB) {
          return json({ success: false, error: "Database not configured. Please set up D1 Database Binding named 'DB' in Worker settings." }, 500, corsHeaders);
        }

        const body = await safeBody(request);
        const token = (body.token || "").trim();
        const user_email = (body.user_email || "").trim();
        const device_type = (body.device_type || "web").trim();
        const user_agent = (body.user_agent || "").trim();
        const is_active = (body.is_active !== undefined ? body.is_active : true);

        if (!token || !user_email) {
          return json({ success: false, error: "Token and user_email are required" }, 400, corsHeaders);
        }

        try {
          // Create table if it doesn't exist
          await env.DB.prepare(`
            CREATE TABLE IF NOT EXISTS FCM_tokens (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              user_email TEXT NOT NULL,
              token TEXT NOT NULL,
              device_type TEXT,
              user_agent TEXT,
              is_active INTEGER DEFAULT 1,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              UNIQUE(user_email, token)
            )
          `).run();

          const now = new Date().toISOString();

          // Try INSERT first, if it fails due to unique constraint, do UPDATE
          try {
            await env.DB.prepare(`
              INSERT INTO FCM_tokens (user_email, token, device_type, user_agent, is_active, created_at, updated_at)
              VALUES (?, ?, ?, ?, ?, ?, ?)
            `).bind(user_email, token, device_type || null, user_agent || null, is_active ? 1 : 0, now, now).run();
          } catch (insertError) {
            // If insert fails due to unique constraint, update existing record
            if (String(insertError).includes('UNIQUE constraint') || String(insertError).includes('duplicate')) {
              await env.DB.prepare(`
                UPDATE FCM_tokens SET
                  device_type = ?,
                  user_agent = ?,
                  is_active = ?,
                  updated_at = ?
                WHERE user_email = ? AND token = ?
              `).bind(device_type || null, user_agent || null, is_active ? 1 : 0, now, user_email, token).run();
            } else {
              throw insertError;
            }
          }

          return json({ success: true, message: "FCM token saved successfully" }, 200, corsHeaders);
        } catch (dbError) {
          return json({ 
            success: false, 
            error: `Database error: ${String(dbError)}` 
          }, 500, corsHeaders);
        }
      }

      // POST /get-fcm-tokens → retrieves FCM tokens for a user
      if (url.pathname === "/get-fcm-tokens" && request.method === "POST") {
        if (!env.DB) {
          return json({ success: false, error: "Database not configured. Please set up D1 Database Binding named 'DB' in Worker settings." }, 500, corsHeaders);
        }

        const body = await safeBody(request);
        const user_email = (body.user_email || "").trim();

        if (!user_email) {
          return json({ success: false, error: "user_email is required" }, 400, corsHeaders);
        }

        try {
          const result = await env.DB.prepare(`
            SELECT token, device_type, user_agent, is_active, created_at, updated_at
            FROM FCM_tokens
            WHERE user_email = ? AND is_active = 1
            ORDER BY updated_at DESC
          `).bind(user_email).all();

          const tokens = result.results.map(row => ({
            token: row.token,
            device_type: row.device_type,
            user_agent: row.user_agent,
            is_active: row.is_active === 1,
            created_at: row.created_at,
            updated_at: row.updated_at
          }));

          return json({ success: true, tokens: tokens }, 200, corsHeaders);
        } catch (dbError) {
          return json({ 
            success: false, 
            error: `Database error: ${String(dbError)}` 
          }, 500, corsHeaders);
        }
      }

      // POST /delete-fcm-token → deactivates or deletes FCM token
      if (url.pathname === "/delete-fcm-token" && request.method === "POST") {
        if (!env.DB) {
          return json({ success: false, error: "Database not configured. Please set up D1 Database Binding named 'DB' in Worker settings." }, 500, corsHeaders);
        }

        const body = await safeBody(request);
        const user_email = (body.user_email || "").trim();
        const token = (body.token || "").trim();
        const hard_delete = body.hard_delete === true; // If true, delete record; if false, just deactivate

        if (!user_email || !token) {
          return json({ success: false, error: "user_email and token are required" }, 400, corsHeaders);
        }

        try {
          if (hard_delete) {
            await env.DB.prepare(`
              DELETE FROM FCM_tokens
              WHERE user_email = ? AND token = ?
            `).bind(user_email, token).run();
          } else {
            // Soft delete: deactivate token
            await env.DB.prepare(`
              UPDATE FCM_tokens SET
                is_active = 0,
                updated_at = ?
              WHERE user_email = ? AND token = ?
            `).bind(new Date().toISOString(), user_email, token).run();
          }

          return json({ success: true, message: hard_delete ? "FCM token deleted successfully" : "FCM token deactivated successfully" }, 200, corsHeaders);
        } catch (dbError) {
          return json({ 
            success: false, 
            error: `Database error: ${String(dbError)}` 
          }, 500, corsHeaders);
        }
      }

      return json({ success: false, error: "Not found" }, 404, corsHeaders);
    } catch (err) {
      return json({ success: false, error: String(err) }, 500, corsHeaders);
    }
  },
};

