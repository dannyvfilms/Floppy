// Native counterparts of the server error pages (src/templates/{400,403,404,500}.html;
// wording from src/app/error_views.py). `offline` has no server template: it is the
// state the app shows when the server cannot be reached at all.
export const ERROR_PAGES = {
  400: {
    status: 400,
    heading: 'Bad Request',
    message: 'The server could not understand the request due to invalid syntax or missing parameters.',
  },
  403: {
    status: 403,
    heading: 'Access Forbidden',
    message: "You don't have permission to access this resource. Please log in or contact an administrator.",
    checks: [
      "Confirm you're logged in and your session hasn't expired.",
      'Reload the page and try again.',
    ],
  },
  404: {
    status: 404,
    heading: 'Page Not Found',
    message: "The page you are looking for doesn't exist or has been moved.",
  },
  500: {
    status: 500,
    heading: 'Something Went Wrong',
    message: "We're sorry, but there was an error processing your request.",
  },
  offline: {
    status: 503,
    heading: 'Cannot Reach the Server',
    message: 'Could not reach the Floppy server. Check the address and your connection.',
    checks: [
      "Confirm the server is running and you're online.",
      'Check that the server address is correct.',
    ],
  },
};

export const ISSUES_URL = 'https://github.com/dannyvfilms/Floppy/issues';

// Map a transport failure (an AuthError, or any error with `status`/`code`) to
// the page that describes it.
export function errorPageFor(error) {
  const code = error && error.code;
  const status = Number(error && error.status) || 0;
  if (code === 'server_unreachable' || (!status && code !== 'forbidden' && code !== 'not_found')) {
    return ERROR_PAGES.offline;
  }
  if (status === 403 || code === 'forbidden' || code === 'csrf') return ERROR_PAGES[403];
  if (status === 404 || code === 'not_found') return ERROR_PAGES[404];
  if (status >= 500) return ERROR_PAGES[500];
  if (status === 400) return ERROR_PAGES[400];
  return ERROR_PAGES[500];
}

// A message the server sent is shown instead of the generic copy when it is
// plain text, so a specific explanation is not lost.
export function errorPageWithMessage(error) {
  const page = errorPageFor(error);
  const detail = error && typeof error.message === 'string' ? error.message.trim() : '';
  return detail && page !== ERROR_PAGES.offline ? { ...page, message: detail } : page;
}
