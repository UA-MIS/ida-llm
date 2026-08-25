import { describe, it, expect } from 'vitest';
import { renderMarkdown, toPlainText } from '@/lib/markdown';

describe('renderMarkdown — XSS hardening', () => {
  it('renders ordinary markdown', () => {
    const html = renderMarkdown('# Title\n\nSome **bold** and `code`.');
    expect(html).toContain('<h1>Title</h1>');
    expect(html).toContain('<strong>bold</strong>');
    expect(html).toContain('<code>code</code>');
  });

  it('strips raw script tags', () => {
    const html = renderMarkdown('Hello <script>alert(document.cookie)</script> world');
    expect(html).not.toContain('<script');
    expect(html).not.toContain('alert(');
  });

  it('strips inline event handlers', () => {
    const html = renderMarkdown('<img src=x onerror="alert(1)">');
    expect(html).not.toContain('onerror');
    expect(html).not.toContain('alert(1)');
    // The tag itself now survives -- which is precisely why the attribute
    // allow-list, not the tag allow-list, has to be what kills the handler.
    expect(html).toContain('<img');
  });

  it('neutralises javascript: links', () => {
    const html = renderMarkdown('[click me](javascript:alert(1))');
    expect(html).not.toContain('javascript:');
  });

  it('neutralises data: URLs', () => {
    const html = renderMarkdown('[x](data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==)');
    expect(html).not.toContain('data:text/html');
  });

  it('drops iframes, objects, embeds, forms and styles', () => {
    const html = renderMarkdown(
      '<iframe src="//evil"></iframe><object data="x"></object><embed src="x"><form action="/x"><input name="a"></form><style>body{display:none}</style>',
    );
    for (const tag of ['<iframe', '<object', '<embed', '<form', '<style']) {
      expect(html, `${tag} must be stripped`).not.toContain(tag);
    }
  });

  it('keeps safe links but forces them to open safely', () => {
    const html = renderMarkdown('[GitHub](https://github.com/UA-MIS/ida-llm)');
    expect(html).toContain('href="https://github.com/UA-MIS/ida-llm"');
    expect(html).toContain('rel="noopener noreferrer nofollow"');
    expect(html).toContain('target="_blank"');
  });

  it('renders task list checkboxes as disabled', () => {
    const html = renderMarkdown('- [x] done\n- [ ] todo');
    expect(html).toContain('disabled');
    expect(html).not.toMatch(/<input(?![^>]*disabled)/);
  });

  it('returns an empty string for blank input', () => {
    expect(renderMarkdown('')).toBe('');
    expect(renderMarkdown('   ')).toBe('');
  });
});

describe('renderMarkdown — images are allowed, but only relative or https', () => {
  it('renders a relative image, which is how the board loads its diagrams', () => {
    const html = renderMarkdown('![Architecture](/architecture.svg)');
    expect(html).toContain('<img');
    expect(html).toContain('src="/architecture.svg"');
    expect(html).toContain('alt="Architecture"');
  });

  it('keeps an https image', () => {
    const html = renderMarkdown('![x](https://example.org/a.png)');
    expect(html).toContain('src="https://example.org/a.png"');
  });

  it('drops a data: image source', () => {
    const html = renderMarkdown(
      '![x](data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciPjxzY3JpcHQ+YWxlcnQoMSk8L3NjcmlwdD48L3N2Zz4=)',
    );
    expect(html).not.toContain('data:image');
    expect(html).not.toContain('base64');
  });

  it('drops a javascript: image source', () => {
    const html = renderMarkdown('![x](javascript:alert(1))');
    expect(html).not.toContain('javascript:');
    expect(html).not.toContain('alert(1)');
  });

  it('drops a protocol-relative image source', () => {
    const html = renderMarkdown('![x](//evil.example/a.svg)');
    expect(html).not.toContain('//evil.example');
  });

  it('drops a protocol-relative link href too', () => {
    const html = renderMarkdown('[x](//evil.example/page)');
    expect(html).not.toContain('//evil.example');
  });

  it('drops a plain http image, so a diagram cannot become mixed content', () => {
    const html = renderMarkdown('![x](http://insecure.example/a.png)');
    expect(html).not.toContain('http://insecure.example');
  });

  it('allows no attribute on an image beyond src, alt and title', () => {
    const html = renderMarkdown(
      '<img src="/a.svg" alt="a" title="t" onload="alert(1)" onerror="alert(2)" srcset="//evil/x 1x" formaction="/x" style="position:fixed">',
    );
    expect(html).toContain('src="/a.svg"');
    for (const banned of ['onload', 'onerror', 'srcset', 'formaction', 'style', 'alert(']) {
      expect(html, `${banned} must not survive on an img`).not.toContain(banned);
    }
  });

  it('still refuses inline svg, which can carry script', () => {
    const html = renderMarkdown('<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>');
    expect(html).not.toContain('<svg');
    expect(html).not.toContain('<script');
    expect(html).not.toContain('alert(1)');
  });

  it('does not let an uppercase or spaced scheme sneak past', () => {
    for (const src of ['JavaScript:alert(1)', ' javascript:alert(1)', 'JAVASCRIPT:alert(1)']) {
      const html = renderMarkdown(`![x](${src})`);
      expect(html.toLowerCase(), `${src} must be neutralised`).not.toContain('javascript:');
    }
  });

  it('leaves image markup out of card previews', () => {
    expect(toPlainText('![Architecture](/architecture.svg) after')).not.toContain('architecture.svg');
  });
});

describe('toPlainText', () => {
  it('flattens markdown to a single line', () => {
    expect(toPlainText('# Title\n\nBody **text** here.')).toBe('Title Body text here.');
  });

  it('removes markup entirely, including scripts', () => {
    expect(toPlainText('<script>alert(1)</script>hello')).not.toContain('alert');
  });

  it('truncates with an ellipsis', () => {
    const out = toPlainText('x'.repeat(500), 20);
    expect(out).toHaveLength(20);
    expect(out.endsWith('…')).toBe(true);
  });
});
