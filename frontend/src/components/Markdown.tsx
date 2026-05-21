import { useMemo } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import { CopyButton } from "./CopyButton";

// Pull the language token out of `language-xxx` class produced by remark-gfm
function extractLang(className: string | undefined): string {
  if (!className) return "";
  const m = /language-([a-zA-Z0-9_+-]+)/.exec(className);
  return m ? m[1] : "";
}

function nodeText(node: { children?: { type?: string; value?: string }[] } | undefined): string {
  if (!node || !node.children) return "";
  return node.children
    .filter((c) => c.type === "text" && typeof c.value === "string")
    .map((c) => c.value as string)
    .join("");
}

export function Markdown({ children }: { children: string }) {
  const components = useMemo<Components>(() => {
    return {
      // Render fenced code blocks with header (lang + copy). Inline code keeps default <code>.
      pre({ children: preChildren }) {
        // react-markdown gives us <pre><code …>; introspect that single child.
        const child = Array.isArray(preChildren) ? preChildren[0] : preChildren;
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const codeEl: any = child as any;
        const className: string | undefined = codeEl?.props?.className;
        const lang = extractLang(className);
        const raw = nodeText(codeEl?.props?.node);
        return (
          <div className="code-block-wrap group">
            <div className="code-block-header">
              <span className="font-mono">{lang || "text"}</span>
              <CopyButton text={raw} iconOnly className="opacity-0 transition-opacity group-hover:opacity-100" />
            </div>
            <pre>{preChildren}</pre>
          </div>
        );
      },
      a({ href, children }) {
        return (
          <a href={href} target="_blank" rel="noopener noreferrer">
            {children}
          </a>
        );
      },
    };
  }, []);

  return (
    <div className="markdown-body">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={components}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
