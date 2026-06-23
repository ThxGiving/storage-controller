import { beforeAll, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import i18n from "@/i18n";
import { StatusIndicator } from "@/components/dashboard/StatusIndicator";
import { TemperatureRangeGauge } from "@/components/dashboard/TemperatureRangeGauge";
import {
  TimeRangeSegmentedControl,
} from "@/components/dashboard/TimeRangeSegmentedControl";
import { OperationalStateStrip } from "@/components/dashboard/OperationalStateStrip";
import type { DashboardRoleValue } from "@/lib/types";

beforeAll(async () => {
  await i18n.changeLanguage("en");
});

describe("StatusIndicator", () => {
  it("shows a text label (not color-only) for each status", () => {
    const { rerender } = render(<StatusIndicator status="outside_range" />);
    expect(screen.getByRole("status")).toHaveTextContent("Out of range");
    rerender(<StatusIndicator status="configuration_error" />);
    expect(screen.getByRole("status")).toHaveTextContent("Configuration error");
  });
});

describe("TimeRangeSegmentedControl", () => {
  it("renders options and reports selection on click", () => {
    const onChange = vi.fn();
    render(<TimeRangeSegmentedControl value="24h" onChange={onChange} />);
    fireEvent.click(screen.getByText("7 d"));
    expect(onChange).toHaveBeenCalledWith("7d");
  });

  it("supports arrow-key navigation", () => {
    const onChange = vi.fn();
    render(<TimeRangeSegmentedControl value="24h" onChange={onChange} />);
    const selected = screen.getByRole("radio", { checked: true });
    fireEvent.keyDown(selected, { key: "ArrowRight" });
    expect(onChange).toHaveBeenCalledWith("7d");
  });
});

describe("TemperatureRangeGauge", () => {
  it("renders numeric limit values (not color-only)", () => {
    render(<TemperatureRangeGauge current={5} lower={0} upper={8} warningMargin={0.5} />);
    expect(screen.getByText("0°")).toBeInTheDocument();
    expect(screen.getByText("8°")).toBeInTheDocument();
    expect(screen.getByRole("img")).toHaveAttribute("aria-label");
  });
});

describe("OperationalStateStrip", () => {
  it("renders only assigned roles with on/off labels", () => {
    const roles: DashboardRoleValue[] = [
      {
        role: "compressor",
        entity_id: "binary_sensor.kh1_kompressor",
        exists: true,
        available: true,
        quality: "valid",
        numeric_c: null,
        raw: "on",
        unit: null,
        bool_value: true,
      },
    ];
    render(<OperationalStateStrip roles={roles} />);
    expect(screen.getByText("Compressor")).toBeInTheDocument();
    expect(screen.getByText("On")).toBeInTheDocument();
  });

  it("renders nothing when no roles are assigned", () => {
    const { container } = render(<OperationalStateStrip roles={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
