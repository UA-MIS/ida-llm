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
