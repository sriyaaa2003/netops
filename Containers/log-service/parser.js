// Parser for the BlueGene/L RAS log format (Loghub BGL, Oliner and Stearley, DSN 2007):
//
//   LABEL EPOCH DATE NODE TIMESTAMP NODE TYPE COMPONENT LEVEL MESSAGE...
//   - 1117838570 2005.06.03 R02-M1-N0-C:J12-U11 2005-06-03-15.42.50.363779 R02-M1-N0-C:J12-U11 RAS KERNEL INFO instruction cache parity error corrected
//
// LABEL is "-" for a normal line and an alert category (for example KERNDTLB) for an alert line. The label is
// stored for evaluation only; the anomaly detector never reads it.

const LEVELS = new Set(['INFO', 'WARNING', 'ERROR', 'SEVERE', 'FATAL', 'FAILURE']);
const LINE_RE = /^(\S+)\s+(\d{9,10})\s+\S+\s+(\S+)\s+\S+\s+\S+\s+\S+\s+(\S+)\s+(\S+)\s*(.*)$/;

// R02-M1-N0-C:J12-U11 -> R02-M1-N0 (rack, midplane, node card)
function nodeCard(node) {
  return node.split('-').slice(0, 3).join('-');
}

function parseLine(line) {
  const match = line.trim().match(LINE_RE);
  if (!match) return null;
  const [, label, epoch, node, subsystem, level, message] = match;
  const severity = level.toUpperCase();
  if (!LEVELS.has(severity)) return null;
  return {
    label: label === '-' ? null : label,
    timestamp: new Date(Number(epoch) * 1000).toISOString(),
    severity,
    component: nodeCard(node),
    subsystem,
    message,
    raw: line.trim(),
  };
}

module.exports = { parseLine, nodeCard, LEVELS };
