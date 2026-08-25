import { marked } from 'marked';
import sanitizeHtml from 'sanitize-html';

/**
 * Renders user-authored markdown to HTML.
 *
 * Descriptions and comments are written by team members but are still
 * untrusted input: the output is injected with dangerouslySetInnerHTML, so it
 * is sanitised with a strict allow-list AFTER rendering. Never bypass this.
 */
const ALLOWED_TAGS = [
  'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
  'p', 'br', 'hr', 'blockquote',
  'ul', 'ol', 'li',
  'strong', 'em', 'del', 'code', 'pre',
  'a', 'table', 'thead', 'tbody', 'tr', 'th', 'td',
  'input', // task-list checkboxes only; forced disabled below
];

export function renderMarkdown(source: string): string {
  if (!source || !source.trim()) return '';

  const raw = marked.parse(source, { async: false, gfm: true, breaks: true }) as string;

  return sanitizeHtml(raw, {
    allowedTags: ALLOWED_TAGS,
    allowedAttributes: {
      a: ['href', 'title', 'target', 'rel'],
      code: ['class'],
      input: ['type', 'checked', 'disabled'],
      th: ['align'],
      td: ['align'],
    },
    // Blocks javascript:, data: and vbscript: URLs.
    allowedSchemes: ['http', 'https', 'mailto'],
    allowedSchemesAppliedToAttributes: ['href'],
    disallowedTagsMode: 'discard',
    transformTags: {
      a: (tagName, attribs) => ({
        tagName,
        attribs: { ...attribs, target: '_blank', rel: 'noopener noreferrer nofollow' },
      }),
      // A checkbox in rendered markdown must never be interactive.
      input: (tagName, attribs) => ({
        tagName,
        attribs: { type: 'checkbox', disabled: 'disabled', ...(attribs.checked ? { checked: 'checked' } : {}) },
      }),
    },
  });
}

/** Plain-text preview for board cards and list rows. */
export function toPlainText(source: string, maxLength = 160): string {
  const text = sanitizeHtml(marked.parse(source ?? '', { async: false, gfm: true }) as string, {
    allowedTags: [],
    allowedAttributes: {},
  })
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/\s+/g, ' ')
    .trim();

  return text.length > maxLength ? `${text.slice(0, maxLength - 1)}…` : text;
}
