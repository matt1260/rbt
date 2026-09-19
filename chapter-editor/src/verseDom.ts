/**
 * Server-parity rendering of one verse inside its .rbt-verse wrapper, matching the
 * paraphrase loop in handle_nt_chapter (search/views/chapter_handlers.py).
 */

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
