// Maps the answers on a Floppy issue form to extra labels. Pure and
// deterministic: no network, no AI. Unknown, missing or legacy answers add nothing.
const FEATURE_HEADING = "What does your request primarily relate to?";
const BUG_HEADING = "Where did this happen?";

// Keyed by the option text before the " — " description, so a reworded
// description does not break the mapping.
const FEATURE_LABELS = {
  "Interface & Usability": "interface",
  "Tracking & Media Management": "tracking",
  "Integrations & Data Sources": "integration",
  "Performance & Technical": "technical",
};
const BUG_LABELS = {
  "Web browser": "web",
  "iOS app": "ios",
  "Android app": "android",
  "Integration or background activity": "integration",
  "Server or installation": "server",
};

// Issue forms render each field as "### Label" followed by the answer.
function answerFor(body, heading) {
  const lines = String(body || "").replace(/\r\n/g, "\n").split("\n");
  const start = lines.findIndex((l) => l.trim() === `### ${heading}`);
  if (start === -1) return null;
  const rest = lines.slice(start + 1);
  const end = rest.findIndex((l) => l.startsWith("### "));
  const answer = (end === -1 ? rest : rest.slice(0, end)).join("\n").trim();
  return answer || null;
}

function labelFor(answer, table) {
  if (!answer) return null;
  const key = answer.split(/\s+[—–-]\s+/)[0].trim();
  return table[key] || null;
}

function labelsFromIssueBody(body) {
  const labels = [
    labelFor(answerFor(body, FEATURE_HEADING), FEATURE_LABELS),
    labelFor(answerFor(body, BUG_HEADING), BUG_LABELS),
  ];
  return labels.filter(Boolean);
}

// Issues made by a script or agent skip the form, so the form's own labels and
// Type are never applied. Recognise a form-shaped body by its headings and
// supply them, plus the category label, so those issues are triaged the same way.
function classifyIssueBody(body) {
  const isBug = answerFor(body, "What went wrong?") !== null;
  const isFeature = answerFor(body, FEATURE_HEADING) !== null;
  const type = isBug ? "Bug" : isFeature ? "Feature" : null;
  const baseLabel = isBug ? "bug" : isFeature ? "enhancement" : null;
  const labels = [baseLabel, ...labelsFromIssueBody(body)].filter(Boolean);
  return { type, labels };
}

module.exports = { labelsFromIssueBody, classifyIssueBody };
