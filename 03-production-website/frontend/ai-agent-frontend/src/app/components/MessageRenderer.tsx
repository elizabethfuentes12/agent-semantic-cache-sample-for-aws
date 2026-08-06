import { useState, useEffect, useRef, useId } from "react";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";
import {
  Copy,
  Check,
  Wrench,
  CheckCircle2,
  MessageSquare,
  Sparkles,
  ChevronRight,
  ChevronDown,
  Loader2,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Button } from "./ui/button";
import { Badge } from "./ui/badge";
import { CopyFormatButton } from "./CopyFormatButton";

interface AgentResponse {
  type: "tool_call" | "tool_result" | "message" | "complete";
  tool?: string;
  toolUseId?: string;
  input?: any;
  result?: string;
  content?: string;
  answer?: string;
}

interface MessageRendererProps {
  content: string;
}

export function MessageRenderer({
  content,
}: MessageRendererProps) {
  let response: AgentResponse;

  try {
    response = JSON.parse(content);
  } catch {
    // If not JSON, render as plain text
    return <div className="whitespace-pre-wrap">{content}</div>;
  }

  switch (response.type) {
    case "tool_call":
      return (
        <ToolCallRenderer
          tool={response.tool}
          input={response.input}
          result={response.result}
        />
      );
    case "tool_result":
      return (
        <ToolCallRenderer
          tool={response.tool}
          result={response.result}
          defaultExpanded
        />
      );
    case "message":
      return (
        <MessageContentRenderer content={response.content} />
      );
    case "complete":
      return <CompleteRenderer answer={response.answer} />;
    default:
      return (
        <div className="whitespace-pre-wrap">{content}</div>
      );
  }
}

