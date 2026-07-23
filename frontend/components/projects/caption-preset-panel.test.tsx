import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createDefaultCaptionStyle } from "@/lib/caption-style";

const { mockApi } = vi.hoisted(() => {
  const baseStyle = {
    font_family: "Arial, Helvetica, sans-serif",
    font_size: 22,
    font_weight: 600,
    text_color: "#FFFFFF",
    active_word_color: "#FFFFFF",
    outline_color: "#000000",
    outline_width: 1,
    background_color: "#000000",
    background_opacity: 0.45,
    shadow_enabled: false,
    shadow_strength: 0,
    text_alignment: "center" as const,
    horizontal_position: 50,
    vertical_position: 88,
    max_line_width: 85,
    words_per_group: "full" as const,
    text_transform: "none" as const,
    animation_type: "fade" as const,
    animation_intensity: 0.4,
    safe_area_mode: "none" as const,
  };
  const mockPresets = [
    {
      id: "minimal-clean",
      name: "Minimal Clean",
      is_builtin: true,
      is_default: true,
      style: baseStyle,
      created_at: "1970-01-01T00:00:00+00:00",
      updated_at: "1970-01-01T00:00:00+00:00",
    },
    {
      id: "custom-1",
      name: "My Custom",
      is_builtin: false,
      is_default: false,
      style: {
        ...baseStyle,
        text_color: "#AABBCC",
      },
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    },
  ];

  return {
    mockApi: {
      mockPresets,
      fetchCaptionPresets: vi.fn(async () => ({
        presets: mockPresets,
        default_preset_id: "minimal-clean",
      })),
      createCaptionPreset: vi.fn(async ({ name }: { name: string }) => ({
        id: "created-1",
        name,
        is_builtin: false,
        is_default: false,
        style: baseStyle,
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
      })),
      updateCaptionPreset: vi.fn(
        async (presetId: string, request: { name?: string; is_default?: boolean }) => ({
          ...mockPresets.find((preset) => preset.id === presetId)!,
          name: request.name ?? mockPresets.find((preset) => preset.id === presetId)!.name,
          is_default: request.is_default ?? false,
        }),
      ),
      deleteCaptionPreset: vi.fn(async () => undefined),
      duplicateCaptionPreset: vi.fn(async () => ({
        id: "dup-1",
        name: "Minimal Clean Copy",
        is_builtin: false,
        is_default: false,
        style: baseStyle,
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
      })),
      exportCaptionPreset: vi.fn(async () => ({
        schema_version: 1,
        preset: { name: "Minimal Clean", style: baseStyle },
      })),
      importCaptionPresets: vi.fn(async () => ({ imported: [mockPresets[1]] })),
    },
  };
});

vi.mock("@/lib/api/caption-presets", () => ({
  fetchCaptionPresets: mockApi.fetchCaptionPresets,
  createCaptionPreset: mockApi.createCaptionPreset,
  updateCaptionPreset: mockApi.updateCaptionPreset,
  deleteCaptionPreset: mockApi.deleteCaptionPreset,
  duplicateCaptionPreset: mockApi.duplicateCaptionPreset,
  exportCaptionPreset: mockApi.exportCaptionPreset,
  importCaptionPresets: mockApi.importCaptionPresets,
}));

import { CaptionPresetPanel } from "@/components/projects/CaptionPresetPanel";

describe("CaptionPresetPanel", () => {
  beforeEach(() => {
    mockApi.fetchCaptionPresets.mockClear();
    mockApi.createCaptionPreset.mockClear();
    mockApi.updateCaptionPreset.mockClear();
    mockApi.deleteCaptionPreset.mockClear();
    mockApi.duplicateCaptionPreset.mockClear();
    mockApi.exportCaptionPreset.mockClear();
    mockApi.importCaptionPresets.mockClear();
  });

  it("loads preset list", async () => {
    render(
      <CaptionPresetPanel
        currentStyle={createDefaultCaptionStyle()}
        onApplyStyle={vi.fn()}
      />,
    );

    expect(await screen.findByText("Minimal Clean")).toBeInTheDocument();
    expect(screen.getAllByText("Built-in").length).toBeGreaterThan(0);
    expect(screen.getByText("Custom")).toBeInTheDocument();
  });

  it("applies preset without changing caption text props", async () => {
    const user = userEvent.setup();
    const onApplyStyle = vi.fn();

    render(
      <CaptionPresetPanel
        currentStyle={createDefaultCaptionStyle()}
        onApplyStyle={onApplyStyle}
      />,
    );

    await screen.findByRole("button", { name: "Preset My Custom" });
    await user.click(screen.getByRole("button", { name: "Preset My Custom" }));
    await user.click(screen.getByRole("button", { name: /apply preset/i }));

    expect(onApplyStyle).toHaveBeenCalledWith(
      expect.objectContaining({
        preset_id: "custom",
        text_color: "#AABBCC",
      }),
    );
  });

  it("saves current style as preset", async () => {
    const user = userEvent.setup();

    render(
      <CaptionPresetPanel
        currentStyle={createDefaultCaptionStyle()}
        onApplyStyle={vi.fn()}
      />,
    );

    await screen.findByText("Minimal Clean");
    await user.type(screen.getByPlaceholderText("Preset name"), "Saved Look");
    await user.click(screen.getByRole("button", { name: /save preset/i }));

    await waitFor(() => {
      expect(mockApi.createCaptionPreset).toHaveBeenCalledWith(
        expect.objectContaining({ name: "Saved Look" }),
      );
    });
  });

  it("duplicates built-in preset once per double click guard", async () => {
    const user = userEvent.setup();

    render(
      <CaptionPresetPanel
        currentStyle={createDefaultCaptionStyle()}
        onApplyStyle={vi.fn()}
      />,
    );

    await screen.findByText("Minimal Clean");
    await user.click(screen.getByRole("button", { name: /duplicate/i }));
    await user.click(screen.getByRole("button", { name: /duplicate/i }));

    await waitFor(() => {
      expect(mockApi.duplicateCaptionPreset).toHaveBeenCalledTimes(1);
    });
  });

  it("protects built-in rename/delete controls", async () => {
    render(
      <CaptionPresetPanel
        currentStyle={createDefaultCaptionStyle()}
        onApplyStyle={vi.fn()}
      />,
    );

    await screen.findByText("Minimal Clean");
    expect(screen.queryByRole("button", { name: /^rename$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /delete preset/i })).not.toBeInTheDocument();
  });

  it("allows rename and delete for custom preset", async () => {
    const user = userEvent.setup();

    render(
      <CaptionPresetPanel
        currentStyle={createDefaultCaptionStyle()}
        onApplyStyle={vi.fn()}
      />,
    );

    await screen.findByRole("button", { name: "Preset My Custom" });
    await user.click(screen.getByRole("button", { name: "Preset My Custom" }));
    expect(screen.getByRole("button", { name: /^rename$/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /delete preset/i })).toBeInTheDocument();
  });

  it("sets default preset", async () => {
    const user = userEvent.setup();

    render(
      <CaptionPresetPanel
        currentStyle={createDefaultCaptionStyle()}
        onApplyStyle={vi.fn()}
      />,
    );

    await screen.findByRole("button", { name: "Preset My Custom" });
    await user.click(screen.getByRole("button", { name: "Preset My Custom" }));
    await user.click(screen.getByRole("button", { name: /set default/i }));

    await waitFor(() => {
      expect(mockApi.updateCaptionPreset).toHaveBeenCalledWith("custom-1", { is_default: true });
    });
  });
});
