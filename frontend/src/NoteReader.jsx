import { Children, isValidElement } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeRaw from 'rehype-raw'
import rehypeSanitize, { defaultSchema } from 'rehype-sanitize'
import rehypeHighlight from 'rehype-highlight'

// Notes embed raw HTML (<details> transcripts), so rehype-raw is required and
// sanitize is non-negotiable. Highlight runs AFTER sanitize so hljs classes survive.
const schema = {
  ...defaultSchema,
  tagNames: [...(defaultSchema.tagNames || []), 'details', 'summary'],
  attributes: {
    ...defaultSchema.attributes,
    details: ['open'],
    code: [...(defaultSchema.attributes?.code || []), ['className', /^language-/]],
  },
}

// Obsidian dialect → plain markdown: strip frontmatter, unwrap image embeds
// ![[x.png]] and wikilinks [[target|display]] (display text only in v1).
function preprocess(markdown) {
  let text = String(markdown || '')
  text = text.replace(/^---\n[\s\S]*?\n---\n/, '')
  text = text.replace(/!\[\[([^\]|]+?\.(?:png|jpe?g|gif|webp|svg|bmp|avif))(?:\|[^\]]*)?\]\]/gi, '![]($1)')
  text = text.replace(/\[\[([^\]|]+)\|([^\]]+)\]\]/g, '$2')
  text = text.replace(/\[\[([^\]]+)\]\]/g, '$1')
  return text
}

const CALLOUT_LABEL = {
  info: '🛈', note: '🛈', tip: '💡', hint: '💡', success: '✓', check: '✓',
  warning: '⚠', caution: '⚠', danger: '⚠', error: '⚠', quote: '❝', question: '?',
}

// Obsidian callout: blockquote whose first paragraph starts with "[!type] title".
function Blockquote({ children }) {
  const blocks = Children.toArray(children)
  for (const block of blocks) {
    if (!isValidElement(block) || !block.props?.children) continue
    const kids = Children.toArray(block.props.children)
    if (typeof kids[0] !== 'string') continue
    const m = kids[0].match(/^\[!(\w+)\][ \t]*(.*)/)
    if (!m) break
    const type = m[1].toLowerCase()
    const title = [m[2], ...kids.slice(1)]
    const body = blocks.filter((b) => b !== block)
    return (
      <div className={`md-callout md-callout-${type}`}>
        <div className="md-callout-title">{CALLOUT_LABEL[type] || '🛈'} {title}</div>
        {body}
      </div>
    )
  }
  return <blockquote>{children}</blockquote>
}

function timestampChildren(children, onTimestamp) {
  if (!onTimestamp) return children
  return Children.map(children, (child) => {
    if (typeof child !== 'string') return child
    return child.split(/(\[\d{1,2}:\d{2}\])/g).map((part, index) => {
      const match = /^\[(\d{1,2}:\d{2})\]$/.exec(part)
      return match
        ? <button key={`${match[1]}-${index}`} type="button" className="ts ts-seek" onClick={() => onTimestamp(match[1])}>{match[1]}</button>
        : part
    })
  })
}

export default function NoteReader({ content, assetUrl, onTimestamp }) {
  const components = {
    blockquote: Blockquote,
    p({ children, ...props }) {
      return <p {...props}>{timestampChildren(children, onTimestamp)}</p>
    },
    li({ children, ...props }) {
      return <li {...props}>{timestampChildren(children, onTimestamp)}</li>
    },
    img({ src, alt }) {
      const resolved = /^https?:/.test(src || '') ? src : assetUrl ? assetUrl(src) : src
      return <img src={resolved} alt={alt || ''} loading="lazy" />
    },
    a({ href, children }) {
      return <a href={href} target="_blank" rel="noreferrer">{children}</a>
    },
  }
  return (
    <div className="note-reader">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeRaw, [rehypeSanitize, schema], rehypeHighlight]}
        components={components}
      >
        {preprocess(content)}
      </ReactMarkdown>
    </div>
  )
}
