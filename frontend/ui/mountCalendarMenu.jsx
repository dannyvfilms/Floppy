import React from 'react';
import { mountRoot } from '../settings/root';
import { ActionMenu } from './controls';
import { Icon } from './Icon';

function post(url, csrf, fields) {
  return fetch(url, { method: 'POST', headers: { 'X-CSRFToken': csrf }, body: new URLSearchParams(fields) });
}

// Calendar gear menu. The week-start choice reuses the preferences endpoint Statistics
// already saves to, then reloads so the grid is laid out from the new first day.
function CalendarMenu({ props }) {
  const { csrf, labels, urls, weekStart } = props;
  const items = [
    { label: labels.today, href: urls.today },
    { label: labels.fetch, onSelect: () => {
      const form = Object.assign(document.createElement('form'), { method: 'post', action: urls.fetch });
      form.append(Object.assign(document.createElement('input'), { type: 'hidden', name: 'csrfmiddlewaretoken', value: csrf }));
      document.body.append(form);
      form.submit();
    } },
    { label: labels.download, href: urls.download },
    { label: labels.weekStart, actions: ['monday', 'sunday'].map(value => ({
      label: labels[value],
      selected: weekStart === value,
      onSelect: () => weekStart === value ? undefined
        : post(urls.preferences, csrf, { week_start_day: value }).then(() => window.location.reload()),
    })) },
  ];
  return <ActionMenu label={labels.menu} items={items} align="end" secondary
    icon={<Icon spec={props.icon} />} />;
}

export function mountCalendarMenu(host, props) {
  return mountRoot(host, <CalendarMenu props={props} />);
}
