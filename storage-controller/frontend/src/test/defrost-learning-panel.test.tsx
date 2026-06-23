import { beforeAll, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import i18n from "@/i18n";
import type { DefrostLearningStatus } from "@/lib/types";

const status: DefrostLearningStatus = {
  storage_unit_id: 1,
  enabled: true,
  has_defrost_entity: true,
  state: "suggestion_ready",
  valid_cycle_count: 12,
  min_cycles: 10,
  confidence: "preliminary",
  confidence_score: 0.65,
  outlier_count: 0,
  outliers: [],
  drift_warning: false,
  drift_detail: null,
  suggestion: {
    id: 1, version: 0, status: "suggested", confidence: "preliminary", confidence_score: 0.65,
    valid_cycle_count: 12, window_start: null, window_end: null,
    typical_defrost_seconds: 360, max_defrost_seconds: 450,
    typical_recovery_seconds: 180, max_recovery_seconds: 240,
    typical_room_peak_c: 7, max_room_peak_c: 9, typical_evaporator_peak_c: -12,
    max_evaporator_peak_c: -10, typical_interval_seconds: 3600,
    room_peak_variation_c: 0.2, duration_variation_seconds: 10, safety_margin_c: 2,
    drift_warning: false, drift_detail: null, generated_at: null, approved_at: null, approved_by: null,
  },
  approved: null,
  recent_cycles: [],
};

vi.mock("@/lib/api", () => ({
  api: {
    getDefrostLearning: vi.fn(() => Promise.resolve(status)),
    approveDefrostLearning: vi.fn(),
    resetDefrostLearning: vi.fn(),
  },
}));

import { DefrostLearningPanel } from "@/features/units/DefrostLearningPanel";

beforeAll(async () => {
  await i18n.changeLanguage("en");
});

function renderPanel() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <DefrostLearningPanel unitId={1} />
    </QueryClientProvider>,
  );
}

describe("DefrostLearningPanel", () => {
  it("shows the suggestion, an approve action, and the safety note", async () => {
    renderPanel();
    expect(await screen.findByText("Defrost learning")).toBeInTheDocument();
    expect(screen.getByText("Suggestion ready for review")).toBeInTheDocument();
    expect(screen.getByText("Approve suggestion")).toBeInTheDocument();
    // never presents learned values as legal/HACCP limits
    await waitFor(() =>
      expect(
        screen.getByText(/never legal or HACCP-certified limits/i),
      ).toBeInTheDocument(),
    );
  });
});
