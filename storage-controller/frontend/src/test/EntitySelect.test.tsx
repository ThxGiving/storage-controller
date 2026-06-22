import { beforeAll, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import i18n from "@/i18n";
import { EntitySelect } from "@/features/entities/EntitySelect";
import type { HAEntity } from "@/lib/types";

const entities: HAEntity[] = [
  {
    entity_id: "sensor.kuhlhaus_1_temperatur",
    domain: "sensor",
    friendly_name: "Kühlhaus 1 Temperatur",
    state: "6.1",
    unit_of_measurement: "°C",
    device_class: "temperature",
    device_name: "Kühlhaus 1 Controller",
    available: true,
    last_changed: null,
    last_updated: null,
  },
  {
    entity_id: "switch.kuhlhaus_1_licht",
    domain: "switch",
    friendly_name: "Kühlhaus 1 Licht",
    state: "off",
    unit_of_measurement: null,
    device_class: null,
    device_name: null,
    available: true,
    last_changed: null,
    last_updated: null,
  },
];

beforeAll(async () => {
  await i18n.changeLanguage("en");
});

describe("EntitySelect", () => {
  it("searches by friendly name and selects an entity", () => {
    const onChange = vi.fn();
    render(<EntitySelect value="" entities={entities} onChange={onChange} />);

    fireEvent.click(screen.getByText("Select entity…"));
    fireEvent.change(screen.getByPlaceholderText(/Search entity ID or name/i), {
      target: { value: "Licht" },
    });

    fireEvent.click(screen.getByText("Kühlhaus 1 Licht"));
    expect(onChange).toHaveBeenCalledWith("switch.kuhlhaus_1_licht");
  });

  it("allows manual entity-id entry", () => {
    const onChange = vi.fn();
    render(<EntitySelect value="" entities={entities} onChange={onChange} />);

    fireEvent.click(screen.getByText("Select entity…"));
    fireEvent.change(screen.getByPlaceholderText(/Search entity ID or name/i), {
      target: { value: "sensor.custom_probe" },
    });

    fireEvent.click(screen.getByText("sensor.custom_probe"));
    expect(onChange).toHaveBeenCalledWith("sensor.custom_probe");
  });

  it("shows the current state for the selected entity", () => {
    render(
      <EntitySelect
        value="sensor.kuhlhaus_1_temperatur"
        entities={entities}
        onChange={() => {}}
      />,
    );
    expect(screen.getByText("6.1 °C")).toBeInTheDocument();
  });
});
