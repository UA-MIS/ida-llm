import { marked } from 'marked';
import sanitizeHtml from 'sanitize-html';

/**
 * Renders user-authored markdown to HTML.
 *
 * Descriptions and comments are written by team members but are still
 * untrusted input: the output is injected with dangerouslySetInnerHTML, so it
 * is sanitised with a strict allow-list AFTER rendering. Never bypass this.
 *
 * IMAGES
 * ------
 * `img` is allowed so narrative pages can carry the architecture diagrams. The
 * allow-list is widened by exactly one tag, three attributes and one scheme:
 *
 *   - attributes are `src`, `alt`, `title` and nothing else, so every event
 *     handler (`onerror`, `onload`, …) is dropped by omission rather than by a
 *     blocklist that has to guess the next attribute name;
 *   - `allowedSchemesAppliedToAttributes` now covers `src` as well as `href`.
 *     Without that entry the scheme rules simply would not run on `src`, and
 *     `data:`/`javascript:` image sources would be legal;
 *   - `allowedSchemesByTag` gives images an EMPTY scheme list, which is
 *     stricter than any list of schemes: a `src` carrying any scheme at all is
 *     rejected, so an image resolves same-origin or not at all. The two
 *     diagrams this exists for are `/architecture.svg` and `/workflow.svg`,
 *     both relative, so nothing legitimate needs a scheme;
 *   - `allowProtocolRelative` is off, so `//host/x.svg` is not a back door
 *     around the scheme rules for either `src` or `href`.
 *
 * Same-origin-only is what closes off-origin image loading in ALL its
 * spellings, which an allow-list of schemes does not. `https:/\evil/x.png` is
 * read by this library as scheme `https` and by a browser as
 * `https://evil/x.png`, so an `https`-allowing policy passes a request to a
 * host the page author chose -- no script, but the author learns the IP, the
 * user agent and a Referer carrying the item id of every reader. Plain
 * `https://evil/x.png` is the same leak spelled honestly. An empty scheme list
 * ends the whole class rather than the one spelling `allowProtocolRelative`
 * covers.
 *
 * `svg` is deliberately NOT allowed: inline SVG carries scripts and event
 * handlers. An SVG referenced through `<img src>` is safe for a different
 * reason -- browsers load it in a context that cannot run script or fetch
 * subresources -- which is the form the board actually uses.
 */
const ALLOWED_TAGS = [
  'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
  'p', 'br', 'hr', 'blockquote',
  'ul', 'ol', 'li',
  'strong', 'em', 'del', 'code', 'pre',
  'a', 'table', 'thead', 'tbody', 'tr', 'th', 'td',
  'img', // relative or https sources only; see the note above
  'input', // task-list checkboxes only; forced disabled below
];

export function renderMarkdown(source: string): string {
  if (!source || !source.trim()) return '';

  const raw = marked.parse(source, { async: false, gfm: true, breaks: true }) as string;

  return sanitizeHtml(raw, {
    allowedTags: ALLOWED_TAGS,
    allowedAttributes: {
      a: ['href', 'title', 'target', 'rel'],
      img: ['src', 'alt', 'title'],
      code: ['class'],
      input: ['type', 'checked', 'disabled'],
      th: ['align'],
      td: ['align'],
    },
    // Blocks javascript:, data: and vbscript: URLs.
    allowedSchemes: ['http', 'https', 'mailto'],
    // `src` must be listed or the scheme rules never run on an image source.
    // `cite` is carried so the policy stays correct if it is ever allowed --
    // this replaces the library default ['href', 'src', 'cite'] and must not
    // silently narrow it.
    allowedSchemesAppliedToAttributes: ['href', 'src', 'cite'],
    // Empty on purpose: an image may carry NO scheme, i.e. same-origin only.
    allowedSchemesByTag: { img: [] },
    // `//host/x` must not slip past the scheme rules.
    allowProtocolRelative: false,
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
