// Status chip shapes, copied from the web card's inline SVGs so native draws the
// same icons through the shared Icon contract (viewBox 24, 2px round stroke).
const n = (tag, attrs) => ({ tag, attrs, children: [] });
const spec = (...children) => ({
  viewBox: '0 0 24 24',
  root: { fill: 'none', stroke: 'currentColor', 'stroke-width': '2', 'stroke-linecap': 'round', 'stroke-linejoin': 'round' },
  children,
});

export const STATUS_ICON_SPECS = {
  Completed: spec(n('path', { d: 'M21.801 10A10 10 0 1 1 17 3.335' }), n('path', { d: 'm9 11 3 3L22 4' })),
  'In progress': spec(n('polygon', { points: '6 3 20 12 6 21 6 3' })),
  Paused: spec(n('rect', { x: '14', y: '4', width: '4', height: '16', rx: '1' }),
    n('rect', { x: '6', y: '4', width: '4', height: '16', rx: '1' })),
  Planning: spec(n('path', { d: 'm19 21-7-4-7 4V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v16z' }),
    n('line', { x1: '12', x2: '12', y1: '7', y2: '13' }), n('line', { x1: '15', x2: '9', y1: '10', y2: '10' })),
  Dropped: spec(n('path', { d: 'm15 9-6 6' }),
    n('path', { d: 'M2.586 16.726A2 2 0 0 1 2 15.312V8.688a2 2 0 0 1 .586-1.414l4.688-4.688A2 2 0 0 1 8.688 2h6.624a2 2 0 0 1 1.414.586l4.688 4.688A2 2 0 0 1 22 8.688v6.624a2 2 0 0 1-.586 1.414l-4.688 4.688a2 2 0 0 1-1.414.586H8.688a2 2 0 0 1-1.414-.586z' }),
    n('path', { d: 'm9 9 6 6' })),
};
