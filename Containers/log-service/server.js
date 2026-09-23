const express = require('express');
const { Pool } = require('pg');

const app = express();
app.use(express.json({ limit: '2mb' }));

const PORT = process.env.PORT || 4000;

const REQUIRED_DB_ENV = ['DB_HOST', 'DB_PORT', 'DB_USER', 'DB_PASSWORD', 'DB_NAME'];
const missingEnv = REQUIRED_DB_ENV.filter((key) => !process.env[key]);
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

// Expected line format, similar to what a network node test rig emits:
// 2026-09-19T10:15:32Z [ERROR] radio-scheduler: RLC retransmission threshold exceeded on cell 12
const LOG_LINE_RE = /^(\S+)\s+\[(\w+)\]\s+([\w.-]+):\s*(.*)$/;

function parseLine(line) {
  const match = line.trim().match(LOG_LINE_RE);
  if (!match) return null;
  const [, timestamp, severity, component, message] = match;
  return {
    timestamp,
    severity: severity.toUpperCase(),
    component,
    message,
    raw: line,
  };
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
          message TEXT NOT NULL,
          raw TEXT NOT NULL,
          ingested_at TIMESTAMPTZ DEFAULT now()
        );
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

// Accepts either one line or a multi-line dump under "raw".
// Lines that don't match the expected format are skipped and reported
// back, rather than silently dropped or rejecting the whole batch.
app.post('/logs', async (req, res) => {
  const { raw } = req.body;
  if (!raw || typeof raw !== 'string') {
    return res.status(400).json({ error: 'raw (string) is required' });
  }

  const lines = raw.split('\n').map((l) => l.trim()).filter(Boolean);
  const parsed = [];
  const skipped = [];

  for (const line of lines) {
    const entry = parseLine(line);
    if (entry) parsed.push(entry);
    else skipped.push(line);
  }

  const inserted = [];
  const client = await pool.connect();
  try {
    await client.query('BEGIN');
    for (const entry of parsed) {
      const result = await client.query(
        `INSERT INTO logs (log_timestamp, severity, component, message, raw)
         VALUES ($1, $2, $3, $4, $5) RETURNING *`,
        [entry.timestamp, entry.severity, entry.component, entry.message, entry.raw]
      );
      inserted.push(result.rows[0]);
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
    inserted_count: inserted.length,
    skipped_count: skipped.length,
    skipped,
    entries: inserted,
  });
});

// ?limit=, ?severity=, ?component= filters
app.get('/logs', async (req, res) => {
  const limit = Math.min(parseInt(req.query.limit) || 100, 1000);
  const conditions = [];
  const values = [];

  if (req.query.severity) {
    values.push(req.query.severity.toUpperCase());
    conditions.push(`severity = $${values.length}`);
  }
  if (req.query.component) {
    values.push(req.query.component);
    conditions.push(`component = $${values.length}`);
  }

  const where = conditions.length ? `WHERE ${conditions.join(' AND ')}` : '';
  values.push(limit);

  try {
    const result = await pool.query(
      `SELECT * FROM logs ${where} ORDER BY ingested_at DESC LIMIT $${values.length}`,
      values
    );
    res.json(result.rows);
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: 'database error' });
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

initDb()
  .then(() => {
    app.listen(PORT, () => console.log(`log-service listening on ${PORT}`));
  })
  .catch((err) => {
    console.error('Fatal: could not start log-service', err);
    process.exit(1);
  });
