import { formatJobDescription } from "./job-description-format";

export default function JobDescription({ content }: { content: string }) {
  return <div className="job-description-text">{formatJobDescription(content).map((block, index) =>
    block.type === "heading" ? <h4 key={index}>{block.lines[0]}</h4>
      : block.type === "list" ? <ul key={index}>{block.lines.map((line, item) => <li key={item}>{line}</li>)}</ul>
      : <p key={index}>{block.lines[0]}</p>
  )}</div>;
}
