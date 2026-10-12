import type { ComponentProps } from 'react'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'

/** A document's markdown, drawn for reading. Read mode only — edit mode shows the source, since
 * the source is what gets saved.
 *
 * These documents are edited by teammates, so nothing in one may reach the app as behaviour:
 *  - raw HTML is dropped (`skipHtml`), which also hides the `<!-- ... -->` scaffolding
 *    comments templates carry;
 *  - a link is drawn as its text, never as an anchor, so nothing in a document can navigate the
 *    app window — the address stays in a tooltip for anyone who wants it;
 *  - an image is drawn as its description, so a document cannot make the app fetch a remote URL.
 */

const Heading = (className: string) =>
  function HeadingTag({ children }: ComponentProps<'h3'>) {
    return <h4 className={className}>{children}</h4>
  }

const components: Components = {
  h1: Heading('mt-3 text-sm font-semibold text-ink-1 first:mt-0'),
  h2: Heading('mt-3 text-sm font-semibold text-ink-1 first:mt-0'),
  h3: Heading('mt-3 text-sm font-semibold text-ink-1 first:mt-0'),
  h4: Heading('mt-2 text-sm font-medium text-ink-1 first:mt-0'),
  h5: Heading('mt-2 text-sm font-medium text-ink-2 first:mt-0'),
  h6: Heading('mt-2 text-sm font-medium text-ink-2 first:mt-0'),
  p: ({ children }) => <p className="mt-1.5 text-sm leading-relaxed text-ink-1 first:mt-0">{children}</p>,
  ul: ({ children, className }) => (
    <ul className={`mt-1.5 space-y-0.5 pl-5 text-sm text-ink-1 first:mt-0 ${
      className?.includes('contains-task-list') ? 'list-none pl-0' : 'list-disc'}`}
    >
      {children}
    </ul>
  ),
  ol: ({ children }) => <ol className="mt-1.5 list-decimal space-y-0.5 pl-5 text-sm text-ink-1 first:mt-0">{children}</ol>,
  li: ({ children }) => <li className="leading-relaxed">{children}</li>,
  // A glyph, not a disabled <input>: DocumentView's rule is that no control exists outside edit
  // mode, and a disabled checkbox still says "you could tick this here".
  input: ({ type, checked }) =>
    type === 'checkbox'
      ? <span role="img" aria-label={checked ? 'done' : 'not done'} className="mr-2 text-ink-3">{checked ? '☑' : '☐'}</span>
      : null,
  strong: ({ children }) => <strong className="font-semibold text-ink-1">{children}</strong>,
  em: ({ children }) => <em className="italic">{children}</em>,
  code: ({ children }) => <code className="rounded bg-surface-2 px-1 py-0.5 font-mono text-xs text-ink-1">{children}</code>,
  pre: ({ children }) => (
    <pre className="mt-1.5 overflow-x-auto rounded-lg bg-surface-2 p-3 font-mono text-xs text-ink-1 first:mt-0">{children}</pre>
  ),
  blockquote: ({ children }) => (
    <blockquote className="mt-1.5 border-l-2 border-line-2 pl-3 text-sm italic text-ink-3 first:mt-0">{children}</blockquote>
  ),
  hr: () => <hr className="my-3 border-line-1" />,
  table: ({ children }) => (
    <div className="mt-1.5 overflow-x-auto first:mt-0">
      <table className="w-full border-collapse text-left text-sm">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className="bg-surface-0">{children}</thead>,
  th: ({ children }) => <th className="border border-line-1 px-2.5 py-1.5 font-medium text-ink-2">{children}</th>,
  td: ({ children }) => <td className="border border-line-1 px-2.5 py-1.5 align-top text-ink-1">{children}</td>,
  a: ({ href, children }) => <span className="underline decoration-line-2" title={href}>{children}</span>,
  img: ({ alt }) => (alt ? <span className="italic text-ink-3">[image: {alt}]</span> : null),
}

export function MarkdownView({ source }: { source: string }) {
  if (source.trim() === '') return null
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml components={components}>
      {source}
    </ReactMarkdown>
  )
}
