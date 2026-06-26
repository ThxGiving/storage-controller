import { beforeAll, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import i18n from "@/i18n";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: {
      listUnits: vi.fn(() => Promise.resolve([{ id: 1, name: "Kühlhaus 1", report_enabled: true }])),
      listReports: vi.fn(() =>
        Promise.resolve([
          {
            id: 7, uuid: "abcd1234-0000", status: "completed", period_year: 2026, period_month: 6,
            locale: "de", timezone: "Europe/Berlin", detail_level: "standard", storage_unit_ids: [1],
            checksum_sha256: "a".repeat(64), has_pdf: true, has_csv: true, has_json: true,
            created_by: "admin", created_at: "2026-07-01T08:00:00Z", generated_at: "2026-07-01T08:00:01Z",
            duration_ms: 800, failure_category: null, error_message: null,
          },
        ]),
      ),
      getReportBranding: vi.fn(() =>
        Promise.resolve({
          organization_name: "Connie's", site_name: null, address: null, contact: null,
          logo_filename: null, report_title: "HACCP", subtitle: null, accent: null,
          footer_text: null, disclaimer: null, signature_labels: [], default_locale: "de",
          default_timezone: "Europe/Berlin", default_detail_level: "standard",
        }),
      ),
      reportDownloadUrl: (id: number, fmt: string) => `api/reports/${id}/${fmt}`,
      previewReport: vi.fn(),
      createReport: vi.fn(),
      deleteReport: vi.fn(),
      updateReportBranding: vi.fn(),
      uploadReportLogo: vi.fn(),
    },
  };
});

import { ReportsPage } from "@/pages/Reports";

beforeAll(async () => {
  await i18n.changeLanguage("en");
});

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ReportsPage />
    </QueryClientProvider>,
  );
}

describe("ReportsPage", () => {
  it("renders config, a completed report with downloads, and the checksum", async () => {
    renderPage();
    // page heading + tab both carry this text — at least one must be present
    expect((await screen.findAllByText("HACCP reports")).length).toBeGreaterThan(0);
    expect(screen.getByText("New report")).toBeInTheDocument();
    // the generated report row with PDF/CSV/JSON downloads + checksum
    expect(await screen.findByText("PDF")).toBeInTheDocument();
    expect(screen.getByText("CSV")).toBeInTheDocument();
    expect(screen.getByText("JSON")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText(/Checksum:/)).toBeInTheDocument());
    // PDF link points at the download endpoint
    expect(screen.getByText("PDF").closest("a")).toHaveAttribute("href", "api/reports/7/pdf");
  });
});
