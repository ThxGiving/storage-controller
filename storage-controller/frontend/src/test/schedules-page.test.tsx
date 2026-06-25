import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import i18n from "@/i18n";

const mocks = vi.hoisted(() => ({
  getEmailSettings: vi.fn(), updateEmailSettings: vi.fn(), testSmtpConnection: vi.fn(),
  sendTestEmail: vi.fn(), listSchedules: vi.fn(), createSchedule: vi.fn(), updateSchedule: vi.fn(),
  deleteSchedule: vi.fn(), enableSchedule: vi.fn(), disableSchedule: vi.fn(), runScheduleNow: vi.fn(),
  listScheduleRuns: vi.fn(), listUnits: vi.fn(),
}));

vi.mock("@/lib/api", () => ({ api: mocks }));

const smtp = {
  host: "smtp.example.com", port: 587, security_mode: "starttls", auth_enabled: true,
  username: "user", password_configured: true, sender_name: "Connie's", sender_email: "from@x.com",
  reply_to: null, connection_timeout_seconds: 30, verify_certificates: true, allow_insecure_plain: false,
  default_to: ["ops@example.com"], default_cc: [], default_bcc: [], max_attachment_bytes: 20971520,
  site_name: "Connie's", last_test_at: null, last_test_ok: null, last_test_error: null,
};

const schedule = {
  id: 1, name: "Monthly HACCP", enabled: true, report_type: "monthly", period_rule: "previous_month",
  storage_unit_ids: [1], locale: "de", timezone: "Europe/Berlin", detail_level: "standard",
  recipients_to: ["ops@example.com"], recipients_cc: [], recipients_bcc: [], recipient_count: 1,
  attachment_formats: ["pdf"], run_day: 1, run_time: "06:00", catch_up_mode: "one",
  next_run_utc: "2026-07-01T04:00:00Z", last_run_utc: null, last_result: "completed",
  run_now_period: "2026-06",
};

import { SchedulesPage } from "@/pages/Schedules";

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <SchedulesPage />
    </QueryClientProvider>,
  );
}

describe("SchedulesPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getEmailSettings.mockResolvedValue(smtp);
    mocks.updateEmailSettings.mockResolvedValue(smtp);
    mocks.testSmtpConnection.mockResolvedValue({ ok: true, category: null, message: null });
    mocks.sendTestEmail.mockResolvedValue({ ok: true, category: null, message: null });
    mocks.listSchedules.mockResolvedValue([schedule]);
    mocks.createSchedule.mockResolvedValue(schedule);
    mocks.updateSchedule.mockResolvedValue(schedule);
    mocks.disableSchedule.mockResolvedValue({ ...schedule, enabled: false });
    mocks.runScheduleNow.mockResolvedValue({});
    mocks.listScheduleRuns.mockResolvedValue([]);
    mocks.listUnits.mockResolvedValue([{ id: 1, name: "Kühlhaus 1" }]);
    i18n.changeLanguage("en");
  });

  it("renders SMTP settings and the schedule list", async () => {
    renderPage();
    expect(await screen.findByDisplayValue("smtp.example.com")).toBeTruthy();
    expect(await screen.findByText("Monthly HACCP")).toBeTruthy();
  });

  it("password is write-only: shows configured placeholder, saves without a password value", async () => {
    renderPage();
    const pw = (await screen.findByPlaceholderText(/configured/i)) as HTMLInputElement;
    expect(pw.value).toBe("");  // never pre-filled with the secret
    fireEvent.click(screen.getByText("Save"));
    await waitFor(() => expect(mocks.updateEmailSettings).toHaveBeenCalled());
    const arg = mocks.updateEmailSettings.mock.calls[0][0] as { password?: string };
    expect(arg.password).toBeUndefined();  // blank field preserves the stored secret
  });

  it("tests the SMTP connection", async () => {
    renderPage();
    await screen.findByDisplayValue("smtp.example.com");
    fireEvent.click(screen.getByText("Test connection"));
    await waitFor(() => expect(mocks.testSmtpConnection).toHaveBeenCalled());
  });

  it("sends a test email to a recipient", async () => {
    renderPage();
    await screen.findByDisplayValue("smtp.example.com");
    fireEvent.change(screen.getByPlaceholderText("test@example.com"), {
      target: { value: "qa@example.com" },
    });
    fireEvent.click(screen.getByText("Send test email"));
    await waitFor(() => expect(mocks.sendTestEmail).toHaveBeenCalledWith("qa@example.com"));
  });

  it("runs a schedule now", async () => {
    renderPage();
    await screen.findByText("Monthly HACCP");
    fireEvent.click(screen.getByTitle("Run now"));
    await waitFor(() => expect(mocks.runScheduleNow).toHaveBeenCalledWith(1, true));
  });

  it("creates a schedule from the editor", async () => {
    renderPage();
    await screen.findByText("Monthly HACCP");
    fireEvent.click(screen.getByText("New schedule"));
    const dialog = await screen.findByRole("dialog");
    const nameInput = within(dialog).getAllByRole("textbox")[0];
    fireEvent.change(nameInput, { target: { value: "Weekly" } });
    fireEvent.click(within(dialog).getByText("Save"));
    await waitFor(() => expect(mocks.createSchedule).toHaveBeenCalled());
  });

  it("renders German translations", async () => {
    i18n.changeLanguage("de");
    renderPage();
    expect(await screen.findByText("Zeitpläne & E-Mail")).toBeTruthy();
    expect(await screen.findByText("SMTP-Einstellungen")).toBeTruthy();
  });
});
