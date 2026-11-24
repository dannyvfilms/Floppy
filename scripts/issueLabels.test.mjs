import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";

const { labelsFromIssueBody } = createRequire(import.meta.url)("../.github/scripts/issue-labels.cjs");

const feature = (a) => `### What does your request primarily relate to?\n\n${a}\n\n### What would you like Floppy to do?\n\nx`;
const bug = (a) => `### What went wrong?\n\nx\n\n### Where did this happen?\n\n${a}\n\n### Floppy version\n\nv1`;

test("every feature category maps to its label", () => {
  const cases = {
    "Interface & Usability — Appearance, navigation, sorting and filtering": "interface",
    "Tracking & Media Management — Progress, ratings, notes and collections": "tracking",
    "Integrations & Data Sources — External services, metadata, imports and sync": "integration",
    "Performance & Technical — Speed, resources, deployment, API and MCP": "technical",
  };
  for (const [answer, label] of Object.entries(cases)) assert.deepEqual(labelsFromIssueBody(feature(answer)), [label]);
});

test("every bug platform maps to its label", () => {
  const cases = {
    "Web browser": "web",
    "iOS app": "ios",
    "Android app": "android",
    "Integration or background activity": "integration",
    "Server or installation": "server",
  };
  for (const [answer, label] of Object.entries(cases)) assert.deepEqual(labelsFromIssueBody(bug(answer)), [label]);
});

test("other, multiple, unknown, missing and legacy answers add nothing", () => {
  for (const a of ["Other / Not Sure", "Multiple platforms", "Something new", "", "_No response_"]) {
    assert.deepEqual(labelsFromIssueBody(feature(a)), []);
    assert.deepEqual(labelsFromIssueBody(bug(a)), []);
  }
  assert.deepEqual(labelsFromIssueBody(null), []);
  assert.deepEqual(labelsFromIssueBody("**Describe the solution you'd like**\nstuff"), []);
});

test("CRLF bodies and plain-hyphen separators still match", () => {
  assert.deepEqual(labelsFromIssueBody(feature("Performance & Technical - Speed").replace(/\n/g, "\r\n")), ["technical"]);
});
