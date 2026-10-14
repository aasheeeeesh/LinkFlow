import { describe, expect, it } from "vitest";
import { parseLinks, splitDomains } from "./live";

describe("splitDomains", () => {
  it("splits on commas, spaces and new lines and drops duplicates", () => {
    expect(splitDomains(" a.com, b.org\nc.net  a.com ")).toEqual(["a.com", "b.org", "c.net"]);
    expect(splitDomains("   ")).toEqual([]);
  });
});

describe("parseLinks", () => {
  it("reads one link per line with an arrow or a space", () => {
    expect(parseLinks("a.com -> b.org\nc.net→d.com\n\ne.com f.com\nbroken")).toEqual({
      links: [
        { source: "a.com", target: "b.org" },
        { source: "c.net", target: "d.com" },
        { source: "e.com", target: "f.com" },
      ],
      bad: ["broken"],
    });
  });
});
