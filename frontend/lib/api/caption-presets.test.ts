import { describe, expect, it, vi, beforeEach } from "vitest";
import {
  createCaptionPreset,
  deleteCaptionPreset,
  duplicateCaptionPreset,
  exportCaptionPreset,
  fetchCaptionPresets,
  importCaptionPresets,
  updateCaptionPreset,
} from "@/lib/api/caption-presets";
import { createDefaultCaptionStyle } from "@/lib/caption-style";
import { captionStyleToPresetStyle } from "@/lib/caption-presets";

describe("caption presets API client", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("loads preset list", async () => {
    vi.spyOn(global, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          presets: [],
          default_preset_id: "minimal-clean",
        }),
        { status: 200 },
      ),
    );

    const result = await fetchCaptionPresets();
    expect(result.default_preset_id).toBe("minimal-clean");
  });

  it("creates a preset", async () => {
    vi.spyOn(global, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          id: "preset-1",
          name: "Saved",
          is_builtin: false,
          is_default: false,
          style: captionStyleToPresetStyle(createDefaultCaptionStyle()),
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
        }),
        { status: 201 },
      ),
    );

    const created = await createCaptionPreset({
      name: "Saved",
      style: captionStyleToPresetStyle(createDefaultCaptionStyle()),
    });
    expect(created.name).toBe("Saved");
  });

  it("updates, duplicates, exports, imports, and deletes presets", async () => {
    const style = captionStyleToPresetStyle(createDefaultCaptionStyle());
    const preset = {
      id: "preset-1",
      name: "Saved",
      is_builtin: false,
      is_default: false,
      style,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    };
    const fetchMock = vi.spyOn(global, "fetch");

    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ ...preset, name: "Renamed" }), { status: 200 }));
    await updateCaptionPreset("preset-1", { name: "Renamed" });

    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ ...preset, id: "preset-2", name: "Saved Copy" }), {
        status: 201,
      }),
    );
    await duplicateCaptionPreset("preset-1");

    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          schema_version: 1,
          preset: { name: "Saved", style },
        }),
        { status: 200 },
      ),
    );
    const exported = await exportCaptionPreset("preset-1");
    expect(exported.schema_version).toBe(1);

    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ imported: [preset] }), { status: 200 }),
    );
    const imported = await importCaptionPresets({
      schema_version: 1,
      preset: { name: "Saved", style },
    });
    expect(imported.imported).toHaveLength(1);

    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
    await deleteCaptionPreset("preset-1");
  });
});
