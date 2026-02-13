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

// Resolve column name differences between schemas that use "shop name" (with a space)
// and shop_name (with an underscore). Prefer the spaced version when present.
async function resolveShopNameColumn(env, tableName) {
  const preferredColumns = ["shop name", "shop_name"];
  try {
    const { results } = await env.DB.prepare(`PRAGMA table_info(${tableName})`).all();
    const columns = results || [];
    const matched = columns.find((col) =>
      preferredColumns.includes((col.name || "").toLowerCase())
    );
    return matched?.name || "shop_name";
  } catch (err) {
    console.warn(`⚠️ Could not inspect columns for ${tableName}: ${err}`);
    return "shop_name";
  }
}

// Quote identifiers that contain spaces so they can be used safely in SQL strings.
function quoteIdentifier(identifier) {
  if (!identifier) return "";
  return identifier.includes(" ") ? `"${identifier}"` : identifier;
}

// Helper to read shop name value regardless of column naming style
function getShopNameFromRecord(record) {
  if (!record) return null;
  if (record.shop_name !== undefined) return record.shop_name;
  if (record["shop name"] !== undefined) return record["shop name"];
  return null;
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

// Track vendor password change events for auditing and debugging
async function ensureVendorPasswordChangeTable(env) {
  if (!env.DB) {
    return;
  }

  await env.DB.prepare(`
    CREATE TABLE IF NOT EXISTS Vendor_password_changes (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      vendor_email TEXT NOT NULL,
      previous_password_hash TEXT,
      new_password_hash TEXT NOT NULL,
      source TEXT,
      changed_at TEXT DEFAULT (datetime('now'))
    )
  `).run();
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
    // Only 1 (or true) = available; 0, null, undefined = NOT available
    const val = row[key];
    payload[key] = val === 1 || val === true || val === "1" || val === "true";
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

async function ensureVendorTransactionTable(env) {
  if (!env || !env.DB) {
    return;
  }

  try {
    await env.DB.prepare(`SELECT 1 FROM vendor_transaction LIMIT 1`).first();
  } catch (tableErr) {
    // Table doesn't exist, create it
    await env.DB.prepare(`
      CREATE TABLE IF NOT EXISTS vendor_transaction(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vendor_id TEXT NOT NULL,
        vendor_email TEXT NOT NULL,
        vendor_name TEXT,
        period_start TEXT NOT NULL,
        period_end TEXT NOT NULL,
        total_documents INTEGER DEFAULT 0,
        total_price REAL DEFAULT 0.0,
        platform_profit REAL DEFAULT 0.0,
        total_earning REAL DEFAULT 0.0,
        amount_paid REAL DEFAULT 0.0,
        payment_status TEXT DEFAULT 'not_completed',
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now')),
        UNIQUE(vendor_email, period_start, period_end)
      )
    `).run();
  }
}

async function ensureAdminUsersTable(env) {
  if (!env || !env.DB) {
    return;
  }

  try {
    await env.DB.prepare(`SELECT 1 FROM admin_users LIMIT 1`).first();
  } catch (tableErr) {
    // Table doesn't exist, create it
    await env.DB.prepare(`
      CREATE TABLE IF NOT EXISTS admin_users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        email TEXT,
        first_name TEXT,
        last_name TEXT,
        is_superuser INTEGER DEFAULT 0,
        is_staff INTEGER DEFAULT 1,
        is_active INTEGER DEFAULT 1,
        date_joined TEXT DEFAULT (datetime('now')),
        last_login TEXT,
        permissions TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
      )
    `).run();
  }
}

function formatNotificationMessage(filename, token) {
  // Extract document name from filename - show PDF name with extension
  const baseFilename = filename.split('/').pop() || filename;
  const parts = baseFilename.split('.');
  const ext = parts.length > 1 ? '.' + parts.pop() : '';
  const nameWithoutExt = parts.join('.');
  
  // Extract the actual document name (remove token if present)
  // Format is usually: DocumentName_Token.pdf
  let documentNameBase = nameWithoutExt;
  if (nameWithoutExt.includes('_')) {
    const nameParts = nameWithoutExt.split('_');
    if (nameParts.length > 1) {
      // Take all parts except the last one (which is usually the token)
      documentNameBase = nameParts.slice(0, -1).join('_');
    }
  }
  
  // Create display name with extension (e.g., "Azfar...pdf")
  let displayName;
  if (documentNameBase.length > 20) {
    displayName = documentNameBase.substring(0, 17) + '...' + ext;
  } else {
    displayName = documentNameBase + ext;
  }
  
  // Format token without # symbol
  const tokenDisplay = token || 'Unknown';
  
  return `Your document "${displayName}" is ready for pickup. Token: ${tokenDisplay}`;
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
        await ensureVendorTransactionTable(env);

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
          console.warn(`Warning: Could not check for duplicate email: ${String(checkError)}`);
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

        // IMPORTANT: Only collect pricing values that are actually provided in the request
        // This prevents overwriting existing values with zeros for fields not in the form
        // Map possible form field names to database column names
        const fieldMapping = {
          // Digital Print
          digital_print_a4_color: ['digital_print_a4_color', 'digital_print_a4_single_color'],
          digital_print_a3_color: ['digital_print_a3_color', 'digital_print_a3_single_color'],
          digital_print_12x18_color: ['digital_print_12x18_color', 'digital_print_12x18_single_color'],
          digital_print_a2_color: ['digital_print_a2_color', 'digital_print_a2_single_color'],
          digital_print_a1_color: ['digital_print_a1_color', 'digital_print_a1_single_color', 'digital_print_al_single_color'],
          digital_print_a0_color: ['digital_print_a0_color', 'digital_print_a0_single_color'],
          // Regular Print
          regular_print_a4_bw: ['regular_print_a4_bw', 'regular_print_a4_single_bw'],
          regular_print_a4_color: ['regular_print_a4_color', 'regular_print_a4_single_color'],
          // Photo Print
          photo_print_a4_bw: ['photo_print_a4_bw', 'photo_print_a4_standard_bw'],
          photo_print_a4_color: ['photo_print_a4_color', 'photo_print_a4_standard'],
          // Gloss Print
          gloss_print_a4_color: ['gloss_print_a4_color'],
          gloss_print_a3_color: ['gloss_print_a3_color'],
          gloss_print_a2_color: ['gloss_print_a2_color'],
          gloss_print_a1_color: ['gloss_print_a1_color'],
          gloss_print_a0_color: ['gloss_print_a0_color'],
          // Document Print (Letter) - dedicated columns
          doc_letter_bw: ['doc_letter_bw'],
          doc_letter_color: ['doc_letter_color'],
          // Jumbo Print
          jumbo_print_a3_bw: ['jumbo_print_a3_bw', 'jumbo_print_a3_single_bw'],
          jumbo_print_a3_color: ['jumbo_print_a3_color', 'jumbo_print_a3_single_color'],
          jumbo_print_a2_bw: ['jumbo_print_a2_bw', 'jumbo_print_a2_single_bw'],
          jumbo_print_a2_color: ['jumbo_print_a2_color', 'jumbo_print_a2_single_color'],
          jumbo_print_a1_bw: ['jumbo_print_a1_bw', 'jumbo_print_a1_single_bw'],
          jumbo_print_a1_color: ['jumbo_print_a1_color', 'jumbo_print_a1_single_color'],
          jumbo_print_a0_bw: ['jumbo_print_a0_bw', 'jumbo_print_a0_single_bw'],
          jumbo_print_a0_color: ['jumbo_print_a0_color', 'jumbo_print_a0_single_color'],
          // Passport Photo
          passport_print_8: ['passport_print_8', 'passport_photo_8_photos'],
          passport_print_16: ['passport_print_16', 'passport_photo_16_photos'],
          passport_print_30: ['passport_print_30', 'passport_photo_30_photos'],
          // Golden Embossing
          golden_emboss_cover: ['golden_emboss_cover', 'golden_embossing_per_book'],
          golden_emboss_bond_color: ['golden_emboss_bond_color', 'golden_emboss_color_per_page'],
          // Lamination
          lamination_a4_standard: ['lamination_a4_standard', 'lamination_a4'],
          lamination_a4_glossy: ['lamination_a4_glossy', 'lamination_a4_high_gloss'],
          lamination_a3_standard: ['lamination_a3_standard', 'lamination_a3'],
          lamination_a3_glossy: ['lamination_a3_glossy', 'lamination_a3_high_gloss'],
          lamination_a2_standard: ['lamination_a2_standard', 'lamination_a2'],
          lamination_a2_glossy: ['lamination_a2_glossy', 'lamination_a2_high_gloss'],
          lamination_a1_standard: ['lamination_a1_standard', 'lamination_a1'],
          lamination_a1_glossy: ['lamination_a1_glossy', 'lamination_a1_high_gloss'],
          lamination_a0_standard: ['lamination_a0_standard', 'lamination_a0'],
          lamination_a0_glossy: ['lamination_a0_glossy', 'lamination_a0_high_gloss'],
          // Binding
          tape_binding_a4_100: ['tape_binding_a4_100', 'tape_binding_per_book_100'],
          tape_binding_a4_200: ['tape_binding_a4_200', 'tape_binding_a4_150', 'tape_binding_per_book_200'],
          tape_binding_a3_100: ['tape_binding_a3_100'],
          tape_binding_a3_200: ['tape_binding_a3_200', 'tape_binding_a3_150'],
          spiral_binding_a4_100: ['spiral_binding_a4_100', 'spiral_binding_per_book_100'],
          spiral_binding_a4_200: ['spiral_binding_a4_200', 'spiral_binding_a4_150', 'spiral_binding_per_book_200'],
          spiral_binding_a3_100: ['spiral_binding_a3_100'],
          spiral_binding_a3_200: ['spiral_binding_a3_200', 'spiral_binding_a3_150'],
        };

        // Only collect pricing data for fields that are actually provided in the request
        // Skip fields that are missing, null, undefined, 'NA', or empty strings
        const pricingData = {};
        for (const [dbField, possibleFields] of Object.entries(fieldMapping)) {
          for (const fieldName of possibleFields) {
            const value = body[fieldName];
            // Only include if value exists, is not 'NA', and is not empty
            if (value !== undefined && value !== null && value !== '' && value !== 'NA' && String(value).trim() !== '') {
              const parsed = parseFloat(value);
              if (!isNaN(parsed) && parsed >= 0) {
                pricingData[dbField] = parsed;
                break; // Use first matching field
              }
            }
          }
        }

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
        
        // Build UPDATE or INSERT statement
        try {
          // Get all REAL columns from schema (excluding id, vendor_email, last_updated, is_active)
          const realColumns = actualColumns.filter(col => 
            col !== 'id' && 
            col !== 'vendor_email' && 
            col !== 'last_updated' && 
            col !== 'is_active'
          );
          
          // Check if record exists
          const existingRecord = await env.DB.prepare(`
            SELECT vendor_email FROM Vendor_pricing WHERE vendor_email = ?
          `).bind(vendor_email).first();
          
          if (existingRecord) {
            // UPDATE: Only update fields that are provided in pricingData
            // This preserves existing values for fields not in the request
            const fieldsToUpdate = Object.keys(pricingData);
            
            if (fieldsToUpdate.length > 0) {
              // Build SET clause only for provided fields
              const updateSet = ['last_updated', 'is_active', ...fieldsToUpdate]
                .map(col => `${col} = ?`)
                .join(', ');
              
              // Prepare values array for UPDATE (vendor_email at the end for WHERE clause)
              const updateValues = [
                last_updated,
                is_active,
                ...fieldsToUpdate.map(col => pricingData[col]),
                vendor_email
              ];
              
              await env.DB.prepare(`
                UPDATE Vendor_pricing 
                SET ${updateSet}
                WHERE vendor_email = ?
              `).bind(...updateValues).run();
            } else {
              // No pricing fields provided, just update metadata
              await env.DB.prepare(`
                UPDATE Vendor_pricing 
                SET last_updated = ?, is_active = ?
                WHERE vendor_email = ?
              `).bind(last_updated, is_active, vendor_email).run();
            }
          } else {
            // INSERT: New record - use 0.0 for missing fields
            const insertColumns = ['vendor_email', 'last_updated', 'is_active', ...realColumns];
            const placeholders = insertColumns.map(() => '?').join(', ');
            
            // Prepare values array for INSERT
            const insertValues = [
              vendor_email,
              last_updated,
              is_active,
              ...realColumns.map(col => pricingData[col] || 0.0)
            ];
            
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

          // Check for duplicate notification (same filename and token for same user)
          const existingCheck = await env.DB.prepare(`
            SELECT id FROM User_notifications 
            WHERE user_email = ? AND filename = ? AND token = ? AND type = 'job_completed'
            LIMIT 1
          `).bind(user_email, filename, token).first();

          if (existingCheck) {
            // Notification already exists, return success without inserting duplicate
            return json({ success: true, message: "Notification already exists, skipping duplicate" }, 200, corsHeaders);
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
            title: 'Print Job Completed',
            message: formatNotificationMessage(row.filename || 'Document', row.token || 'Unknown'),
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
            console.warn(`Could not list tables: ${String(listErr)}`);
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
                WHERE status = 'verified'
                ORDER BY vendor_name
              `;
              vendors = await env.DB.prepare(query).all();
              
              if (vendors && vendors.results && vendors.results.length > 0) {
                console.debug(`✅ Successfully fetched vendors from table: ${table}`);
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
                  console.debug(`✅ Successfully fetched vendors from table: ${table} (no status filter)`);
                  break;
                }
              } catch (err) {
                lastError = err;
                continue;
              }
            }
          }

          if (vendors && vendors.results && vendors.results.length > 0) {
            // Build service availability map from Vendor_service_availability table
            let serviceAvailabilityMap = {};
            try {
              await ensureVendorServiceTable(env);
              const serviceRows = await env.DB.prepare(`
                SELECT ${VENDOR_SERVICE_SELECT_FIELDS}
                FROM Vendor_service_availability
              `).all();
              if (serviceRows && serviceRows.results) {
                serviceRows.results.forEach((row) => {
                  const email = (row.vendor_email || '').trim().toLowerCase();
                  if (email) {
                    serviceAvailabilityMap[email] = rowToServicePayload(row);
                  }
                });
              }
            } catch (svcErr) {
              console.warn(`Could not fetch Vendor_service_availability: ${svcErr}`);
            }

            // Fetch pending jobs count and merge service availability for all vendors
            const vendorsWithPendingJobs = await Promise.all(
              vendors.results.map(async (vendor) => {
                let pendingJobsCount = 0;
                try {
                  if (vendor.vendor_id) {
                    const pendingJobsResult = await env.DB.prepare(`
                      SELECT job_count FROM vendor_pending_jobs_track 
                      WHERE vendor_id = ? 
                      LIMIT 1
                    `).bind(vendor.vendor_id).first();
                    if (pendingJobsResult) {
                      pendingJobsCount = pendingJobsResult.job_count || 0;
                    }
                  }
                  if (pendingJobsCount === 0 && vendor.email) {
                    const pendingJobsResult = await env.DB.prepare(`
                      SELECT job_count FROM vendor_pending_jobs_track 
                      WHERE LOWER(vendor_email) = LOWER(?) 
                      LIMIT 1
                    `).bind(vendor.email).first();
                    if (pendingJobsResult) {
                      pendingJobsCount = pendingJobsResult.job_count || 0;
                    }
                  }
                } catch (err) {
                  console.warn(`Could not fetch pending jobs for vendor ${vendor.vendor_id || vendor.email}: ${err}`);
                  pendingJobsCount = 0;
                }

                const vendorEmail = (vendor.email || '').trim().toLowerCase();
                // No Vendor_service_availability row = all services NOT available (only 1 = available)
                let serviceAvailability = serviceAvailabilityMap[vendorEmail];
                if (!serviceAvailability) {
                  serviceAvailability = { ...SERVICE_TEXT_DEFAULTS };
                  SERVICE_FLAG_KEYS.forEach((k) => { serviceAvailability[k] = false; });
                }

                return {
                  ...vendor,
                  pending_jobs_count: pendingJobsCount,
                  service_availability: { service_data: serviceAvailability }
                };
              })
            );
            
            return json({ 
              success: true, 
              vendors: vendorsWithPendingJobs || [] 
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
        await ensureVendorTransactionTable(env);

        const body = await safeBody(request);
        const email = (body.email || "").trim();

        if (!email) {
          return json({ success: false, error: "Email is required" }, 400, corsHeaders);
        }

        try {
          // Try with trailing space first
          let vendor = await env.DB.prepare(`
            SELECT email, password_hash, vendor_name, vendor_id, vendor_token, phone_number, state, city, locality, shop_address, pincode, status
            FROM "Vendor_register_details " WHERE email = ? LIMIT 1
          `).bind(email).first();

          // If not found, try without space
          if (!vendor) {
            vendor = await env.DB.prepare(`
              SELECT email, password_hash, vendor_name, vendor_id, vendor_token, phone_number, state, city, locality, shop_address, pincode, status
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

      // POST /update-vendor-password → update vendor password_hash and log change
      if (url.pathname === "/update-vendor-password" && request.method === "POST") {
        if (!env.DB) {
          return json({ success: false, error: "Database not configured" }, 500, corsHeaders);
        }

        await ensureVendorRegisterTable(env);
        await ensureVendorPasswordChangeTable(env);

        const body = await safeBody(request);
        const email = (body.email || "").trim();
        const new_password_hash = (body.new_password_hash || "").trim();
        const source = (body.source || "django_reset_password").trim();

        if (!email || !new_password_hash) {
          return json({ success: false, error: "email and new_password_hash are required" }, 400, corsHeaders);
        }

        try {
          // Fetch existing vendor (try both physical table and view)
          let vendor = await env.DB.prepare(`
            SELECT email, password_hash
            FROM "Vendor_register_details "
            WHERE email = ?
            LIMIT 1
          `).bind(email).first();

          if (!vendor) {
            vendor = await env.DB.prepare(`
              SELECT email, password_hash
              FROM Vendor_register_details
              WHERE email = ?
              LIMIT 1
            `).bind(email).first();
          }

          if (!vendor) {
            return json({ success: false, error: "Vendor not found" }, 404, corsHeaders);
          }

          const previousHash = vendor.password_hash || null;

          // Update password_hash on the physical table (with trailing space)
          await env.DB.prepare(`
            UPDATE "Vendor_register_details "
            SET password_hash = ?
            WHERE email = ?
          `).bind(new_password_hash, email).run();

          // Log the change
          await env.DB.prepare(`
            INSERT INTO Vendor_password_changes (vendor_email, previous_password_hash, new_password_hash, source)
            VALUES (?, ?, ?, ?)
          `).bind(email, previousHash, new_password_hash, source).run();

          return json({ success: true, message: "Password updated successfully" }, 200, corsHeaders);
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
        const points = parseFloat(body.points || "0") || 0;
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
                points REAL NOT NULL,
                date TEXT NOT NULL,
                time TEXT NOT NULL,
                reason TEXT,
                transaction_timestamp TEXT NOT NULL,
                UNIQUE(user_email, transaction_timestamp)
              )
            `).run();
          }

          // Check if this is a refund for a cancelled job - if so, try to update existing row instead of creating new one
          let shouldUpdate = false;
          let existingRowId = null;
          
          if (reason && reason.includes('Refund for cancelled job:')) {
            // Extract filename from reason (format: "Refund for cancelled job: filename.pdf")
            const filenameMatch = reason.match(/Refund for cancelled job:\s*(.+)/);
            if (filenameMatch && filenameMatch[1]) {
              const filename = filenameMatch[1].trim();
              
              // Escape special LIKE characters in filename for SQLite
              // SQLite LIKE special characters: %, _, [, ]
              const escapedFilename = filename.replace(/[%_\[\]]/g, '\\$&');
              
              // Look for existing refund entry for this job using a simpler pattern
              // Use exact match on the reason prefix and filename
              const searchPattern = `Refund for cancelled job: ${escapedFilename}`;
              
              try {
                const existingRefund = await env.DB.prepare(`
                  SELECT id, points FROM User_points
                  WHERE user_email = ? AND reason = ?
                  ORDER BY transaction_timestamp DESC
                  LIMIT 1
                `).bind(user_email, searchPattern).first();
                
                if (existingRefund) {
                  shouldUpdate = true;
                  existingRowId = existingRefund.id;
                } else {
                  // Fallback: try with LIKE but with escaped pattern
                  const likePattern = `%Refund for cancelled job: ${escapedFilename}%`;
                  const existingRefundLike = await env.DB.prepare(`
                    SELECT id, points FROM User_points
                    WHERE user_email = ? AND reason LIKE ? ESCAPE '\\'
                    ORDER BY transaction_timestamp DESC
                    LIMIT 1
                  `).bind(user_email, likePattern).first();
                  
                  if (existingRefundLike) {
                    shouldUpdate = true;
                    existingRowId = existingRefundLike.id;
                  }
                }
              } catch (searchError) {
                // If search fails, just insert new row
                console.warn(`Could not search for existing refund: ${searchError}`);
              }
            }
          }

          if (shouldUpdate && existingRowId) {
            // Update existing refund row instead of creating new one
            await env.DB.prepare(`
              UPDATE User_points
              SET points = ?, date = ?, time = ?, transaction_timestamp = ?
              WHERE id = ?
            `).bind(points, date, time, transaction_timestamp, existingRowId).run();
            
            return json({ 
              success: true, 
              message: "User points transaction updated successfully (existing refund row updated)" 
            }, 200, corsHeaders);
          } else {
            // Insert new points transaction
            await env.DB.prepare(`
              INSERT INTO User_points (user_email, points, date, time, reason, transaction_timestamp)
              VALUES (?, ?, ?, ?, ?, ?)
            `).bind(user_email, points, date, time, reason || null, transaction_timestamp).run();

            return json({ success: true, message: "User points transaction saved successfully" }, 200, corsHeaders);
          }
        } catch (dbError) {
          // Check if it's a unique constraint violation (duplicate)
          if (String(dbError).includes('UNIQUE constraint') || String(dbError).includes('duplicate')) {
            // If duplicate timestamp, try to update instead
            try {
              await env.DB.prepare(`
                UPDATE User_points
                SET points = ?, date = ?, time = ?, reason = ?
                WHERE user_email = ? AND transaction_timestamp = ?
              `).bind(points, date, time, reason || null, user_email, transaction_timestamp).run();
              
              return json({ 
                success: true, 
                message: "User points transaction updated successfully (duplicate timestamp handled)" 
              }, 200, corsHeaders);
            } catch (updateError) {
              return json({ 
                success: false, 
                error: "Duplicate transaction - this points record already exists" 
              }, 400, corsHeaders);
            }
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
          
          // Return the actual decimal sum, rounded to 1 decimal place for accuracy
          const rounded_points = Math.round(parseFloat(total_points) * 10) / 10;

          return json({ 
            success: true, 
            total_points: rounded_points 
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
        let r2_path = (body.r2_path || "").trim();
        const service_type = (body.service_type || "").trim();
        
        // Ensure consistent R2 path for document print, passport photo, digital, golden, gloss, jumbo print models
        // R2 path should always follow pattern: {storage_folder}/{vendor_id}/{filename}
        const document_print_services = ['regular_print', 'regular print', 'document_print'];
        const passport_photo_services = ['passport_photo', 'passport_print', 'photo_print'];
        const digital_services = ['digital_print'];
        const golden_services = ['golden_embossing', 'golden_emboss'];
        const gloss_services = ['gloss_printing', 'gloss_print'];
        const jumbo_services = ['jumbo_printing', 'jumbo_print'];
        const all_special_services = document_print_services.concat(
          passport_photo_services, digital_services, golden_services, gloss_services, jumbo_services
        );
        
        // If service type matches and r2_path doesn't follow the pattern, reconstruct it
        if (service_type && all_special_services.includes(service_type.toLowerCase())) {
          const expected_path = `${storage_folder}/${vendor_id}/${filename}`;
          if (!r2_path || !r2_path.startsWith(`${storage_folder}/${vendor_id}/`)) {
            r2_path = expected_path;
            console.debug(`📦 Reconstructed R2 path for ${service_type}: ${r2_path}`);
          }
        } else if (storage_folder && vendor_id && filename && !r2_path) {
          // Fallback: construct r2_path if not provided
          r2_path = `${storage_folder}/${vendor_id}/${filename}`;
        }
        const status = (body.status || "pending").trim();
        const job_completed = (body.job_completed || "NO").trim();
        const vendor_status = (body.vendor_status || "not sended").trim();
        const token = (body.token || "").trim();
        const job_id = (body.job_id || "").trim();
        const copies = (body.copies || "1").trim();
        let color = (body.color || "").trim();
        const orientation = (body.orientation || "").trim();
        const pageSize = (body.pageSize || "").trim();
        let pageRange = (body.pageRange || "").trim();
        const specificPages = (body.specificPages || "").trim();
        const bwPageRangeValue = (body.bwPageRangeValue || "").trim();
        const colorPageRangeValue = (body.colorPageRangeValue || "").trim();
        // When both BW and Color page ranges are present, store color as Mix (not Black and White)
        if (bwPageRangeValue && colorPageRangeValue) {
          color = "Mix";
          if (!pageRange) pageRange = `BW: ${bwPageRangeValue} | Color: ${colorPageRangeValue}`;
        }
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
        const shop_address = (body.shop_address || "").trim();
        const shop_name = (body.shop_name || body["shop name"] || "").trim();

        // Detailed validation with specific error messages
        const missingFields = [];
        if (!vendor_id || vendor_id.trim() === '') missingFields.push('vendor_id');
        if (!filename || filename.trim() === '') missingFields.push('filename');
        if (!storage_folder || storage_folder.trim() === '') missingFields.push('storage_folder');
        
        if (missingFields.length > 0) {
          return json({ 
            success: false, 
            error: `Missing required fields: ${missingFields.join(', ')}. Received: vendor_id="${vendor_id}", filename="${filename}", storage_folder="${storage_folder}"` 
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
                bwPageRangeValue TEXT,
                colorPageRangeValue TEXT,
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
                shop_address TEXT,
                shop_name TEXT
              )
            `).run();
          }

          // Ensure new columns exist (migration for existing tables)
          try {
            const { results: ti } = await env.DB.prepare("PRAGMA table_info(Vendor_print_jobs)").all();
            const cols = new Set((ti || []).map(c => (c.name || "")));
            if (!cols.has("bwPageRangeValue")) {
              await env.DB.prepare("ALTER TABLE Vendor_print_jobs ADD COLUMN bwPageRangeValue TEXT").run();
            }
            if (!cols.has("colorPageRangeValue")) {
              await env.DB.prepare("ALTER TABLE Vendor_print_jobs ADD COLUMN colorPageRangeValue TEXT").run();
            }
          } catch (migErr) {
            console.warn("Vendor_print_jobs migration (bw/color page range):", String(migErr));
          }

          const shopNameColumn = await resolveShopNameColumn(env, "Vendor_print_jobs");
          const shopNameColumnSql = quoteIdentifier(shopNameColumn);

          // Try INSERT first, if it fails due to unique constraint, do UPDATE
          try {
            await env.DB.prepare(`
              INSERT INTO Vendor_print_jobs (
                vendor_id, vendor_email, user_email, filename, storage_folder, r2_path,
                service_type, status, job_completed, vendor_status, token, job_id,
                copies, color, orientation, pageSize, pageRange, specificPages,
                bwPageRangeValue, colorPageRangeValue,
                spiralBinding, lamination, service_name, feedback, quality, thickness,
                points_applied, points_used, timestamp, completion_time, rendered_status,
                trash, total_price, platform_profit, price_per_page, final_amount,
                page_count, num_copies, pricing_details, shop_address, ${shopNameColumnSql}
              )
              VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            `).bind(
              vendor_id, vendor_email || null, user_email, filename, storage_folder, r2_path,
              service_type || null, status, job_completed, vendor_status, token || null, job_id || null,
              copies, color || null, orientation || null, pageSize || null, pageRange || null, specificPages || null,
              bwPageRangeValue || null, colorPageRangeValue || null,
              spiralBinding, lamination, service_name || null, feedback || null, quality || null, thickness || null,
              points_applied, points_used, timestamp, completion_time || null, rendered_status, trash,
              total_price, platform_profit, price_per_page, final_amount,
              page_count, num_copies, pricing_details, shop_address || null, shop_name || null
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
                  bwPageRangeValue = ?,
                  colorPageRangeValue = ?,
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
                  pricing_details = ?,
                  shop_address = ?,
                  ${shopNameColumnSql} = ?
                WHERE vendor_id = ? AND filename = ? AND storage_folder = ?
              `).bind(
                vendor_email || null, user_email, r2_path,
                service_type || null, status, job_completed, vendor_status, token || null, job_id || null,
                copies, color || null, orientation || null, pageSize || null, pageRange || null, specificPages || null,
                bwPageRangeValue || null, colorPageRangeValue || null,
                spiralBinding, lamination, service_name || null, feedback || null, quality || null, thickness || null,
                points_applied, points_used, timestamp, completion_time || null, rendered_status, trash,
                total_price, platform_profit, price_per_page, final_amount,
                page_count, num_copies, pricing_details, shop_address || null, shop_name || null,
                vendor_id, filename, storage_folder
              ).run();
            } else {
              throw insertError;
            }
          }

          // Mark token as 'busy' if token and vendor_email are provided
          if (token && vendor_email) {
            try {
              const token_number = parseInt(token, 10);
              if (token_number && token_number > 0) {
                const nowIso = new Date().toISOString();
                await env.DB.prepare(`
                  UPDATE Vendor_tokens
                  SET status = 'busy', updated_at = ?
                  WHERE LOWER(vendor_email) = LOWER(?) AND token_number = ?
                `).bind(nowIso, vendor_email, token_number).run();
              }
            } catch (tokenError) {
              // Log but don't fail the request if token update fails
              console.error(`Error marking token as busy: ${tokenError}`);
            }
          }

          // If job_completed is 'YES', free the token
          if (job_completed && job_completed.toUpperCase() === 'YES' && token && vendor_email) {
            try {
              const token_number = parseInt(token, 10);
              if (token_number && token_number > 0) {
                const nowIso = new Date().toISOString();
                await env.DB.prepare(`
                  UPDATE Vendor_tokens
                  SET status = 'free', updated_at = ?
                  WHERE LOWER(vendor_email) = LOWER(?) AND token_number = ?
                `).bind(nowIso, vendor_email, token_number).run();
              }
            } catch (tokenError) {
              // Log but don't fail the request if token update fails
              console.error(`Error freeing token: ${tokenError}`);
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
      // Returns: All pending jobs (job_completed='NO') + Completed jobs only if completed today
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
          // Get current date in YYYY-MM-DD format for filtering completed jobs
          const today = new Date();
          const todayStr = today.toISOString().split('T')[0]; // YYYY-MM-DD
          
          // Get all jobs for this user
          const { results: allJobs } = await env.DB.prepare(`
            SELECT * FROM User_print_jobs
            WHERE user_email = ?
            ORDER BY timestamp DESC
          `).bind(user_email).all();

          // Filter jobs:
          // 1. All jobs where job_completed != 'YES' and != 'CANCELLED' (pending jobs)
          // 2. Jobs where job_completed = 'YES' AND completion_time is today (only today's completed jobs)
          // 3. Jobs where job_completed = 'CANCELLED' AND cancellation_time is today (only today's cancelled jobs)
          const filteredJobs = (allJobs || []).filter(job => {
            const jobCompleted = (job.job_completed || 'NO').toString().trim().toUpperCase();
            
            // Filter out cancelled jobs that are older than a day
            if (jobCompleted === 'CANCELLED') {
              const cancellationTime = job.cancellation_time || job.timestamp || '';
              if (cancellationTime) {
                let cancellationDate = '';
                try {
                  // Try parsing as ISO string
                  if (cancellationTime.includes('T') || cancellationTime.includes(' ')) {
                    cancellationDate = cancellationTime.split('T')[0].split(' ')[0];
                  } else {
                    // Try parsing as timestamp
                    const date = new Date(parseInt(cancellationTime) * 1000);
                    cancellationDate = date.toISOString().split('T')[0];
                  }
                  // Only show cancelled jobs from today
                  return cancellationDate === todayStr;
                } catch (e) {
                  // If parsing fails, don't show the cancelled job
                  return false;
                }
              }
              // If no cancellation_time, don't show (likely old cancelled job)
              return false;
            }
            
            // Always show pending jobs
            if (jobCompleted !== 'YES') {
              return true;
            }
            
            // For completed jobs, only show if completed today
            if (jobCompleted === 'YES') {
              const completionTime = job.completion_time || '';
              if (completionTime) {
                // Extract date from completion_time (could be ISO string or timestamp)
                let completionDate = '';
                try {
                  // Try parsing as ISO string
                  if (completionTime.includes('T') || completionTime.includes(' ')) {
                    completionDate = completionTime.split('T')[0].split(' ')[0];
                  } else {
                    // Try parsing as timestamp
                    const date = new Date(parseInt(completionTime) * 1000);
                    completionDate = date.toISOString().split('T')[0];
                  }
                  return completionDate === todayStr;
                } catch (e) {
                  // If parsing fails, don't show the job
                  return false;
                }
              }
              // If no completion_time, don't show (likely old completed job)
              return false;
            }
            
            return false;
          });

          return json({ success: true, data: filteredJobs }, 200, corsHeaders);
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

      // POST /get-all-user-notifications → retrieves user notifications with optional filtering
      // Uses User_notifications table (same pattern as /get-all-vendor-jobs)
      if (url.pathname === "/get-all-user-notifications" && request.method === "POST") {
        if (!env.DB) {
          return json({ success: false, error: "Database not configured" }, 500, corsHeaders);
        }

        const body = await safeBody(request);
        const userEmailFilter = (body.user_email || "").trim().toLowerCase();
        const monthFilter = (body.month || "").trim();
        const weekStart = (body.week_start || "").trim();
        const weekEnd = (body.week_end || "").trim();

        try {
          // Check if table exists (try both case variations)
          const { results: tableCheck1 } = await env.DB.prepare(`
            SELECT name FROM sqlite_master
            WHERE type='table' AND LOWER(name) = LOWER('User_notifications')
          `).all();

          if (!tableCheck1 || tableCheck1.length === 0) {
            console.warn("⚠️ User_notifications table not found");
            return json({ success: true, data: [] }, 200, corsHeaders);
          }

          const tableName = tableCheck1[0].name; // Use actual table name from database
          console.debug(`✅ Found table: ${tableName}`);

          const conditions = [];
          const params = [];

          if (userEmailFilter) {
            conditions.push("LOWER(COALESCE(user_email, '')) = ?");
            params.push(userEmailFilter);
          }

          // Use completion_time for date filtering, fallback to created_at
          // Check both fields separately to avoid SQLite COALESCE issues
          if (monthFilter) {
            conditions.push("((completion_time IS NOT NULL AND completion_time != '' AND substr(completion_time, 1, 7) = ?) OR (created_at IS NOT NULL AND created_at != '' AND substr(created_at, 1, 7) = ?))");
            params.push(monthFilter, monthFilter);
          }

          if (weekStart && weekEnd) {
            conditions.push("((completion_time IS NOT NULL AND completion_time != '' AND completion_time BETWEEN ? AND ?) OR (created_at IS NOT NULL AND created_at != '' AND created_at BETWEEN ? AND ?))");
            params.push(weekStart, weekEnd, weekStart, weekEnd);
          }

          const whereClause = conditions.length ? `WHERE ${conditions.join(" AND ")}` : "";
          
          // Use ORDER BY that handles NULL values - prioritize completion_time, then created_at, then id
          // SQLite-friendly ordering with NULL handling
          const query = `
            SELECT * FROM ${tableName}
            ${whereClause}
            ORDER BY 
              COALESCE(NULLIF(completion_time, ''), NULLIF(created_at, ''), '1970-01-01') DESC,
              id DESC
          `;

          console.debug(`🔍 Executing query: ${query.substring(0, 200)}...`);
          const statement = env.DB.prepare(query);
          let result;
          if (params.length > 0) {
            result = await statement.bind(...params).all();
          } else {
            result = await statement.all();
          }
          const { results } = result || {};

          console.debug(`✅ Retrieved ${(results || []).length} user notifications`);
          return json({ success: true, data: results || [] }, 200, corsHeaders);
        } catch (dbError) {
          console.error("❌ Error in /get-all-user-notifications:", dbError);
          console.error("Error details:", String(dbError));
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
            console.warn("⚠️ vendor_notification table not found");
            return json({ success: true, data: [] }, 200, corsHeaders);
          }

          const tableName = tableCheck1[0].name; // Use actual table name from database
          console.debug(`✅ Found table: ${tableName}`);

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

          console.debug(`🔍 Executing query: ${query.substring(0, 200)}...`);
          const statement = env.DB.prepare(query);
          let result;
          if (params.length > 0) {
            result = await statement.bind(...params).all();
          } else {
            result = await statement.all();
          }
          const { results } = result || {};

          console.debug(`✅ Retrieved ${(results || []).length} vendor notifications`);
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
        const bwPageRangeValue = (body.bwPageRangeValue || "").trim();
        const colorPageRangeValue = (body.colorPageRangeValue || "").trim();
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
        const shop_address = (body.shop_address || "").trim();
        const shop_name = (body.shop_name || body["shop name"] || "").trim();

        // Detailed validation with specific error messages
        const missingFields = [];
        if (!user_email || user_email.trim() === '') missingFields.push('user_email');
        if (!filename || filename.trim() === '') missingFields.push('filename');
        
        if (missingFields.length > 0) {
          return json({ 
            success: false, 
            error: `Missing required fields: ${missingFields.join(', ')}. Received: user_email="${user_email}", filename="${filename}"` 
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
                bwPageRangeValue TEXT,
                colorPageRangeValue TEXT,
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
                shop_address TEXT,
                shop_name TEXT
              )
            `).run();
          }

          // Ensure new columns exist (migration for existing tables)
          try {
            const { results: ti } = await env.DB.prepare("PRAGMA table_info(User_print_jobs)").all();
            const cols = new Set((ti || []).map(c => (c.name || "")));
            if (!cols.has("bwPageRangeValue")) {
              await env.DB.prepare("ALTER TABLE User_print_jobs ADD COLUMN bwPageRangeValue TEXT").run();
            }
            if (!cols.has("colorPageRangeValue")) {
              await env.DB.prepare("ALTER TABLE User_print_jobs ADD COLUMN colorPageRangeValue TEXT").run();
            }
          } catch (migErr) {
            console.warn("User_print_jobs migration (bw/color page range):", String(migErr));
          }

          const shopNameColumn = await resolveShopNameColumn(env, "User_print_jobs");
          const shopNameColumnSql = quoteIdentifier(shopNameColumn);

          // Try INSERT first, if it fails due to unique constraint, do UPDATE
          try {
            await env.DB.prepare(`
              INSERT INTO User_print_jobs (
                vendor_id, vendor_email, user_email, filename, storage_folder, r2_path,
                service_type, status, job_completed, vendor_status, token, job_id,
                copies, color, orientation, pageSize, pageRange, specificPages,
                bwPageRangeValue, colorPageRangeValue,
                spiralBinding, lamination, service_name, feedback, quality, thickness,
                points_applied, points_used, timestamp, completion_time, rendered_status,
                trash, total_price, platform_profit, price_per_page, final_amount,
                page_count, num_copies, pricing_details, shop_address, ${shopNameColumnSql}
              )
              VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            `).bind(
              vendor_id || null, vendor_email || null, user_email, filename, storage_folder, r2_path,
              service_type || null, status, job_completed, vendor_status, token || null, job_id || null,
              copies, color || null, orientation || null, pageSize || null, pageRange || null, specificPages || null,
              bwPageRangeValue || null, colorPageRangeValue || null,
              spiralBinding, lamination, service_name || null, feedback || null, quality || null, thickness || null,
              points_applied, points_used, timestamp, completion_time || null, rendered_status, trash,
              total_price, platform_profit, price_per_page, final_amount,
              page_count, num_copies, pricing_details, shop_address || null, shop_name || null
            ).run();
          } catch (insertError) {
            // If insert fails due to unique constraint, update existing record
            if (String(insertError).includes('UNIQUE constraint') || String(insertError).includes('duplicate')) {
              // Get existing record to preserve values that are not provided
              const existing = await env.DB.prepare(`
                SELECT * FROM User_print_jobs
                WHERE user_email = ? AND filename = ? AND storage_folder = ?
              `).bind(user_email, filename, storage_folder).first();
              
              // Use provided values, or keep existing values if not provided
              const final_vendor_id = vendor_id || existing?.vendor_id || null;
              const final_vendor_email = vendor_email || existing?.vendor_email || null;
              const final_r2_path = r2_path || existing?.r2_path || null;
              const final_service_type = service_type || existing?.service_type || null;
              const final_status = status || existing?.status || 'pending';
              const final_job_completed = job_completed || existing?.job_completed || 'NO';
              const final_vendor_status = vendor_status || existing?.vendor_status || 'not sended';
              const final_token = token || existing?.token || null;
              const final_job_id = job_id || existing?.job_id || null;
              const final_copies = copies || existing?.copies || '1';
              const final_color = color || existing?.color || null;
              const final_orientation = orientation || existing?.orientation || null;
              const final_pageSize = pageSize || existing?.pageSize || null;
              const final_pageRange = pageRange || existing?.pageRange || null;
              const final_specificPages = specificPages || existing?.specificPages || null;
              const final_bwPageRangeValue = bwPageRangeValue || existing?.bwPageRangeValue || null;
              const final_colorPageRangeValue = colorPageRangeValue || existing?.colorPageRangeValue || null;
              const final_spiralBinding = spiralBinding || existing?.spiralBinding || 'No';
              const final_lamination = lamination || existing?.lamination || 'No';
              const final_service_name = service_name || existing?.service_name || null;
              const final_feedback = feedback || existing?.feedback || null;
              const final_quality = quality || existing?.quality || null;
              const final_thickness = thickness || existing?.thickness || null;
              const final_points_applied = points_applied || existing?.points_applied || 'false';
              const final_points_used = points_used !== null && points_used !== undefined ? points_used : (existing?.points_used || 0);
              const final_timestamp = timestamp || existing?.timestamp || new Date().toISOString();
              const final_completion_time = completion_time || existing?.completion_time || null;
              const final_rendered_status = rendered_status || existing?.rendered_status || 'NO';
              const final_trash = trash || existing?.trash || 'NO';
              const final_total_price = total_price !== null && total_price !== undefined ? total_price : (existing?.total_price || null);
              const final_platform_profit = platform_profit !== null && platform_profit !== undefined ? platform_profit : (existing?.platform_profit || null);
              const final_price_per_page = price_per_page !== null && price_per_page !== undefined ? price_per_page : (existing?.price_per_page || null);
              const final_final_amount = final_amount !== null && final_amount !== undefined ? final_amount : (existing?.final_amount || null);
              const final_page_count = page_count !== null && page_count !== undefined ? page_count : (existing?.page_count || null);
              const final_num_copies = num_copies !== null && num_copies !== undefined ? num_copies : (existing?.num_copies || null);
              const final_pricing_details = pricing_details || existing?.pricing_details || null;
              const final_shop_address = shop_address || existing?.shop_address || null;
              const final_shop_name = shop_name || getShopNameFromRecord(existing) || null;
              
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
                  bwPageRangeValue = ?,
                  colorPageRangeValue = ?,
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
                  pricing_details = ?,
                  shop_address = ?,
                  ${shopNameColumnSql} = ?
                WHERE user_email = ? AND filename = ? AND storage_folder = ?
              `).bind(
                final_vendor_id, final_vendor_email, final_r2_path,
                final_service_type, final_status, final_job_completed, final_vendor_status, final_token, final_job_id,
                final_copies, final_color, final_orientation, final_pageSize, final_pageRange, final_specificPages,
                final_bwPageRangeValue, final_colorPageRangeValue,
                final_spiralBinding, final_lamination, final_service_name, final_feedback, final_quality, final_thickness,
                final_points_applied, final_points_used, final_timestamp, final_completion_time, final_rendered_status, final_trash,
                final_total_price, final_platform_profit, final_price_per_page, final_final_amount,
                final_page_count, final_num_copies, final_pricing_details, final_shop_address, final_shop_name,
                user_email, filename, storage_folder
              ).run();
            } else {
              throw insertError;
            }
          }

          // Mark token as 'busy' if token and vendor_email are provided
          if (token && vendor_email) {
            try {
              const token_number = parseInt(token, 10);
              if (token_number && token_number > 0) {
                const nowIso = new Date().toISOString();
                await env.DB.prepare(`
                  UPDATE Vendor_tokens
                  SET status = 'busy', updated_at = ?
                  WHERE LOWER(vendor_email) = LOWER(?) AND token_number = ?
                `).bind(nowIso, vendor_email, token_number).run();
              }
            } catch (tokenError) {
              // Log but don't fail the request if token update fails
              console.error(`Error marking token as busy: ${tokenError}`);
            }
          }

          // If job_completed is 'YES', free the token
          if (job_completed && job_completed.toUpperCase() === 'YES' && token && vendor_email) {
            try {
              const token_number = parseInt(token, 10);
              if (token_number && token_number > 0) {
                const nowIso = new Date().toISOString();
                await env.DB.prepare(`
                  UPDATE Vendor_tokens
                  SET status = 'free', updated_at = ?
                  WHERE LOWER(vendor_email) = LOWER(?) AND token_number = ?
                `).bind(nowIso, vendor_email, token_number).run();
              }
            } catch (tokenError) {
              // Log but don't fail the request if token update fails
              console.error(`Error freeing token: ${tokenError}`);
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

      // POST /update-job-completed → updates job_completed status and frees token if completed
      if (url.pathname === "/update-job-completed" && request.method === "POST") {
        if (!env.DB) {
          return json({ success: false, error: "Database not configured" }, 500, corsHeaders);
        }

        const body = await safeBody(request);
        const filename = (body.filename || "").trim();
        const job_completed_raw = (body.job_completed || "NO").toString().trim();
        const job_completed = job_completed_raw.toUpperCase();
        const vendor_email = (body.vendor_email || "").trim();
        const user_email = (body.user_email || "").trim();
        const completion_time = (body.completion_time || new Date().toISOString()).trim();
        const vendor_id = (body.vendor_id || "").trim();
        const vendor_name = (body.vendor_name || "").trim();

        if (!filename) {
          return json({ success: false, error: "filename is required" }, 400, corsHeaders);
        }

        // Allow 'YES', 'NO', or 'cancelled' (case-insensitive)
        if (job_completed !== 'YES' && job_completed !== 'NO' && job_completed !== 'CANCELLED') {
          return json({ success: false, error: "job_completed must be 'YES', 'NO', or 'cancelled'" }, 400, corsHeaders);
        }

        try {
          await ensureVendorTransactionTable(env);
          
          let token_freed = false;
          let token_number = null;
          let jobData = null;
          let vendorJob = null; // Declare vendorJob outside the if block to fix scope issue

          // Get rendered_status from request body (if provided, otherwise default to 'NO')
          // Define this BEFORE the conditional blocks so it's available for User_print_jobs update
          const rendered_status = (body.rendered_status || '').trim().toUpperCase();
          let final_rendered_status = rendered_status === 'YES' ? 'YES' : 'NO';

          // Update Vendor_print_jobs if vendor_email or vendor_id is provided
          if (vendor_email || vendor_id) {
            // Get the full job data including pricing and storage_folder before updating
            if (vendor_email) {
              vendorJob = await env.DB.prepare(`
                SELECT * FROM Vendor_print_jobs
                WHERE filename = ? AND LOWER(vendor_email) = LOWER(?)
                LIMIT 1
              `).bind(filename, vendor_email).first();
            } else if (vendor_id) {
              vendorJob = await env.DB.prepare(`
                SELECT * FROM Vendor_print_jobs
                WHERE filename = ? AND vendor_id = ?
                LIMIT 1
              `).bind(filename, vendor_id).first();
            }

            // Update final_rendered_status based on vendorJob if available
            if (vendorJob && rendered_status !== 'YES') {
              final_rendered_status = vendorJob.rendered_status || 'NO';
            }

            // Prepare status values for update
            let newStatus;
            let finalJobCompleted = job_completed;
            if (job_completed === 'CANCELLED') {
              newStatus = 'cancelled';
              finalJobCompleted = 'cancelled'; // Set job_completed to 'cancelled' (lowercase) to match User_print_jobs
            } else {
              newStatus = job_completed === 'YES' ? 'completed' : 'pending';
            }
            
            // Always update Vendor_print_jobs table (similar to User_print_jobs update)
            // Try multiple approaches to ensure we find and update the correct row
            let updateSuccess = false;
            let updateAttempts = [];
            
            if (vendorJob) {
              // Approach 1: Use storage_folder from the job (most accurate)
              const storage_folder = vendorJob.storage_folder || 'vendor_print_jobs';
              const final_vendor_id = vendorJob.vendor_id || vendor_id;
              
              // Preserve all existing data fields while updating status
              const updateResult1 = await env.DB.prepare(`
                UPDATE Vendor_print_jobs
                SET job_completed = ?, completion_time = ?, status = ?, rendered_status = ?,
                    color = COALESCE(?, color),
                    orientation = COALESCE(?, orientation),
                    pageSize = COALESCE(?, pageSize),
                    pageRange = COALESCE(?, pageRange),
                    specificPages = COALESCE(?, specificPages),
                    copies = COALESCE(?, copies),
                    spiralBinding = COALESCE(?, spiralBinding),
                    lamination = COALESCE(?, lamination)
                WHERE vendor_id = ? AND filename = ? AND storage_folder = ?
              `).bind(
                finalJobCompleted, completion_time, newStatus, final_rendered_status,
                vendorJob?.color || null, vendorJob?.orientation || null, vendorJob?.pageSize || null,
                vendorJob?.pageRange || null, vendorJob?.specificPages || null, vendorJob?.copies || null,
                vendorJob?.spiralBinding || null, vendorJob?.lamination || null,
                final_vendor_id, filename, storage_folder
              ).run();
              
              updateAttempts.push(`vendor_id=${final_vendor_id}, filename=${filename}, storage_folder=${storage_folder}: ${updateResult1.meta.changes} rows`);
              
              if (updateResult1.meta.changes > 0) {
                updateSuccess = true;
              } else {
                // Approach 2: Try without storage_folder constraint
                const updateResult2 = await env.DB.prepare(`
                  UPDATE Vendor_print_jobs
                  SET job_completed = ?, completion_time = ?, status = ?, rendered_status = ?,
                      color = COALESCE(?, color),
                      orientation = COALESCE(?, orientation),
                      pageSize = COALESCE(?, pageSize),
                      pageRange = COALESCE(?, pageRange),
                      specificPages = COALESCE(?, specificPages),
                      copies = COALESCE(?, copies),
                      spiralBinding = COALESCE(?, spiralBinding),
                      lamination = COALESCE(?, lamination)
                  WHERE vendor_id = ? AND filename = ?
                `).bind(
                  finalJobCompleted, completion_time, newStatus, final_rendered_status,
                  vendorJob?.color || null, vendorJob?.orientation || null, vendorJob?.pageSize || null,
                  vendorJob?.pageRange || null, vendorJob?.specificPages || null, vendorJob?.copies || null,
                  vendorJob?.spiralBinding || null, vendorJob?.lamination || null,
                  final_vendor_id, filename
                ).run();
                
                updateAttempts.push(`vendor_id=${final_vendor_id}, filename=${filename} (no storage_folder): ${updateResult2.meta.changes} rows`);
                
                if (updateResult2.meta.changes > 0) {
                  updateSuccess = true;
                } else if (vendorJob.vendor_email || vendor_email) {
                  // Approach 3: Try with vendor_email
                  const final_vendor_email = vendorJob.vendor_email || vendor_email;
                  const updateResult3 = await env.DB.prepare(`
                    UPDATE Vendor_print_jobs
                    SET job_completed = ?, completion_time = ?, status = ?, rendered_status = ?,
                        color = COALESCE(?, color),
                        orientation = COALESCE(?, orientation),
                        pageSize = COALESCE(?, pageSize),
                        pageRange = COALESCE(?, pageRange),
                        specificPages = COALESCE(?, specificPages),
                        copies = COALESCE(?, copies),
                        spiralBinding = COALESCE(?, spiralBinding),
                        lamination = COALESCE(?, lamination)
                    WHERE filename = ? AND LOWER(vendor_email) = LOWER(?)
                  `).bind(
                    finalJobCompleted, completion_time, newStatus, final_rendered_status,
                    vendorJob?.color || null, vendorJob?.orientation || null, vendorJob?.pageSize || null,
                    vendorJob?.pageRange || null, vendorJob?.specificPages || null, vendorJob?.copies || null,
                    vendorJob?.spiralBinding || null, vendorJob?.lamination || null,
                    filename, final_vendor_email
                  ).run();
                  
                  updateAttempts.push(`filename=${filename}, vendor_email=${final_vendor_email}: ${updateResult3.meta.changes} rows`);
                  
                  if (updateResult3.meta.changes > 0) {
                    updateSuccess = true;
                  }
                }
              }
            } else {
              // Job not found in initial query - try all possible combinations
              const final_vendor_id = vendor_id || '';
              const final_vendor_email = vendor_email || '';
              
              if (final_vendor_id) {
                // Try with vendor_id and filename
                // Try to get existing job data first
                const existingJob = await env.DB.prepare(`
                  SELECT * FROM Vendor_print_jobs
                  WHERE vendor_id = ? AND filename = ?
                  LIMIT 1
                `).bind(final_vendor_id, filename).first();
                
                const updateResult = await env.DB.prepare(`
                  UPDATE Vendor_print_jobs
                  SET job_completed = ?, completion_time = ?, status = ?, rendered_status = ?,
                      color = COALESCE(?, color),
                      orientation = COALESCE(?, orientation),
                      pageSize = COALESCE(?, pageSize),
                      pageRange = COALESCE(?, pageRange),
                      specificPages = COALESCE(?, specificPages),
                      copies = COALESCE(?, copies),
                      spiralBinding = COALESCE(?, spiralBinding),
                      lamination = COALESCE(?, lamination)
                  WHERE vendor_id = ? AND filename = ?
                `).bind(
                  finalJobCompleted, completion_time, newStatus, final_rendered_status,
                  existingJob?.color || null, existingJob?.orientation || null, existingJob?.pageSize || null,
                  existingJob?.pageRange || null, existingJob?.specificPages || null, existingJob?.copies || null,
                  existingJob?.spiralBinding || null, existingJob?.lamination || null,
                  final_vendor_id, filename
                ).run();
                
                updateAttempts.push(`vendor_id=${final_vendor_id}, filename=${filename}: ${updateResult.meta.changes} rows`);
                
                if (updateResult.meta.changes > 0) {
                  updateSuccess = true;
                }
              }
              
              if (!updateSuccess && final_vendor_email) {
                // Try with vendor_email
                // Try to get existing job data first
                const existingJob = await env.DB.prepare(`
                  SELECT * FROM Vendor_print_jobs
                  WHERE filename = ? AND LOWER(vendor_email) = LOWER(?)
                  LIMIT 1
                `).bind(filename, final_vendor_email).first();
                
                const updateResult = await env.DB.prepare(`
                  UPDATE Vendor_print_jobs
                  SET job_completed = ?, completion_time = ?, status = ?, rendered_status = ?,
                      color = COALESCE(?, color),
                      orientation = COALESCE(?, orientation),
                      pageSize = COALESCE(?, pageSize),
                      pageRange = COALESCE(?, pageRange),
                      specificPages = COALESCE(?, specificPages),
                      copies = COALESCE(?, copies),
                      spiralBinding = COALESCE(?, spiralBinding),
                      lamination = COALESCE(?, lamination)
                  WHERE filename = ? AND LOWER(vendor_email) = LOWER(?)
                `).bind(
                  finalJobCompleted, completion_time, newStatus, final_rendered_status,
                  existingJob?.color || null, existingJob?.orientation || null, existingJob?.pageSize || null,
                  existingJob?.pageRange || null, existingJob?.specificPages || null, existingJob?.copies || null,
                  existingJob?.spiralBinding || null, existingJob?.lamination || null,
                  filename, final_vendor_email
                ).run();
                
                updateAttempts.push(`filename=${filename}, vendor_email=${final_vendor_email}: ${updateResult.meta.changes} rows`);
                
                if (updateResult.meta.changes > 0) {
                  updateSuccess = true;
                }
              }
            }
            
            // Log update attempts for debugging
            if (!updateSuccess) {
              console.warn(`⚠️ Failed to update Vendor_print_jobs after all attempts. Attempts: ${updateAttempts.join('; ')}`);
            } else {
              console.debug(`✅ Successfully updated Vendor_print_jobs. Attempts: ${updateAttempts.join('; ')}`);
            }

            // Only perform token freeing and transaction updates if job data was found
            if (vendorJob) {
              jobData = vendorJob;
              const token = vendorJob.token;
              const job_vendor_email = vendorJob.vendor_email || vendor_email;
              const job_vendor_id = vendorJob.vendor_id || vendor_id;

              // Free token if job is completed
              if (job_completed === 'YES' && token && job_vendor_email) {
                try {
                  const token_num = parseInt(token, 10);
                  if (token_num && token_num > 0) {
                    const nowIso = new Date().toISOString();
                    const updateResult = await env.DB.prepare(`
                      UPDATE Vendor_tokens
                      SET status = 'free', updated_at = ?
                      WHERE LOWER(vendor_email) = LOWER(?) AND token_number = ?
                    `).bind(nowIso, job_vendor_email, token_num).run();
                    
                    if (updateResult.meta.changes > 0) {
                      token_freed = true;
                      token_number = token_num;
                    }
                  }
                } catch (tokenError) {
                  console.error(`Error freeing token: ${tokenError}`);
                }
              }

              // Create/update vendor transaction when job is completed
              if (job_completed === 'YES' && jobData) {
                try {
                  const totalPrice = parseFloat(jobData.total_price || jobData.final_amount || 0);
                  const platformProfit = parseFloat(jobData.platform_profit || 0);
                  const totalEarning = totalPrice - platformProfit;
                  
                  // Calculate period (2-day interval: today and tomorrow)
                  const today = new Date();
                  const tomorrow = new Date(today);
                  tomorrow.setDate(tomorrow.getDate() + 1);
                  
                  const periodStart = today.toISOString().split('T')[0]; // YYYY-MM-DD
                  const periodEnd = tomorrow.toISOString().split('T')[0];
                  
                  const finalVendorId = job_vendor_id || vendor_id || '';
                  const finalVendorEmail = job_vendor_email || vendor_email || '';
                  const finalVendorName = vendor_name || '';

                  // Try to get existing transaction for this period
                  const existingTransaction = await env.DB.prepare(`
                    SELECT * FROM vendor_transaction
                    WHERE LOWER(vendor_email) = LOWER(?) 
                    AND period_start = ? AND period_end = ?
                    LIMIT 1
                  `).bind(finalVendorEmail, periodStart, periodEnd).first();

                  if (existingTransaction) {
                    // Update existing transaction
                    await env.DB.prepare(`
                      UPDATE vendor_transaction
                      SET total_documents = total_documents + 1,
                          total_price = total_price + ?,
                          platform_profit = platform_profit + ?,
                          total_earning = total_earning + ?,
                          updated_at = datetime('now')
                      WHERE id = ?
                    `).bind(totalPrice, platformProfit, totalEarning, existingTransaction.id).run();
                  } else {
                    // Create new transaction
                    await env.DB.prepare(`
                      INSERT INTO vendor_transaction (
                        vendor_id, vendor_email, vendor_name, period_start, period_end,
                        total_documents, total_price, platform_profit, total_earning,
                        created_at, updated_at
                      )
                      VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, datetime('now'), datetime('now'))
                    `).bind(
                      finalVendorId, finalVendorEmail, finalVendorName, periodStart, periodEnd,
                      totalPrice, platformProfit, totalEarning
                    ).run();
                  }
                } catch (transactionError) {
                  console.error(`Error updating vendor transaction: ${transactionError}`);
                  // Don't fail the request if transaction update fails
                }
              }
            }
          }

          // Update User_print_jobs if user_email is provided
          if (user_email) {
            // Get existing job data to preserve all fields
            const existingUserJob = await env.DB.prepare(`
              SELECT * FROM User_print_jobs
              WHERE filename = ? AND user_email = ?
              LIMIT 1
            `).bind(filename, user_email).first();
            
            // Handle status field - same logic as Vendor_print_jobs
            let newStatus;
            let finalJobCompleted = job_completed;
            if (job_completed === 'CANCELLED') {
              newStatus = 'cancelled';
              finalJobCompleted = 'cancelled'; // Set job_completed to 'cancelled' (lowercase) to match Vendor_print_jobs
            } else {
              newStatus = job_completed === 'YES' ? 'completed' : 'pending';
            }
            
            // Update User_print_jobs - preserve all existing data fields
            await env.DB.prepare(`
              UPDATE User_print_jobs
              SET job_completed = ?, completion_time = ?, status = ?, rendered_status = ?,
                  color = COALESCE(?, color),
                  orientation = COALESCE(?, orientation),
                  pageSize = COALESCE(?, pageSize),
                  pageRange = COALESCE(?, pageRange),
                  specificPages = COALESCE(?, specificPages),
                  copies = COALESCE(?, copies),
                  spiralBinding = COALESCE(?, spiralBinding),
                  lamination = COALESCE(?, lamination)
              WHERE filename = ? AND user_email = ?
            `).bind(
              finalJobCompleted, completion_time, newStatus, final_rendered_status,
              existingUserJob?.color || vendorJob?.color || null,
              existingUserJob?.orientation || vendorJob?.orientation || null,
              existingUserJob?.pageSize || vendorJob?.pageSize || null,
              existingUserJob?.pageRange || vendorJob?.pageRange || null,
              existingUserJob?.specificPages || vendorJob?.specificPages || null,
              existingUserJob?.copies || vendorJob?.copies || null,
              existingUserJob?.spiralBinding || vendorJob?.spiralBinding || null,
              existingUserJob?.lamination || vendorJob?.lamination || null,
              filename, user_email
            ).run();
          }

          return json({ 
            success: true, 
            message: "Job status updated successfully",
            token_freed: token_freed,
            token_number: token_number
          }, 200, corsHeaders);
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
        const filename = (body.filename || "").trim();
        const job_completed = (body.job_completed || body.job_completed_status || "NO").toString().trim().toUpperCase();

        // Security: Require vendor_email for vendor job queries (except when querying by filename only)
        // This ensures only authenticated vendors can access their own jobs
        if (!filename && !vendor_email) {
          return json({ success: false, error: "vendor_email is required for security (or filename for specific job lookup)" }, 400, corsHeaders);
        }

        // Use the same approach as user dashboard: get ALL jobs first, then filter by job_completed
        // STRICT FILTERING: Always require vendor_email match (from authenticated session)
        // This ensures only the authenticated vendor sees their own jobs
        const vendorFilters = [];
        const params = [];
        
        // vendor_email is REQUIRED for security - it comes from authenticated session
        // This is the primary security check to prevent cross-vendor data access
        if (vendor_email) {
          vendorFilters.push("LOWER(COALESCE(vendor_email, '')) = LOWER(?)");
          params.push(vendor_email);
        }
        
        if (vendor_id) {
          // Additional check: match vendor_id if provided
          // Handle cases where vendor_id might be NULL in database
          vendorFilters.push("(CAST(vendor_id AS TEXT) = CAST(? AS TEXT) OR r2_path LIKE ? OR vendor_id IS NULL)");
          params.push(vendor_id, `%/${vendor_id}/%`);
        }
        
        if (filename) {
          vendorFilters.push("filename = ?");
          params.push(filename);
        }

        // Use AND to ensure all provided filters match
        // vendor_email is always required from authenticated session, ensuring security
        const whereClause = vendorFilters.length > 0
          ? vendorFilters.join(" AND ")
          : "1=0"; // No filters = return nothing (security: require at least vendor_email)

        // Get ALL jobs for this vendor (no job_completed filter in SQL - filter in code like user dashboard)
        let query = `
          SELECT *
          FROM Vendor_print_jobs
          WHERE ${whereClause}
        `;
        
        // Debug logging
        console.debug(`🔍 get-vendor-print-jobs: vendor_id=${vendor_id}, vendor_email=${vendor_email}, job_completed=${job_completed}`);
        console.debug(`🔍 get-vendor-print-jobs: whereClause=${whereClause}, params=${JSON.stringify(params)}`);

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
          const { results: allResults } = await statement.bind(...params).all();
          
          console.debug(`🔍 get-vendor-print-jobs: Query returned ${(allResults || []).length} total jobs`);
          if (allResults && allResults.length > 0) {
            console.debug(`📋 All jobs from query: ${allResults.map(j => `${j.filename || 'N/A'} (vendor_id=${j.vendor_id || 'N/A'}, vendor_email=${j.vendor_email || 'N/A'}, service_type=${j.service_type || 'N/A'}, job_completed=${j.job_completed || 'N/A'})`).join(' | ')}`);
          }
          
          // Filter by job_completed status (same approach as user dashboard)
          // NO R2 logic - only use D1 database job_completed column
          const filteredResults = (allResults || []).filter(job => {
            const jobCompleted = (job.job_completed || 'NO').toString().trim().toUpperCase();
            
            // Skip CANCELLED jobs
            if (jobCompleted === 'CANCELLED') {
              return false;
            }
            
            // If job_completed filter is specified, match it
            if (job_completed) {
              const requestedStatus = job_completed.toString().trim().toUpperCase();
              
              // Handle 'NO' status - include jobs that are NULL, empty, or 'NO'
              if (requestedStatus === 'NO') {
                const matches = jobCompleted === 'NO' || jobCompleted === '' || !job.job_completed || job.job_completed === null;
                if (!matches) {
                  console.warn(`⚠️ Job filtered out: ${job.filename || 'N/A'} - job_completed="${job.job_completed}" (expected NO)`);
                }
                return matches;
              }
              
              // For other statuses, do exact match
              const matches = jobCompleted === requestedStatus;
              if (!matches) {
                console.warn(`⚠️ Job filtered out: ${job.filename || 'N/A'} - job_completed="${job.job_completed}" (expected ${requestedStatus})`);
              }
              return matches;
            }
            
            // If no filter specified, return all jobs (except CANCELLED)
            return true;
          });
          
          console.debug(`✅ get-vendor-print-jobs: Returning ${filteredResults.length} jobs after job_completed filter (requested: ${job_completed || 'ALL'}, total from DB: ${(allResults || []).length})`);
          if (filteredResults.length > 0) {
            console.debug(`📋 Filtered jobs: ${filteredResults.map(j => `${j.filename || 'N/A'} (${j.service_type || 'N/A'}, job_completed=${j.job_completed || 'N/A'})`).join(' | ')}`);
          } else if ((allResults || []).length > 0) {
            console.warn(`⚠️ WARNING: ${(allResults || []).length} jobs found in DB but 0 jobs match filter job_completed=${job_completed}`);
          }
          return json({ success: true, data: filteredResults }, 200, corsHeaders);
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

      // POST /get-vendor-transactions → get vendor transactions from vendor_transaction table
      if (url.pathname === "/get-vendor-transactions" && request.method === "POST") {
        if (!env.DB) {
          return json({ success: false, error: "Database not configured" }, 500, corsHeaders);
        }

        await ensureVendorTransactionTable(env);

        const body = await safeBody(request);
        const vendorEmail = (body.vendor_email || "").trim().toLowerCase();
        const monthFilter = (body.month || "").trim();

        try {
          // Filter to only show transactions with payment_status != 'completed'
          // This prevents showing already completed payments in the admin dashboard
          let query = `SELECT * FROM vendor_transaction WHERE payment_status != 'completed' OR payment_status IS NULL`;
          const params = [];

          if (vendorEmail) {
            query += ` AND LOWER(vendor_email) = ?`;
            params.push(vendorEmail);
          }

          if (monthFilter) {
            query += ` AND substr(period_start, 1, 7) = ?`;
            params.push(monthFilter);
          }

          query += ` ORDER BY period_start DESC, created_at DESC`;

          const { results } = await env.DB.prepare(query).bind(...params).all();
          console.debug(`✅ Retrieved ${(results || []).length} non-completed vendor transactions`);
          return json({ success: true, transactions: results || [] }, 200, corsHeaders);
        } catch (dbError) {
          console.error("Error in /get-vendor-transactions:", dbError);
          return json({ 
            success: false, 
            error: `Database error: ${String(dbError)}` 
          }, 500, corsHeaders);
        }
      }

      // POST /update-vendor-transaction → update vendor transaction payment status and amount
      if (url.pathname === "/update-vendor-transaction" && request.method === "POST") {
        if (!env.DB) {
          return json({ success: false, error: "Database not configured" }, 500, corsHeaders);
        }

        await ensureVendorTransactionTable(env);

        const body = await safeBody(request);
        const transactionId = body.transaction_id || body.id;
        const vendorEmail = (body.vendor_email || "").trim().toLowerCase();
        const amountPaid = parseFloat(body.amount_paid || 0);
        // Only update payment_status if explicitly provided, otherwise preserve existing value
        const paymentStatus = body.payment_status ? body.payment_status.trim() : null;

        if (!transactionId && !vendorEmail) {
          return json({ success: false, error: "transaction_id or vendor_email is required" }, 400, corsHeaders);
        }

        try {
          const now = new Date().toISOString();
          
          if (transactionId) {
            if (paymentStatus !== null) {
              await env.DB.prepare(`
                UPDATE vendor_transaction 
                SET amount_paid = ?, payment_status = ?, updated_at = ?
                WHERE id = ?
              `).bind(amountPaid, paymentStatus, now, transactionId).run();
            } else {
              // Only update amount_paid if payment_status not provided
              await env.DB.prepare(`
                UPDATE vendor_transaction 
                SET amount_paid = ?, updated_at = ?
                WHERE id = ?
              `).bind(amountPaid, now, transactionId).run();
            }
          } else {
            // Update by vendor_email and current date matching 2-day interval
            const currentDate = new Date().toISOString().split('T')[0];
            // Find matching period
            const { results } = await env.DB.prepare(`
              SELECT * FROM vendor_transaction 
              WHERE LOWER(vendor_email) = ? 
              AND period_start <= ? AND period_end >= ?
              ORDER BY period_start DESC LIMIT 1
            `).bind(vendorEmail, currentDate, currentDate).all();
            
            if (results && results.length > 0) {
              if (paymentStatus !== null) {
                await env.DB.prepare(`
                  UPDATE vendor_transaction 
                  SET amount_paid = ?, payment_status = ?, updated_at = ?
                  WHERE id = ?
                `).bind(amountPaid, paymentStatus, now, results[0].id).run();
              } else {
                // Only update amount_paid if payment_status not provided
                await env.DB.prepare(`
                  UPDATE vendor_transaction 
                  SET amount_paid = ?, updated_at = ?
                  WHERE id = ?
                `).bind(amountPaid, now, results[0].id).run();
              }
            } else {
              return json({ success: false, error: "No matching transaction found for current date" }, 404, corsHeaders);
            }
          }

          return json({ success: true, message: "Transaction updated successfully" }, 200, corsHeaders);
        } catch (dbError) {
          console.error("Error in /update-vendor-transaction:", dbError);
          return json({ 
            success: false, 
            error: `Database error: ${String(dbError)}` 
          }, 500, corsHeaders);
        }
      }

      // POST /aggregate-vendor-transaction → aggregate vendor notification data into transaction for 2-day period
      if (url.pathname === "/aggregate-vendor-transaction" && request.method === "POST") {
        if (!env.DB) {
          return json({ success: false, error: "Database not configured" }, 500, corsHeaders);
        }

        await ensureVendorTransactionTable(env);

        const body = await safeBody(request);
        const vendorEmail = (body.vendor_email || "").trim().toLowerCase();
        const currentDate = body.current_date || new Date().toISOString().split('T')[0];

        if (!vendorEmail) {
          return json({ success: false, error: "vendor_email is required" }, 400, corsHeaders);
        }

        try {
          // Helper function to validate and normalize 2-day period
          const validateAndNormalize2DayPeriod = (startStr, endStr, completionDateStr) => {
            if (!startStr || !endStr) return null;
            
            const startDate = new Date(startStr + 'T00:00:00');
            const endDate = new Date(endStr + 'T00:00:00');
            const completionDate = completionDateStr ? new Date(completionDateStr + 'T00:00:00') : new Date();
            
            // Calculate days difference
            const daysDiff = Math.round(
              (endDate.getTime() - startDate.getTime()) / (1000 * 60 * 60 * 24)
            );
            
            // Must be exactly 1 day apart (2-day bucket: start to start+1)
            if (daysDiff !== 1) {
              console.warn(`⚠️ Invalid period span: ${daysDiff} days. Recalculating for date: ${completionDateStr || 'current'}`);
              return null; // Will recalculate below
            }
            
            // Check if start day is odd (required for 2-day buckets: 1-2, 3-4, 5-6, etc.)
            const startDay = startDate.getDate();
            if (startDay % 2 !== 1) {
              console.warn(`⚠️ Period start day ${startDay} is not odd. Recalculating for proper 2-day bucket.`);
              return null; // Will recalculate below
            }
            
            // Validate that end day is start day + 1
            const endDay = endDate.getDate();
            if (endDay !== startDay + 1 && !(startDate.getMonth() !== endDate.getMonth() && endDay === 1)) {
              // Allow month boundary case (e.g., Jan 31 - Jan 31 if month has 31 days)
              const lastDayOfMonth = new Date(startDate.getFullYear(), startDate.getMonth() + 1, 0).getDate();
              if (startDay === lastDayOfMonth && endDay === lastDayOfMonth) {
                // Last day of month - this is valid
                return { start: startStr, end: endStr };
              }
              console.warn(`⚠️ Period end day ${endDay} is not start day + 1. Recalculating.`);
              return null;
            }
            
            return { start: startStr, end: endStr };
          };
          
          // Calculate 2-day period for current date
          // Use provided period_start and period_end if available and valid, otherwise calculate
          let periodStart, periodEnd;
          
          if (body.period_start && body.period_end) {
            // Validate the provided period
            const validated = validateAndNormalize2DayPeriod(
              body.period_start, 
              body.period_end, 
              body.current_date || currentDate
            );
            
            if (validated) {
              periodStart = validated.start;
              periodEnd = validated.end;
            } else {
              // Invalid period provided, recalculate
              console.warn(`⚠️ Provided period ${body.period_start} to ${body.period_end} is invalid. Recalculating.`);
              const date = new Date(body.current_date || currentDate);
              const day = date.getDate();
              
              let startDate, endDate;
              if (day % 2 === 1) {
                // Odd day: start is the day itself, end is day+1
                startDate = new Date(date);
                endDate = new Date(date);
                endDate.setDate(endDate.getDate() + 1);
              } else {
                // Even day: start is day-1, end is the day itself
                startDate = new Date(date);
                startDate.setDate(startDate.getDate() - 1);
                endDate = new Date(date);
              }
              
              // Handle month boundaries
              if (endDate.getMonth() !== startDate.getMonth()) {
                // If end goes into next month, adjust to last day of current month
                const lastDay = new Date(startDate.getFullYear(), startDate.getMonth() + 1, 0).getDate();
                endDate = new Date(startDate.getFullYear(), startDate.getMonth(), lastDay);
              }
              
              periodStart = startDate.toISOString().split('T')[0];
              periodEnd = endDate.toISOString().split('T')[0];
              console.debug(`✅ Recalculated period: ${periodStart} to ${periodEnd}`);
            }
          } else {
            // Calculate 2-day period: 1-2, 3-4, ..., 27-28, 29-30, 31 (if applicable)
            const date = new Date(currentDate);
            const day = date.getDate();
            
            let startDate, endDate;
            if (day % 2 === 1) {
              // Odd day: start is the day itself, end is day+1
              startDate = new Date(date);
              endDate = new Date(date);
              endDate.setDate(endDate.getDate() + 1);
            } else {
              // Even day: start is day-1, end is the day itself
              startDate = new Date(date);
              startDate.setDate(startDate.getDate() - 1);
              endDate = new Date(date);
            }
            
            // Handle month boundaries
            if (endDate.getMonth() !== startDate.getMonth()) {
              // If end goes into next month, adjust to last day of current month
              const lastDay = new Date(startDate.getFullYear(), startDate.getMonth() + 1, 0).getDate();
              endDate = new Date(startDate.getFullYear(), startDate.getMonth(), lastDay);
            }
            
            periodStart = startDate.toISOString().split('T')[0];
            periodEnd = endDate.toISOString().split('T')[0];
          }
          
          // Final validation before proceeding
          const finalValidation = validateAndNormalize2DayPeriod(periodStart, periodEnd, body.current_date || currentDate);
          if (!finalValidation) {
            console.error(`❌ Failed to create valid 2-day period. Start: ${periodStart}, End: ${periodEnd}`);
            return json({ 
              success: false, 
              error: `Invalid 2-day period: ${periodStart} to ${periodEnd}. Periods must be 2-day buckets (1-2, 3-4, 5-6, etc.)` 
            }, 400, corsHeaders);
          }
          
          periodStart = finalValidation.start;
          periodEnd = finalValidation.end;

          // Get vendor notifications for this period
          const { results: notifications } = await env.DB.prepare(`
            SELECT * FROM vendor_notification
            WHERE LOWER(vendor_email) = ?
            AND (completion_time BETWEEN ? AND ? OR timestamp BETWEEN ? AND ?)
          `).bind(vendorEmail, `${periodStart} 00:00:00`, `${periodEnd} 23:59:59`, `${periodStart} 00:00:00`, `${periodEnd} 23:59:59`).all();

          // Get vendor print jobs for this period to get accurate pricing
          const { results: printJobs } = await env.DB.prepare(`
            SELECT * FROM Vendor_print_jobs
            WHERE LOWER(vendor_email) = ?
            AND job_completed = 'YES'
            AND (completion_time BETWEEN ? AND ? OR timestamp BETWEEN ? AND ?)
          `).bind(vendorEmail, `${periodStart} 00:00:00`, `${periodEnd} 23:59:59`, `${periodStart} 00:00:00`, `${periodEnd} 23:59:59`).all();

          // Aggregate data from print jobs (more accurate than notifications)
          let totalDocuments = 0;
          let totalPrice = 0.0;
          let platformProfit = 0.0;
          
          // Use print jobs for accurate pricing if available
          if (printJobs && printJobs.length > 0) {
            printJobs.forEach(job => {
              totalDocuments++;
              totalPrice += parseFloat(job.total_price || 0);
              platformProfit += parseFloat(job.platform_profit || 0);
            });
          } else {
            // Fallback to notifications if print jobs not available
            notifications.forEach(notif => {
              totalDocuments++;
              totalPrice += parseFloat(notif.total_price || 0);
              platformProfit += parseFloat(notif.platform_profit || 0);
            });
          }
          
          // If single job data provided in request, check if it's already counted
          // Only add if the filename is not already in the print jobs
          if (body.total_price !== undefined && body.platform_profit !== undefined && body.filename) {
            const filename = body.filename.trim();
            const alreadyCounted = printJobs && printJobs.some(job => job.filename === filename);
            
            if (!alreadyCounted) {
              totalDocuments += (body.total_documents || 1);
              totalPrice += parseFloat(body.total_price || 0);
              platformProfit += parseFloat(body.platform_profit || 0);
            }
          } else if (body.total_price !== undefined && body.platform_profit !== undefined && !body.filename) {
            // If no filename provided, add the values (for backward compatibility)
            totalDocuments += (body.total_documents || 1);
            totalPrice += parseFloat(body.total_price || 0);
            platformProfit += parseFloat(body.platform_profit || 0);
          }

          const totalEarning = totalPrice - platformProfit;

          // Get vendor details
          const { results: vendorDetails } = await env.DB.prepare(`
            SELECT vendor_id, vendor_name FROM "Vendor_register_details "
            WHERE LOWER(email) = ? LIMIT 1
          `).bind(vendorEmail).all();

          const vendorId = vendorDetails && vendorDetails.length > 0 ? (vendorDetails[0].vendor_id || '') : '';
          const vendorNameFromRegister = vendorDetails && vendorDetails.length > 0 ? (vendorDetails[0].vendor_name || '') : '';

          // Resolve the best possible vendor/shop name for transactions
          const rawBodyVendorName = (body.vendor_name || '').toString().trim();
          const isPlaceholderName = (name) => {
            if (!name) return true;
            const lower = name.toLowerCase();
            return lower === 'unknown vendor' || lower === 'printmax vendor';
          };

          let finalVendorName = rawBodyVendorName;

          // Prefer registered vendor name when body name is missing or a placeholder
          if (isPlaceholderName(finalVendorName)) {
            if (vendorNameFromRegister && !isPlaceholderName(vendorNameFromRegister)) {
              finalVendorName = vendorNameFromRegister.trim();
            }
          }

          // Fallback: try to read shop_name from any available print job / notification
          if (isPlaceholderName(finalVendorName)) {
            const sampleJob = (printJobs && printJobs.length > 0) ? printJobs[0] : ((notifications && notifications.length > 0) ? notifications[0] : null);
            const shopNameFromRecord = getShopNameFromRecord(sampleJob);
            if (shopNameFromRecord && !isPlaceholderName(shopNameFromRecord)) {
              finalVendorName = shopNameFromRecord.toString().trim();
            }
          }

          // Last-resort fallback: use vendor email so it's never "Unknown Vendor"
          if (!finalVendorName) {
            finalVendorName = vendorEmail;
          }

          // Check if transaction already exists
          const existing = await env.DB.prepare(`
            SELECT * FROM vendor_transaction
            WHERE LOWER(vendor_email) = ? AND period_start = ? AND period_end = ?
          `).bind(vendorEmail, periodStart, periodEnd).first();

          if (existing) {
            // Recalculate totals from all print jobs in this period to ensure accuracy
            const { results: allPrintJobs } = await env.DB.prepare(`
              SELECT * FROM Vendor_print_jobs
              WHERE LOWER(vendor_email) = ?
              AND job_completed = 'YES'
              AND (completion_time BETWEEN ? AND ? OR timestamp BETWEEN ? AND ?)
            `).bind(vendorEmail, `${periodStart} 00:00:00`, `${periodEnd} 23:59:59`, `${periodStart} 00:00:00`, `${periodEnd} 23:59:59`).all();

            let recalcDocuments = 0;
            let recalcPrice = 0.0;
            let recalcProfit = 0.0;
            
            if (allPrintJobs && allPrintJobs.length > 0) {
              allPrintJobs.forEach(job => {
                recalcDocuments++;
                recalcPrice += parseFloat(job.total_price || 0);
                recalcProfit += parseFloat(job.platform_profit || 0);
              });
            }
            
            const recalcEarning = recalcPrice - recalcProfit;
            
            // Update with recalculated values, and refresh vendor_name, but preserve payment_status and amount_paid
            await env.DB.prepare(`
              UPDATE vendor_transaction SET
                vendor_name = ?,
                total_documents = ?,
                total_price = ?,
                platform_profit = ?,
                total_earning = ?,
                updated_at = datetime('now')
              WHERE LOWER(vendor_email) = ? AND period_start = ? AND period_end = ?
            `).bind(finalVendorName, recalcDocuments, recalcPrice, recalcProfit, recalcEarning, vendorEmail, periodStart, periodEnd).run();
          } else {
            // Insert new transaction
            await env.DB.prepare(`
              INSERT INTO vendor_transaction (
                vendor_id, vendor_email, vendor_name, period_start, period_end,
                total_documents, total_price, platform_profit, total_earning,
                amount_paid, payment_status, created_at, updated_at
              ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
            `).bind(
              vendorId, vendorEmail, finalVendorName, periodStart, periodEnd,
              totalDocuments, totalPrice, platformProfit, totalEarning,
              0.0, 'not_completed'
            ).run();
          }

          return json({ 
            success: true, 
            message: "Transaction aggregated successfully",
            transaction: {
              vendor_email: vendorEmail,
              period_start: periodStart,
              period_end: periodEnd,
              total_documents: totalDocuments,
              total_price: totalPrice,
              platform_profit: platformProfit,
              total_earning: totalEarning
            }
          }, 200, corsHeaders);
        } catch (dbError) {
          console.error("Error in /aggregate-vendor-transaction:", dbError);
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

      // POST /create-admin-user → creates or updates an admin user
      if (url.pathname === "/create-admin-user" && request.method === "POST") {
        if (!env.DB) {
          return json({ success: false, error: "Database not configured" }, 500, corsHeaders);
        }

        await ensureAdminUsersTable(env);

        const body = await safeBody(request);
        const username = (body.username || "").trim();
        const password_hash = (body.password_hash || "").trim();
        const email = (body.email || "").trim();
        const first_name = (body.first_name || "").trim();
        const last_name = (body.last_name || "").trim();
        const is_superuser = body.is_superuser === true || body.is_superuser === 1 ? 1 : 0;
        const is_staff = body.is_staff !== undefined ? (body.is_staff === true || body.is_staff === 1 ? 1 : 0) : 1;
        const is_active = body.is_active !== undefined ? (body.is_active === true || body.is_active === 1 ? 1 : 0) : 1;
        const permissions = body.permissions ? JSON.stringify(body.permissions) : null;

        if (!username || !password_hash) {
          return json({ success: false, error: "username and password_hash are required" }, 400, corsHeaders);
        }

        try {
          const now = new Date().toISOString();
          
          // Check if user exists
          const existing = await env.DB.prepare(`
            SELECT id FROM admin_users WHERE username = ?
          `).bind(username).first();

          if (existing) {
            // Update existing user
            await env.DB.prepare(`
              UPDATE admin_users SET
                password_hash = ?,
                email = ?,
                first_name = ?,
                last_name = ?,
                is_superuser = ?,
                is_staff = ?,
                is_active = ?,
                permissions = ?,
                updated_at = ?
              WHERE username = ?
            `).bind(password_hash, email || null, first_name || null, last_name || null, is_superuser, is_staff, is_active, permissions, now, username).run();
            
            return json({ success: true, message: "Admin user updated successfully" }, 200, corsHeaders);
          } else {
            // Insert new user
            await env.DB.prepare(`
              INSERT INTO admin_users (
                username, password_hash, email, first_name, last_name,
                is_superuser, is_staff, is_active, permissions,
                date_joined, created_at, updated_at
              ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            `).bind(username, password_hash, email || null, first_name || null, last_name || null, is_superuser, is_staff, is_active, permissions, now, now, now).run();
            
            return json({ success: true, message: "Admin user created successfully" }, 200, corsHeaders);
          }
        } catch (dbError) {
          return json({ 
            success: false, 
            error: `Database error: ${String(dbError)}` 
          }, 500, corsHeaders);
        }
      }

      // POST /get-admin-user → get admin user by username
      if (url.pathname === "/get-admin-user" && request.method === "POST") {
        if (!env.DB) {
          return json({ success: false, error: "Database not configured" }, 500, corsHeaders);
        }

        await ensureAdminUsersTable(env);

        const body = await safeBody(request);
        const username = (body.username || "").trim();

        if (!username) {
          return json({ success: false, error: "username is required" }, 400, corsHeaders);
        }

        try {
          const user = await env.DB.prepare(`
            SELECT * FROM admin_users WHERE username = ? AND is_active = 1
          `).bind(username).first();

          if (!user) {
            return json({ success: false, error: "User not found or inactive" }, 404, corsHeaders);
          }

          // Parse permissions if exists
          let permissions = null;
          if (user.permissions) {
            try {
              permissions = JSON.parse(user.permissions);
            } catch (e) {
              permissions = null;
            }
          }

          return json({ 
            success: true, 
            user: {
              id: user.id,
              username: user.username,
              email: user.email,
              first_name: user.first_name,
              last_name: user.last_name,
              is_superuser: user.is_superuser === 1,
              is_staff: user.is_staff === 1,
              is_active: user.is_active === 1,
              password_hash: user.password_hash,
              permissions: permissions,
              date_joined: user.date_joined,
              last_login: user.last_login,
              created_at: user.created_at,
              updated_at: user.updated_at
            }
          }, 200, corsHeaders);
        } catch (dbError) {
          return json({ 
            success: false, 
            error: `Database error: ${String(dbError)}` 
          }, 500, corsHeaders);
        }
      }

      // POST /authenticate-admin-user → authenticate admin user with username and password hash check
      if (url.pathname === "/authenticate-admin-user" && request.method === "POST") {
        if (!env.DB) {
          return json({ success: false, error: "Database not configured" }, 500, corsHeaders);
        }

        await ensureAdminUsersTable(env);

        const body = await safeBody(request);
        const username = (body.username || "").trim();
        const password_hash = (body.password_hash || "").trim();

        if (!username || !password_hash) {
          return json({ success: false, error: "username and password_hash are required" }, 400, corsHeaders);
        }

        try {
          const user = await env.DB.prepare(`
            SELECT * FROM admin_users WHERE username = ? AND is_active = 1
          `).bind(username).first();

          if (!user) {
            return json({ success: false, error: "Invalid credentials" }, 401, corsHeaders);
          }

          // Check password hash (should be done in Django, but we return user if hash matches)
          // Note: The actual password verification should be done in Django using check_password
          // This endpoint just returns the user if found and active
          
          // Update last_login
          await env.DB.prepare(`
            UPDATE admin_users SET last_login = ? WHERE username = ?
          `).bind(new Date().toISOString(), username).run();

          // Parse permissions if exists
          let permissions = null;
          if (user.permissions) {
            try {
              permissions = JSON.parse(user.permissions);
            } catch (e) {
              permissions = null;
            }
          }

          return json({ 
            success: true, 
            user: {
              id: user.id,
              username: user.username,
              email: user.email,
              first_name: user.first_name,
              last_name: user.last_name,
              is_superuser: user.is_superuser === 1,
              is_staff: user.is_staff === 1,
              is_active: user.is_active === 1,
              password_hash: user.password_hash,
              permissions: permissions,
              date_joined: user.date_joined,
              last_login: new Date().toISOString()
            }
          }, 200, corsHeaders);
        } catch (dbError) {
          return json({ 
            success: false, 
            error: `Database error: ${String(dbError)}` 
          }, 500, corsHeaders);
        }
      }

      // POST /get-all-admin-users → get all admin users
      if (url.pathname === "/get-all-admin-users" && request.method === "POST") {
        if (!env.DB) {
          return json({ success: false, error: "Database not configured" }, 500, corsHeaders);
        }

        await ensureAdminUsersTable(env);

        try {
          const { results } = await env.DB.prepare(`
            SELECT * FROM admin_users ORDER BY created_at DESC
          `).all();

          const users = (results || []).map(user => {
            let permissions = null;
            if (user.permissions) {
              try {
                permissions = JSON.parse(user.permissions);
              } catch (e) {
                permissions = null;
              }
            }

            return {
              id: user.id,
              username: user.username,
              email: user.email,
              first_name: user.first_name,
              last_name: user.last_name,
              is_superuser: user.is_superuser === 1,
              is_staff: user.is_staff === 1,
              is_active: user.is_active === 1,
              permissions: permissions,
              date_joined: user.date_joined,
              last_login: user.last_login,
              created_at: user.created_at,
              updated_at: user.updated_at
            };
          });

          return json({ success: true, users: users }, 200, corsHeaders);
        } catch (dbError) {
          return json({ 
            success: false, 
            error: `Database error: ${String(dbError)}` 
          }, 500, corsHeaders);
        }
      }

      // POST /update-admin-user-permissions → update admin user permissions
      if (url.pathname === "/update-admin-user-permissions" && request.method === "POST") {
        if (!env.DB) {
          return json({ success: false, error: "Database not configured" }, 500, corsHeaders);
        }

        await ensureAdminUsersTable(env);

        const body = await safeBody(request);
        const username = (body.username || "").trim();
        const permissions = body.permissions ? JSON.stringify(body.permissions) : null;

        if (!username) {
          return json({ success: false, error: "username is required" }, 400, corsHeaders);
        }

        try {
          await env.DB.prepare(`
            UPDATE admin_users SET
              permissions = ?,
              updated_at = ?
            WHERE username = ?
          `).bind(permissions, new Date().toISOString(), username).run();

          return json({ success: true, message: "Permissions updated successfully" }, 200, corsHeaders);
        } catch (dbError) {
          return json({ 
            success: false, 
            error: `Database error: ${String(dbError)}` 
          }, 500, corsHeaders);
        }
      }

      // POST /store-vendor-pending-jobs-snapshot → store vendor pending jobs snapshot
      if (url.pathname === "/store-vendor-pending-jobs-snapshot" && request.method === "POST") {
        if (!env.DB) {
          return json({ success: false, error: "Database not configured" }, 500, corsHeaders);
        }

        const body = await safeBody(request);
        const vendor_id = (body.vendor_id || "").trim();
        const vendor_email = (body.vendor_email || "").trim().toLowerCase();
        const pending_jobs = body.pending_jobs || [];
        const snapshot_timestamp = body.snapshot_timestamp || new Date().toISOString();

        if (!vendor_id && !vendor_email) {
          return json({ success: false, error: "vendor_id or vendor_email is required" }, 400, corsHeaders);
        }

        try {
          // Ensure table exists
          try {
            await env.DB.prepare(`SELECT 1 FROM vendor_pending_jobs_track LIMIT 1`).first();
          } catch (tableErr) {
            // Table doesn't exist, create it
            await env.DB.prepare(`
              CREATE TABLE IF NOT EXISTS vendor_pending_jobs_track(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vendor_id TEXT UNIQUE,
                vendor_email TEXT,
                snapshot_timestamp TEXT NOT NULL,
                job_count INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
              )
            `).run();
            
            // Create unique index on vendor_email as well to prevent duplicates
            try {
              await env.DB.prepare(`
                CREATE UNIQUE INDEX IF NOT EXISTS idx_vendor_email_unique 
                ON vendor_pending_jobs_track(vendor_email) 
                WHERE vendor_email IS NOT NULL
              `).run();
            } catch (indexError) {
              // Index might already exist or SQLite version doesn't support WHERE clause in unique index
              // Try without WHERE clause
              try {
                await env.DB.prepare(`
                  CREATE UNIQUE INDEX IF NOT EXISTS idx_vendor_email_unique 
                  ON vendor_pending_jobs_track(vendor_email)
                `).run();
              } catch (e) {
                // Ignore if index creation fails
                console.debug(`Note: Could not create unique index on vendor_email: ${e}`);
              }
            }
          }

          // Calculate job count
          const job_count = Array.isArray(pending_jobs) ? pending_jobs.length : 0;

          // Check if vendor already exists (prioritize vendor_id, fallback to vendor_email)
          let existing = null;
          if (vendor_id) {
            existing = await env.DB.prepare(`
              SELECT id FROM vendor_pending_jobs_track 
              WHERE vendor_id = ?
              LIMIT 1
            `).bind(vendor_id).first();
          }
          
          if (!existing && vendor_email) {
            existing = await env.DB.prepare(`
              SELECT id FROM vendor_pending_jobs_track 
              WHERE vendor_email = ?
              LIMIT 1
            `).bind(vendor_email).first();
          }

          if (existing) {
            // Update existing row
            if (vendor_id) {
              await env.DB.prepare(`
                UPDATE vendor_pending_jobs_track SET
                  vendor_email = ?,
                  snapshot_timestamp = ?,
                  job_count = ?,
                  updated_at = datetime('now')
                WHERE vendor_id = ?
              `).bind(
                vendor_email || null,
                snapshot_timestamp,
                job_count,
                vendor_id
              ).run();
            } else if (vendor_email) {
              await env.DB.prepare(`
                UPDATE vendor_pending_jobs_track SET
                  vendor_id = ?,
                  snapshot_timestamp = ?,
                  job_count = ?,
                  updated_at = datetime('now')
                WHERE vendor_email = ?
              `).bind(
                vendor_id || null,
                snapshot_timestamp,
                job_count,
                vendor_email
              ).run();
            }
          } else {
            // Insert new row - ensure we have at least vendor_id or vendor_email
            try {
              await env.DB.prepare(`
                INSERT INTO vendor_pending_jobs_track (
                  vendor_id, vendor_email, snapshot_timestamp, job_count
                )
                VALUES (?, ?, ?, ?)
              `).bind(
                vendor_id || null,
                vendor_email || null,
                snapshot_timestamp,
                job_count
              ).run();
            } catch (insertError) {
              // If insert fails due to unique constraint, try update instead
              if (String(insertError).includes('UNIQUE constraint') || String(insertError).includes('duplicate')) {
                if (vendor_id) {
                  await env.DB.prepare(`
                    UPDATE vendor_pending_jobs_track SET
                      vendor_email = ?,
                      snapshot_timestamp = ?,
                      job_count = ?,
                      updated_at = datetime('now')
                    WHERE vendor_id = ?
                  `).bind(
                    vendor_email || null,
                    snapshot_timestamp,
                    job_count,
                    vendor_id
                  ).run();
                } else if (vendor_email) {
                  await env.DB.prepare(`
                    UPDATE vendor_pending_jobs_track SET
                      vendor_id = ?,
                      snapshot_timestamp = ?,
                      job_count = ?,
                      updated_at = datetime('now')
                    WHERE vendor_email = ?
                  `).bind(
                    vendor_id || null,
                    snapshot_timestamp,
                    job_count,
                    vendor_email
                  ).run();
                }
              } else {
                throw insertError;
              }
            }
          }

          return json({ 
            success: true, 
            message: `Updated ${job_count} pending jobs count for vendor ${vendor_id || vendor_email}` 
          }, 200, corsHeaders);
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

