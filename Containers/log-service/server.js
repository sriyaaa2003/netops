const crypto = require('crypto');
const express = require('express');
const { Pool } = require('pg');
const { parseLine } = require('./parser');

const app = express();
app.use(express.json({ limit: '4mb' }));

const PORT = process.env.PORT || 4000;

const REQUIRED_ENV = ['DB_HOST', 'DB_PORT', 'DB_USER', 'DB_PASSWORD', 'DB_NAME', 'API_KEY'];
const missingEnv = REQUIRED_ENV.filter((key) => !process.env[key]);
if (missingEnv.length > 0) {
  console.error(`Fatal: missing required environment variable(s): ${missingEnv.join(', ')}`);
  process.exit(1);
}

const pool = new Pool({
  host: process.env.DB_HOST,
  port: process.env.DB_PORT,
  user: process.env.DB_USER,
  password: process.env.DB_PASSWORD,
  database: process.env.DB_NAME,
});

// Shared-secret check on every route except the health probe. The browser never sees the key: nginx adds it.
const KEY = Buffer.from(process.env.API_KEY);
function requireKey(req, res, next) {
  const given = Buffer.from(req.get('X-API-Key') || '');
  if (given.length === KEY.length && crypto.timingSafeEqual(given, KEY)) return next();
  return res.status(401).json({ error: 'missing or wrong X-API-Key' });
}

async function initDb(retries = 20, delayMs = 3000) {
  for (let i = 0; i < retries; i++) {
    try {
      await pool.query(`
        CREATE TABLE IF NOT EXISTS logs (
          id SERIAL PRIMARY KEY,
          log_timestamp TIMESTAMPTZ,
          severity TEXT NOT NULL,
          component TEXT NOT NULL,
          subsystem TEXT,
          message TEXT NOT NULL,
          raw TEXT NOT NULL,
          alert_label TEXT,
          ingested_at TIMESTAMPTZ DEFAULT now()
        );
        ALTER TABLE logs ADD COLUMN IF NOT EXISTS subsystem TEXT;
        ALTER TABLE logs ADD COLUMN IF NOT EXISTS alert_label TEXT;
        CREATE INDEX IF NOT EXISTS logs_ts_idx ON logs (log_timestamp DESC);
      `);
      console.log('Database ready.');
      return;
    } catch (err) {
      console.log(`DB not ready yet (attempt ${i + 1}/${retries}): ${err.message}`);
      await new Promise((r) => setTimeout(r, delayMs));
    }
  }
  throw new Error('Could not connect to database after retries.');
}

app.get('/health', (req, res) => res.json({ status: 'ok', service: 'log-service' }));
app.use(requireKey);

// Accepts one line or a multi-line dump under "raw". Lines that are not BGL records are skipped and counted
// rather than rejecting the whole batch.
app.post('/logs', async (req, res) => {
  const { raw } = req.body;
  if (!raw || typeof raw !== 'string') {
    return res.status(400).json({ error: 'raw (string) is required' });
  }

  const parsed = [];
  const skipped = [];
  for (const line of raw.split('\n').map((l) => l.trim()).filter(Boolean)) {
    const entry = parseLine(line);
    if (entry) parsed.push(entry);
    else skipped.push(line);
  }

  const client = await pool.connect();
  try {
    await client.query('BEGIN');
    const CHUNK = 500;
    for (let i = 0; i < parsed.length; i += CHUNK) {
      const rows = parsed.slice(i, i + CHUNK);
      const values = [];
      const tuples = rows.map((e, j) => {
        values.push(e.timestamp, e.severity, e.component, e.subsystem, e.message, e.raw, e.label);
        const b = j * 7;
        return `($${b + 1}, $${b + 2}, $${b + 3}, $${b + 4}, $${b + 5}, $${b + 6}, $${b + 7})`;
      });
      await client.query(
        `INSERT INTO logs (log_timestamp, severity, component, subsystem, message, raw, alert_label) VALUES ${tuples.join(', ')}`,
        values
      );
    }
    await client.query('COMMIT');
  } catch (err) {
    await client.query('ROLLBACK');
    console.error(err);
    return res.status(500).json({ error: 'database error' });
  } finally {
    client.release();
  }

  res.status(201).json({
    inserted_count: parsed.length,
    skipped_count: skipped.length,
    skipped_examples: skipped.slice(0, 5),
  });
});

// ?limit= (max 20000), ?severity=, ?component=, ?since= and ?until= (ISO timestamps, on the log's own time)
app.get('/logs', async (req, res) => {
  const limit = Math.min(parseInt(req.query.limit) || 100, 20000);
  const conditions = [];
  const values = [];
  const add = (sql, v) => {
    values.push(v);
    conditions.push(sql.replace('?', `$${values.length}`));
  };

  if (req.query.severity) add('severity = ?', req.query.severity.toUpperCase());
  if (req.query.component) add('component = ?', req.query.component);
  if (req.query.since) add('log_timestamp >= ?', req.query.since);
  if (req.query.until) add('log_timestamp < ?', req.query.until);

  const where = conditions.length ? `WHERE ${conditions.join(' AND ')}` : '';
  values.push(limit);

  try {
    const result = await pool.query(
      `SELECT id, log_timestamp, severity, component, subsystem, message, alert_label
       FROM logs ${where} ORDER BY log_timestamp DESC, id DESC LIMIT $${values.length}`,
      values
    );
    res.json(result.rows);
  } catch (err) {
    console.error(err);
    res.status(400).json({ error: 'bad query' });
  }
});

app.get('/logs/:id', async (req, res) => {
  try {
    const result = await pool.query('SELECT * FROM logs WHERE id = $1', [req.params.id]);
    if (result.rows.length === 0) return res.status(404).json({ error: 'not found' });
    res.json(result.rows[0]);
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: 'database error' });
  }
});

if (require.main === module) {
  initDb()
    .then(() => {
      app.listen(PORT, () => console.log(`log-service listening on ${PORT}`));
    })
    .catch((err) => {
      console.error('Fatal: could not start log-service', err);
      process.exit(1);
    });
}
