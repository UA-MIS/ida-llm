/**
 * A small YAML EMITTER (no parser) for showing a task document as editable
 * YAML in the admin task editor. The design allows no new dependencies, and
 * the browser never needs to parse: edited YAML is sent to the API, which
 * parses it with `yaml.safe_load` and validates it.
 *
 * The output is deliberately conservative so it always re-parses to the same
 * JSON value: keys and plain-looking strings are double-quoted JSON strings
 * unless they are clearly safe bare words; multi-line strings use a literal
 * block (`|`, `|-`, `|+`) only when that round-trips exactly.
 */

type Json = null | boolean | number | string | Json[] | { [k: string]: Json };

const BARE = /^[A-Za-z_][A-Za-z0-9_./-]*$/;
/** Words YAML 1.1 (PyYAML) would read as something other than a string. */
const RESERVED = /^(true|false|yes|no|on|off|y|n|null|~)$/i;

function scalar(s: string): string {
  return BARE.test(s) && !RESERVED.test(s) ? s : JSON.stringify(s);
}

/** PyYAML (YAML 1.1) reads `1e+21` as a string; it needs `1.0e+21`. */
function number(n: number): string {
  const s = String(n);
  return /e/.test(s) && !/\./.test(s) ? s.replace("e", ".0e") : s;
}

function blockable(s: string): boolean {
  if (!s.includes("\n") || /[\r\t]/.test(s)) return false;
  const lines = s.replace(/\n+$/, "").split("\n");
  // A first line starting with a space needs an indentation indicator; any
  // trailing spaces or non-printing characters are safer quoted.
  if (/^ /.test(lines[0] ?? "")) return false;
  return lines.every((l) => !/ $/.test(l) && !/[\u0000-\u0008\u000b-\u001f\u007f\u0085\u2028\u2029\ufeff]/.test(l));
}

function block(s: string, indent: string): string {
  const trailing = s.match(/\n*$/)![0].length;
  const chomp = trailing === 0 ? "|-" : trailing === 1 ? "|" : "|+";
  const body = s.slice(0, s.length - trailing);
  const lines = body.split("\n").map((l) => (l ? indent + l : ""));
  const extra = trailing > 1 ? "\n".repeat(trailing - 1) : "";
  return `${chomp}\n${lines.join("\n")}${extra}`;
}

function value(v: Json, indent: string): string {
  if (v === null) return "null";
  if (typeof v === "boolean") return v ? "true" : "false";
  if (typeof v === "number") return Number.isFinite(v) ? number(v) : JSON.stringify(String(v));
  if (typeof v === "string") return blockable(v) ? block(v, indent + "  ") : scalar(v);
  return "";
}

function emit(v: Json, indent: string): string {
  if (Array.isArray(v)) {
    if (!v.length) return "[]";
    return v
      .map((item) => {
        if (item !== null && typeof item === "object" && !(Array.isArray(item) && !item.length) && !(isObj(item) && !Object.keys(item).length)) {
          const inner = emit(item, indent + "  ");
          return `\n${indent}- ${inner.replace(/^\n\s*/, "")}`;
        }
        return `\n${indent}- ${leaf(item, indent + "  ")}`;
      })
      .join("");
  }
  if (isObj(v)) {
    const keys = Object.keys(v);
    if (!keys.length) return "{}";
    return keys
      .map((k) => {
        const item = v[k]!;
        const head = `\n${indent}${scalar(k)}:`;
        if (item !== null && typeof item === "object" && !isEmpty(item)) return head + emit(item, indent + "  ");
        return `${head} ${leaf(item, indent)}`;
      })
      .join("");
  }
  return value(v, indent);
}

function leaf(v: Json, indent: string): string {
  if (Array.isArray(v)) return "[]";
  if (isObj(v)) return "{}";
  return value(v, indent);
}

function isObj(v: Json): v is { [k: string]: Json } {
  return v !== null && typeof v === "object" && !Array.isArray(v);
}

function isEmpty(v: Json): boolean {
  return Array.isArray(v) ? v.length === 0 : isObj(v) ? Object.keys(v).length === 0 : false;
}

/** Render a JSON-compatible value as block YAML. */
export function toYaml(doc: unknown): string {
  const out = emit(JSON.parse(JSON.stringify(doc ?? null)) as Json, "");
  return out.replace(/^\n/, "") + "\n";
}
