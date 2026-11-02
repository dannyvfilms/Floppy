import React, { useState } from 'react';
import { Button, Card } from '../ui/controls';
import { mountRoot } from '../settings/root';

function Parts({ parts, values }) {
  return parts.map((part, index) => {
    const [kind, text, url] = part;
    if (kind === 'b') return <strong key={index}> {text} </strong>;
    if (kind === 'em') return <em key={index}> {text} </em>;
    if (kind === 'code') return <code key={index}> {text} </code>;
    if (kind === 'pre') return <PreBlock key={index} text={text} values={values} />;
    if (kind === 'clink') return <a key={index} href={values.copy[url] || '#'}> {text} </a>;
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

function PreBlock({ text, values }) {
  const [copied, setCopied] = useState(false);
  const { guide } = values;
  const copy = () => navigator.clipboard?.writeText(text).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500); }, () => {});
  return <span className="ui-copy-block"><pre>{text}</pre>
    <Button type="button" secondary onClick={copy} aria-label={guide.copyLabel}>{copied ? guide.copiedLabel : guide.copyLabel}</Button></span>;
}

export function SetupGuide({ guide, copy }) {
  const values = { guide, copy };
  const Wrapper = guide.bare ? 'div' : Card;
  return <Wrapper {...(guide.bare ? {} : { title: guide.title })}>
    {!guide.bare && <p>{guide.description}</p>}
    {guide.warning && <p role="alert" data-testid="jellyfin-template-outdated"><strong>{guide.warning.title}</strong> {guide.warning.text}</p>}
    <h4>{guide.heading}</h4>
    <ol className="ui-guide-steps">{guide.steps.map((step, index) => {
      const parts = Array.isArray(step) ? step : step.parts;
      return <li key={index}><Parts parts={parts} values={values} />
        {step.items && <ul>{step.items.map((item, i) => <li key={i}><Parts parts={item} values={values} /></li>)}</ul>}</li>;
    })}</ol>
  </Wrapper>;
}

export function mountSetupGuide(host, guide) {
  const copy = Object.fromEntries([...host.querySelectorAll('input[data-copy-id]')].map(input => [input.dataset.copyId, input.value]));
  return mountRoot(host, <SetupGuide guide={guide} copy={copy} />);
}
