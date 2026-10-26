/**
 * Server-parity rendering of one verse inside its .rbt-verse wrapper, matching the verse
 * loops in search/views/chapter_handlers.py (NT, Genesis and OT chapters).
 *
 * A verse's editing key is its number, or 'literal:N' for Genesis's Hebrew literal, which
 * the Genesis page shows beside the RBT Translation (the wrapper's data-key).
 */

export function keyOf(wrapper: HTMLElement): string {
  return wrapper.dataset.key ?? wrapper.dataset.verse ?? ''
}

export const isLiteral = (key: string) => key.startsWith('literal:')

export const verseNumber = (key: string) => key.slice(key.indexOf(':') + 1)

/** "3", or "3 (Hebrew literal)", for messages ("Verse 3 (Hebrew literal) didn't save"). */
export function verseLabel(key: string): string {
  return isLiteral(key) ? `${verseNumber(key)} (Hebrew literal)` : key
}

/** The Genesis Hebrew literal: the ref inside its paragraph (the second, if it has two), no closing <br>. */
export function composeLiteral(html: string, refHtml: string): string {
  const split = html.indexOf('</p><p>')
  if (split >= 0) return `${html.slice(0, split)}</p><p>${refHtml}${html.slice(split + '</p><p>'.length)}`
  if (html.startsWith('<p>')) return `<p>${refHtml}${html.slice(3)}`
  return `${refHtml}${html}`
}

export function closeText(html: string): string {
  return html.endsWith('</span>') ? '' : '<br>'
}

/** heading + ref + rest, or ref + ' ' + verse, followed by <br> unless the verse ends in </span>. */
export function composeVerse(html: string, refHtml: string): string {
  const close = closeText(html)
  if (html.includes('<h5>')) {
    const match = /^([\s\S]*?<\/h5>)([\s\S]*)$/.exec(html)
    return match ? `${match[1]}${refHtml}${match[2]}${close}` : `${refHtml}${html}${close}`
  }
  return `${refHtml} ${html}${close}`
}

// Same pattern as wrapParenthesesText() in static/chapter-viewer.js: parentheses holding
// a quoted name, e.g. ("Bethlehem"), hidden by default on the chapter page.
const QUOTED_PARENS = /\(\s*["“”„«»‹›'‘’][^)]*?["“”„«»‹›'‘’]\s*\)/g

function isAion(match: string): boolean {
  const inner = match
    .slice(1, -1)
    .trim()
    .replace(/^["“”„«»‹›'‘’]+|["“”„«»‹›'‘’]+$/g, '')
    .normalize('NFD')
    .replace(/\p{M}/gu, '')
    .toLowerCase()
    .replace(/[^a-z]+/g, '')
  return inner === 'aion'
}

/**
 * Re-apply the chapter page's hidden-names treatment to a freshly rendered verse, so an
 * edited verse doesn't suddenly show its parenthesised names.
 */
export function wrapParentheses(root: HTMLElement): void {
  const existing = document.querySelector<HTMLElement>('.paren-hide')
  const hidden = existing ? existing.style.display === 'none' : true
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  const texts: Text[] = []
  while (walker.nextNode()) texts.push(walker.currentNode as Text)

  for (const text of texts) {
    if (text.parentElement?.closest('h5, .paren-hide')) continue
    const value = text.nodeValue ?? ''
    QUOTED_PARENS.lastIndex = 0
    if (!QUOTED_PARENS.test(value)) continue

    const fragment = document.createDocumentFragment()
    let last = 0
    for (const match of value.matchAll(QUOTED_PARENS)) {
      if (isAion(match[0])) continue
      const end = match.index! + match[0].length
      let before = value.slice(last, match.index)
      const span = document.createElement('span')
      span.className = 'paren-hide'
      span.textContent = match[0]
      if (hidden) {
        // Like hideParenSpan(): drop the space before a hidden name when punctuation follows,
        // remembering it so the page's Names (P) toggle can put it back.
        const trailing = /(\s+)$/.exec(before)
        if (trailing && /^[,.;:!?)%]/.test(value.slice(end))) {
          span.dataset.prevTrailingSpaces = trailing[1]
          before = before.slice(0, -trailing[1].length)
        }
        span.style.setProperty('display', 'none', 'important')
      }
      fragment.append(before, span)
      last = end
    }
    if (last === 0) continue
    fragment.append(value.slice(last))
    text.replaceWith(fragment)
  }
}
