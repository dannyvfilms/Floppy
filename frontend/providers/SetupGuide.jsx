import React, { useState } from 'react';
import { Button, Card } from '../ui/controls';
import { mountRoot } from '../settings/root';

function Parts({ parts, values }) {
  return parts.map((part, index) => {
    const [kind, text, url] = part;
    if (kind === 'b') return <strong key={index}> {text} </strong>;
    if (kind === 'em') return <em key={index}> {text} </em>;
    if (kind === 'code') return <code key={index}> {text} </code>;
    if (kind === 'a') return <a key={index} href={url}> {text} </a>;
    if (kind === 'copy') return <CopyValue key={index} id={text} values={values} />;
    return <span key={index}> {text} </span>;
  });
}

// Copyable values come from the server-rendered fallback, never from serialized props.
function CopyValue({ id, values }) {
  const [copied, setCopied] = useState(false);
  const { guide } = values;
  const value = values.copy[id] || '';
  const copy = () => navigator.clipboard?.writeText(value).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500); }, () => {});
  return <span className="ui-copy-value"><code>{value}</code>
    <Button type="button" secondary onClick={copy} aria-label={guide.copyLabel}>{copied ? guide.copiedLabel : guide.copyLabel}</Button></span>;
}

export function SetupGuide({ guide, copy }) {
  const values = { guide, copy };
  return <Card title={guide.title}>
    <p>{guide.description}</p>
    <h4>{guide.heading}</h4>
    <ol className="ui-guide-steps">{guide.steps.map((step, index) => {
      const parts = Array.isArray(step) ? step : step.parts;
      return <li key={index}><Parts parts={parts} values={values} />
        {step.items && <ul>{step.items.map((item, i) => <li key={i}><Parts parts={item} values={values} /></li>)}</ul>}</li>;
    })}</ol>
  </Card>;
}

export function mountSetupGuide(host, guide) {
  const copy = Object.fromEntries([...host.querySelectorAll('input[data-copy-id]')].map(input => [input.dataset.copyId, input.value]));
  return mountRoot(host, <SetupGuide guide={guide} copy={copy} />);
}
