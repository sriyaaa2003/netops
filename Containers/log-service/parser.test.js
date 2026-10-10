const test = require('node:test');
const assert = require('node:assert');
const { parseLine, nodeCard } = require('./parser');

const NORMAL =
  '- 1117838570 2005.06.03 R02-M1-N0-C:J12-U11 2005-06-03-15.42.50.363779 R02-M1-N0-C:J12-U11 RAS KERNEL INFO instruction cache parity error corrected';
const ALERT =
  'APPREAD 1117869872 2005.06.04 R04-M1-L2-U11-A 2005-06-04-00.24.32.398331 R04-M1-L2-U11-A RAS APP FATAL ciod: failed to read message prefix on control stream';

test('parses a normal BGL line', () => {
  const e = parseLine(NORMAL);
  assert.strictEqual(e.label, null);
  assert.strictEqual(e.severity, 'INFO');
  assert.strictEqual(e.component, 'R02-M1-N0');
  assert.strictEqual(e.subsystem, 'KERNEL');
  assert.strictEqual(e.timestamp, new Date(1117838570 * 1000).toISOString());
  assert.match(e.message, /^instruction cache parity error corrected/);
});

test('keeps the alert label separate from the line content', () => {
  const e = parseLine(ALERT);
  assert.strictEqual(e.label, 'APPREAD');
  assert.strictEqual(e.severity, 'FATAL');
  assert.strictEqual(e.component, 'R04-M1-L2');
});

test('rejects lines that are not BGL records', () => {
  assert.strictEqual(parseLine('hello world'), null);
  assert.strictEqual(parseLine(''), null);
  assert.strictEqual(parseLine(NORMAL.replace('INFO', 'CHATTY')), null);
});

test('nodeCard keeps rack, midplane and node card', () => {
  assert.strictEqual(nodeCard('R23-M1-NC-I:J18-U01'), 'R23-M1-NC');
});
