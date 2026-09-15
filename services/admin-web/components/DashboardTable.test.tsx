import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { DashboardTable } from "@/components/DashboardTable";
import type { Bot } from "@/lib/api";

function makeBot(overrides: Partial<Bot>): Bot {
  return {
    id: "1",
    name: "Бот",
    enabled: true,
    phone: null,
    linked_at: null,
    system_prompt: "промпт",
    image_prompt: null,
    pdf_prompt: null,
    status: null,
    last_seen: null,
    ...overrides,
  };
}

describe("DashboardTable", () => {
  it("shows an explanatory message instead of a table when there are no bots", () => {
    render(<DashboardTable bots={[]} />);
    expect(screen.getByText("Ботов пока нет")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("renders the StatusPulse label and last_seen for a healthy bot, with no raw-status caption", () => {
    render(
      <DashboardTable
        bots={[
          makeBot({ id: "1", name: "Открыт", status: "open", last_seen: "2026-09-12T10:30:00Z" }),
        ]}
      />
    );
    expect(screen.getByText("Подключён")).toBeInTheDocument();
    expect(screen.getByText("2026-09-12 10:30")).toBeInTheDocument();
    // "open" не дублируется мелкой подписью — для здорового бота это шум,
    // подпись нужна только там, где StatusPulse что-то схлопывает.
    expect(screen.queryByText("open")).not.toBeInTheDocument();
  });

  it("shows a placeholder for a bot that was never linked, with no raw-status caption", () => {
    render(<DashboardTable bots={[makeBot({ status: null, last_seen: null })]} />);
    expect(screen.getByText("Не подключён")).toBeInTheDocument();
    // "—" встречается один раз в этой строке (последняя активность) — колонка
    // "Пауза" ушла, бейдж "на паузе" не рендерится для enabled:true.
    expect(screen.getAllByText("—")).toHaveLength(1);
  });

  it("shows the raw status as a caption for a bot with a problem status", () => {
    render(<DashboardTable bots={[makeBot({ status: "reconnecting" })]} />);
    expect(screen.getByText("Подключается")).toBeInTheDocument();
    expect(screen.getByText("reconnecting")).toBeInTheDocument();
  });

  it("marks a paused bot", () => {
    render(<DashboardTable bots={[makeBot({ enabled: false })]} />);
    expect(screen.getByText("на паузе")).toBeInTheDocument();
  });

  // FEATURES.md 6.17 — операционное здоровье: проблемные боты должны быть
  // видны сразу, не потеряны в алфавитном списке из 31 бота.
  it("sorts problem bots (not open) before healthy ones, regardless of name", () => {
    render(
      <DashboardTable
        bots={[
          makeBot({ id: "1", name: "А-бот, всё хорошо", status: "open" }),
          makeBot({ id: "2", name: "Я-бот, разорвана сессия", status: "logged_out" }),
          makeBot({ id: "3", name: "Б-бот, переподключается", status: "reconnecting" }),
        ]}
      />
    );
    const rows = screen.getAllByRole("row").slice(1); // без заголовка
    const names = rows.map((r) => r.textContent);
    expect(names[0]).toContain("Я-бот, разорвана сессия");
    expect(names[1]).toContain("Б-бот, переподключается");
    expect(names[2]).toContain("А-бот, всё хорошо");
  });
});
