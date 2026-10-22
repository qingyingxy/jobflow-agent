export type DescriptionBlock = { type: "heading" | "paragraph" | "list"; lines: string[] };

const sectionName = "工作职责|岗位职责|职位职责|职责描述|工作内容|职责要求|任职要求|职位要求|岗位要求|任职资格|任职条件|职位描述|岗位描述|加分项|优先条件|加分条件|Responsibilities|Requirements|Qualifications|Preferred Qualifications";
const heading = new RegExp(`^(?:#{1,6}\\s+)?(?:[一二三四五六七八九十\\d]+[、.．)）]\\s*)?(?:${sectionName})[：:]?$`, "i");
const inlineHeading = new RegExp(`^((?:${sectionName})[：:])\\s*(.+)$`, "i");
const listItem = /^(?:[-*•●]\s+|[-•●](?=\p{Script=Han})|(?:\d{1,2}|[一二三四五六七八九十]+)[、.)）](?=\D)\s*)/u;

// Layout only: keep every non-whitespace character and never infer or rewrite requirements.
export function formatJobDescription(content: string): DescriptionBlock[] {
  const blocks: DescriptionBlock[] = [];
  const lines = content.replace(/\r\n?/g, "\n").split("\n").flatMap(line => {
    const text = line.trim();
    const match = text.match(inlineHeading);
    return match ? [match[1], match[2]] : [text];
  });
  let continueList = false;
  for (const line of lines) {
    if (!line) { continueList = false; continue; }
    if (heading.test(line)) {
      blocks.push({ type: "heading", lines: [line] });
      continueList = false;
      continue;
    }
    if (listItem.test(line)) {
      // Some source pages flatten Chinese bullet items onto one line. Split only
      // repeated explicit markers, preserving dates, ranges and English hyphens.
      const items = /^[-•●]/u.test(line)
        ? line.split(/[ \t]+(?=[-•●](?:\s*\p{Script=Han}|[A-Z][A-Za-z0-9+.#/]*(?=[ \t]+\p{Script=Han})))/u) : [line];
      const previous = blocks[blocks.length - 1];
      if (continueList && previous?.type === "list") previous.lines.push(...items);
      else blocks.push({ type: "list", lines: items });
      continueList = true;
    } else {
      blocks.push({ type: "paragraph", lines: [line] });
      continueList = false;
    }
  }
  return blocks;
}
