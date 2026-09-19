/**
 * Round-trip audit: parse every stored NT verse into the editor schema and serialise it
 * back. Verses that don't come back identical (modulo whitespace) stay read-only in the
 * editor, so this reports how many verses that is and why.
 *
 *   python manage.py dump_nt_verses /tmp/nt_verses.json
 *   npm run roundtrip -- /tmp/nt_verses.json
 */
import { readFileSync } from 'node:fs'
import { JSDOM } from 'jsdom'
import { normalizeHtml, parseVerse, serializeDoc } from '../src/schema'

const file = process.argv[2]
if (!file) {
  console.error('usage: npm run roundtrip -- <verses.json>')
  process.exit(2)
}

const { window } = new JSDOM('<!doctype html><html><body></body></html>')
const doc = window.document
// schema.ts's toDOM helpers reference the global document (only used for display).
Object.assign(globalThis, { document: doc, HTMLElement: window.HTMLElement })

const verses: { ref: string; html: string }[] = JSON.parse(readFileSync(file, 'utf-8'))
const failures: { ref: string; expected: string; actual: string }[] = []
let editableBlocks = 0
let rawBlocks = 0

for (const { ref, html } of verses) {
  let actual: string
  try {
    const pmDoc = parseVerse(html, doc)
    pmDoc.forEach((block) => (block.type.name === 'raw_block' ? rawBlocks++ : editableBlocks++))
    actual = normalizeHtml(serializeDoc(pmDoc, doc), doc)
  } catch (error) {
    actual = `THREW: ${error}`
  }
  const expected = normalizeHtml(html, doc)
  if (actual !== expected) failures.push({ ref, expected, actual })
}

console.log(`${verses.length} verses, ${failures.length} do not round-trip (read-only in the editor)`)
console.log(`${editableBlocks} editable blocks, ${rawBlocks} raw (non-editable) blocks`)

const firstDiff = (a: string, b: string) => {
  let i = 0
  while (i < a.length && a[i] === b[i]) i++
  return i
}
for (const { ref, expected, actual } of failures.slice(0, 25)) {
  const at = firstDiff(expected, actual)
  console.log(`\n${ref} (first difference at ${at})`)
  console.log(`  stored: …${expected.slice(Math.max(0, at - 60), at + 80)}…`)
  console.log(`  editor: …${actual.slice(Math.max(0, at - 60), at + 80)}…`)
}
process.exit(failures.length ? 1 : 0)
