import { beforeAll, describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import i18n from "@/i18n";
import { IncidentBadge } from "@/components/incidents/IncidentBadge";

beforeAll(async () => {
  await i18n.changeLanguage("en");
});

describe("IncidentBadge", () => {
  it("renders a translated type label with an icon (not color-only)", () => {
    render(<IncidentBadge type="abnormal_defrost" />);
    expect(screen.getByText("Abnormal defrost")).toBeInTheDocument();
  });

  it("includes the state when provided", () => {
    render(<IncidentBadge type="temperature_high" state="active_violation" />);
    expect(screen.getByText("Temperature too high")).toBeInTheDocument();
    expect(screen.getByText(/Active/)).toBeInTheDocument();
  });
});