function ToolCallRenderer({
  tool,
  input,
  result,
  defaultExpanded = false,
}: {
  tool?: string;
  input?: any;
  result?: string;
  defaultExpanded?: boolean;
}) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const hasResult = result !== undefined;

  return (
    <div className="inline-flex flex-col">
      <button
        onClick={() => setExpanded(!expanded)}
        className={`inline-flex items-center gap-1.5 px-2 py-1 rounded-md transition-colors text-xs ${
          hasResult
            ? 'bg-green-500/10 hover:bg-green-500/20'
            : 'bg-amber-500/10 hover:bg-amber-500/20'
        }`}
      >
        {expanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        {hasResult ? (
          <CheckCircle2 className="w-3 h-3 text-green-500" />
        ) : (
          <Loader2 className="w-3 h-3 text-amber-500 animate-spin" />
        )}
        <span className="font-medium">{tool}</span>
      </button>
      {expanded && (
        <div className="mt-1 ml-2 space-y-1">
          {input && (
            <div>
              <div className="text-[10px] uppercase text-muted-foreground font-semibold mb-0.5">Input</div>
              <SyntaxHighlighter
                language="json"
                style={oneDark}
                customStyle={{ margin: 0, borderRadius: "0.375rem", fontSize: "0.75rem", padding: "0.5rem" }}
              >
                {JSON.stringify(input, null, 2)}
              </SyntaxHighlighter>
            </div>
          )}
          {result && (
            <div>
              <div className="text-[10px] uppercase text-muted-foreground font-semibold mb-0.5">Result</div>
              <pre className="text-xs whitespace-pre-wrap font-mono bg-secondary/50 rounded-md p-2 max-h-48 overflow-auto">
                {result}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function MessageContentRenderer({
  content,
}: {
  content?: string;
}) {
  if (!content) return null;

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 mb-2">
        <MessageSquare className="w-4 h-4 text-blue-500" />
        <span className="font-medium">Assistant Message</span>
      </div>
      <div className="prose prose-sm dark:prose-invert max-w-none">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            code(props) {
              const {
                node,
                className,
                children,
                ...rest
              } = props;
              const match = /language-(\w+)/.exec(
                className || "",
              );
              const language = match ? match[1] : "";
              const codeStr = String(children).replace(/\n$/, "");
              const isInline =
                !className?.includes("language-") &&
                !String(children).includes("\n");

              if (!isInline && language === "mermaid") {
                return <MermaidBlock code={codeStr} />;
              }

              return !isInline ? (
                <CodeBlock
                  code={`\`\`\`${language}\n${codeStr}\n\`\`\``}
                />
              ) : (
                <code
                  className="bg-muted px-1.5 py-0.5 rounded text-sm font-mono"
                  {...rest}
                >
                  {children}
                </code>
              );
            },
            p(props) {
              const hasBlock = Array.isArray(props.children)
                ? props.children.some(
                    (child: unknown) =>
                      child != null &&
                      typeof child === 'object' &&
                      'type' in (child as Record<string, unknown>) &&
                      typeof (child as Record<string, unknown>).type !== 'string',
                  )
                : false;
              return hasBlock ? (
                <div className="mb-2 last:mb-0">
                  {props.children}
                </div>
              ) : (
                <p className="mb-2 last:mb-0">
                  {props.children}
                </p>
              );
            },
            ul(props) {
              return (
                <ul className="list-disc pl-4 mb-2">
                  {props.children}
                </ul>
              );
            },
            ol(props) {
              return (
                <ol className="list-decimal pl-4 mb-2">
                  {props.children}
                </ol>
              );
            },
            li(props) {
              return <li className="mb-1">{props.children}</li>;
            },
            a(props) {
              return (
                <a
                  href={props.href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-blue-600 dark:text-blue-400 underline hover:text-blue-800 dark:hover:text-blue-300"
                >
                  {props.children}
                </a>
              );
            },
            blockquote(props) {
              return (
                <blockquote className="border-l-4 border-muted-foreground/30 pl-4 italic my-2">
                  {props.children}
                </blockquote>
              );
            },
            table(props) {
              return (
                <div className="overflow-x-auto my-2">
                  <table className="min-w-full border-collapse border border-border text-sm">
                    {props.children}
                  </table>
                </div>
              );
            },
            thead(props) {
              return <thead className="bg-muted">{props.children}</thead>;
            },
            th(props) {
              return (
                <th className="border border-border px-3 py-2 text-left font-semibold">
                  {props.children}
                </th>
              );
            },
            td(props) {
              return (
                <td className="border border-border px-3 py-2">
                  {props.children}
                </td>
              );
            },
            tr(props) {
              return <tr className="even:bg-muted/50">{props.children}</tr>;
            },
          }}
        >
          {content}
        </ReactMarkdown>
      </div>
    </div>
  );
}

function CompleteRenderer({ answer }: { answer?: string }) {
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <Sparkles className="w-4 h-4 text-purple-500" />
        <span className="font-medium">Final Answer</span>
      </div>
      <div className="relative bg-gradient-to-r from-purple-500/10 to-blue-500/10 rounded-lg p-4 border border-purple-500/20">
        <CopyFormatButton content="" role="assistant" markdown={answer} className="absolute top-2 right-2" />
        <div className="prose prose-sm dark:prose-invert max-w-none pr-10">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              code(props) {
                const {
                  node,
                  className,
                  children,
                  ...rest
                } = props;
                const match = /language-(\w+)/.exec(
                  className || "",
                );
                const language = match ? match[1] : "";
                const codeStr = String(children).replace(/\n$/, "");
                const isInline =
                  !className?.includes("language-") &&
                  !String(children).includes("\n");

                if (!isInline && language === "mermaid") {
                  return <MermaidBlock code={codeStr} />;
                }

                return !isInline ? (
                  <CodeBlock
                    code={`\`\`\`${language}\n${codeStr}\n\`\`\``}
                  />
                ) : (
                  <code
                    className="bg-muted px-1.5 py-0.5 rounded text-sm font-mono"
                    {...rest}
                  >
                    {children}
                  </code>
                );
              },
              p(props) {
                const hasBlock = Array.isArray(props.children)
                  ? props.children.some(
                      (child: unknown) =>
                        child != null &&
                        typeof child === 'object' &&
                        'type' in (child as Record<string, unknown>) &&
                        typeof (child as Record<string, unknown>).type !== 'string',
                    )
                  : false;
                return hasBlock ? (
                  <div className="mb-2 last:mb-0">
                    {props.children}
                  </div>
                ) : (
                  <p className="mb-2 last:mb-0">
                    {props.children}
                  </p>
                );
              },
              ul(props) {
                return (
                  <ul className="list-disc pl-4 mb-2">
                    {props.children}
                  </ul>
                );
              },
              ol(props) {
                return (
                  <ol className="list-decimal pl-4 mb-2">
                    {props.children}
                  </ol>
                );
              },
              li(props) {
                return <li className="mb-1">{props.children}</li>;
              },
              a(props) {
                return (
                  <a
                    href={props.href}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-blue-600 dark:text-blue-400 underline hover:text-blue-800 dark:hover:text-blue-300"
                  >
                    {props.children}
                  </a>
                );
              },
              blockquote(props) {
                return (
                  <blockquote className="border-l-4 border-muted-foreground/30 pl-4 italic my-2">
                    {props.children}
                  </blockquote>
                );
              },
              table(props) {
                return (
                  <div className="overflow-x-auto my-2">
                    <table className="min-w-full border-collapse border border-border text-sm">
                      {props.children}
                    </table>
                  </div>
                );
              },
              thead(props) {
                return <thead className="bg-muted">{props.children}</thead>;
              },
              th(props) {
                return (
                  <th className="border border-border px-3 py-2 text-left font-semibold">
                    {props.children}
                  </th>
                );
              },
              td(props) {
                return (
                  <td className="border border-border px-3 py-2">
                    {props.children}
                  </td>
                );
              },
              tr(props) {
                return <tr className="even:bg-muted/50">{props.children}</tr>;
              },
            }}
          >
            {answer || ""}
          </ReactMarkdown>
        </div>
      </div>
    </div>
  );
}

function MermaidBlock({ code }: { code: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const uniqueId = useId();
  const [svg, setSvg] = useState<string>('');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        const mermaid = (await import('mermaid')).default;
        mermaid.initialize({ startOnLoad: false, theme: 'dark' });
        const { svg: rendered } = await mermaid.render(
          `mermaid-${uniqueId.replace(/:/g, '')}`,
          code,
        );
        if (!cancelled) setSvg(rendered);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to render diagram');
      }
    })();

    return () => { cancelled = true; };
  }, [code, uniqueId]);

  if (error) {
    return <CodeBlock code={`\`\`\`mermaid\n${code}\n\`\`\``} />;
  }

  return (
    <div
      ref={containerRef}
      className="my-2 flex justify-center overflow-x-auto rounded-lg bg-muted/30 p-4"
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
}

function CodeBlock({ code }: { code: string }) {
  const [copied, setCopied] = useState(false);

  // Extract language and code
  const match = code.match(/```(\w+)?\n([\s\S]*?)```/);
  const language = match?.[1] || "text";
  const codeContent =
    match?.[2] || code.replace(/```/g, "").trim();

  const handleCopy = () => {
    navigator.clipboard.writeText(codeContent);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="relative">
      <div className="absolute top-2 right-2 z-10 flex items-center gap-2">
        <Badge variant="secondary" className="text-xs">
          {language}
        </Badge>
        <Button
          size="sm"
          variant="ghost"
          onClick={handleCopy}
          className="h-7 px-2"
        >
          {copied ? (
            <Check className="w-3 h-3" />
          ) : (
            <Copy className="w-3 h-3" />
          )}
        </Button>
      </div>
      <SyntaxHighlighter
        language={language}
        style={oneDark}
        customStyle={{
          margin: 0,
          borderRadius: "0.5rem",
          fontSize: "0.875rem",
          padding: "1rem",
          paddingTop: "2.5rem",
        }}
      >
        {codeContent}
      </SyntaxHighlighter>
    </div>
  );
}