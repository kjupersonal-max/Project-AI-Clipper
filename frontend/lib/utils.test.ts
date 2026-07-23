import { describe, expect, it } from "vitest";
import { uniqueStringListItems } from "@/lib/utils";

describe("uniqueStringListItems", () => {
  it("deduplicates repeated strings and uses stable index keys", () => {
    const items = uniqueStringListItems(
      [
        "Low-confidence transcription detected (7 words).",
        "Low-confidence transcription detected (7 words).",
        "Clip-boundary speech detected near start.",
      ],
      "warning",
    );

    expect(items).toEqual([
      {
        key: "warning-0",
        text: "Low-confidence transcription detected (7 words).",
      },
      {
        key: "warning-2",
        text: "Clip-boundary speech detected near start.",
      },
    ]);
  });

  it("returns an empty list for missing input", () => {
    expect(uniqueStringListItems(undefined)).toEqual([]);
    expect(uniqueStringListItems([])).toEqual([]);
  });
});
