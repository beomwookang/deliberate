"use client";

/**
 * Safe markdown renderer for user-supplied text.
 * Uses rehype-sanitize to strip dangerous HTML (scripts, images with onerror, etc.)
 */

import Markdown from "react-markdown";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";

const sanitizeSchema = {
  ...defaultSchema,
  tagNames: [
    "p",
    "ul",
    "ol",
    "li",
    "strong",
    "em",
    "code",
    "br",
    "a",
    "blockquote",
  ],
  attributes: {
    ...defaultSchema.attributes,
    a: ["href"],
  },
};

export function MarkdownText({
  content,
  className,
}: {
  content: string;
  className?: string;
}) {
  return (
    <div className={`prose prose-sm max-w-none ${className || ""}`}>
      <Markdown rehypePlugins={[[rehypeSanitize, sanitizeSchema]]}>
        {content}
      </Markdown>
    </div>
  );
}
