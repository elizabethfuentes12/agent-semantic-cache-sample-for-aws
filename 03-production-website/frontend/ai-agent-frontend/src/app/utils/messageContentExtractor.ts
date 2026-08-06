/**
 * Extracts human-readable text content from the internal JSON message format.
 *
 * @param rawContent - The raw message content string (may be JSON or plain text)
 * @returns The extracted readable text content
 */
export function extractMessageContent(rawContent: string): string {
  let parsed: unknown;

  try {
    parsed = JSON.parse(rawContent);
  } catch {
    // Not valid JSON — return original string unchanged
    return rawContent;
  }

  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    return rawContent;
  }

  const response = parsed as Record<string, unknown>;

  switch (response.type) {
    case "message":
      return response.content != null ? String(response.content) : "";

    case "complete":
      return response.answer != null ? String(response.answer) : "";

    case "tool_call": {
      const tool = response.tool != null ? String(response.tool) : "Unknown tool";
      let inputStr: string;
      try {
        inputStr = JSON.stringify(response.input, null, 2);
      } catch {
        inputStr = "[unable to display input]";
      }
      return `Tool: ${tool}\nInput:\n${inputStr}`;
    }

    case "tool_result": {
      const tool = response.tool != null ? String(response.tool) : "Unknown tool";
      const result = response.result != null ? String(response.result) : "";
      return `Tool: ${tool}\nResult:\n${result}`;
    }

    default:
      // Unrecognized type — return original string unchanged
      return rawContent;
  }
}
