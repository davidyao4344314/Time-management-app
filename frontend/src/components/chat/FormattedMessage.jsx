// Small, deliberately limited formatter. React escapes every text node;
// model text is never interpreted as HTML, scripts or clickable URLs.
function inline(text) {
  return text.split(/(\*\*[^*\n]+\*\*|`[^`\n]+`)/g).map((part, index) => {
    if (part.startsWith('**') && part.endsWith('**')) return <strong key={index}>{part.slice(2, -2)}</strong>
    if (part.startsWith('`') && part.endsWith('`')) return <code key={index}>{part.slice(1, -1)}</code>
    return part
  })
}

export default function FormattedMessage({ text }) {
  const blocks = []
  const lines = String(text || '').split('\n')
  let paragraph = [], items = [], listType = null
  function flushParagraph() {
    if (paragraph.length) { blocks.push(<p key={blocks.length}>{inline(paragraph.join('\n'))}</p>); paragraph = [] }
  }
  function flushList() {
    if (items.length) {
      const List = listType
      blocks.push(<List key={blocks.length}>{items.map((item, index) => <li key={index}>{inline(item)}</li>)}</List>)
      items = []; listType = null
    }
  }
  for (const line of lines) {
    const bullet = line.match(/^\s*(?:[-*]\s+|\d+\.\s+)(.+)$/)
    const heading = line.match(/^#{1,6}\s+(.+)$/)
    if (bullet) {
      flushParagraph()
      const type = /^\s*\d+\./.test(line) ? 'ol' : 'ul'
      if (listType && type !== listType) flushList()
      listType = type; items.push(bullet[1])
    } else {
      flushList()
      if (heading) { flushParagraph(); blocks.push(<h3 key={blocks.length}>{inline(heading[1])}</h3>) }
      else if (!line.trim()) flushParagraph()
      else paragraph.push(line)
    }
  }
  flushParagraph(); flushList()
  return <div className="ai-agent-response-text">{blocks}</div>
}
